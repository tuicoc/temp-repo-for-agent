"""PostgreSQL access.

A small connection pool rather than a connection per request: Azure Database
for PostgreSQL charges a real round trip for every new connection, TLS
handshake included, and a B1 instance has one core to spend on it.

The schema is applied at startup and is written to be safe to run again, so a
deployment that restarts the app does not need a migration step yet. That
stops being true the moment a column changes type; when it does, this is the
place a migration tool goes.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

import bcrypt
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import database_env_candidates, get_settings

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT 'New conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS conversations_user_idx
    ON conversations (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    model           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx
    ON messages (conversation_id, created_at);
"""

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    """The process-wide pool, opened on first use."""
    global _pool
    if _pool is None:
        settings = get_settings()
        url, source = settings.require_database_url()
        # Which variable it came from, never what was in it. On Azure this is
        # the difference between "the database is not connected" and "it is
        # connected under a name we were not reading".
        logger.info("Connecting to PostgreSQL using %s", source)
        pool_ = ConnectionPool(
            url,
            min_size=1,
            # One core, and Azure's smaller Postgres tiers cap connections
            # low enough that a generous pool is a way to exhaust them.
            max_size=5,
            open=True,
            # Fail in seconds, not half a minute. A container that dies after
            # thirty seconds of silence tells you nothing.
            timeout=10,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
        )
        # Opening the pool does not connect: it retries in the background and
        # the failure would otherwise surface far from here, as a bare
        # PoolTimeout on whichever query ran first. wait() brings it forward.
        try:
            pool_.wait(timeout=12)
        except Exception as error:
            pool_.close()
            raise RuntimeError(_diagnose(url, source, error)) from error
        _pool = pool_
    return _pool


@contextmanager
def connection() -> Iterator[Any]:
    """A pooled connection, committed on success and rolled back on error."""
    with pool().connection() as conn:
        yield conn


def init_db() -> None:
    """Apply the schema and make sure the seeded account exists.

    Several workers start at once and CREATE TABLE IF NOT EXISTS is not atomic:
    each finds the table missing, each creates it, and the losers fail on a
    duplicate key in pg_type. A single process never sees this, which is why it
    survived local testing and appeared on the first real deployment.

    The loser is simply forgiven. An advisory lock was tried first and is the
    textbook answer, but it deadlocked against the connection pool — the
    waiting workers each hold a pooled connection while they block, and
    getting that right is more machinery than the problem deserves. Losing a
    race to create a table that now exists is not a failure.
    """
    settings = get_settings()
    try:
        with connection() as conn:
            _apply_schema(conn, settings)
    except (
        psycopg.errors.UniqueViolation,
        psycopg.errors.DuplicateTable,
        psycopg.errors.DuplicateObject,
    ):
        logger.info("Another worker created the schema first; continuing")
        with connection() as conn:
            _seed_account(conn, settings)


def _apply_schema(conn: Any, settings: Any) -> None:
    conn.execute(SCHEMA)
    _seed_account(conn, settings)


def _seed_account(conn: Any, settings: Any) -> None:
    """Create the one account, or reset its password to match the setting."""
    email = settings.require("seed_user_email").strip().lower()
    password = settings.require("seed_user_password")
    existing = conn.execute(
        "SELECT id FROM users WHERE email = %s", (email,)
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
            (email, hash_password(password)),
        )
        logger.info("Seeded the account for %s", email)
    else:
        # Rotating SEED_USER_PASSWORD in the Azure settings should change
        # the password, otherwise the variable is a lie after the first
        # deploy.
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hash_password(password), existing["id"]),
        )
        logger.info("Refreshed the password for %s", email)


def diagnose_connection() -> dict[str, Any]:
    """Everything needed to tell a working database apart from a broken one.

    Never the connection string itself: it carries a password. The host and the
    address it resolves to are the two facts that settle where a failure is.
    A private address means DNS found the private zone and the problem is
    further along; a public address, or none at all, means the zone is not
    reachable from here and nothing else matters yet.
    """
    import socket

    report: dict[str, Any] = {"database": "unknown"}
    try:
        url, source = get_settings().require_database_url()
    except Exception as error:
        report["database"] = "not configured"
        report["detail"] = str(error).splitlines()[0]
        # The point of the whole report. Truncating the error to its first line
        # threw away exactly the answer it was written to give.
        report["candidates"] = database_env_candidates()
        return report

    report["source"] = source
    host = _host_of(url)
    report["host"] = host

    try:
        report["resolved_ip"] = socket.gethostbyname(host)
    except Exception as error:
        report["resolved_ip"] = None
        report["dns_error"] = f"{type(error).__name__}: {error}"

    # Connect directly rather than through the pool. psycopg_pool retries in
    # the background and reports only "pool initialization incomplete", which
    # names no cause: it hid a one-character error in a connection string for
    # an afternoon. A direct connect raises what actually went wrong.
    try:
        with psycopg.connect(url, connect_timeout=8) as conn:
            conn.execute("SELECT 1")
        report["database"] = "ok"
    except Exception as error:
        report["database"] = "error"
        report["detail"] = f"{type(error).__name__}: {error}"[:300]
    return report


def _host_of(url: str) -> str:
    if "@" in url:
        return url.rsplit("@", 1)[-1].split("/")[0].split("?")[0].split(":")[0]
    if "host=" in url:
        return url.split("host=", 1)[1].split()[0]
    return "unknown"


def _diagnose(url: str, source: str, error: Exception) -> str:
    """Turn a connection failure into something actionable.

    psycopg reports a refused connection as a timeout, which says nothing about
    why. On Azure there are three usual causes and they are indistinguishable
    from the exception alone, so all three are named.
    """
    host = _host_of(url)

    return (
        f"Could not reach PostgreSQL at {host} "
        f"(connection string from {source}): {type(error).__name__}: {error}\n"
        "Check /health first: it reports the address the host resolves to, "
        "which decides which of these it is.\n"
        "  No address at all, or a public one, on a server using private "
        "networking: the private DNS zone is not reachable from here. Link "
        "the zone to the app's virtual network, or set WEBSITE_DNS_SERVER to "
        "168.63.129.16.\n"
        "  A private address that still will not connect: the app is not "
        "integrated with that virtual network, or is integrated with a "
        "different one.\n"
        "  A public server instead: the firewall is closed. Tick 'Allow public "
        "access from any Azure service within Azure to this server'.\n"
        "  Either kind: a missing sslmode=require is refused outright, and a "
        "paused server answers nothing."
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # A malformed hash in the table should read as "wrong password", not
        # crash the login endpoint.
        return False


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None

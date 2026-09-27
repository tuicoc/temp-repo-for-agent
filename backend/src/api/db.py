"""PostgreSQL access.

One async pool per process, opened on first use. Async because the service
runs on a single event loop: a request waiting on the database must not stop
every other request from being served, and a pooled connection held across an
``await`` costs nothing while it waits. Azure Database for PostgreSQL charges a
real round trip for every new connection, TLS handshake included, so the pool
is small and reused rather than opened per request.

The schema is applied at startup and is written to be safe to run again, so a
deployment that restarts the app does not need a migration step yet. That
stops being true the moment a column changes type; when it does, this is the
place a migration tool goes.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import bcrypt
import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ..agents import CHECKPOINTED_TYPES
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

-- One turn at a time per conversation. A turn claims the lease with a single
-- conditional UPDATE and releases it when done; the expiry is what frees a
-- conversation whose turn died without releasing.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS turn_lease_until TIMESTAMPTZ;

-- The id the browser chose for a turn, on both the question and the answer.
-- Unique per role so that a retried turn replays the stored answer instead of
-- producing a second one. NULL on rows written before the column existed.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS turn_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS messages_turn_idx
    ON messages (conversation_id, turn_id, role) WHERE turn_id IS NOT NULL;

-- Staff roles, docs/design.md section 11. One seeded account, a consultant.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'consultant';

-- A call is the product's unit: it starts, it ends, and ending it is what
-- will enqueue the persist job of section 8.1. The customer is a phone
-- number, kept as a keyed hash (section 5) plus the last four digits for
-- display. The brief and its warnings are stored as rendered at pickup, so
-- the console shows exactly what the agent was given.
CREATE TABLE IF NOT EXISTS calls (
    id               BIGSERIAL PRIMARY KEY,
    -- NULL until the customer is known. A web visitor starts anonymous and
    -- may identify by stating a phone number in the conversation.
    customer_key     TEXT,
    phone_last4      TEXT,
    channel          TEXT NOT NULL CHECK (channel IN ('web', 'hotline', 'zalo', 'facebook')),
    tier             TEXT NOT NULL,
    lane             TEXT NOT NULL,
    mode             TEXT NOT NULL DEFAULT 'speak',
    brief            JSONB NOT NULL DEFAULT '[]',
    warnings         JSONB NOT NULL DEFAULT '[]',
    opened_by        BIGINT REFERENCES users(id) ON DELETE SET NULL,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at         TIMESTAMPTZ,
    turn_lease_until TIMESTAMPTZ
);

-- Tables created before the web channel existed: relax the two columns and
-- widen the channel check. Each statement is safe to run again.
ALTER TABLE calls ALTER COLUMN customer_key DROP NOT NULL;
ALTER TABLE calls ALTER COLUMN phone_last4 DROP NOT NULL;
ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_channel_check;
ALTER TABLE calls ADD CONSTRAINT calls_channel_check
    CHECK (channel IN ('web', 'hotline', 'zalo', 'facebook'));

-- Handoff, docs/design.md section 4.10: a change of mode, not an end. Requested
-- by the customer asking for a person, or by the assistant once the router
-- exists; pending until a consultant claims it with one conditional update.
-- In copilot mode the assistant only drafts; the consultant sends. The draft
-- waits in `suggestion` until it is used, edited or replaced.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS handoff_status TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS handoff_reason TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS handoff_requested_at TIMESTAMPTZ;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS accepted_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS suggestion JSONB;

-- The projection of the hot graph's state that the screens read
-- (docs/design.md section 3.1): who the caller turned out to be, the Call
-- Brief object as built, the business day the call ran on, the channel's
-- own identity, the Handoff Brief, and what after_call left behind.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS customer_id TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS customer_label TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS channel_ref TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_token TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS business_day DATE;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS brief_object JSONB;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS route_reason TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS handoff_brief JSONB;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS memory_status TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS after_call JSONB;

CREATE INDEX IF NOT EXISTS calls_customer_idx ON calls (customer_key, started_at DESC);
CREATE INDEX IF NOT EXISTS calls_open_idx ON calls (started_at DESC) WHERE ended_at IS NULL;

-- One utterance. speaker is who said it; meta carries what the console
-- needs to explain an agent turn: model, confidence, brief lines used, tool
-- calls with arguments and results (section 16.1).
CREATE TABLE IF NOT EXISTS turns (
    id         BIGSERIAL PRIMARY KEY,
    call_id    BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    turn_id    TEXT NOT NULL,
    speaker    TEXT NOT NULL CHECK (speaker IN ('customer', 'agent', 'human_agent', 'system')),
    content    TEXT NOT NULL,
    meta       JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS turns_turn_idx ON turns (call_id, turn_id, speaker);
CREATE INDEX IF NOT EXISTS turns_call_idx ON turns (call_id, created_at);

-- docs/design.md section 4.1: personal data a call carried, one row per
-- token, the value encrypted. The model, the checkpoint and the transcript
-- only ever hold the token. Deleting a customer deletes their rows.
CREATE TABLE IF NOT EXISTS pii_vault (
    call_id     BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    token       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    value_enc   BYTEA NOT NULL,
    customer_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, token)
);
"""

_pool: AsyncConnectionPool | None = None
# Two requests arriving before the pool exists must not each build one. The
# lock is only ever contended once, at startup.
_pool_lock = asyncio.Lock()


async def pool() -> AsyncConnectionPool:
    """The process-wide pool, opened on first use."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is not None:
            return _pool
        settings = get_settings()
        url, source = settings.require_database_url()
        # Which variable it came from, never what was in it. On Azure this is
        # the difference between "the database is not connected" and "it is
        # connected under a name we were not reading".
        logger.info("Connecting to PostgreSQL using %s", source)
        pool_ = AsyncConnectionPool(
            url,
            min_size=1,
            # One core, and Azure's smaller Postgres tiers cap connections
            # low enough that a generous pool is a way to exhaust them. Every
            # other process that will share the server — the cold worker, each
            # MCP server, an evaluation run — draws from the same cap.
            max_size=5,
            open=False,
            # Fail in seconds, not half a minute. A container that dies after
            # thirty seconds of silence tells you nothing.
            timeout=10,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": 10,
                # The LangGraph checkpointer shares this pool and is written
                # for autocommit connections with server-side prepared
                # statements off (its own from_conn_string sets exactly
                # this). Our own queries are single statements, so each one
                # being its own transaction changes nothing for them, and no
                # connection ever sits idle inside an open transaction.
                "autocommit": True,
                "prepare_threshold": 0,
            },
        )
        await pool_.open()
        # Opening the pool does not connect: it retries in the background and
        # the failure would otherwise surface far from here, as a bare
        # PoolTimeout on whichever query ran first. wait() brings it forward.
        try:
            await pool_.wait(timeout=12)
        except Exception as error:
            await pool_.close()
            raise RuntimeError(_diagnose(url, source, error)) from error
        _pool = pool_
        return _pool


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    """A pooled connection. Autocommit, so every statement stands alone."""
    pool_ = await pool()
    async with pool_.connection() as conn:
        yield conn


_checkpointer: AsyncPostgresSaver | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    """Build the LangGraph checkpointer over the shared pool, once.

    This is docs/design.md section 3.1's working memory: the hot graph's
    state per call, in the same database as everything else. ``setup()`` creates its tables
    and is safe to run again, so it belongs with the schema at startup.
    """
    global _checkpointer
    if _checkpointer is None:
        # The serializer rebuilds an agent's structured reply from the
        # checkpoint only for types on its allow-list; an unlisted one is a
        # warning today and a refusal in a later LangGraph.
        serde = JsonPlusSerializer(
            allowed_msgpack_modules=[
                (cls.__module__, cls.__name__) for cls in CHECKPOINTED_TYPES
            ]
        )
        saver = AsyncPostgresSaver(await pool(), serde=serde)
        await saver.setup()
        _checkpointer = saver
        logger.info("Checkpointer ready")
    return _checkpointer


def checkpointer() -> AsyncPostgresSaver:
    """The checkpointer built at startup. Agents are compiled with it."""
    if _checkpointer is None:
        raise RuntimeError(
            "The checkpointer has not been initialised; the app's lifespan "
            "calls init_checkpointer() after init_db()."
        )
    return _checkpointer


def checkpointer_ready() -> bool:
    return _checkpointer is not None


async def ping() -> dict[str, Any]:
    """One round trip, for the health report."""
    try:
        async with connection() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as error:  # noqa: BLE001 - this is the report
        return {"status": "error", "detail": f"{type(error).__name__}: {error}"[:200]}


async def init_db() -> None:
    """Apply the schema and make sure the seeded account exists.

    Several processes starting at once each find a table missing, each create
    it, and the losers fail on a duplicate key in pg_type, because CREATE
    TABLE IF NOT EXISTS is not atomic. The service now runs one worker, so
    this cannot happen in deployment, but ``--reload`` in development restarts
    the process under the same schema and the forgiveness costs nothing.
    Losing a race to create a table that now exists is not a failure.
    """
    settings = get_settings()
    try:
        async with connection() as conn:
            await _apply_schema(conn, settings)
    except (
        psycopg.errors.UniqueViolation,
        psycopg.errors.DuplicateTable,
        psycopg.errors.DuplicateObject,
    ):
        logger.info("Another process created the schema first; continuing")
        async with connection() as conn:
            await _seed_account(conn, settings)


async def _apply_schema(conn: Any, settings: Any) -> None:
    # The pool prepares statements server-side from the first execution, and
    # a string holding several statements cannot be prepared. This one call
    # opts out; every other query in the service is a single statement.
    await conn.execute(SCHEMA, prepare=False)
    await _seed_account(conn, settings)


async def _seed_account(conn: Any, settings: Any) -> None:
    """Create the seeded accounts, or reset their passwords to the settings.

    The staff account is required. The customer account exists only when its
    two settings are set; it is what a tester signs in with to use the chat
    as a customer while the console is open elsewhere.
    """
    await _upsert_user(
        conn,
        settings.require("seed_user_email"),
        settings.require("seed_user_password"),
        role="consultant",
    )
    if settings.seed_customer_email and settings.seed_customer_password:
        await _upsert_user(
            conn, settings.seed_customer_email, settings.seed_customer_password, role="customer"
        )


async def _upsert_user(conn: Any, email: str, password: str, *, role: str) -> None:
    email = email.strip().lower()
    cursor = await conn.execute("SELECT id FROM users WHERE email = %s", (email,))
    existing = await cursor.fetchone()
    # bcrypt is slow on purpose. At startup nobody is waiting, but the habit of
    # keeping it off the event loop is the one that matters at login.
    password_hash = await asyncio.to_thread(hash_password, password)

    if existing is None:
        await conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s)",
            (email, password_hash, role),
        )
        logger.info("Seeded the %s account for %s", role, email)
    else:
        # Rotating the password in the settings should change the password,
        # otherwise the variable is a lie after the first deploy. The role is
        # refreshed for the same reason.
        await conn.execute(
            "UPDATE users SET password_hash = %s, role = %s WHERE id = %s",
            (password_hash, role, existing["id"]),
        )
        logger.info("Refreshed the %s account for %s", role, email)


async def diagnose_connection() -> dict[str, Any]:
    """Everything needed to tell a working database apart from a broken one.

    Never the connection string itself: it carries a password. The host and the
    address it resolves to are the two facts that settle where a failure is.
    A private address means DNS found the private zone and the problem is
    further along; a public address, or none at all, means the zone is not
    reachable from here and nothing else matters yet.
    """
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

    # A blocking DNS lookup, moved off the loop: /health is polled, and a slow
    # resolver must not stall the requests that are actually working.
    try:
        report["resolved_ip"] = await asyncio.to_thread(socket.gethostbyname, host)
    except Exception as error:
        report["resolved_ip"] = None
        report["dns_error"] = f"{type(error).__name__}: {error}"

    # Connect directly rather than through the pool. psycopg_pool retries in
    # the background and reports only "pool initialization incomplete", which
    # names no cause: it hid a one-character error in a connection string for
    # an afternoon. A direct connect raises what actually went wrong.
    try:
        async with await psycopg.AsyncConnection.connect(url, connect_timeout=8) as conn:
            await conn.execute("SELECT 1")
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


async def close_pool() -> None:
    global _pool, _checkpointer
    _checkpointer = None
    if _pool is not None:
        await _pool.close()
        _pool = None

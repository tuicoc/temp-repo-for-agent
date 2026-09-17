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
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import get_settings

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
        _pool = ConnectionPool(
            settings.require("database_url"),
            min_size=1,
            # One core, and Azure's smaller Postgres tiers cap connections
            # low enough that a generous pool is a way to exhaust them.
            max_size=5,
            open=True,
            kwargs={"row_factory": dict_row},
        )
    return _pool


@contextmanager
def connection() -> Iterator[Any]:
    """A pooled connection, committed on success and rolled back on error."""
    with pool().connection() as conn:
        yield conn


def init_db() -> None:
    """Apply the schema and make sure the seeded account exists."""
    settings = get_settings()
    with connection() as conn:
        conn.execute(SCHEMA)

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

"""mcp-memory: the ledger of what the shop knows about each customer.

``docs/design.md`` sections 5 and 6. The one server the brief requires by
name. Its tables:

| Table | Holds |
|---|---|
| ``facts`` | profile: one row per value a slot has had, never overwritten |
| ``episodes`` | one line per call |
| ``identities`` | hashed keys (phone, Zalo, Facebook) to customers; a key may point to several |

Roles decide who may do what (section 6.2), checked here on every call:
``advisor`` and ``harness`` read; ``harness`` may link a key provisionally;
only ``memory_writer`` (the MemoryAgent, after the call) commits facts and
episodes and confirms identities; ``admin`` deletes a customer.

The ledger is append-only (section 5.3). A change of mind closes the old
row's window and opens a new one; ``current`` facts are those active and in
force on the day asked about, so two contradicting values are never live
together. Keys arrive already hashed: the raw phone number never reaches
this server.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from ..server_base import Server, ToolFailure, apply_schema, database

server = Server("memory")

READERS = {"advisor", "harness", "memory_writer", "admin"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id        TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL,
    slot           TEXT NOT NULL,
    value          JSONB NOT NULL,
    kind           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'invalidated', 'disputed')),
    valid_from     DATE NOT NULL,
    valid_to       DATE,
    confidence     REAL NOT NULL DEFAULT 1.0,
    source         JSONB NOT NULL DEFAULT '{}',
    superseded_by  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS facts_customer_idx ON facts (customer_id, slot);
-- The idempotency key of section 5.4: a replayed after_call writes nothing twice.
CREATE UNIQUE INDEX IF NOT EXISTS facts_once_idx ON facts (
    customer_id, slot, (source->>'call_id'), (source->>'turn'), (source->>'extractor_version')
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id       TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL,
    call_id          TEXT NOT NULL,
    channel          TEXT NOT NULL,
    started_at       DATE NOT NULL,
    summary          TEXT NOT NULL,
    outcome          TEXT,
    objection_type   TEXT,
    sentiment        TEXT,
    commitments      JSONB NOT NULL DEFAULT '[]',
    source_turn_span JSONB NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (customer_id, call_id)
);

CREATE TABLE IF NOT EXISTS identities (
    key_type    TEXT NOT NULL CHECK (key_type IN ('phone', 'zalo_id', 'fb_id')),
    key_hash    TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'provisional' CHECK (status IN ('provisional', 'confirmed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (key_type, key_hash, customer_id)
);
"""

KeyType = Literal["phone", "zalo_id", "fb_id"]


def _day(value: str | None) -> date:
    if not value:
        return date.today()
    return datetime.fromisoformat(value[:10]).date()


def _fact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": row["fact_id"],
        "slot": row["slot"],
        "value": row["value"],
        "kind": row["kind"],
        "status": row["status"],
        "valid_from": row["valid_from"].isoformat(),
        "valid_to": row["valid_to"].isoformat() if row["valid_to"] else None,
        "confidence": row["confidence"],
        "source": row["source"],
    }


# ── read ──────────────────────────────────────────────────────────────────


@server.tool(roles=READERS, name="memory_get_profile")
async def memory_get_profile(customer_id: str, on: str | None = None) -> dict[str, Any]:
    """What is known about a customer and still holds on the day of the call.

    Args:
        customer_id: The customer, as identity resolution named them.
        on: The day of the call, YYYY-MM-DD. Set by the system.
    """
    day = _day(on)
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM facts WHERE customer_id = %s AND status IN ('active', 'disputed') "
            "AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s) "
            "ORDER BY valid_from, created_at",
            (customer_id, day, day),
        )
        rows = await cursor.fetchall()
    return {"customer_id": customer_id, "facts": [_fact(r) for r in rows]}


@server.tool(roles=READERS, name="memory_get_episodes")
async def memory_get_episodes(customer_id: str, n: int = 3) -> dict[str, Any]:
    """The customer's last calls, one line each, newest first.

    Args:
        customer_id: The customer.
        n: How many, at most 10.
    """
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM episodes WHERE customer_id = %s ORDER BY started_at DESC, created_at DESC LIMIT %s",
            (customer_id, max(1, min(n, 10))),
        )
        rows = await cursor.fetchall()
    return {
        "episodes": [
            {
                "episode_id": r["episode_id"], "call_id": r["call_id"], "channel": r["channel"],
                "date": r["started_at"].isoformat(), "summary": r["summary"], "outcome": r["outcome"],
                "objection_type": r["objection_type"], "sentiment": r["sentiment"],
                "commitments": r["commitments"],
            }
            for r in rows
        ]
    }


@server.tool(roles=READERS, name="memory_get_open_items")
async def memory_get_open_items(customer_id: str, on: str | None = None) -> dict[str, Any]:
    """Unfinished business: blockers, callbacks, commitments, disputed facts.

    Args:
        customer_id: The customer.
        on: The day of the call. Set by the system.
    """
    profile = await memory_get_profile(customer_id, on)
    open_slots = {"blocker", "callback_at", "commitments", "decision_maker"}
    return {
        "customer_id": customer_id,
        "items": [f for f in profile["facts"] if f["slot"] in open_slots or f["status"] == "disputed"],
    }


@server.tool(roles={"harness", "memory_writer", "admin"}, name="identity_find")
async def identity_find(key_type: KeyType, key_hash: str) -> dict[str, Any]:
    """Customers a hashed key points to. More than one means a shared key.

    Args:
        key_type: phone, zalo_id or fb_id.
        key_hash: The keyed hash of the value, never the value.
    """
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT customer_id, status FROM identities WHERE key_type = %s AND key_hash = %s "
            "ORDER BY created_at",
            (key_type, key_hash),
        )
        rows = await cursor.fetchall()
    return {"matches": [{"customer_id": r["customer_id"], "status": r["status"]} for r in rows]}


# ── write ─────────────────────────────────────────────────────────────────


@server.tool(roles={"harness"}, name="identity_link_provisional")
async def identity_link_provisional(customer_id: str, key_type: KeyType, key_hash: str) -> dict[str, Any]:
    """Note, during a call, that a key seems to belong to a customer. Unconfirmed.

    Args:
        customer_id: The customer.
        key_type: phone, zalo_id or fb_id.
        key_hash: The keyed hash.
    """
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO identities (key_type, key_hash, customer_id) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (key_type, key_hash, customer_id),
        )
    return {"customer_id": customer_id, "status": "provisional"}


@server.tool(roles={"memory_writer"}, name="memory_confirm_identity")
async def memory_confirm_identity(
    keys: list[dict[str, str]], customer_id: str | None = None
) -> dict[str, Any]:
    """Confirm that keys belong to a customer; with no customer, create one.

    Args:
        keys: [{key_type, key_hash}] seen and confirmed in the call.
        customer_id: The customer; omit for a caller the shop has never met.
    """
    customer_id = customer_id or f"N-{uuid.uuid4().hex[:10]}"
    pool = await database()
    async with pool.connection() as conn:
        for key in keys:
            await conn.execute(
                "INSERT INTO identities (key_type, key_hash, customer_id, status) "
                "VALUES (%s, %s, %s, 'confirmed') "
                "ON CONFLICT (key_type, key_hash, customer_id) DO UPDATE SET status = 'confirmed'",
                (key["key_type"], key["key_hash"], customer_id),
            )
    return {"customer_id": customer_id, "confirmed": len(keys)}


@server.tool(roles={"memory_writer"}, name="memory_commit_facts")
async def memory_commit_facts(customer_id: str, decisions: list[dict[str, Any]], on: str) -> dict[str, Any]:
    """Apply the write gate's decisions to the ledger.

    Each decision is {operation: add | update | invalidate | skip, slot, value,
    kind, confidence, source, replaces, disputed, valid_to}. update and
    invalidate close the replaced row on ``on``; nothing is deleted.

    Args:
        customer_id: The customer, confirmed in the call.
        decisions: What to write, from the MemoryAgent.
        on: The day of the call.
    """
    day = _day(on)
    written: list[dict[str, Any]] = []
    pool = await database()
    async with pool.connection() as conn:
        async with conn.transaction():
            for decision in decisions:
                operation = decision.get("operation")
                if operation == "skip":
                    continue
                if operation not in ("add", "update", "invalidate"):
                    raise ToolFailure("BAD_REQUEST", f"Unknown operation {operation!r}")
                new_id = None
                if operation in ("add", "update"):
                    new_id = f"F-{uuid.uuid4().hex[:12]}"
                    cursor = await conn.execute(
                        "INSERT INTO facts (fact_id, customer_id, slot, value, kind, status, valid_from, "
                        "valid_to, confidence, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT DO NOTHING RETURNING fact_id",
                        (
                            new_id, customer_id, decision["slot"],
                            json.dumps(decision.get("value"), ensure_ascii=False),
                            decision.get("kind", "preference"),
                            "disputed" if decision.get("disputed") else "active",
                            day, _day(decision["valid_to"]) if decision.get("valid_to") else None,
                            float(decision.get("confidence", 1.0)),
                            json.dumps(decision.get("source") or {}, ensure_ascii=False),
                        ),
                    )
                    if await cursor.fetchone() is None:
                        continue  # already written by an earlier run of the same call
                if decision.get("replaces"):
                    await conn.execute(
                        "UPDATE facts SET status = 'invalidated', valid_to = %s, superseded_by = %s "
                        "WHERE fact_id = %s AND customer_id = %s",
                        (day, new_id, decision["replaces"], customer_id),
                    )
                source = decision.get("source") or {}
                written.append({
                    "key": decision["slot"],
                    "value": decision.get("value"),
                    "op": {"add": "set", "update": "supersede", "invalidate": "delete"}[operation],
                    "source": f"{source.get('call', 'call')}#turn{source.get('turn', 0)}",
                    "customer_id": customer_id,
                    "fact_id": new_id,
                })
    return {"customer_id": customer_id, "memory_writes": written}


@server.tool(roles={"memory_writer"}, name="memory_commit_episode")
async def memory_commit_episode(customer_id: str, episode: dict[str, Any]) -> dict[str, Any]:
    """Write the call's one-line episode.

    Args:
        customer_id: The customer.
        episode: {call_id, channel, date, summary, outcome, objection_type,
            sentiment, commitments, source_turn_span}.
    """
    episode_id = f"E-{uuid.uuid4().hex[:12]}"
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO episodes (episode_id, customer_id, call_id, channel, started_at, summary, outcome, "
            "objection_type, sentiment, commitments, source_turn_span) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (customer_id, call_id) DO UPDATE SET summary = EXCLUDED.summary, outcome = EXCLUDED.outcome",
            (
                episode_id, customer_id, str(episode["call_id"]), episode.get("channel", "web"),
                _day(episode.get("date")), episode["summary"], episode.get("outcome"),
                episode.get("objection_type"), episode.get("sentiment"),
                json.dumps(episode.get("commitments") or [], ensure_ascii=False),
                json.dumps(episode.get("source_turn_span") or [], ensure_ascii=False),
            ),
        )
    return {"episode_id": episode_id}


@server.tool(roles={"admin"}, name="memory_delete_customer")
async def memory_delete_customer(customer_id: str) -> dict[str, Any]:
    """Forget a customer entirely, on their request (policy QT-06).

    Args:
        customer_id: The customer.
    """
    pool = await database()
    async with pool.connection() as conn:
        counts = {}
        for table in ("facts", "episodes", "identities"):
            cursor = await conn.execute(f"DELETE FROM {table} WHERE customer_id = %s", (customer_id,))
            counts[table] = cursor.rowcount
    return {"customer_id": customer_id, "deleted": counts}


if __name__ == "__main__":
    apply_schema(SCHEMA)
    server.run()

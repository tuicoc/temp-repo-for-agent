"""The call endpoints. ``docs/design.md`` sections 2, 4 and 11.

A call is the product's unit: placed on a channel, the agent speaks first,
turns alternate, and it is hung up. Three channels are simulated, each with
its own key (section 4.2):

| Channel | How it is placed | Key from the connection |
|---|---|---|
| ``web`` | the shop's own chat | none: anonymous until the visitor states a number |
| ``zalo`` | a chat from a Zalo OA identity | the Zalo id |
| ``hotline`` | a phone call, spoken, from a number | the caller's number |

(``facebook`` is accepted too, keyed by the fanpage identity.)

Every turn, typed or spoken, goes through :func:`~src.api.harness.run_turn`
and the hot graph; this module is the HTTP around it. The rules that keep
concurrent callers apart are unchanged:

- one turn at a time per call, claimed with a conditional UPDATE and refused
  with 409, with a lease that expires on its own;
- a turn id chosen by the browser, so a retry replays the stored reply;
- the turn as a background task that survives a dropped connection;
- a keepalive comment while the model works.

Hanging up starts ``after_call``. A handoff turns the call to copilot: a
consultant accepts, the assistant drafts, the consultant sends, and what they
send passes the same hard check as the assistant's drafts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from ..components.guardrails.fallback import LINES
from ..components.guardrails.hard import GuardInput, check
from ..components.handoff import copilot
from ..components.identity import resolver
from ..components.intake import pii
from ..mcp import client as mcp_client
from ..mcp.tools import ToolBox
from . import harness, options, vault as vaults
from .auth import CurrentUser, StaffUser
from .db import connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["calls"])

Channel = Literal["web", "hotline", "zalo", "facebook"]

TURN_LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 15

#: A session nobody has spoken in for this long is over, and remembered.
IDLE_MINUTES = 30

JOINED_MARK = "[consultant joined]"


# ── shapes ────────────────────────────────────────────────────────────────


class StartCall(BaseModel):
    channel: Channel = "web"
    #: The caller's number, for a hotline call: a simulated caller id, any digits.
    phone: str | None = Field(default=None, min_length=3, max_length=24)
    #: The channel's own identity, for Zalo or Facebook.
    channel_id: str | None = Field(default=None, min_length=2, max_length=80)


class TakeTurn(BaseModel):
    turn_id: str = Field(min_length=1, max_length=64)
    #: Absent on the first turn: the customer has picked up and the agent speaks first.
    content: str | None = Field(default=None, min_length=1, max_length=4000)


class HandoffRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class ConsultantReply(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    #: The feedback signal of section 4.6: used is approval, the other two a rejection.
    action: Literal["used", "edited", "own"] = "own"
    #: Send even though the guard warned.
    force: bool = False


class FaqEntry(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=3, max_length=2000)


class Call(BaseModel):
    id: int
    phone_last4: str | None
    channel: str
    channel_ref: str | None = None
    tier: str
    lane: str
    route_reason: str | None = None
    mode: str
    customer_id: str | None = None
    customer_label: str | None = None
    #: {id, text, sensitive, fact_ids}: the console shows every line; the model
    #: only the ones the tier allows.
    brief: list[dict[str, Any]]
    brief_object: dict[str, Any] | None = None
    warnings: list[str]
    business_day: str | None = None
    started_at: str
    ended_at: str | None
    turn_count: int
    handoff_status: str | None = None
    handoff_reason: str | None = None
    handoff_brief: dict[str, Any] | None = None
    accepted_by: int | None = None
    suggestion: dict[str, Any] | None = None
    memory_status: str | None = None
    after_call: dict[str, Any] | None = None


class Turn(BaseModel):
    id: int
    turn_id: str
    speaker: str
    content: str
    meta: dict[str, Any]
    created_at: str


class CallDetail(Call):
    turns: list[Turn]


class ReplyResult(BaseModel):
    sent: bool
    warnings: list[str] = []
    call: Call | None = None


# ── placing and listing ───────────────────────────────────────────────────


@router.post("/calls", response_model=Call, status_code=201)
async def start_call(body: StartCall, user: CurrentUser) -> Call:
    """Place a call. Nothing is said yet: the first turn, sent without
    content, makes the agent speak, and resolves the caller's key."""
    phone = None
    if body.channel == "hotline":
        # A simulated caller id: any number will do. One that reads as a
        # Vietnamese mobile is normalised, so it matches the CRM; any other is
        # kept as typed and is simply a caller the shop has never met.
        digits = re.sub(r"\D", "", body.phone or "")
        phone = pii.normalise_phone(body.phone or "") or digits
        if not 3 <= len(phone) <= 15:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the number the call comes from: 3 to 15 digits.")
    elif body.channel in ("zalo", "facebook") and not body.channel_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"A {body.channel} conversation needs its channel identity.")

    async with connection() as conn:
        cursor = await conn.execute(
            "INSERT INTO calls (customer_key, phone_last4, channel, channel_ref, tier, lane, opened_by, business_day) "
            "VALUES (%s, %s, %s, %s, 'UNKNOWN', 'NEW', %s, %s) RETURNING *",
            (
                resolver.digest("phone", phone, vaults.identity_secret()) if phone else None,
                phone[-4:] if phone else None,
                body.channel,
                body.channel_id if body.channel in ("zalo", "facebook") else None,
                user.id,
                options.business_day(),
            ),
        )
        row = await cursor.fetchone()
    if phone:
        vault = pii.Vault()
        token = vault.put("PHONE", phone)
        await vaults.save(row["id"], vault)
        async with connection() as conn:
            cursor = await conn.execute("UPDATE calls SET caller_token = %s WHERE id = %s RETURNING *", (token, row["id"]))
            row = await cursor.fetchone()
    logger.info("Call %s placed over %s", row["id"], body.channel)
    return _call(row, 0)


@router.get("/calls", response_model=list[Call])
async def list_calls(
    user: StaffUser,
    open_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[Call]:
    """The console's queue: open sessions first, newest first. A session that
    ended with nobody having said anything is a page opened and closed."""
    await _expire_idle()
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT c.*, (SELECT count(*) FROM turns t WHERE t.call_id = c.id AND t.speaker = 'customer') AS turn_count "
            "FROM calls c WHERE (c.ended_at IS NULL OR EXISTS (SELECT 1 FROM turns t WHERE t.call_id = c.id "
            "AND t.speaker = 'customer')) "
            + ("AND c.ended_at IS NULL " if open_only else "")
            + "ORDER BY (c.ended_at IS NULL) DESC, c.started_at DESC LIMIT %s",
            (limit,),
        )
        rows = await cursor.fetchall()
    return [_call(row, row["turn_count"]) for row in rows]


@router.get("/calls/{call_id}", response_model=CallDetail)
async def get_call(call_id: int, user: CurrentUser) -> CallDetail:
    """The call and its transcript. The transcript is kept tokenised; the
    customer sees their own number back, staff see its last four digits."""
    await _expire_idle()
    row = await _call_row(call_id, user)
    vault = await vaults.load(call_id)
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id, turn_id, speaker, content, meta, created_at FROM turns WHERE call_id = %s ORDER BY created_at, id",
            (call_id,),
        )
        turns = await cursor.fetchall()
    reveal = not user.is_staff
    visible = [t for t in turns if t["speaker"] != "system"]
    call = _call(row, sum(1 for t in visible if t["speaker"] == "customer"))
    if call.handoff_brief:
        call.handoff_brief = json.loads(pii.detokenize(json.dumps(call.handoff_brief, ensure_ascii=False), vault, reveal_phone=reveal))
    return CallDetail(
        **call.model_dump(),
        turns=[
            Turn(
                id=t["id"], turn_id=t["turn_id"], speaker=t["speaker"],
                content=pii.detokenize(t["content"], vault, reveal_phone=reveal),
                meta=t["meta"] or {}, created_at=t["created_at"].isoformat(),
            )
            for t in turns
        ],
    )


@router.post("/calls/{call_id}/end", response_model=Call)
async def end_call(call_id: int, user: CurrentUser) -> Call:
    """Hang up. Idempotent. Starts ``after_call`` the first time."""
    await _call_row(call_id, user)
    row = await hang_up(call_id)
    return _call(row, await _customer_turns(call_id))


async def hang_up(call_id: int) -> dict[str, Any]:
    """End the call once, and start ``after_call`` that once. The row after."""
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET ended_at = now(), turn_lease_until = NULL WHERE id = %s AND ended_at IS NULL RETURNING id",
            (call_id,),
        )
        newly = await cursor.fetchone() is not None
        cursor = await conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,))
        row = await cursor.fetchone()
    if newly:
        await _mark_pending(call_id)
        harness.spawn(harness.remember(call_id))
    return row


# ── a turn ────────────────────────────────────────────────────────────────


@router.post("/calls/{call_id}/turn")
async def take_turn(call_id: int, body: TakeTurn, request: Request, user: CurrentUser) -> StreamingResponse:
    """One turn of the call, over Server-Sent Events.

    In order: replay if this turn already has an answer; refuse an ended
    call; claim the lease or refuse; run the turn as a task and stream its
    result. The clock starts when the request reached the API.
    """
    arrived = getattr(request.state, "arrived", None) or time.perf_counter()
    await _expire_idle()
    row = await _call_row(call_id, user)

    stored = await _stored_reply(call_id, body.turn_id)
    if stored is not None:
        return _sse(_replay(stored, await vaults.load(call_id), reveal=not user.is_staff))
    if row["ended_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This session has ended. Start a new one.")
    if body.content is None and await _has_turns(call_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The call is already open; send content.")
    if not await claim_lease(call_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "The assistant is still answering the previous message.")

    async def work() -> harness.Outcome:
        try:
            return await harness.run_turn(row, content=body.content, turn_id=body.turn_id, arrived=arrived,
                                          user_id=str(user.id))
        finally:
            await release_lease(call_id)

    return _sse(_stream(harness.spawn(work())))


def _sse(frames: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(frames, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _stream(task: asyncio.Task[harness.Outcome]) -> AsyncIterator[str]:
    """Keepalives while the turn runs, then the reply, then done.

    Not a token stream: the guard needs a complete reply before the customer
    sees any of it (Appendix E keeps streaming open). No filler line either:
    the organisers do not count one as the answer, and the page shows the
    assistant typing instead.
    """
    while True:
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
        if done:
            break
        yield ": keepalive\n\n"
    outcome = task.result()
    if outcome.kind == "error":
        yield _event("error", {"message": "The assistant could not answer this turn. Try again.", "detail": outcome.error})
        return
    if outcome.kind == "waiting":
        yield _event("waiting", {"for": "consultant"})
    else:
        yield _event("message", {"content": outcome.content, "meta": outcome.meta})
    yield _event("done", {"latency": outcome.latency})


async def _replay(stored: dict[str, Any], vault: pii.Vault, *, reveal: bool) -> AsyncIterator[str]:
    yield _event("message", {"content": pii.detokenize(stored["content"], vault, reveal_phone=reveal),
                             "meta": {**(stored["meta"] or {}), "replayed": True}})
    yield _event("done", {"latency": None, "replayed": True})


# ── handoff and copilot, sections 4.6 and 4.10 ────────────────────────────


@router.post("/calls/{call_id}/handoff", response_model=Call)
async def request_handoff(call_id: int, body: HandoffRequest, user: CurrentUser) -> Call:
    """The customer asks for a person. A change of mode, not an end.

    The assistant hands over on its own through ``handoff.transfer`` when a
    question must go to a person; this is the customer pressing the button.
    Either way the bridging line is said once and the call goes to copilot.
    """
    row = await _call_row(call_id, user)
    if row["ended_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This session has ended.")
    if row["handoff_status"] is None:
        if await _lease_held(call_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "The assistant is still answering. Try again in a moment.")
        reason = body.reason or ("The customer asked for a person" if not user.is_staff else f"Requested by {user.email}")
        turn_id = f"bridge-{call_id}"
        async with connection() as conn:
            cursor = await conn.execute(
                "UPDATE calls SET mode = 'copilot', handoff_status = 'pending', handoff_reason = %s, "
                "handoff_requested_at = now() WHERE id = %s AND handoff_status IS NULL RETURNING *",
                (reason, call_id),
            )
            row = await cursor.fetchone() or row
            await conn.execute(
                "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'agent', %s, %s) "
                "ON CONFLICT (call_id, turn_id, speaker) DO NOTHING",
                (call_id, turn_id, LINES["bridging"], json.dumps({"bridging": True})),
            )
        await harness.add_spoken(call_id, AIMessage(content=LINES["bridging"], id=f"agent-{turn_id}"))
        logger.info("Handoff requested on call %s: %s", call_id, reason)
    return _call(row, await _customer_turns(call_id))


@router.post("/calls/{call_id}/accept", response_model=Call)
async def accept_handoff(call_id: int, user: StaffUser) -> Call:
    """Claim a waiting handoff. One conditional update: two consultants
    pressing at once cannot both win, and the loser is told."""
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET handoff_status = 'accepted', accepted_by = %s, accepted_at = now() "
            "WHERE id = %s AND handoff_status = 'pending' RETURNING *",
            (user.id, call_id),
        )
        row = await cursor.fetchone()
    if row is None:
        existing = await _call_row(call_id, user)
        if existing["handoff_status"] == "accepted":
            raise HTTPException(status.HTTP_409_CONFLICT, "Another consultant already took this conversation.")
        raise HTTPException(status.HTTP_409_CONFLICT, "No handoff is waiting on this conversation.")
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'system', %s, %s) "
            "ON CONFLICT (call_id, turn_id, speaker) DO NOTHING",
            (call_id, f"joined-{call_id}", JOINED_MARK, json.dumps({"joined": user.email})),
        )
    logger.info("Handoff on call %s accepted by %s", call_id, user.email)
    return _call(row, await _customer_turns(call_id))


@router.post("/calls/{call_id}/reply", response_model=ReplyResult)
async def consultant_reply(call_id: int, body: ConsultantReply, user: StaffUser) -> ReplyResult:
    """The consultant answers the customer, in copilot mode.

    Their words pass the same hard check as a draft (section 4.6); a
    violation comes back as warnings, and sending anyway is recorded. The
    choice (used, edited, own) is the feedback signal.
    """
    row = await _call_row(call_id, user)
    if row["ended_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This session has ended.")
    if row["mode"] != "copilot" or row["handoff_status"] != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Accept the handoff before replying.")
    if row["accepted_by"] != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Another consultant holds this conversation.")

    vault = await vaults.load(call_id)
    content = pii.tokenise(body.content.strip(), vault)
    verdict = check(GuardInput(text=content, tool_results=(), tier=row["tier"], tokens=frozenset(vault.entries),
                               customer_said=tuple(await _customer_lines(call_id))))
    # A consultant may quote a price the tools did not give this turn: they
    # are the person accountable. Everything else is a warning to confirm.
    warnings = [r for r in verdict.reasons if not r.startswith("Số tiền")]
    if warnings and not body.force:
        return ReplyResult(sent=False, warnings=warnings)

    suggestion = row["suggestion"] or {}
    signal = copilot.signal_of(copilot.HumanDecision(content, body.action, "sent despite warnings" if warnings else None),
                               suggestion.get("text"))
    turn_id = uuid.uuid4().hex
    meta = {"action": body.action, "consultant": user.email, "suggested": suggestion.get("text"),
            "signal": signal, "warnings": warnings}
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'human_agent', %s, %s)",
            (call_id, turn_id, content, json.dumps(meta, ensure_ascii=False)),
        )
        cursor = await conn.execute("UPDATE calls SET suggestion = NULL WHERE id = %s RETURNING *", (call_id,))
        row = await cursor.fetchone()
    await vaults.save(call_id, vault)
    await harness.add_spoken(call_id, AIMessage(content=content, id=f"human_agent-{turn_id}", name="human_agent"))
    return ReplyResult(sent=True, warnings=warnings, call=_call(row, await _customer_turns(call_id)))


@router.post("/calls/{call_id}/faq")
async def save_faq(call_id: int, body: FaqEntry, user: StaffUser) -> dict[str, Any]:
    """The Gap Loop's step 6c (section 10.2): the consultant saves their answer as a FAQ entry.

    It goes live at once, through ``kb.upsert`` under the ``admin`` role, and
    the Improvement page lists it for QA to revoke. Mock: the entry is saved
    as the consultant wrote it; the model that rewrites it into a general
    answer without the customer's details (step 6b) is not built.
    """
    await _call_row(call_id, user)
    admin = ToolBox(await mcp_client.tools_for("admin"))
    envelope = await admin.call("kb_upsert", source="faq", title=body.question, text=body.answer,
                                provenance={"call_id": call_id, "saved_by": user.email})
    if not envelope.get("ok"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, (envelope.get("error") or {}).get("message", "Could not save"))
    return envelope["data"]


# ── the lease ─────────────────────────────────────────────────────────────


async def claim_lease(call_id: int) -> bool:
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET turn_lease_until = now() + %s * interval '1 second' WHERE id = %s AND ended_at IS NULL "
            "AND (turn_lease_until IS NULL OR turn_lease_until < now()) RETURNING id",
            (TURN_LEASE_SECONDS, call_id),
        )
        return await cursor.fetchone() is not None


async def release_lease(call_id: int) -> None:
    try:
        async with connection() as conn:
            await conn.execute("UPDATE calls SET turn_lease_until = NULL WHERE id = %s", (call_id,))
    except Exception:  # noqa: BLE001 - the lease expires on its own
        logger.exception("Could not release the turn lease on call %s", call_id)


async def _lease_held(call_id: int) -> bool:
    async with connection() as conn:
        cursor = await conn.execute("SELECT 1 FROM calls WHERE id = %s AND turn_lease_until > now()", (call_id,))
        return await cursor.fetchone() is not None


# ── queries ───────────────────────────────────────────────────────────────


async def call_row(call_id: int, user: Any) -> dict[str, Any]:
    return await _call_row(call_id, user)


async def _call_row(call_id: int, user: Any) -> dict[str, Any]:
    """The call, if this user may see it. Staff see every call; a customer
    only the sessions their own sign-in opened."""
    async with connection() as conn:
        cursor = await conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,))
        row = await cursor.fetchone()
    if row is None or (not user.is_staff and row["opened_by"] != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
    return row


async def _expire_idle() -> None:
    """End every open session with no activity for IDLE_MINUTES, and remember it."""
    async with connection() as conn:
        cursor = await conn.execute(
            "UPDATE calls SET ended_at = now(), turn_lease_until = NULL WHERE ended_at IS NULL AND COALESCE("
            "(SELECT max(created_at) FROM turns t WHERE t.call_id = calls.id), started_at"
            ") < now() - %s * interval '1 minute' RETURNING id",
            (IDLE_MINUTES,),
        )
        expired = await cursor.fetchall()
    for row in expired:
        await _mark_pending(row["id"])
        harness.spawn(harness.remember(row["id"]))
    if expired:
        logger.info("Ended %d idle session(s): %s", len(expired), [r["id"] for r in expired])


async def _mark_pending(call_id: int) -> None:
    async with connection() as conn:
        await conn.execute("UPDATE calls SET memory_status = 'pending' WHERE id = %s", (call_id,))


async def _stored_reply(call_id: int, turn_id: str) -> dict[str, Any] | None:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT content, meta FROM turns WHERE call_id = %s AND turn_id = %s AND speaker = 'agent'", (call_id, turn_id)
        )
        return await cursor.fetchone()


async def _has_turns(call_id: int) -> bool:
    async with connection() as conn:
        cursor = await conn.execute("SELECT 1 FROM turns WHERE call_id = %s LIMIT 1", (call_id,))
        return await cursor.fetchone() is not None


async def _customer_turns(call_id: int) -> int:
    async with connection() as conn:
        cursor = await conn.execute("SELECT count(*) AS n FROM turns WHERE call_id = %s AND speaker = 'customer'", (call_id,))
        return int((await cursor.fetchone())["n"])


async def _customer_lines(call_id: int) -> list[str]:
    async with connection() as conn:
        cursor = await conn.execute("SELECT content FROM turns WHERE call_id = %s AND speaker = 'customer'", (call_id,))
        return [r["content"] for r in await cursor.fetchall()]


async def session_counts() -> dict[str, int]:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT count(*) FILTER (WHERE ended_at IS NULL) AS open, "
            "count(*) FILTER (WHERE started_at >= date_trunc('day', now())) AS today, "
            "count(*) FILTER (WHERE handoff_status = 'pending') AS handoffs_waiting FROM calls"
        )
        row = await cursor.fetchone()
    return {k: int(v) for k, v in row.items()}


# ── helpers ───────────────────────────────────────────────────────────────


def _call(row: dict[str, Any], turn_count: int) -> Call:
    return Call(
        id=row["id"],
        phone_last4=row["phone_last4"],
        channel=row["channel"],
        channel_ref=row.get("channel_ref"),
        tier=row["tier"],
        lane=row["lane"],
        route_reason=row.get("route_reason"),
        mode=row["mode"],
        customer_id=row.get("customer_id"),
        customer_label=row.get("customer_label"),
        brief=list(row["brief"] or []),
        brief_object=row.get("brief_object"),
        warnings=list(row["warnings"] or []),
        business_day=row["business_day"].isoformat() if row.get("business_day") else None,
        started_at=row["started_at"].isoformat(),
        ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
        turn_count=int(turn_count),
        handoff_status=row.get("handoff_status"),
        handoff_reason=row.get("handoff_reason"),
        handoff_brief=row.get("handoff_brief"),
        accepted_by=row.get("accepted_by"),
        suggestion=row.get("suggestion"),
        memory_status=row.get("memory_status"),
        after_call=row.get("after_call"),
    )


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

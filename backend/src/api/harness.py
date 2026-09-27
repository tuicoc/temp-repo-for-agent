"""The harness as the API runs it: the hot graph and its collaborators, built once.

``docs/design.md`` sections 2 to 4. One compiled hot graph with the
Postgres checkpointer, shared by every call: it holds no per-call state, the
checkpointer does, per thread ``call-<id>``. The collaborators the graph's
nodes are handed each turn (section 3.2): the AdvisorAgent, the
PolicyAgent, the harness's own MCP tools, and the store ``persist`` writes
through.

:func:`run_turn` is the one way a turn is taken, whether it came as a chat
message over SSE or as speech over the voice WebSocket. It times the turn
the organisers' way (``eval/huong-dan-do-latency.md``): from the request
reaching the API to the answer being ready to emit, in integer
milliseconds. Not streaming, so TTFT equals Total (their rule 7). A filler
line is never counted.

:func:`remember` runs ``after_call`` once a call has ended.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..agents.advisor import AdvisorAgent
from ..agents.memory import MemoryAgent
from ..agents.policy import PolicyAgent
from ..agents.qa import QaAgent
from ..components import clock
from ..components.handoff.render import REASONS
from ..components.intake import itn, pii
from ..components.intake import text as intake_text
from ..mcp import client as mcp_client
from ..mcp.tools import ToolBox
from ..pipeline.cold.after_call import after_call
from ..pipeline.hot.graph import build_graph
from ..pipeline.hot.state import HotContext
from . import options, vault as vaults
from .db import checkpointer, connection

logger = logging.getLogger(__name__)

#: The organisers drop the first three turns as warm-up (their rule 2).
WARMUP_TURNS = 3

#: Tool results kept in a turn's meta in full; the rest are trimmed for the console.
FULL_RESULTS = {"pricing.get_quote", "inventory.check", "order.create", "order.status", "order.update",
                "schedule.callback", "handoff.transfer", "crm.get_customer"}


@dataclass
class Collaborators:
    graph: Any
    advisor: AdvisorAgent
    policy: PolicyAgent
    harness: ToolBox
    memory: MemoryAgent = field(default_factory=MemoryAgent)
    qa: QaAgent = field(default_factory=QaAgent)
    writer: ToolBox | None = None


_built: Collaborators | None = None
_lock = asyncio.Lock()
_turns_timed = 0
_background: set[asyncio.Task[Any]] = set()


async def ready() -> Collaborators:
    """Everything a turn needs, built on first use and shared after."""
    global _built
    if _built is not None:
        return _built
    async with _lock:
        if _built is None:
            advisor_tools, harness_tools = await asyncio.gather(
                mcp_client.tools_for("advisor"), mcp_client.tools_for("harness")
            )
            _built = Collaborators(
                graph=build_graph(checkpointer=checkpointer()),
                advisor=_advisor(advisor_tools),
                policy=PolicyAgent(),
                harness=ToolBox(harness_tools),
            )
    return _built


def _advisor(tools: list[Any]) -> AdvisorAgent:
    overrides = options.advisor_overrides()
    return AdvisorAgent(
        tools=tools,
        provider=overrides.get("provider"),
        model=overrides.get("model"),
        generation={k: v for k, v in overrides.items() if k == "temperature"},
    )


async def rebuild_advisor(*, provider: str | None, model: str | None, temperature: float | None) -> AdvisorAgent:
    """Swap the advisor's model for this process. The graph is untouched: it
    is handed the advisor each turn, and calls in flight finish on the old one."""
    built = await ready()
    options.set_advisor(provider, model, temperature)
    built.advisor = _advisor(await mcp_client.tools_for("advisor"))
    return built.advisor


async def writer() -> ToolBox:
    """The ``memory_writer`` role's tools, opened at the first hang-up."""
    built = await ready()
    if built.writer is None:
        built.writer = ToolBox(await mcp_client.tools_for("memory_writer"), timeout=10.0)
    return built.writer


def status() -> dict[str, Any]:
    if _built is None:
        return {"status": "not built"}
    return {"status": "ok", "model": _built.advisor.model_name, "tools": _built.advisor.tool_names}


def spawn(coroutine: Any) -> asyncio.Task[Any]:
    task = asyncio.create_task(coroutine)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def thread(call_id: int) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"call-{call_id}"}}


# ── one turn ──────────────────────────────────────────────────────────────


@dataclass
class Outcome:
    kind: str  # "message", "waiting" or "error"
    turn_id: str
    content: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    latency: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    #: The reply split for speech, for the voice channel.
    spoken: str | None = None


async def run_turn(
    row: dict[str, Any],
    *,
    content: str | None,
    turn_id: str,
    arrived: float,
    user_id: str | None,
    input_mode: str | None = None,
    asr_confidence: float | None = None,
) -> Outcome:
    """Take one turn through the hot graph; the caller holds the call's lease."""
    global _turns_timed
    built = await ready()
    call_id = int(row["id"])
    vault = await vaults.load(call_id)
    now = clock.at(row.get("business_day") or options.business_day())
    turn_no = await _customer_turns(call_id) + (0 if content is None else 1)
    context = HotContext(
        text=content,
        asr_confidence=asr_confidence,
        caller_phone=vault.get(row["caller_token"]) if row.get("caller_token") else None,
        zalo_id=row.get("channel_ref") if row["channel"] == "zalo" else None,
        fb_id=row.get("channel_ref") if row["channel"] == "facebook" else None,
        vault=vault,
        identity_secret=vaults.identity_secret(),
        user_id=user_id,
        advisor=built.advisor,
        policy=built.policy,
        harness=built.harness,
        store=CallStore(call_id, vault),
    )
    turn_input: dict[str, Any] = {
        "call_id": str(call_id),
        "channel": row["channel"],
        "now": now,
        "on": clock.on(now),
        "switches": {"memory": True},
        "mode": row.get("mode") or "speak",
        "phase": "opening" if content is None else "turn",
        "turn_id": turn_id,
        "turn_no": turn_no,
    }
    if input_mode:
        turn_input["input_mode"] = input_mode
    try:
        state = await built.graph.ainvoke(turn_input, config=thread(call_id), context=context)
    except Exception as error:  # noqa: BLE001 - the page and the call both need to hear about it
        logger.exception("Turn failed on call %s", call_id)
        if content is not None:
            await _store_customer_fallback(call_id, turn_id, content, vault, now)
        await vaults.save(call_id, vault)
        return Outcome("error", turn_id, error=f"{type(error).__name__}: {error}"[:300])
    await vaults.save(call_id, vault, customer_id=state.get("customer_id"))

    total_ms = int((time.perf_counter() - arrived) * 1000)
    _turns_timed += 1
    latency = {
        "ttft_ms": total_ms,
        "total_ms": total_ms,
        "ttfa_ms": None,
        "call_brief_latency_ms": state.get("call_brief_latency_ms"),
        "warmup": _turns_timed <= WARMUP_TURNS,
        "streaming": False,
    }
    suggestion = state.get("suggestion")
    if (row.get("mode") or "speak") == "copilot":
        await _patch_meta(call_id, turn_id, "customer", {"latency": latency})
        return Outcome("waiting", turn_id, meta={"suggestion": bool(suggestion)}, latency=latency)
    reply = state.get("reply") or {}
    text = reply.get("text") or ""
    await _patch_meta(call_id, turn_id, "agent", {"latency": latency})
    shown = pii.detokenize(text, vault)
    meta = {"lane": state.get("lane"), "tier": state.get("tier"), "used_brief_lines": reply.get("used_lines") or [],
            "model": (state.get("draft") or {}).get("model"), "latency": latency}
    return Outcome("message", turn_id, content=shown, meta=meta, latency=latency, spoken=shown)


async def record_ttfa(call_id: int, turn_id: str, ttfa_ms: int, extra: dict[str, Any]) -> None:
    """The voice channel's figure, measured by the voice session and added to the turn."""
    async with connection() as conn:
        await conn.execute(
            "UPDATE turns SET meta = jsonb_set(meta, '{latency}', COALESCE(meta->'latency', '{}'::jsonb) || %s::jsonb) "
            "WHERE call_id = %s AND turn_id = %s AND speaker = 'agent'",
            (json.dumps({"ttfa_ms": int(ttfa_ms), **extra}), call_id, turn_id),
        )


async def keep_heard(call_id: int, turn_id: str, heard: str) -> None:
    """The caller cut the agent off: working memory keeps only what was said (section 4.11)."""
    built = await ready()
    config = thread(call_id)
    snapshot = await built.graph.aget_state(config)
    if not snapshot.values:
        return
    vault = await vaults.load(call_id)
    said = pii.tokenise(heard, vault) if heard else "…"
    await vaults.save(call_id, vault)
    await built.graph.aupdate_state(config, {"messages": [AIMessage(content=said, id=f"agent-{turn_id}")]}, as_node="persist")
    await _patch_meta(call_id, turn_id, "agent", {"interrupted": True, "heard": said})


async def add_spoken(call_id: int, message: AIMessage) -> None:
    """Put words said outside a turn (the consultant's, the bridging line) into the call's thread."""
    built = await ready()
    config = thread(call_id)
    snapshot = await built.graph.aget_state(config)
    if snapshot.values:
        await built.graph.aupdate_state(config, {"messages": [message]}, as_node="persist")


# ── the store persist writes through ──────────────────────────────────────


class CallStore:
    """``persist``'s writes for a live call: the transcript rows and the
    ``calls`` projection the screens read (section 3.1)."""

    def __init__(self, call_id: int, vault: pii.Vault) -> None:
        self.call_id = call_id
        self.vault = vault

    async def persist(self, state: dict[str, Any]) -> None:
        turn_id = state["turn_id"]
        rows: list[tuple[str, str, dict[str, Any]]] = []
        if state.get("phase") == "opening":
            rows.append(("system", "[call connected]", {}))
        else:
            said = next((m for m in reversed(state.get("messages") or [])
                         if isinstance(m, HumanMessage) and m.id == f"customer-{turn_id}"), None)
            if said is not None:
                rows.append(("customer", str(said.content), {"input_mode": state.get("input_mode"), "turn_no": state.get("turn_no")}))
        reply = state.get("reply")
        if reply:
            rows.append(("agent", reply["text"], self._meta(state)))
        async with connection() as conn:
            for speaker, text, meta in rows:
                await conn.execute(
                    "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (call_id, turn_id, speaker) DO NOTHING",
                    (self.call_id, turn_id, speaker, text, json.dumps(meta, ensure_ascii=False, default=str)),
                )
            await self._project(conn, state)

    def _meta(self, state: dict[str, Any]) -> dict[str, Any]:
        draft = state.get("draft") or {}
        return {
            "lane": state.get("lane"), "route_rule": state.get("route_rule"), "route_reason": state.get("route_reason"),
            "tier": state.get("tier"), "model": draft.get("model"), "model_calls": draft.get("model_calls"),
            "advisor_seconds": draft.get("seconds"), "fallback": bool(draft.get("fallback")), "error": draft.get("error"),
            "used_brief_lines": (state.get("reply") or {}).get("used_lines") or [],
            "tool_calls": [self._tool(r) for r in state.get("tool_results") or []],
            "guard": state.get("guard") or {}, "blocked_drafts": state.get("blocked_drafts") or [],
            "regenerations": state.get("regen_count") or 0,
            "call_brief_latency_ms": state.get("call_brief_latency_ms"),
            "handoff": state.get("handoff") if (state.get("handoff") or {}).get("status") == "pending" else None,
            "turn_no": state.get("turn_no"),
        }

    def _tool(self, result: dict[str, Any]) -> dict[str, Any]:
        """A tool call for the console and for after_call, with the phone tokenised."""
        args = json.loads(pii.tokenise(json.dumps(result.get("args") or {}, ensure_ascii=False), self.vault))
        envelope = result.get("result") or {}
        if result.get("name") not in FULL_RESULTS and envelope.get("ok"):
            data = envelope.get("data") or {}
            if "items" in data:
                data = {**data, "items": [{k: i.get(k) for k in ("sku", "name", "list_price_vnd")} for i in data["items"][:8]]}
            if "hits" in data:
                data = {**data, "hits": [{**h, "text": (h.get("text") or "")[:240]} for h in data["hits"]]}
            envelope = {**envelope, "data": data}
        return {"name": result.get("name"), "args": args, "result": envelope, "turn": result.get("turn"),
                "blocked_by": result.get("blocked_by")}

    async def _project(self, conn: Any, state: dict[str, Any]) -> None:
        name = " ".join(x for x in (state.get("honorific"), state.get("customer_name")) if x) or None
        handoff = state.get("handoff") or {}
        await conn.execute(
            "UPDATE calls SET tier = %(tier)s, lane = %(lane)s, customer_id = %(customer_id)s, "
            "customer_label = %(label)s, phone_last4 = COALESCE(%(last4)s, phone_last4), "
            "brief = %(brief)s, brief_object = %(brief_object)s, warnings = %(warnings)s, "
            "route_reason = %(route_reason)s, mode = %(mode)s, "
            "suggestion = CASE WHEN %(copilot)s THEN %(suggestion)s ELSE suggestion END, "
            "handoff_status = CASE WHEN %(handoff)s AND handoff_status IS NULL THEN 'pending' ELSE handoff_status END, "
            "handoff_reason = CASE WHEN %(handoff)s AND handoff_status IS NULL THEN %(reason)s ELSE handoff_reason END, "
            "handoff_requested_at = CASE WHEN %(handoff)s AND handoff_status IS NULL THEN now() ELSE handoff_requested_at END, "
            "handoff_brief = CASE WHEN %(handoff)s THEN %(handoff_brief)s ELSE handoff_brief END "
            "WHERE id = %(id)s",
            {
                "id": self.call_id,
                "tier": state.get("tier") or "UNKNOWN",
                "lane": state.get("lane") or "NEW",
                "customer_id": state.get("customer_id"),
                "label": name,
                "last4": state.get("phone_last4"),
                "brief": json.dumps(state.get("brief_lines") or [], ensure_ascii=False),
                "brief_object": json.dumps(state.get("brief"), ensure_ascii=False, default=str) if state.get("brief") else None,
                "warnings": json.dumps(state.get("freshness") or [], ensure_ascii=False),
                "route_reason": state.get("route_reason"),
                "mode": state.get("mode") or "speak",
                "copilot": state.get("mode") == "copilot",
                "suggestion": json.dumps(state.get("suggestion"), ensure_ascii=False) if state.get("suggestion") else None,
                "handoff": handoff.get("status") == "pending",
                "reason": _reason_label(handoff.get("reason")),
                # Tokenised like the transcript: the brief carries the phone.
                "handoff_brief": pii.tokenise(json.dumps(handoff.get("brief"), ensure_ascii=False, default=str), self.vault)
                if handoff else None,
            },
        )


def _reason_label(code: str | None) -> str | None:
    return f"The assistant handed over: {REASONS.get(code or '', code or 'no reason given')}" if code else None


# ── after the call ────────────────────────────────────────────────────────


async def remember(call_id: int) -> None:
    """``after_call`` for one ended call; its outcome goes on the call's row."""
    try:
        built = await ready()
        snapshot = await built.graph.aget_state(thread(call_id))
        state = snapshot.values or {}
        async with connection() as conn:
            cursor = await conn.execute(
                "SELECT speaker, content, meta FROM turns WHERE call_id = %s AND speaker <> 'system' ORDER BY created_at, id",
                (call_id,),
            )
            turns = await cursor.fetchall()
            cursor = await conn.execute("SELECT channel, business_day FROM calls WHERE id = %s", (call_id,))
            row = await cursor.fetchone()
        transcript, tool_log, number = [], [], 0
        for turn in turns:
            if turn["speaker"] == "customer":
                number += 1
            transcript.append({"speaker": turn["speaker"], "text": turn["content"], "turn": number})
            for call in (turn["meta"] or {}).get("tool_calls") or []:
                tool_log.append({**call, "turn": call.get("turn") or number})
        if not state:
            result = {"status": "skipped", "reason": "nothing was said", "memory_writes": []}
        else:
            call = {
                "call_id": call_id,
                "channel": row["channel"],
                "on": state.get("on") or clock.on(clock.at(row["business_day"] or options.business_day())),
                "tier": state.get("tier"),
                "customer_id": state.get("customer_id"),
                "keys_seen": state.get("keys_seen") or [],
                "returning": bool((state.get("brief") or {}).get("is_returning")),
            }
            result = await after_call(call, transcript, tool_log, writer=await writer(), memory=built.memory, qa=built.qa)
        status = result.get("status", "done")
    except Exception as error:  # noqa: BLE001 - marked, and run again at the next start
        logger.exception("after_call failed on call %s", call_id)
        result, status = {"error": f"{type(error).__name__}: {error}"[:300]}, "failed"
    async with connection() as conn:
        await conn.execute(
            "UPDATE calls SET memory_status = %s, after_call = %s WHERE id = %s",
            (status, json.dumps(result, ensure_ascii=False, default=str), call_id),
        )


async def remember_unfinished(limit: int = 20) -> None:
    """At start: calls that ended without being remembered, or whose after_call failed."""
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id FROM calls WHERE ended_at IS NOT NULL AND (memory_status IS NULL OR memory_status = 'failed') "
            "AND ended_at > now() - interval '2 days' ORDER BY ended_at DESC LIMIT %s",
            (limit,),
        )
        rows = await cursor.fetchall()
    for row in rows:
        await remember(row["id"])


# ── helpers ───────────────────────────────────────────────────────────────


async def _customer_turns(call_id: int) -> int:
    async with connection() as conn:
        cursor = await conn.execute("SELECT count(*) AS n FROM turns WHERE call_id = %s AND speaker = 'customer'", (call_id,))
        return int((await cursor.fetchone())["n"])


async def _patch_meta(call_id: int, turn_id: str, speaker: str, patch: dict[str, Any]) -> None:
    async with connection() as conn:
        await conn.execute(
            "UPDATE turns SET meta = meta || %s::jsonb WHERE call_id = %s AND turn_id = %s AND speaker = %s",
            (json.dumps(patch, ensure_ascii=False), call_id, turn_id, speaker),
        )


async def _store_customer_fallback(call_id: int, turn_id: str, content: str, vault: pii.Vault, now: datetime) -> None:
    """When the graph failed before ``persist``, the customer's words still join the transcript, tokenised."""
    cleaned, _ = intake_text.clean(content)
    tokenised = pii.tokenise(itn.normalise(cleaned, now), vault)
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO turns (call_id, turn_id, speaker, content, meta) VALUES (%s, %s, 'customer', %s, %s) "
            "ON CONFLICT (call_id, turn_id, speaker) DO NOTHING",
            (call_id, turn_id, tokenised, json.dumps({"graph_failed": True})),
        )

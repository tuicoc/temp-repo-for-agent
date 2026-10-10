"""Our agent behind the evaluation harness in ``evaluation/``: the product side of its adapter.

``evaluation/product_adapter.py`` starts this module, one process per scenario
and configuration, and talks to it in JSON lines over stdin and stdout:

| The adapter sends | The bridge answers |
|---|---|
| ``{"mode": "lifecycle", "context", "llm"}`` | ``{"type": "ready", "model", "provider", "parameters"}`` |
| ``{"type": "start_call", "context"}`` | ``{"type": "result", "result": {memory_snapshot, call_brief, identified_at, brief_ready_at}}`` |
| ``{"type": "turn", "text"}`` | ``{"type": "result", "result": {agent_text, mode, request_at, completed_at, usage}}`` |
| ``{"type": "end_call"}`` | ``{"type": "result", "result": {completed, barrier_complete, memory_snapshot}}`` |
| ``{"type": "close"}`` | the process exits |

While a hook runs, the bridge may send ``{"type": "tool", "name", "args"}`` and
wait for ``{"type": "tool_result", "result" | "error"}``: every business tool
is answered by the harness's own copy of the organisers' mock, which records
the call and the state it changed. Memory and knowledge stay on our MCP
servers, in the evaluation database. ``{"type": "event", "event"}`` carries
what the harness asks for beside the hooks (the Handoff Brief's timing).

The agent is the one the API runs: the seven-node graph, ``AdvisorAgent``,
``PolicyAgent``, ``after_call``. Two things differ, both because the harness
requires them: nothing is retried (its ``retry: {agent: 0, tool: 0}``), and
the caller is identified when the call connects, as on the hotline, so the
Call Brief exists before the first turn. ``catalog.search`` keeps the loose
match our catalogue server adds when a name finds nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, TextIO

from ...components import clock
from ...components.intake import pii
from ...config.config_manager import get_models_config
from ...llm import jev, token_ledger
from ...mcp import client as mcp_client
from ...mcp.server_base import ToolFailure, database, failure, ok
from ...mcp.servers import btc
from ...mcp.servers.catalog import _rank
from ..hot import nodes
from ..hot.state import HotContext
from . import runner

logger = logging.getLogger(__name__)

#: The harness's input field or mode, and the product's input mode.
INPUT_MODES = {"asr_transcript": "asr_transcript", "chat_teencode": "chat_teencode",
               "customer_turns_asr": "asr_transcript"}


def parameters(provider: str, model: str) -> dict[str, Any]:
    """The advisor's generation parameters as the manifest pins them."""
    config = get_models_config().llm_config(provider, model, agent="advisor")
    return {"provider": provider, **{k: config.get(k) for k in ("temperature", "max_tokens", "timeout", "max_retries")},
            "retries": 0}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Call:
    thread: str
    context: dict[str, Any]
    channel: str
    keys: dict[str, str | None]
    at: datetime
    memory: bool
    input_mode: str | None
    customer_id: str | None
    vault: pii.Vault = field(default_factory=pii.Vault)
    mode: str = "speak"
    turn: int = 0
    transcript: list[dict[str, Any]] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    last: dict[str, Any] = field(default_factory=dict)


class Bridge:
    def __init__(self, protocol: TextIO) -> None:
        self.protocol = protocol
        self.rig: runner.Rig | None = None
        self.scope: dict[str, Any] = {}
        self.call: Call | None = None
        self.lock = asyncio.Lock()

    # ── the pipe ──────────────────────────────────────────────────────────

    def send(self, message: dict[str, Any]) -> None:
        self.protocol.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
        self.protocol.flush()

    async def receive(self) -> dict[str, Any]:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            raise EOFError("The adapter closed the pipe")
        return json.loads(line)

    # ── business tools, answered by the harness ───────────────────────────

    async def ask(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """One call to the harness's mock, as our MCP servers' envelope."""
        async with self.lock:
            if name == "handoff.transfer":
                at = now()
                self.send({"type": "event", "event": {"kind": "handoff_brief", "object": args.get("brief"),
                                                      "identified_at": at, "ready_at": at}})
            self.send({"type": "tool", "name": name, "args": args})
            reply = await self.receive()
        if reply.get("type") != "tool_result":
            raise RuntimeError(f"Expected a tool result, got {reply.get('type')!r}")
        if "error" in reply:
            # The harness never retries and neither do we: an unknown outcome stays unknown.
            return failure("TOOL_ERROR", f"{name}: {reply['error']}", retryable=False)
        try:
            return ok(btc.unwrap(name, reply["result"]))
        except ToolFailure as fail:
            return failure(fail.code, fail.message, retryable=fail.retryable, details=fail.details)

    async def tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """``ask``, with ``catalog.search``'s loose match as ``mcp/servers/catalog.py`` does it."""
        found = await self.ask(name, args)
        if name != "catalog.search" or not found.get("ok"):
            return found
        if found["data"].get("items") or not args.get("query"):
            return ok({**found["data"], "match": "exact"})
        loose = await self.ask(name, {k: v for k, v in args.items() if k != "query"})
        ranked = _rank(args["query"], ((loose.get("data") or {}).get("items")) or [])
        return ok({"items": ranked[:10], "total": len(ranked), "match": "loose" if ranked else "none"})

    # ── hooks ─────────────────────────────────────────────────────────────

    async def lifecycle(self, message: dict[str, Any]) -> None:
        context = message["context"]
        if any(seed.get("history") for seed in context.get("seed_history") or []):
            raise ValueError("seed_history is not supported: the scenario's past calls would not reach the ledger")
        runner.use_evaluation_database()
        os.environ["MCP_TRANSPORT"] = "stdio"
        llm = message["llm"]
        self.rig = await runner.build(provider=llm["provider"], model=llm["model"], business=self.tool, retries=0)
        await runner.reset()
        self.scope = context
        self.send({"type": "ready", "model": self.rig.advisor.model_name, "provider": self.rig.provider,
                   "parameters": parameters(self.rig.provider, self.rig.advisor.model_name)})

    async def start_call(self, context: dict[str, Any]) -> dict[str, Any]:
        rig = self.rig
        assert rig is not None
        thread = "|".join(context[k] for k in ("run_id", "config", "scenario_id", "call"))
        channel, keys = runner.connection(
            {"scenario_id": context["scenario_id"], "customer_phone": context["customer_phone"]},
            {k: context[k] for k in ("channel", "channel_identity") if k in context},
        )
        at = clock.at(context["on"])
        memory = bool(context["memory_read_previous"])
        call = Call(thread, context, channel, keys, at, memory, INPUT_MODES.get(str(context.get("input_mode"))), None)
        self.call = call

        # The call connects: who is calling, and what the shop knows (section 4.2).
        state = {"call_id": thread, "channel": channel, "now": at, "on": clock.on(at), "switches": {"memory": memory},
                 "mode": "speak", "phase": "opening", "turn_id": "t0", "turn_no": 0, "flags": {}}
        hot = HotContext(vault=call.vault, identity_secret=runner.IDENTITY_SECRET, advisor=rig.advisor,
                         policy=rig.policy, harness=rig.harness, **keys)
        identified = now()
        update = await nodes.load_context(state, SimpleNamespace(context=hot))
        ready = now()
        await rig.graph.aupdate_state({"configurable": {"thread_id": thread}}, {**state, **update}, as_node="load_context")
        call.last = {**state, **update}
        call.customer_id = update.get("customer_id")
        brief = update.get("brief") if memory else None
        return {"memory_snapshot": await self.snapshot(call.customer_id, []), "call_brief": brief,
                "identified_at": identified, "brief_ready_at": ready, "customer_id": call.customer_id or "unidentified"}

    async def turn(self, text: str) -> dict[str, Any]:
        rig, call = self.rig, self.call
        assert rig is not None and call is not None
        call.turn += 1
        before = token_ledger.snapshot()
        request_at = now()
        state, error = await runner.take_turn(
            rig, thread=call.thread, channel=call.channel, keys=call.keys, vault=call.vault, now=call.at,
            memory=call.memory, mode=call.mode, text=text, turn_no=call.turn, input_mode=call.input_mode,
        )
        completed_at = now()
        if error:
            raise RuntimeError(error)
        call.mode = state.get("mode") or call.mode
        call.last = state
        runner.record(state, call.turn, text, call.at, call.vault, call.transcript, call.tool_log)
        if (state.get("draft") or {}).get("error"):
            self.send({"type": "event", "event": {"kind": "advisor_error", "error": state["draft"]["error"]}})
        reply = (state.get("reply") or {}).get("text") or ""
        # The ledger is written after the call, so after a turn it is what it was at the start.
        return {"agent_text": pii.detokenize(reply, call.vault), "mode": "nonstream", "request_at": request_at,
                "completed_at": completed_at, "first_token_at": None, "usage": usage(before, token_ledger.snapshot()),
                "memory_snapshot": await self.snapshot(call.customer_id, [])}

    async def end_call(self) -> dict[str, Any]:
        rig, call = self.rig, self.call
        assert rig is not None and call is not None
        remembered = await runner.remember(rig, thread=call.thread, channel=call.channel, now=call.at,
                                           state=call.last, transcript=call.transcript, tool_log=call.tool_log)
        if remembered.get("status") == "failed":
            self.send({"type": "event", "event": {"kind": "after_call_failed", "error": remembered.get("error")}})
        customer = remembered.get("customer_id") or call.customer_id
        return {"completed": True, "barrier_complete": remembered.get("status") != "failed",
                "outcome": remembered.get("status"),
                "memory_snapshot": await self.snapshot(customer, remembered.get("memory_writes") or [])}

    # ── memory as the harness reads it ────────────────────────────────────

    async def snapshot(self, customer_id: str | None, writes: list[dict[str, Any]]) -> dict[str, Any]:
        """The customer's ledger in the harness's ``MemoryEvidence`` shape."""
        namespace = self.scope["namespace"]
        if not customer_id:
            return {"customer_id": "unidentified", "namespace": namespace, "facts": [], "writes": []}
        pool = await database()
        async with pool.connection() as conn:
            cursor = await conn.execute("SELECT * FROM facts WHERE customer_id = %s ORDER BY created_at", (customer_id,))
            rows = await cursor.fetchall()
        by_id = {row["fact_id"]: row for row in rows}
        facts = [fact for fact in map(memory_fact, rows) if fact is not None]
        written = []
        for item in writes:
            row = by_id.get(item.get("fact_id") or "")
            source = origin(row["source"]) if row else None
            if source is not None:
                written.append({"key": item["key"], "value": item["value"], "op": item["op"],
                                "customer_id": customer_id, "source": source})
        return {"customer_id": customer_id, "namespace": namespace, "facts": facts, "writes": written}


def origin(source: dict[str, Any]) -> dict[str, Any] | None:
    """A fact's source as the turn it came from: ``{context, field}``."""
    parts = str(source.get("call_id") or "").split("|")
    if len(parts) != 4:
        return None
    run_id, config, scenario_id, call = parts
    context = {"run_id": run_id, "config": config, "scenario_id": scenario_id, "call": call,
               "turn": max(1, int(source.get("turn") or 1))}
    return {"context": context, "field": "customer_text" if source.get("said_by") == "customer" else "agent_text"}


def memory_fact(row: dict[str, Any]) -> dict[str, Any] | None:
    """One ledger row as a ``MemoryFact``; a disputed claim is not a fact the shop holds."""
    if row["status"] == "disputed":
        return None
    source = origin(row["source"] or {})
    if source is None:
        return None
    state = "active" if row["status"] == "active" else "superseded" if row["superseded_by"] else "deleted"
    return {"key": row["slot"], "value": row["value"], "customer_id": row["customer_id"], "source": source,
            "valid_from": f"{row['valid_from'].isoformat()}T00:00:00+07:00",
            "valid_until": f"{row['valid_to'].isoformat()}T00:00:00+07:00" if row["valid_to"] else None,
            "state": state}


def usage(before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Tokens of the turn's model calls; no price is pinned, so no cost."""
    def total(key: str) -> int:
        return sum(entry[key] for entry in after.values()) - sum(entry[key] for entry in before.values())

    return {"input_tokens": total("input"), "output_tokens": total("output"), "cost": None, "currency": None}


async def serve(protocol: TextIO) -> None:
    bridge = Bridge(protocol)
    try:
        first = await bridge.receive()
        if first.get("mode") != "lifecycle":
            raise ValueError("The first message must be the lifecycle handshake")
        await bridge.lifecycle(first)
        while True:
            message = await bridge.receive()
            kind = message.get("type")
            if kind == "close":
                break
            if kind == "start_call":
                result = await bridge.start_call(message["context"])
            elif kind == "turn":
                result = await bridge.turn(message["text"])
            elif kind == "end_call":
                result = await bridge.end_call()
            else:
                raise ValueError(f"Unknown message {kind!r}")
            bridge.send({"type": "result", "result": result})
    finally:
        await mcp_client.close_all()
        await jev.close()


def main() -> int:
    # stdout is the protocol: keep a private handle on it and send anything
    # else that prints, from any library, to stderr.
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        asyncio.run(serve(protocol))
    except Exception as error:  # noqa: BLE001 - reported to the adapter, which stops the scenario
        logger.exception("Bridge failed")
        protocol.write(json.dumps({"type": "error", "error_type": type(error).__name__,
                                   "message": str(error)[:500]}, ensure_ascii=False) + "\n")
        protocol.flush()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

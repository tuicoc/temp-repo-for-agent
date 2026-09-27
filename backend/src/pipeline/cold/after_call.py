"""``after_call``: what the call leaves behind. ``docs/design.md`` sections 4.7 and 5.4.

Memory poisoning is stopped here, by rule: facts are written only to a
customer confirmed in the call. VERIFIED writes to that customer and confirms
the keys seen. UNKNOWN with a key (a new caller, a Zalo identity, a number
they typed that matched nobody) creates a customer on those keys. PROBABLE
or AMBIGUOUS at hang-up writes nothing to anyone: the one question was never
answered, and a guess would put one person's facts in another's file.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Sequence

from ...agents.memory import MemoryAgent
from ...agents.qa import QaAgent
from ...components.memory import gate, ledger

logger = logging.getLogger(__name__)


async def after_call(
    call: dict[str, Any],
    transcript: Sequence[dict[str, Any]],
    tool_log: Sequence[dict[str, Any]],
    *,
    writer: Any,
    memory: MemoryAgent,
    qa: QaAgent,
) -> dict[str, Any]:
    """Run both branches; what was written, and how the call was tagged.

    ``call`` is ``{call_id, channel, on, tier, customer_id, keys_seen}``;
    ``transcript`` the spoken turns ``{speaker, text, turn}``, tokenised;
    ``tool_log`` every tool call ``{name, args, result, turn}``; ``writer``
    a ``ToolBox`` holding the ``memory_writer`` role.
    """
    candidates = await memory.extract(transcript, tool_log, on=call["on"])
    remembered, tags = await asyncio.gather(
        _remember(call, candidates, writer=writer, memory=memory),
        qa.tag(candidates, returning=bool(call.get("returning"))),
    )
    score = await qa.score(transcript, tool_log)
    return {**remembered, "tags": tags, "qa": score}


async def _remember(call: dict[str, Any], candidates: list[gate.Candidate], *, writer: Any, memory: MemoryAgent) -> dict[str, Any]:
    tier = call.get("tier") or "UNKNOWN"
    keys = [{"key_type": k["kind"], "key_hash": k["digest"]} for k in call.get("keys_seen") or []]
    if tier in ("PROBABLE", "AMBIGUOUS"):
        return {"status": "skipped", "reason": f"identity still {tier.lower()} at hang-up", "memory_writes": []}
    customer_id = call.get("customer_id") if tier == "VERIFIED" else None
    if customer_id is None and not keys:
        return {"status": "skipped", "reason": "anonymous: no key to remember them by", "memory_writes": []}
    if keys or customer_id is None:
        confirmed = await writer.data("memory_confirm_identity", keys=keys, customer_id=customer_id)
        if not confirmed:
            return {"status": "failed", "reason": "could not confirm the identity", "memory_writes": []}
        customer_id = confirmed["customer_id"]

    profile, history = await asyncio.gather(
        writer.data("memory_get_profile", customer_id=customer_id, on=call["on"]),
        writer.data("memory_get_episodes", customer_id=customer_id, n=10),
    )
    current = list((profile or {}).get("facts") or [])
    number = len((history or {}).get("episodes") or []) + 1
    source = {"call_id": str(call["call_id"]), "call": f"call_{number}", "channel": call.get("channel")}
    # Within one call the newest word wins: "phòng 20 mét... à không, 25".
    latest = {c.slot: c for c in candidates if c.slot}
    decisions = []
    for candidate in latest.values():
        verdict = gate.check(candidate, current, open_notes=0)
        if not verdict.passed:
            continue
        decision = ledger.plan(candidate, verdict, current, source=source, on=call["on"])
        if decision.operation != "skip":
            decisions.append(decision)
    committed = await writer.data("memory_commit_facts", customer_id=customer_id,
                                  decisions=[d.as_dict() for d in decisions], on=call["on"])
    episode = await memory.summarize(candidates, call_number=number, day=call["on"], channel=call.get("channel") or "web")
    await writer.data("memory_commit_episode", customer_id=customer_id, episode={
        "call_id": str(call["call_id"]), "channel": call.get("channel"), "date": call["on"], **episode,
        "source_turn_span": [min((c.turn for c in candidates), default=0), max((c.turn for c in candidates), default=0)],
    })
    writes = (committed or {}).get("memory_writes") or []
    logger.info("after_call %s: %d facts written for %s", call["call_id"], len(writes), customer_id)
    return {"status": "done", "customer_id": customer_id, "memory_writes": writes, "episode": episode["summary"]}


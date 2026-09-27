"""The hot graph's seven nodes. ``docs/design.md`` section 4.

Each node builds the input a component or an agent declares from
:class:`~.state.HotState`, calls it, and writes the result back into the
keys it owns. What a step *does* is documented where it is done, in the
module each docstring names. Collaborators arrive through
``runtime.context`` (:class:`~.state.HotContext`), never as module globals.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.runtime import Runtime

from ...agents.advisor import AgentContext
from ...agents.policy import PolicyInput
from ...components.context import compact
from ...components.guardrails import fallback
from ...components.guardrails.hard import GuardInput, check
from ...components.identity import resolver
from ...components.intake import itn, pii, text as intake_text
from ...components.memory import brief as briefs
from ...components.memory import recall
from ...components.memory.brief import BriefLine
from ...components.orchestration.rules import RouteInput, decide
from ...mcp.tools import INFRASTRUCTURE_CODES
from .state import TURN_KEYS, HotContext, HotState

logger = logging.getLogger(__name__)

#: Section 4.5: two regenerations, then the safe line.
MAX_REGENERATIONS = 2

#: Below this the recogniser's confidence sends the turn to CLARIFY.
ASR_LOW_CONFIDENCE = 0.45

CITATION = re.compile(r"\s*\[(B\d+)\]")


# ── 1. perceive ───────────────────────────────────────────────────────────


async def perceive(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.1, ``components.intake``: clean, NFC, ITN, tokenise.

    Writes the tokenised utterance to ``messages`` under ``customer-<turn_id>``
    (a retried turn replaces its first copy), the input mode, and
    ``flags.new_key`` when the words carry a phone number the call has not
    seen; clears the previous turn's keys. The opening turn has no words.
    """
    context = runtime.context
    update: dict[str, Any] = {**TURN_KEYS, "flags": {"asr_low_conf": False, "new_key": False}}
    raw = (context.text or "").strip()
    if state.get("phase") == "opening" or not raw:
        return update

    cleaned, teencode = intake_text.clean(raw)
    written = itn.normalise(cleaned, state["now"])
    tokenised = pii.tokenise(written, context.vault)
    seen = {k["digest"] for k in state.get("keys_seen") or []}
    # A phone number in the words the call has not seen yet is a new key.
    new_phones = [
        token for token in dict.fromkeys(m.group(0) for m in pii.TOKEN.finditer(tokenised) if m.group(1) == "PHONE")
        if resolver.digest("phone", context.vault.get(token) or "", context.identity_secret) not in seen
    ]
    mode = state.get("input_mode") or ("chat_teencode" if teencode else "clean")
    low = context.asr_confidence is not None and context.asr_confidence < ASR_LOW_CONFIDENCE
    update.update(
        input_mode=mode,
        messages=[HumanMessage(content=tokenised, id=f"customer-{state['turn_id']}")],
        flags={"asr_low_conf": low, "new_key": bool(new_phones), "new_phone_tokens": new_phones},
    )
    return update


# ── 2. load_context: resolve, retrieve, refresh ───────────────────────────


async def load_context(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.2: who is speaking, and what the shop knows about them.

    Works on the opening turn (keys from the connection), on a turn that
    brings a new key, and on the answer to a confirming question. Every other
    turn passes straight through. The Call Brief's latency runs from the
    identification event to the brief being ready, ``refresh`` included.
    """
    context = runtime.context
    flags = state.get("flags") or {}
    opening = state.get("phase") == "opening"
    tier = state.get("tier") or "UNKNOWN"
    answer = _last_customer_text(state)

    if not opening and not flags.get("new_key"):
        if tier == "PROBABLE" and state.get("awaiting") == "confirm" and answer:
            verdict = resolver.confirms(answer)
            if verdict is True:
                started = time.perf_counter()
                return {"tier": "VERIFIED", "awaiting": None, **await _brief(state, context, started)}
            if verdict is False:
                # Not them: a new customer on this key, and nothing of the other's.
                return {"tier": "UNKNOWN", "customer_id": None, "awaiting": None, "brief": None,
                        "brief_lines": [], "freshness": [], "customer_name": None, "honorific": None}
        if tier == "AMBIGUOUS" and answer:
            chosen = resolver.pick_by_name(answer, [resolver.Match(**c) for c in state.get("candidates") or []])
            if chosen is not None:
                started = time.perf_counter()
                bound = {"customer_id": chosen.customer_id, "customer_name": chosen.name,
                         "honorific": chosen.honorific, "tier": "VERIFIED", "awaiting": None, "candidates": []}
                return {**bound, **await _brief({**state, **bound}, context, started)}
        return {}

    started = time.perf_counter()
    keys = _keys(state, context, opening=opening)
    if not keys:
        return {}
    keys_seen = list(state.get("keys_seen") or []) + [
        {"kind": k.kind, "digest": k.digest, "last4": k.last4, "from_connection": k.from_connection} for k in keys
    ]
    if tier == "VERIFIED":
        return {"keys_seen": keys_seen}

    matches, crm_by_customer = await _look_up(keys, context)
    from_connection = any(k.from_connection for k in keys)
    tier = resolver.decide(matches, from_connection=from_connection)
    phone = next((k.value for k in keys if k.kind == "phone"), None)
    update: dict[str, Any] = {"keys_seen": keys_seen, "tier": tier}
    if phone:
        update["phone_last4"] = phone[-4:]
        update["phone_token"] = context.vault.put("PHONE", phone)

    if tier == "UNKNOWN":
        return update
    if tier == "AMBIGUOUS":
        update.update(candidates=[m._asdict() | {"phone": None} for m in matches], awaiting="name",
                      customer_id=None, brief=None, brief_lines=[])
        return update

    match = matches[0]
    if match.phone and not phone:
        update["phone_token"] = context.vault.put("PHONE", match.phone)
        update["phone_last4"] = match.phone[-4:]
    update.update(customer_id=match.customer_id, customer_name=match.name, honorific=match.honorific,
                  awaiting="confirm" if tier == "PROBABLE" else None)
    if tier == "PROBABLE" and context.harness is not None:
        for key in keys:
            await context.harness.call("identity_link_provisional", customer_id=match.customer_id,
                                       key_type=key.kind, key_hash=key.digest)
    merged = {**state, **update, "crm": crm_by_customer.get(match.customer_id) or {}}
    update.update(await _brief(merged, context, started))
    return update


def _keys(state: HotState, context: HotContext, *, opening: bool) -> list[resolver.Key]:
    secret = context.identity_secret
    if opening:
        keys = []
        if context.caller_phone:
            keys.append(resolver.make_key("phone", context.caller_phone, secret, from_connection=True))
        if context.zalo_id:
            keys.append(resolver.make_key("zalo_id", context.zalo_id, secret, from_connection=True))
        if context.fb_id:
            keys.append(resolver.make_key("fb_id", context.fb_id, secret, from_connection=True))
        return keys
    tokens = (state.get("flags") or {}).get("new_phone_tokens") or []
    return [
        resolver.make_key("phone", context.vault.get(token) or "", secret, from_connection=False)
        for token in tokens if context.vault.get(token)
    ]


async def _look_up(keys: list[resolver.Key], context: HotContext) -> tuple[list[resolver.Match], dict[str, dict]]:
    """The organisers' CRM and the ledger's identities, in parallel."""
    harness = context.harness
    if harness is None:
        return [], {}
    lookups = []
    for key in keys:
        lookups.append(harness.data("crm_get_customer", **{key.kind: key.value}))
        lookups.append(harness.data("identity_find", key_type=key.kind, key_hash=key.digest))
    answers = await asyncio.gather(*lookups)
    matches: dict[str, resolver.Match] = {}
    crm: dict[str, dict] = {}
    for index, answer in enumerate(answers):
        if not answer:
            continue
        if index % 2 == 0:
            for match in resolver.matches_from_crm(answer):
                matches[match.customer_id] = match
                if not answer.get("ambiguous"):
                    crm[match.customer_id] = answer
                else:
                    candidate = next((c for c in answer.get("candidates") or [] if c["customer_id"] == match.customer_id), {})
                    crm[match.customer_id] = candidate
        else:
            for row in answer.get("matches") or []:
                matches.setdefault(row["customer_id"], resolver.Match(row["customer_id"], source="ledger"))
    return list(matches.values()), crm


async def _brief(state: dict[str, Any], context: HotContext, started: float) -> dict[str, Any]:
    """Retrieve (the memory switch), refresh, render: the brief and its latency."""
    harness = context.harness
    customer_id = state.get("customer_id")
    if harness is None or not customer_id:
        return {}
    memory_on = bool((state.get("switches") or {}).get("memory", True))
    crm = state.get("crm")
    if crm is None and memory_on:
        phone = context.vault.get(state.get("phone_token") or "")
        crm = await harness.data("crm_get_customer", phone=phone) if phone else {}
        if crm and crm.get("ambiguous"):
            crm = next((c for c in crm.get("candidates") or [] if c["customer_id"] == customer_id), {})
    found = await recall.retrieve(customer_id, state["on"], harness, crm=crm, memory_on=memory_on)
    phone = context.vault.get(state.get("phone_token") or "")
    products, orders, warnings = [], [], []
    if memory_on:
        products = recall.advised(found["facts"], found["orders"])
        products, orders, warnings = await recall.refresh(
            products, found["orders"], found["episodes"], state["on"], harness, customer_phone=phone,
        )
    latency_ms = int((time.perf_counter() - started) * 1000)
    brief, lines = briefs.render(
        customer={"customer_id": customer_id, "name": state.get("customer_name"), "honorific": state.get("honorific"),
                  "phone_last4": state.get("phone_last4")},
        facts=found["facts"], episodes=found["episodes"], orders=orders, products=products,
        warnings=warnings, now=state["now"], latency_ms=latency_ms,
    )
    return {
        "brief": brief,
        "brief_lines": [line.as_dict() for line in lines],
        "freshness": warnings,
        "call_brief_latency_ms": latency_ms if brief["is_returning"] else None,
        "known_orders": [o.get("order_id") for o in orders if o.get("order_id")],
    }


# ── 3. route ──────────────────────────────────────────────────────────────


async def route(state: HotState) -> dict[str, Any]:
    """Section 4.3, ``components.orchestration.rules``: the lane, by rules."""
    decision = decide(RouteInput(
        tier=state.get("tier") or "UNKNOWN",
        has_brief=bool(state.get("brief_lines")),
        brief_mismatch=False,
        has_order=bool(state.get("known_orders")),
        asr_low_conf=bool((state.get("flags") or {}).get("asr_low_conf")),
        tool_failures=int(state.get("tool_failures") or 0),
        safe_lines=int(state.get("safe_lines") or 0),
        customer_said=_last_customer_text(state),
    ))
    return {"lane": decision.lane, "route_rule": decision.rule, "route_reason": decision.reason}


# ── 4. advisor ────────────────────────────────────────────────────────────


async def advisor(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.4, ``AdvisorAgent``: the draft, from the slice of section 3.2.

    Folds old turns into ``working_summary`` once the call grows long. Below
    VERIFIED the model is not shown a brief line carrying a price, an address
    or an order code: withheld here, not merely forbidden in the prompt.
    """
    context = runtime.context
    update: dict[str, Any] = {}
    messages = list(state.get("messages") or [])
    summary = state.get("working_summary")
    folded, kept = compact.split(messages)
    if folded:
        summary = compact.fold(folded, summary)
        update["working_summary"] = summary
        update["messages"] = [RemoveMessage(id=m.id) for m in folded if m.id]
        messages = kept

    tier = state.get("tier") or "UNKNOWN"
    lines = [BriefLine(l["id"], l["text"], l["sensitive"], tuple(l.get("fact_ids") or ())) for l in state.get("brief_lines") or []]
    if tier == "PROBABLE":
        lines = [line for line in lines if not line.sensitive]
    elif tier != "VERIFIED":
        lines = []
    brief = state.get("brief") or {}
    phone = context.vault.get(state.get("phone_token") or "")
    products = brief.get("products_advised") or []
    agent_context = AgentContext(
        call_id=str(state["call_id"]),
        customer_id=state.get("customer_id") if tier == "VERIFIED" else None,
        address_as=" ".join(x for x in (state.get("honorific"), state.get("customer_name")) if x) or None
        if tier == "VERIFIED" else None,
        tier=tier,
        lane=state.get("lane") or "NEW",
        mode=state.get("mode") or "speak",
        phase=state.get("phase") or "turn",
        channel=state.get("channel") or "web",
        now=state.get("now"),
        on=state.get("on"),
        brief_lines=tuple(lines),
        warnings=tuple(state.get("freshness") or []) if tier == "VERIFIED" else (),
        must_not_ask=tuple(brief.get("must_not_ask") or []) if tier == "VERIFIED" else (),
        working_summary=summary,
        block_reasons=tuple(state.get("block_reasons") or []),
        tool_results=tuple(state.get("tool_results") or []),
        quotes=dict(state.get("quotes") or {}),
        known_orders=frozenset(state.get("known_orders") or []),
        customer_phone=phone,
        handoff_defaults={
            "customer_phone": phone or "",
            "customer_name": state.get("customer_name"),
            "customer_id": state.get("customer_id"),
            "channel": {"web": "web_chat", "hotline": "hotline", "zalo": "zalo_oa", "facebook": "chat_fanpage"}.get(state.get("channel") or "web", "other"),
            "product_advised": products[0]["sku"] if products else None,
            "price_quoted_vnd": products[0].get("price_quoted_vnd") if products else None,
            "generated_at": state["now"].isoformat(),
        },
        switches=dict(state.get("switches") or {}),
    )
    turn_messages = messages or [HumanMessage(content="(Khách vừa bắt máy.)", id="opening")]
    try:
        draft = await context.advisor.draft(turn_messages, agent_context, user_id=context.user_id)
    except Exception as error:  # noqa: BLE001 - section 4.9: a failure is never silence
        logger.exception("Advisor failed on call %s", state.get("call_id"))
        update["draft"] = {"text": fallback.LINES["model_error"], "fallback": True, "error": _readable(error)}
        update["tool_failures"] = int(state.get("tool_failures") or 0)
        return update

    new_results = [{**r, "turn": state.get("turn_no") or 0} for r in draft.tool_results]
    results = list(state.get("tool_results") or []) + new_results
    quotes = dict(state.get("quotes") or {})
    orders = list(state.get("known_orders") or [])
    failures = int(state.get("tool_failures") or 0)
    for result in new_results:
        envelope = result.get("result") or {}
        data = envelope.get("data") or {}
        if envelope.get("ok"):
            failures = 0
            if result["name"] == "pricing.get_quote" and data.get("sku"):
                quotes[data["sku"]] = int(data["final_price_vnd"])
            for order in data.get("orders") or ([data] if data.get("order_id") else []):
                if order.get("order_id") and order["order_id"] not in orders:
                    orders.append(order["order_id"])
        elif (envelope.get("error") or {}).get("code") in INFRASTRUCTURE_CODES:
            failures += 1
    update.update(
        draft={"text": draft.text, "model": draft.model, "model_calls": draft.model_calls,
               "seconds": round(draft.seconds, 3)},
        tool_results=results,
        quotes=quotes,
        known_orders=orders,
        tool_failures=failures,
    )
    return update


# ── 5. guard ──────────────────────────────────────────────────────────────


async def guard(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.5: the hard check, then ``PolicyAgent`` on Jev.

    Blocked with regenerations left: back to the advisor with the reasons.
    Blocked with none left: the lane's safe line, counted (two in a call send
    the next turn to HANDOFF). In copilot mode nothing is regenerated: the
    verdict travels with the suggestion as a warning for the consultant.
    """
    context = runtime.context
    draft = state.get("draft") or {}
    if draft.get("fallback"):
        return {"guard": {"passed": True, "fallback": True}}
    text = CITATION.sub("", draft.get("text") or "")
    results = tuple(state.get("tool_results") or [])
    brief = state.get("brief") or {}
    tier = state.get("tier") or "UNKNOWN"
    policy = tuple(
        hit.get("text") or "" for r in results if r.get("name") == "kb.search"
        for hit in ((r.get("result") or {}).get("data") or {}).get("hits") or [] if hit.get("text")
    )
    hard = check(GuardInput(
        text=text,
        tool_results=results,
        tier=tier,
        customer_said=tuple(m.content for m in state.get("messages") or [] if isinstance(m, HumanMessage)),
        policy_texts=policy,
        brief_prices=tuple(int(p["price_quoted_vnd"]) for p in brief.get("products_advised") or [] if p.get("price_quoted_vnd")),
        tokens=frozenset(context.vault.entries),
    ))
    verdict: dict[str, Any] = {"hard": {"passed": hard.passed, "reasons": list(hard.reasons)}}
    reasons = list(hard.reasons)
    if hard.passed and context.policy is not None:
        soft = await context.policy.review(PolicyInput(text=text, tool_results=results, tier=tier, policy_snippets=policy))
        verdict["soft"] = {"passed": soft.passed, "reasons": list(soft.reasons), "decided_by": soft.decided_by,
                           "probabilities": soft.probabilities, "seconds": soft.seconds}
        reasons += list(soft.reasons)
    passed = not reasons
    verdict["passed"] = passed
    if passed or state.get("mode") == "copilot":
        return {"guard": verdict}

    blocked = list(state.get("blocked_drafts") or []) + [{"text": draft.get("text"), "reasons": reasons}]
    regenerations = int(state.get("regen_count") or 0)
    if regenerations < MAX_REGENERATIONS:
        return {"guard": verdict, "block_reasons": reasons, "blocked_drafts": blocked, "regen_count": regenerations + 1}
    line = fallback.safe_line(state.get("lane") or "NEW")
    logger.warning("Call %s: draft blocked %d times, safe line said", state.get("call_id"), regenerations + 1)
    return {
        "guard": {**verdict, "fallback": True},
        "blocked_drafts": blocked,
        "draft": {**draft, "text": line, "fallback": True},
        "safe_lines": int(state.get("safe_lines") or 0) + 1,
    }


def after_guard(state: HotState) -> str:
    """Regenerate while the guard blocks and regenerations are left, else respond."""
    verdict = state.get("guard") or {}
    if verdict.get("passed") or verdict.get("fallback") or state.get("mode") == "copilot":
        return "respond"
    return "advisor"


# ── 6. respond ────────────────────────────────────────────────────────────


async def respond(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.6: say it, or hand it to the consultant.

    The ``[Bn]`` marks are stripped and kept as the lines used. In speak
    mode the reply joins ``messages``, tokenised; the API restores the
    customer's own tokens when it sends it. A successful ``handoff.transfer``
    this turn adds the bridging line once and turns the call to copilot. In
    copilot mode the draft becomes a suggestion for the consultant, with the
    guard's warnings, and nothing is said to the customer.
    """
    draft = state.get("draft") or {}
    raw = draft.get("text") or ""
    used = list(dict.fromkeys(CITATION.findall(raw)))
    text = re.sub(r"\s{2,}", " ", CITATION.sub("", raw)).strip()
    turn_id = state["turn_id"]

    if state.get("mode") == "copilot":
        verdict = state.get("guard") or {}
        warnings = list((verdict.get("hard") or {}).get("reasons") or []) + list((verdict.get("soft") or {}).get("reasons") or [])
        if fallback.is_bridging(text):
            return {"suggestion": None}
        return {"suggestion": {"text": text, "used_lines": used, "warnings": warnings, "turn_id": turn_id}}

    update: dict[str, Any] = {}
    handoff = next(
        (r for r in state.get("tool_results") or [] if r.get("name") == "handoff.transfer" and (r.get("result") or {}).get("ok")),
        None,
    )
    if handoff is not None:
        if not fallback.is_bridging(text):
            text = f"{text} {fallback.LINES['bridging']}".strip()
        brief = (handoff.get("args") or {}).get("brief") or {}
        update["mode"] = "copilot"
        update["handoff"] = {
            "status": "pending",
            "ticket_id": ((handoff.get("result") or {}).get("data") or {}).get("ticket_id"),
            "reason": brief.get("escalation_reason"),
            "brief": brief,
        }
    update["reply"] = {"text": text, "used_lines": used}
    update["messages"] = [AIMessage(content=text, id=f"agent-{turn_id}")]
    return update


# ── 7. persist ────────────────────────────────────────────────────────────


async def persist(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.7: the checkpointer has saved working memory by now; this
    writes the transcript row and the ``calls`` projection through the store
    the caller handed in (the API's tables, or the evaluation runner's trace)."""
    store = runtime.context.store
    if store is not None:
        await store.persist(state)
    return {}


# ── helpers ───────────────────────────────────────────────────────────────


def _last_customer_text(state: HotState) -> str | None:
    for message in reversed(state.get("messages") or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return None


def _readable(error: Exception) -> str:
    text = f"{type(error).__name__}: {error}".lower()
    if any(m in text for m in ("429", "rate limit", "quota", "resource_exhausted")):
        return "The model hit its rate limit."
    if "timeout" in text or "timed out" in text:
        return "The model did not answer in time."
    if "api key" in text or "not set" in text or "401" in text:
        return "The model is not configured on this server."
    return f"{type(error).__name__}"

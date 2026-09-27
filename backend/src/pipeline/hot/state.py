"""The hot graph's state. ``docs/design.md`` section 3.1.

One ``TypedDict``, checkpointed by the hot graph's own checkpointer under
``thread_id = call-<id>``. Each customer turn is one invocation on that
thread; the checkpointer restores the rest, so working memory needs no table
of its own. The ``calls`` table is a projection of this state for the
screens, never a second place state is kept. No agent has a checkpointer:
each is handed a slice of this and returns a result (section 3.2).

Three rules shape this file.

**Raw input is not state.** Whatever is a key here is written to the
checkpoint. The customer's words before ``perceive`` tokenises them, the
number a call came from, the vault that maps ``<PHONE_1>`` back to digits:
all arrive in :class:`HotContext`, which LangGraph hands to nodes and never
persists. Only the tokenised utterance reaches ``messages``.

**Last writer wins, except for messages.** The graph has no parallel branch
(``load_context`` fans out inside one node), so no key is written twice in
one step.

**Per-turn keys are reset by** ``perceive``. The checkpointer restores the
previous turn's draft, tool results and verdicts along with everything else;
:data:`TURN_KEYS` is what ``perceive`` clears so none of it leaks forward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from ...components.identity.resolver import Tier
from ...components.intake.pii import Vault
from ...components.orchestration.rules import Lane

Mode = Literal["speak", "copilot"]
Channel = Literal["web", "hotline", "zalo", "facebook"]
#: "opening" when the customer has just picked up and the agent speaks first.
Phase = Literal["opening", "turn"]
InputMode = Literal["clean", "asr_transcript", "chat_teencode"]


class TurnInput(TypedDict, total=False):
    """What one invocation brings in: the graph's input schema. No personal data."""

    call_id: str
    channel: Channel
    #: The virtual clock (Appendix A). The API sets the business day, the
    #: evaluation runner the scenario's day. No node reads the system clock.
    now: datetime
    #: ``YYYY-MM-DD``, the day of ``now`` in Vietnam: every tool's ``on``.
    on: str
    #: ``{"memory": bool}``: off is the baseline (section 9.5).
    switches: dict[str, Any]
    mode: Mode
    phase: Phase
    turn_id: str
    #: The customer's turn number in this call, for the trace.
    turn_no: int
    input_mode: InputMode


class HotState(TurnInput, total=False):
    """Section 3.1. The comment on each group is the node that writes it."""

    # load_context
    customer_id: str | None
    tier: Tier
    #: Hashes of the keys seen in this call: {kind, digest, last4, from_connection}.
    keys_seen: list[dict[str, Any]]
    #: For AMBIGUOUS: who the key might be, without anything about them.
    candidates: list[dict[str, Any]]
    customer_name: str | None
    honorific: str | None
    phone_last4: str | None
    #: The vault token of the customer's phone, never the number.
    phone_token: str | None
    #: A confirming question is out: "confirm" (PROBABLE) or "name" (AMBIGUOUS).
    awaiting: str | None
    brief: dict[str, Any] | None
    brief_lines: list[dict[str, Any]]
    freshness: list[str]
    #: Set on the turn the brief was built, cleared on every other.
    call_brief_latency_ms: int | None
    known_orders: list[str]

    # perceive, respond (and the API, for a consultant's words)
    messages: Annotated[list[AnyMessage], add_messages]

    # advisor (compaction)
    working_summary: str | None

    # route
    lane: Lane
    route_rule: int
    route_reason: str

    # advisor
    tool_results: list[dict[str, Any]]
    draft: dict[str, Any] | None
    #: Today's price per sku from every quote this call.
    quotes: dict[str, int]
    #: Consecutive infrastructure failures of tools; route rule 1.
    tool_failures: int

    # guard
    guard: dict[str, Any]
    regen_count: int
    block_reasons: list[str]
    blocked_drafts: list[dict[str, Any]]
    #: Safe lines said in this call; route rule 1.
    safe_lines: int

    # respond
    reply: dict[str, Any] | None
    handoff: dict[str, Any] | None
    suggestion: dict[str, Any] | None

    # perceive
    flags: dict[str, Any]


#: Cleared by ``perceive`` at the start of every turn.
TURN_KEYS: dict[str, Any] = {
    "tool_results": [],
    "draft": None,
    "guard": {},
    "regen_count": 0,
    "block_reasons": [],
    "blocked_drafts": [],
    "reply": None,
    "suggestion": None,
    "call_brief_latency_ms": None,
}


@dataclass
class HotContext:
    """Per-invocation context: read by nodes, never checkpointed.

    The raw turn is here for the reason at the top of this file. The
    collaborators are here because they are handed in rather than imported:
    the API passes the real ones, the evaluation runner and the tests their
    own, and no node reaches for a module global.
    """

    #: The customer's words as typed or recognised. None on the opening turn.
    text: str | None = None
    #: From the recogniser, when it gives one; None for typed text.
    asr_confidence: float | None = None
    #: Keys from the connection: the number a call came from, the channel identity.
    caller_phone: str | None = None
    zalo_id: str | None = None
    fb_id: str | None = None
    #: This call's personal data, token to value.
    vault: Vault = field(default_factory=Vault)
    #: The secret keys are hashed with (section 4.2).
    identity_secret: str = ""
    user_id: str | None = None

    # Collaborators, typed loosely to keep this module free of their imports.
    advisor: Any = None
    policy: Any = None
    #: The harness's tools (``src.mcp.tools.ToolBox``, role ``harness``).
    harness: Any = None
    #: Where ``persist`` writes: the API's store, or the evaluation runner's.
    store: Any = None

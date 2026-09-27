"""The routing table of ``docs/design.md`` section 4.3, applied. Pure, so every row is a unit test.

| # | Condition | Lane |
|---|---|---|
| 1 | tools failing in a row, or ``guard`` fell back to the safe line twice in the call | HANDOFF |
| 2 | ``asr_low_conf`` | CLARIFY |
| 3 | tier PROBABLE or AMBIGUOUS, or the words do not fit the brief | CONFIRM_IDENTITY |
| 4 | the customer has an order and the turn is about it | ORDER_SERVICE |
| 5 | an information question the documents do not cover | OUT_OF_SCOPE |
| 6 | VERIFIED with a brief | CONTINUITY |
| 7 | anything else | NEW |

:class:`RouteInput` is everything ``route`` may read: the enforcement is the
signature, since a field that is not here cannot be read.

Rules 4 and 5 need to know what the turn is about. Mock: keyword lists over
the tokenised turn. Rule 5 stops at the topics policy PB-06 says must go to a
person (medical and legal questions); the full rule, "``kb.search`` has no
passage above the threshold", waits for the knowledge threshold to be set on
the organisers' 60 labelled questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..intake.text import plain

Lane = Literal["HANDOFF", "CLARIFY", "CONFIRM_IDENTITY", "ORDER_SERVICE", "OUT_OF_SCOPE", "CONTINUITY", "NEW"]

#: Rule 1: consecutive infrastructure failures of tools.
TOOL_FAILURES = 2
#: Rule 1: safe lines said in one call.
SAFE_LINES = 2

ORDER_TALK = re.compile(
    r"\b(don hang|don cua|ma don|od\d+|dang giao|giao chua|giao den dau|den dau roi|khi nao giao|doi size|"
    r"doi sang|doi mau|doi san pham|tra hang|hoan tien|doi dia chi|sua dia chi|trang thai don)\b"
)
#: PB-06: questions that must go to a person, whatever the documents say.
MUST_TRANSFER = re.compile(
    # Plain text, so "thuốc" and "thuộc" look alike: whole phrases only.
    r"\b(cho con bu|dang bau|mang thai|co thai|benh nhan|bi benh|benh ly|uong thuoc|thuoc men|di ung|"
    r"hen suyen|bac si|y te|phap ly|kien tung|luat su)\b"
)


@dataclass(frozen=True)
class RouteInput:
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    has_brief: bool
    #: The customer's words contradict the brief (another name, another industry).
    brief_mismatch: bool
    has_order: bool
    asr_low_conf: bool
    tool_failures: int
    safe_lines: int
    #: Tokenised, as intake left it. None on the opening turn.
    customer_said: str | None


@dataclass(frozen=True)
class RouteDecision:
    """What was decided, and by which row. Kept for the trace and QA."""

    lane: Lane
    rule: int
    reason: str


def decide(view: RouteInput) -> RouteDecision:
    """The whole table, first match wins."""
    said = plain(view.customer_said or "")
    if view.tool_failures >= TOOL_FAILURES or view.safe_lines >= SAFE_LINES:
        why = "tools failing" if view.tool_failures >= TOOL_FAILURES else "two safe lines in this call"
        return RouteDecision("HANDOFF", 1, why)
    if view.asr_low_conf:
        return RouteDecision("CLARIFY", 2, "the recognition was unclear")
    if view.tier in ("PROBABLE", "AMBIGUOUS") or view.brief_mismatch:
        return RouteDecision("CONFIRM_IDENTITY", 3, f"identity {view.tier.lower()}")
    if view.has_order and ORDER_TALK.search(said):
        return RouteDecision("ORDER_SERVICE", 4, "about an existing order")
    if MUST_TRANSFER.search(said):
        return RouteDecision("OUT_OF_SCOPE", 5, "a topic that must go to a person (PB-06)")
    if view.tier == "VERIFIED" and view.has_brief:
        return RouteDecision("CONTINUITY", 6, "a returning customer with a brief")
    return RouteDecision("NEW", 7, "default")

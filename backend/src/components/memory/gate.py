"""The write gate: what gets remembered, and what does not. ``docs/design.md`` section 5.4.

The MemoryAgent proposes candidates; these doors, code only, decide. A joke
never reaches the ledger because a model was in a good mood.

1. drop noise: a slot the ontology does not know, an empty value;
2. the cap on open notes per customer;
3. type and plausible range: a budget is not 5 đồng, a room is not 2.500 m²;
4. who wins, by the kind of slot:

| Kind | Who wins |
|---|---|
| preference, need | the customer, newest word wins ("thôi anh lấy màu trắng") |
| business event | the tool; the customer's contrary claim is kept as said, the fact marked disputed |
| past event | the system record |
"""

from __future__ import annotations

from typing import Any, Literal, NamedTuple

from .ontology import slot

Door = Literal["noise", "under_cap", "valid_format", "wins"]

#: Hard cap on open notes per customer (section 5.2).
OPEN_NOTE_CAP = 10

RANGES: dict[str, tuple[float, float]] = {
    "budget_vnd": (100_000, 1_000_000_000),
    "price_quoted_vnd": (1_000, 1_000_000_000),
    "competitor_price_vnd": (1_000, 1_000_000_000),
    "room_area_m2": (3, 500),
    "baby_age_months": (0, 72),
}


class Candidate(NamedTuple):
    """One thing the extractor believes the call established."""

    slot: str | None  # None for an open note
    value: Any
    #: Who said it: "customer" (their words) or "tool" (a tool's result).
    said_by: Literal["customer", "tool", "system"]
    turn: int
    confidence: float = 1.0


class Verdict(NamedTuple):
    passed: bool
    stopped_at: Door | None = None
    disputed: bool = False


def check(candidate: Candidate, current: list[dict[str, Any]], *, open_notes: int) -> Verdict:
    """Doors 1 to 4, in order."""
    if candidate.value in (None, "", [], {}):
        return Verdict(False, "noise")
    if candidate.slot is None:
        return Verdict(open_notes < OPEN_NOTE_CAP, None if open_notes < OPEN_NOTE_CAP else "under_cap")
    spec = slot(candidate.slot)
    if spec is None:
        return Verdict(False, "noise")
    bounds = RANGES.get(candidate.slot)
    if bounds is not None:
        try:
            number = float(candidate.value)
        except (TypeError, ValueError):
            return Verdict(False, "valid_format")
        if not bounds[0] <= number <= bounds[1]:
            return Verdict(False, "valid_format")
    held = next((f for f in current if f["slot"] == candidate.slot and f["status"] == "active"), None)
    if held is not None and spec.kind == "business_event" and candidate.said_by == "customer" and held["value"] != candidate.value:
        return Verdict(True, disputed=True)
    return Verdict(True)

"""Deciding the write for a candidate that passed the gate. ``docs/design.md`` section 5.4, step ``commit``.

The ledger is never overwritten and never deleted from (section 5.3). For a
closed slot the operation follows from the win rule, so it is code:

- nothing held for the slot: **add**;
- the same value held: **skip**;
- another value held and the new one wins: **update**, which closes the old
  row and opens the new one;
- a customer contradicting a business fact: **add** the claim as disputed and
  keep the fact.

Every decision carries its source ``{call_id, call, turn, channel,
extractor_version}`` and, from the ontology, when it lapses. Writing goes
through ``memory.commit_facts`` under the ``memory_writer`` role, which is
the one path into the ledger.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal, NamedTuple

from .gate import Candidate, Verdict
from .ontology import slot

Operation = Literal["add", "update", "invalidate", "skip"]

EXTRACTOR_VERSION = "rules-0.1"


class Decision(NamedTuple):
    operation: Operation
    slot: str | None
    value: Any
    kind: str
    source: dict[str, Any]
    replaces: str | None = None
    disputed: bool = False
    valid_to: str | None = None
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return self._asdict()


def plan(candidate: Candidate, verdict: Verdict, current: list[dict[str, Any]], *, source: dict[str, Any], on: str) -> Decision:
    """The operation for one closed-slot candidate."""
    spec = slot(candidate.slot or "")
    kind = spec.kind if spec else "open_note"
    valid_to = None
    if spec and spec.ttl_days:
        valid_to = (date.fromisoformat(on) + timedelta(days=spec.ttl_days)).isoformat()
    source = {**source, "turn": candidate.turn, "said_by": candidate.said_by, "extractor_version": EXTRACTOR_VERSION}
    held = next((f for f in current if f["slot"] == candidate.slot and f["status"] == "active"), None)
    common = dict(slot=candidate.slot, value=candidate.value, kind=kind, source=source,
                  valid_to=valid_to, confidence=candidate.confidence)
    if held is None:
        return Decision("add", **common)
    if held["value"] == candidate.value:
        return Decision("skip", **common)
    if verdict.disputed:
        return Decision("add", disputed=True, **common)
    return Decision("update", replaces=held["fact_id"], **common)

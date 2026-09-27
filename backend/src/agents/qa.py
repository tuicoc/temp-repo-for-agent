"""QaAgent: scores every call and writes what it teaches. ``docs/design.md`` sections 9.7 and 10.3.

Runs in ``after_call`` beside the MemoryAgent, and is the judge of the
offline test.

- ``score``: the organisers' rubric, J01 to J12 (``eval/llm_judge_rubric.json``),
  PASS or FAIL per item with a quoted line as evidence. The sensor that
  replaces QA hearing 2% of calls.
- ``tag``: the call's situation (``config/situations.yaml``) and outcome.
- ``reflect``: for a call worth learning from, one lesson card. **One lesson
  is one vote**: it may be true only for this customer, and it never changes
  the advisor on its own.

It never approves what it writes: the PolicyAgent checks, a person approves.

**Mock.** No rubric call yet: ``score`` returns nothing and says so, ``tag``
reads the situation from the MemoryAgent's candidates, ``reflect`` writes no
lesson. The call is still tagged, so the Improvement page has something real
to count once lessons exist.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..components.memory.gate import Candidate
from .base import BaseAgent

SITUATION_OF = {
    "so_sanh_gia": "price_comparison",
    "gia_cao": "too_expensive",
}


class QaAgent(BaseAgent):
    """Judges calls, and turns many calls into one rule."""

    def __init__(self) -> None:
        super().__init__("qa")

    async def score(self, transcript: Sequence[dict[str, Any]], tool_log: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {"status": "not built", "verdicts": []}

    async def tag(self, candidates: Sequence[Candidate], *, returning: bool) -> dict[str, str]:
        """{"situation": ..., "outcome": ...}."""
        values = {c.slot: c.value for c in candidates if c.slot}
        situation = SITUATION_OF.get(str(values.get("objection_type")), "")
        if not situation and str(values.get("blocker", "")).startswith("cần hỏi"):
            situation = "family_decision"
        if not situation and returning:
            situation = "returning_undecided"
        return {"situation": situation or "other", "outcome": str(values.get("outcome") or "khac")}

    async def reflect(self, transcript: Sequence[dict[str, Any]], tags: dict[str, str]) -> dict[str, Any] | None:
        """A lesson card, or None when the call is not worth learning from. Not built: None."""
        return None

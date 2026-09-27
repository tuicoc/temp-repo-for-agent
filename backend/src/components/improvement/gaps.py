"""Knowledge Gap Loop. ``docs/design.md`` section 10.2, figure G.

Two ways in.

**At once, during the call.** The advisor admits it does not know and hands
over (section 13). The consultant answers the customer. Right under the
answer, the console asks "Save as a FAQ answer?", with a draft a model has
rewritten into a general entry without the customer's details. The consultant
saves, edits and saves, or skips. Saving puts it live immediately: the person
who just answered is the one who knows the answer, and the entry only
affects questions on the same topic. It appears in the "newly added" list of
the Improvement page for QA, with a revoke button.

**Grouped.** A question nobody answered (the customer hung up before anyone
took the call, a callback) goes to the unanswered list; questions with the
same meaning are grouped and counted, the most frequent first, for QA to
answer.

Every new entry adds a case to the growth set, never the golden set. It is
upserted into the knowledge store (``kb.upsert``) and found by ``kb.search``.

Status: not built.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class FaqEntry(NamedTuple):
    question: str
    answer: str
    #: The turn of the consultant's answer, for traceability.
    source_call_id: str
    source_turn_id: str


async def draft_from_answer(question: str, answer: str) -> FaqEntry:
    """The general entry a model drafts from one customer's question and the consultant's answer."""
    raise NotImplementedError("improvement.gaps: docs/design.md section 10.2")


async def save(entry: FaqEntry, *, saved_by: str) -> str:
    """Put the entry live and log it for QA; its id."""
    raise NotImplementedError("improvement.gaps: docs/design.md section 10.2")


async def unanswered() -> list[dict[str, Any]]:
    """Questions nobody answered, grouped by meaning, most frequent first."""
    raise NotImplementedError("improvement.gaps: docs/design.md section 10.2")

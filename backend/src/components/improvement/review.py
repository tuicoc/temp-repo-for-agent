"""Who approves what, and the one log of every change. ``docs/design.md`` 10.4.

The brief asks which changes need a person before they apply:

| Change | Approved before going live by | After |
|---|---|---|
| FAQ entry saved by a consultant | the consultant who just answered | QA sees it as newly added, can revoke |
| answer to a grouped unanswered question | QA | same |
| playbook entry | PolicyAgent check, QA approval, verification | watched, can be revoked |
| a case added to the growth set | automatic | |

No agent both creates and approves: the QaAgent writes lessons, the
PolicyAgent checks, a person approves.

**The improvement log** is the one place everything is written: new FAQ
entries, lessons, clusters, playbook entries, PolicyAgent results, who
approved, verification results, the version that went live, revocations,
with the ``call_id`` and ``turn_id`` behind each (section 5.5). The
Improvement page reads it as: newly added FAQ; unanswered questions; clusters
by situation; entries waiting for QA, including those the PolicyAgent tagged;
under verification; revoked.

Status: not built. The Improvement page shows sample data today.
"""

from __future__ import annotations

from typing import Any, Literal

Event = Literal[
    "faq_saved", "faq_revoked", "lesson_added", "entry_drafted", "policy_flagged",
    "entry_approved", "entry_rejected", "verified", "verification_failed", "went_live", "revoked",
]


async def log(event: Event, *, subject_id: str, actor: str, detail: dict[str, Any]) -> None:
    """Append one event to the improvement log."""
    raise NotImplementedError("improvement.review: docs/design.md section 10.4")


async def decide(entry_id: str, *, approved: bool, reviewer: str, edited: dict[str, Any] | None = None) -> None:
    """QA's decision on a playbook entry."""
    raise NotImplementedError("improvement.review: docs/design.md section 10.4")

"""Reflection, first half: one lesson per call, clustered by situation. ``docs/design.md`` 10.3.

After scoring, branch B tags the call with a **situation** (kind of customer,
kind of objection, from ``config/situations.yaml``, the same list the router
uses) and an **outcome** (closed, callback, refused). A call is worth learning
from when it had an objection, a lost order, a failed rubric item, or a
copilot suggestion the consultant edited. For those, the QaAgent writes one
lesson.

**A lesson is one vote, not a rule.** What worked or failed in one call may be
true only for that customer. A lesson never changes how the advisor answers
by itself; it joins the cluster of its situation, where votes pile up on a
won side and a lost side. The Improvement page lists clusters with their
counts, the largest first. There is no hard threshold: QA decides when a
cluster is ready to be consolidated (:mod:`.playbook`).

Every lesson is checked by the PolicyAgent first: no promise outside policy,
no number that did not come from a tool, nothing against an approved entry.
A lesson that fails is **tagged with the reason, not discarded**, because the
checking agent can be wrong too; QA still sees it.

Status: not built.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

Outcome = Literal["closed", "callback", "refused"]


class Lesson(NamedTuple):
    situation: str
    outcome: Outcome
    what_happened: str
    do: str
    dont: str
    suggested_line: str
    call_id: str
    turns: tuple[str, ...]
    #: Set by the PolicyAgent check; None when it passed.
    policy_flag: str | None = None


class Cluster(NamedTuple):
    situation: str
    won: tuple[Lesson, ...]
    lost: tuple[Lesson, ...]


async def add(lesson: Lesson) -> None:
    """File the lesson under its situation."""
    raise NotImplementedError("improvement.lessons: docs/design.md section 10.3")


async def clusters() -> list[Cluster]:
    """Every situation with its lessons, the largest first."""
    raise NotImplementedError("improvement.lessons: docs/design.md section 10.3")

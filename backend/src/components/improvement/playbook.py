"""Reflection, second half: from a cluster to how the advisor answers. ``docs/design.md`` 10.3.

This is the mechanism that turns many single-call lessons into a change in
behaviour.

1. **Consolidate.** Read a whole cluster, **contrast the lessons of won calls
   with those of lost calls**, and write one playbook entry for the
   situation: when it applies, do, don't, a sample line, and the evidence as
   plain counts ("done: 9 of 14 closed; not done: 2 of 11"). A call won by a
   violation never counts as a win. New evidence re-consolidates only that
   entry's draft; the model never rewrites the whole playbook, because
   rewritten blocks shrink and lose detail every round. (ExpeL and
   ReasoningBank work this way: rules from success and failure pairs,
   managed one entry at a time.)
2. **Approve.** The PolicyAgent checks the entry and tags it if it fails; QA
   approves entries, not individual lessons.
3. **Verify.** Right after approval, the eval runner plays the scenarios of
   that situation, plus a small regression set, with and without the entry
   (``src.pipeline.eval.runner.verify``).
4. **Apply by situation.** A live entry sits in the versioned playbook. In a
   call, ``route`` tags the turn's situation and ``budget`` puts the matching
   entries into the advisor's context. The advisor answers differently only
   in that situation.
5. **Watch.** Live scoring continues on every call; if the closing rate for
   the situation, or the related rubric items, drop, the entry is revoked.

Status: not built.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from .lessons import Cluster

Status = Literal["draft", "approved", "live", "revoked"]


class Entry(NamedTuple):
    situation: str
    when: str
    do: str
    dont: str
    sample_line: str
    #: Plain counts, e.g. {"done_closed": 9, "done_total": 14, ...}.
    evidence: dict[str, int]
    status: Status = "draft"
    policy_flag: str | None = None


async def consolidate(cluster: Cluster) -> Entry:
    """One draft entry from a cluster, contrasting won with lost."""
    raise NotImplementedError("improvement.playbook: docs/design.md section 10.3")


async def for_situation(situation: str) -> list[Entry]:
    """The live entries the budget step puts into the advisor's context."""
    raise NotImplementedError("improvement.playbook: docs/design.md section 10.3")

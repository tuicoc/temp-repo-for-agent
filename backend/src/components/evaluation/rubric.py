"""The rubric: binary items per kind of call. ``docs/design.md`` sections 9.7 and 9.7.

Pass or fail per item, never "a score out of 10" (the brief says so). One
list per kind of call: a new customer, a returning one, a call with a
handoff, a call with an out-of-scope question. For example: opened with a
continuity confirmation; did not ask again what was known; took the price
from a tool; mentioned installments when the customer worried about money;
promised nothing outside policy; admitted not knowing before handing over.

The same rubric is used by the QaAgent on every real call, by the judge of
scenarios ``graded_by: judge``, and by a person hand-scoring 20 calls or more
to measure agreement. One measure, so the three can be compared.

The items themselves belong in a config file next to ``lanes.yaml`` once
they are settled.

Status: not built.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

CallKind = Literal["new", "returning", "handoff", "out_of_scope"]


class Item(NamedTuple):
    id: str
    text: str


class Verdict(NamedTuple):
    item: str
    passed: bool
    #: The turns that show it, for QA Review.
    evidence: tuple[str, ...] = ()


def for_call(kind: CallKind) -> tuple[Item, ...]:
    """The rubric items for this kind of call."""
    raise NotImplementedError("evaluation.rubric: docs/design.md section 9.7")

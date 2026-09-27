"""Can the machine judge be trusted? ``docs/design.md`` sections 9.7 and 9.7.

A person hand-scores 20 calls or more on the same rubric, through QA Review;
this compares the two per item and reports **kappa**, not raw agreement: if
80% of calls pass, a judge that always says "pass" agrees 80% of the time and
knows nothing. Until agreement is acceptable, live scores are shown but not
trusted to raise improvement candidates on their own.

Status: not built.
"""

from __future__ import annotations


def kappa(machine: list[bool], human: list[bool]) -> float:
    """Cohen's kappa between the judge and a person on one rubric item."""
    raise NotImplementedError("evaluation.calibration: docs/design.md section 9.7")

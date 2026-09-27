"""One command for the whole table. ``docs/design.md`` sections 9.2, 9.6 and Appendix D.

    python run_eval.py --scenarios <dir> --config full --out full.jsonl
    python run_eval.py --scenarios <dir> --config baseline_no_memory --out baseline.jsonl

For every scenario: reset the mock, load ``seed_history`` into the ledger,
set ``now`` per call, send each customer turn through the API boundary in
order, run ``after_call`` between calls, write one trace line per agent turn
(``schemas/trace_log.schema.json``). Three warm-up turns run first and are
not traced. The organisers' ``eval/reference_eval.py`` then prints the table.

``compare`` refuses two runs whose manifests differ anywhere but the memory
switch and the knowledge version: the brief's "same test set, same model,
same parameters", enforced by code.

Status: not built.
"""

from __future__ import annotations

from typing import Any, Literal


async def run(test_set: Literal["golden", "growth"], *, memory: Literal["on", "off", "both"], round_name: str) -> str:
    """Run a set and write its report; the run id."""
    raise NotImplementedError("eval.runner.run: docs/design.md section 9.2")


def compare(run_a: str, run_b: str) -> dict[str, Any]:
    """The table of differences, or a refusal naming what differs."""
    raise NotImplementedError("eval.runner.compare: docs/design.md section 9.2")


async def replay(run_id: str) -> str:
    """Rerun from the run's cache without a single API call."""
    raise NotImplementedError("eval.runner.replay: docs/design.md Appendix D")


async def verify(entry_id: str, situation: str) -> dict[str, Any]:
    """With and without one playbook entry, on its situation's scenarios."""
    raise NotImplementedError("eval.runner.verify: docs/design.md section 10.3")

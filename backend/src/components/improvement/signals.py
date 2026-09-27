"""Signals: where the system learns it did something badly. ``docs/design.md`` 10.1.

The brief's four sources, each feeding exactly one place:

| Source | Comes from | Feeds |
|---|---|---|
| call outcome | the ``outcome`` slot, the tool log (``order.create``) | Reflection: won and lost calls in a cluster |
| automatic score | branch B scoring every call on the rubric; ``errors.jsonl`` of an eval run | Reflection: which calls are worth learning from |
| consultant's choice | the answer after a handoff; used, edited or own on a copilot suggestion | Gap Loop (the answer), Reflection (the edit) |
| customer repeating | the question classifier live, or "em nói rồi mà" | memory quality monitoring only |

Plus ``oos_early`` and ``oos_late`` for the Gap Loop. A violation (a wrong
promise, a leak) waits for nothing: branch B alerts QA at once.

Every row keeps ``call_id`` and ``turn_id`` (section 5.5).

Status: not built.
"""

from __future__ import annotations

from typing import Any, Literal

Kind = Literal["outcome", "score", "consultant", "repeat", "oos_early", "oos_late", "violation", "eval_error"]


async def record(kind: Kind, *, call_id: str, turn_id: str | None, value: Any) -> None:
    """Append one signal."""
    raise NotImplementedError("improvement.signals: docs/design.md section 10.1")


async def alert_qa(call_id: str, turn_id: str | None, reason: str) -> None:
    """A violation: tell QA now, not in a batch."""
    raise NotImplementedError("improvement.signals: docs/design.md section 10.1")

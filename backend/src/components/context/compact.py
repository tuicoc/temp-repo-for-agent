"""Compacting a long call. ``docs/design.md`` section 4.4.

Past a threshold, the turns before the last four are folded into
``working_summary`` and removed from the thread, so the prompt stays inside
its window however long the call runs.

Mock: the fold is extractive (each old turn's first sentence, by speaker),
not the small model call the design specifies. It keeps the call inside its
budget and loses nuance; the model call replaces :func:`fold` alone.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

#: Turns kept whole: section 4.4's "bốn lượt gần nhất", a turn being a customer
#: message and its answer.
KEEP_MESSAGES = 8
#: Fold once the thread holds this many messages.
THRESHOLD = 16


def needs_compact(messages: Sequence[Any]) -> bool:
    return len(messages) > THRESHOLD


def fold(messages: Sequence[Any], summary: str | None) -> str:
    """The new summary: the old one plus the first sentence of each folded turn."""
    lines = [summary] if summary else []
    for message in messages:
        text = str(getattr(message, "content", "") or "").strip()
        if not text:
            continue
        first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:160]
        who = "Khách" if getattr(message, "type", "") == "human" else "Bên em"
        lines.append(f"{who}: {first}")
    return "\n".join(lines)


def split(messages: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    """(to fold, to keep)."""
    if not needs_compact(messages):
        return [], list(messages)
    return list(messages[:-KEEP_MESSAGES]), list(messages[-KEEP_MESSAGES:])

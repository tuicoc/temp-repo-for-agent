"""The consultant's choice on a suggestion. ``docs/design.md`` sections 4.6 and 10.1.

The consultant sends the suggestion as written, edits it, or writes their
own. The choice is the feedback signal: used is a thumbs-up, edited or own a
thumbs-down with the difference kept. Reflection reads the edits (section
10.3); the Gap Loop reads the answers given after a handoff (section 10.2).
"""

from __future__ import annotations

import difflib
from typing import Literal, NamedTuple

Action = Literal["used", "edited", "own"]


class HumanDecision(NamedTuple):
    text: str
    action: Action
    #: Given when the consultant sends despite a warning.
    override_reason: str | None = None


def signal_of(decision: HumanDecision, suggestion: str | None) -> dict[str, object]:
    """The ``signals`` row this decision produces."""
    row: dict[str, object] = {
        "kind": "consultant",
        "action": decision.action,
        "thumb": "up" if decision.action == "used" else "down",
    }
    if suggestion and decision.action == "edited":
        row["similarity"] = round(difflib.SequenceMatcher(None, suggestion, decision.text).ratio(), 3)
    if decision.override_reason:
        row["override_reason"] = decision.override_reason
    return row

"""The advisor's context, in priority order, cut from the bottom. ``docs/design.md`` section 4.4.

1. hard rules and tone;
2. ``stale_warnings`` (never cut);
3. the lane's instruction;
4. the brief lines;
5. ``working_summary`` (the last four turns travel as messages);
6. knowledge passages (the advisor fetches them with ``kb_search``);
7. the playbook entries in play.

Tokens are estimated at four characters each, which errs long for
Vietnamese and so errs towards cutting.
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

#: Sections that are never cut, whatever the allowance.
PROTECTED = frozenset({"rules", "warnings"})


class Section(NamedTuple):
    name: str
    text: str


class ContextPack(NamedTuple):
    text: str
    tokens: int
    kept: tuple[str, ...]
    #: Names of the sections that did not fit.
    cut: tuple[str, ...]


def tokens(text: str) -> int:
    return (len(text) + 3) // 4


def assemble(sections: Sequence[Section], *, max_tokens: int) -> ContextPack:
    """Keep what fits, top first; protected sections always."""
    kept: list[Section] = []
    cut: list[str] = []
    used = 0
    for section in sections:
        if not section.text.strip():
            continue
        cost = tokens(section.text)
        if section.name in PROTECTED or used + cost <= max_tokens:
            kept.append(section)
            used += cost
        else:
            cut.append(section.name)
    return ContextPack("\n\n".join(s.text for s in kept), used, tuple(s.name for s in kept), tuple(cut))

"""Guardrails: checks before anything reaches the customer or the business.

``docs/design.md`` sections 4.4, 4.5 and 4.9, figure F. Hard before soft,
because hard is cheap, deterministic and stops most of what goes wrong.

- :mod:`.actions`: before a tool with an effect runs (GUARDRAIL before ACT):
  the price of an order equals today's quote, COD stays under its limit, a
  Handoff Brief is complete.
- :mod:`.hard`: the reply, in code, under 50 ms: every amount of money has a
  source, nothing internal, no raw personal data, nothing the tier forbids,
  no claim to be human, the right shape.
- The soft check is the PolicyAgent, ``src/agents/policy.py``.
- :mod:`.fallback`: what is said when a draft is still blocked after two
  regenerations, and the other lines of the fallback table.

Every check returns a :class:`Verdict`, whoever wrote the text: the
advisor's draft, or the consultant's own words in copilot mode.
"""

from __future__ import annotations

from typing import NamedTuple


class Verdict(NamedTuple):
    passed: bool
    #: Why it was blocked, in words the regenerating model and the console can
    #: both use.
    reasons: tuple[str, ...] = ()

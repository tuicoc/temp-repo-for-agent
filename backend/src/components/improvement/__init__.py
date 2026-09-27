"""Improvement, L6: the system gets better without retraining. ``docs/design.md`` section 18.

The brief's Case 4: QA hears about 2% of calls, so the script never learns
from the other 98%. Scoring every call (branch B of ``after_call``) is the
sensor; this package turns what it finds into changes. Two mechanisms, each
changing one thing and fed by its own signal, so signals never overlap:

| Mechanism | Changes | Learns from | Goes live |
|---|---|---|---|
| Knowledge Gap Loop (:mod:`.gaps`) | what the bot knows: FAQ entries in the knowledge store | questions the bot could not answer, plus the answer the consultant sent | the moment the consultant saves it |
| Reflection (:mod:`.lessons`, :mod:`.playbook`) | how the bot handles a situation: playbook entries | per-call lessons, clustered by situation, won against lost | when QA approves the entry and verification passes |

**The founding rule:** a lesson written after one call may be true only for
that customer. One call is one vote of evidence, never a rule. A playbook
entry comes only from many calls in the same situation.

- :mod:`.signals`: the four sources of the brief, recorded where they occur.
- :mod:`.review`: who approves what, and the one improvement log everything is
  written to, which the Improvement page reads.
- :mod:`.versions`: what is live, verification, rounds R0 to R3, rollback.

Status: not built.
"""

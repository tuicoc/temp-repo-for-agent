"""Evaluation: the measures. ``docs/design.md`` section 17.

The word "evaluation" covers two jobs with different data and different
purposes (section 9.7), and this package serves both:

| | Live scoring | Offline test |
|---|---|---|
| Runs on | every real call, branch B of ``after_call`` | the frozen golden set, the growth set, the simulator |
| When | right after each call | after QA approves a playbook entry; for the report's rounds; for replay |
| For | a **sensor**: find what broke instead of QA hearing 2%; feed improvement; watch a change after it goes live | a **gate and the evidence**: a change that breaks something else does not go live; the table against the baseline |

- :mod:`.rubric`: one rubric per kind of call, used in three places (live
  scoring, the offline judge, human calibration).
- :mod:`.scorers`: the scorers of section 9.4, one per metric.
- :mod:`.calibration`: agreement between the machine judge and a person.

Running scenarios is ``src/pipeline/eval``; this package only measures.

Status: not built.
"""

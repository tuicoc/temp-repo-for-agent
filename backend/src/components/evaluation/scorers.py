"""The scorers behind the five metrics. ``docs/design.md`` section 9.4.

| Scorer | How | Metric |
|---|---|---|
| ``question_classifier`` | small model, temperature 0, cached; accuracy reported on 50 hand labels | Repeat-Question Rate |
| ``fact_usage_checker`` | deterministic | Context Carryover Rate |
| ``assertion_runner`` | the scenario's ``success_if`` on the tool log; judge scenarios go to the rubric | Task Success Rate |
| ``claim_extractor`` | small model, cached; claims checked in code against ground truth | Hallucination Rate, separate for price and promotion |
| ``score_asr`` | ``jiwer`` after the published normalisation; entity exact match after ITN | WER, CER, entity accuracy |

Status: not built.
"""

from __future__ import annotations

from typing import Any


def repeat_question_rate(transcript: list[dict[str, Any]], must_not_ask: list[str]) -> float:
    raise NotImplementedError("evaluation.scorers: docs/design.md section 9.4")


def context_carryover_rate(transcript: list[dict[str, Any]], must_carry_over: list[str]) -> float:
    raise NotImplementedError("evaluation.scorers: docs/design.md section 9.4")


def task_success(tool_log: list[dict[str, Any]], success_if: dict[str, Any]) -> bool:
    raise NotImplementedError("evaluation.scorers: docs/design.md section 9.4")


def hallucination_rate(transcript: list[dict[str, Any]], ground_truth: dict[str, Any]) -> dict[str, float]:
    raise NotImplementedError("evaluation.scorers: docs/design.md section 9.4")


def score_asr(pairs: list[tuple[str, str]]) -> dict[str, float]:
    raise NotImplementedError("evaluation.scorers: docs/design.md section 9.4")

# Evaluation data work

Before any code change under `evaluation/`, read `docs/CODING-INCIDENTS-AND-GUARDRAILS.md` completely. It records prior failure modes, ownership boundaries, evidence checks and the offline gate; do not treat historical run findings as current product state without a fresh trace.

When adding or revising scenarios, ground truth, grading labels, or generated evaluation datasets under `evaluation/`, read `datasets/ground-truth-review/SKILL.md` completely before editing data. Follow its revision and human-review rules. For evaluation code changes that do not alter data or labels, this skill is not required.

Before running model-backed evaluation with any newly added test case, follow the skill's pre-model gate for every new scenario/call; do not use `evaluate` as the preflight check.

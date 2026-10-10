# Evaluation data work

When adding or revising scenarios, ground truth, grading labels, or generated evaluation datasets under `evaluation/`, read `datasets/ground-truth-review/SKILL.md` completely before editing data. Follow its revision and human-review rules. For evaluation code changes that do not alter data or labels, this skill is not required.

Before running model-backed evaluation with any newly added test case, follow the skill's pre-model gate for every new scenario/call; do not use `evaluate` as the preflight check.

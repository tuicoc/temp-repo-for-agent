"""Diagnostic multi-round text comparison of closed scored runs."""
from pathlib import Path

from .assets import Assets, read_json
from .collector import locked_run
from .datasets import close_output
from .extractor import digest
from .rounds import cohort
from .runner import _write

METRICS = {
    "rqr": ("repeat_question_rate", "value"),
    "ccr": ("context_carryover_rate", "value"),
    "tsr": ("task_success_rate", "value"),
    "hr_price_promo": ("hallucination_rate", "price_promo_only", "value"),
    "turns": ("avg_turns_per_call",),
}


def _value(report, path):
    value = report
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value if type(value) in (int, float) else None


def compare(runs, out):
    if len(runs) < 2:
        raise ValueError("At least two distinct closed scored runs required")
    snapshots = []
    for path in runs:
        assets, _ = locked_run(path)
        manifest = read_json(assets.path("manifest.json"))
        official = read_json(assets.path("official-report.json"))
        inputs = Assets(assets.root / "evidence/raw/inputs")
        validation = read_json(assets.path("validation.json"))
        snapshots.append((manifest, official, digest(cohort(assets, manifest, inputs=inputs)), validation["status"]["completeness"]))
    if len({m["run_id"] for m, _, _, _ in snapshots}) != len(snapshots):
        raise ValueError("Round runs must have distinct IDs")
    rows = []
    for (before, first, old_cohort, old_status), (after, second, new_cohort, new_status) in zip(snapshots, snapshots[1:]):
        issues = []
        if old_status != "COMPLETE" or new_status != "COMPLETE":
            issues.append("RUN_EVIDENCE_INCOMPLETE")
        if after["round"] != before["round"] + 1 or after["level"] != before["level"]:
            issues.append("ROUND_ORDER_OR_LEVEL")
        if old_cohort != new_cohort:
            issues.append("COHORT_OR_GRADING_CHANGED")
        for key in ("model", "parameters", "hardware", "tools", "extractor_version", "judge_version"):
            if before["configuration"][key] != after["configuration"][key]:
                issues.append("CONTROL_CHANGED:" + key)
        changed = [key for key in ("prompt", "kb") if before["configuration"][key] != after["configuration"][key]]
        if len(changed) != 1:
            issues.append("IMPROVEMENT_ARTIFACT_UNBOUND")
        metrics = {}
        for name, path in METRICS.items():
            old, new = _value(first["system"], path), _value(second["system"], path)
            metrics[name] = {"r0_full": old, "r1_full": new,
                             "delta": new - old if old is not None and new is not None and not issues else None,
                             "r0_baseline": _value(first["baseline"], path),
                             "r1_baseline": _value(second["baseline"], path)}
        rows.append({"from": before["run_id"], "to": after["run_id"], "changed_resource": changed,
                     "issues": issues, "status": "DIAGNOSTIC" if not issues else "INCOMPLETE", "metrics": metrics})
    out = Path(out).resolve()
    if any(out.is_relative_to(Path(path).resolve()) for path in runs):
        raise ValueError("Output cannot be inside source run")
    out.mkdir(parents=True, exist_ok=False)
    report = {"report_kind": "improvement-rounds-diagnostic-v1", "rounds": rows,
              "notice": "BTC numbers are unchanged; rounded official values are descriptive, not release authority. Approval and runtime consumption require separate evidence."}
    _write(out / "report.json", report)
    close_output(out)
    return report

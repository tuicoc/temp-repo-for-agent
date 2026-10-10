"""Readable, non-authoritative view of one product evaluation run."""
import json
from pathlib import Path


MISSING = "MISSING"
CONFIGS = ("full", "baseline_no_memory")


def _json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def _safe(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower().startswith("_internal") or any(
            secret in key.lower() for secret in ("password", "api_key", "secret", "access_token", "private_key")
        ) else _safe(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def build(run, report):
    """Build one case-first view; never invent evidence missing from a partial run."""
    run = Path(run)
    manifest = _json(run / "inputs/manifest.json") or {}
    official = _json(run / "scored/official-report.json")
    validation = _json(run / "scored/validation.json") or {}
    supplemental = _json(run / "scored/supplemental-report.json") or {}
    trace = {config: _rows(run / f"evidence/{'full' if config == 'full' else 'baseline'}.jsonl")
             for config in CONFIGS}
    cases = []
    for source in sorted((run / "inputs/scenarios").glob("*.json")):
        scenario = _json(source)
        if not isinstance(scenario, dict):
            continue
        sid = scenario["scenario_id"]
        configurations = {}
        for config in CONFIGS:
            rows = {(row["call"], row["turn"]): row for row in trace[config]
                    if row.get("scenario_id") == sid}
            evidence_dir = run / "evidence" / config
            grouped = {}
            for kind, filename in (("tools", "tools.jsonl"), ("memory", "memory.jsonl"),
                                   ("brief", "brief-evidence.jsonl"), ("extraction", "extraction.jsonl")):
                grouped[kind] = {}
                for item in _rows(evidence_dir / filename):
                    context = item.get("context") or {}
                    if context.get("scenario_id") == sid:
                        grouped[kind].setdefault((context.get("call"), context.get("turn")), []).append(item)
            calls = []
            for call_id, call in sorted(scenario["calls"].items()):
                turns = []
                for number, customer_text in enumerate(call["customer_turns"], 1):
                    row = rows.get((call_id, number))
                    key = (call_id, number)
                    turns.append({"turn": number, "status": "PRESENT" if row else MISSING,
                                  "customer_text": customer_text,
                                  "agent_text": row.get("agent_text", MISSING) if row else MISSING,
                                  "tool_calls": _safe(row.get("tool_calls", [])) if row else MISSING,
                                  "questions": row.get("questions", MISSING) if row else MISSING,
                                  "claims": row.get("claims", MISSING) if row else MISSING,
                                  "facts_used": row.get("facts_used", MISSING) if row else MISSING,
                                  "latency": row.get("latency", MISSING) if row else MISSING,
                                  "tool_events": _safe(grouped["tools"].get(key, [])),
                                  "memory": _safe(grouped["memory"].get(key, [])),
                                  "brief": _safe(grouped["brief"].get(key, [])),
                                  "extractor": _safe(grouped["extraction"].get(key, []))})
                calls.append({"call": call_id, "customer_goal": call.get("customer_goal", MISSING),
                              "expected_outcome": call.get("expected_outcome", MISSING),
                              "success_if": call.get("success_if", MISSING), "turns": turns})
            metric = (official or {}).get("system" if config == "full" else "baseline", {}).get("task_success_rate", {})
            failures = [item for item in metric.get("failures", []) if item.get("scenario") == sid]
            configurations[config] = {"status": "PRESENT" if rows else MISSING, "calls": calls,
                                       "task_success": {"status": "FAIL" if failures else "PASS", "failures": failures}
                                       if metric and rows else MISSING,
                                       "evidence_ref": f"evidence/{'full' if config == 'full' else 'baseline'}.jsonl"}
        issues = [issue for issue in validation.get("issues", [])
                  if sid in json.dumps(issue, ensure_ascii=False)]
        checks = [check for check in supplemental.get("checks", [])
                  if sid in json.dumps(check, ensure_ascii=False)]
        cases.append({"scenario_id": sid, "hard_case": scenario.get("hard_case", MISSING),
                      "scenario_ref": str(source.relative_to(run)), "configurations": configurations,
                      "issues": issues, "assertions": checks if checks else MISSING})
    complete = bool(cases) and len(cases) == len(manifest.get("scenarios", cases)) and all(
        turn["status"] == "PRESENT" for case in cases for config in case["configurations"].values()
        for call in config["calls"] for turn in call["turns"])
    score_stage = next((stage for stage in report.get("stages", []) if stage.get("stage") == "score"), {})
    score_complete = score_stage.get("status", {}).get("completeness") == "COMPLETE"
    return _safe({"format": "case-trace-v1", "run_id": manifest.get("run_id", MISSING),
                  "status": "COMPLETE" if complete and official and score_complete and not report.get("pipeline_error") else "INCOMPLETE",
                  "pipeline_error": report.get("pipeline_error"), "stages": report.get("stages", []),
                  "comparison": official.get("comparison", MISSING) if official else MISSING,
                  "metrics": {config: official.get("system" if config == "full" else "baseline", MISSING)
                              for config in CONFIGS} if official else MISSING,
                  "reports": {"official": "scored/official-report.json" if official else MISSING,
                              "validation": "scored/validation.json" if validation else MISSING,
                              "assertions": "scored/supplemental-report.json" if supplemental else MISSING},
                  "cases": cases})


def write(run, report):
    path = Path(run) / "case-trace.json"
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(build(run, report), ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    path.chmod(0o600)
    return path

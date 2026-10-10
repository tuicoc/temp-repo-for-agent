"""P6 one-command M1 orchestration using existing P2/P3/P4/P5 stages."""
from pathlib import Path
import shutil
import hashlib

from .assets import Assets, read_json
from .asr_suite import asr_suite
from .collector import collect, locked_run, status
from .contracts import validate
from .datasets import inspect_dataset, snapshot, close_output
from .preflight import preflight
from .reporting import report_metrics, validate_policy
from .runner import _output_path, _write, run_fixed
from .scoring import score


def benchmark(settings, out):
    settings = Path(settings).resolve()
    config = read_json(settings)
    if set(config) != {"asset_root", "execution_settings", "extractor", "asr"}:
        raise ValueError("P6 settings require asset_root, pinned execution_settings, extractor path and explicit ASR plan")
    assets = Assets(settings.parent / config["asset_root"])
    execution_path = assets.resolve(config["execution_settings"], json_content=False)
    planned = preflight(execution_path)
    if not planned["execution_gate"]["allowed"]:
        raise ValueError("P6 execution input gate blocked")
    execution_config = read_json(execution_path)
    execution_assets = Assets(execution_path.parent / execution_config["asset_root"])
    manifest = execution_assets.resolve(planned["manifest"])
    if manifest["level"] != "M1" or {p["config"] for p in manifest["planned_calls"]} != {"full", "baseline_no_memory"}:
        raise ValueError("P6 benchmark requires M1 paired full/baseline plans")
    # Cost policy and extractor must be pinned before execution, never selected from scores.
    policies = [r for r in manifest["sources"] if r["pointer"] == "" and r["path"].endswith(".json")
                and isinstance(execution_assets.resolve(r), dict) and execution_assets.resolve(r).get("schema_version") == "p6-metrics-policy-v1"]
    if len(policies) != 1:
        raise ValueError("Pin exactly one P6 price policy in manifest.sources before benchmarking")
    validate_policy(execution_assets.resolve(policies[0]))
    extractor = execution_assets.ref(config["extractor"])
    if extractor not in manifest["sources"]:
        raise ValueError("Extractor descriptor must be pinned in manifest.sources")
    asr = config["asr"]
    if set(asr) != {"settings", "split", "mode"} or asr["split"] != "eval" or asr["mode"] not in ("replay", "infer"):
        raise ValueError("Explicit eval ASR settings/split/mode required; no implicit inference")
    asr_settings = assets.resolve(asr["settings"], json_content=False)
    asr_assets, registry, refs, readiness = inspect_dataset(asr_settings)
    if not readiness["execution_gate"]["allowed"]:
        raise ValueError("ASR readiness execution gate blocked")
    out = _output_path(out, execution_assets)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    snapshot(out, asr_assets, refs)
    _write(out / "benchmark-settings.json", config)
    for name, source in {"execution-settings.json": execution_path, "asr-settings.json": asr_settings}.items():
        # Preserve exact pinned settings bytes, not a JSON reserialization.
        shutil.copyfile(source, out / name)
    _write(out / "benchmark-plan.json", {"execution_settings": config["execution_settings"], "manifest": planned["manifest"],
        "asr": asr, "asr_ids": [a["id"] for a in registry["asr"]["cohorts"]["eval"]["audio"]],
        "dataset_id": registry["dataset_id"], "dataset_version": registry["version"],
        "notice": "Pinned separate team ASR cohort; main Agent manifest is not rewritten to attach historical ASR"})
    stages = []
    failure = None
    result = None
    try:
        raw = run_fixed(execution_path, out / "raw")
        stages.append({"stage": "run", "execution_complete": raw["execution_complete"]})
        collected = collect(out / "raw", out / "evidence", extractor_path=config["extractor"])
        stages.append({"stage": "collect", "status": collected["status"]})
        scored = score(out / "evidence", out / "scored")
        stages.append({"stage": "score", "status": scored["status"]})
        # Inputs frozen before Agent execution must still match before invoking ASR.
        assets.resolve(config["execution_settings"], json_content=False)
        assets.resolve(asr["settings"], json_content=False)
        for ref in refs:
            asr_assets.resolve(ref, json_content=False)
        asr_result = asr_suite(asr_settings, out / "asr", split="eval", mode=asr["mode"])
        stages.append({"stage": "asr", "status": asr_result["status"], "mode": asr["mode"]})
        result = report_metrics(out / "scored", out / "metrics", asr_run=out / "asr")
        stages.append({"stage": "metrics", "status": result["status"]})
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        failure = str(exc)
    local = Assets(out)
    issues = []
    if result:
        for item in read_json(out / "metrics/validation.json")["issues"]:
            issues.append({**item, "artifact": {**item["artifact"], "path": "metrics/" + item["artifact"]["path"]}})
    else:
        # A later stage failure must not erase confirmed failures already scored.
        for folder in ("scored", "asr", "evidence", "raw"):
            path = out / folder / "validation.json"
            if path.is_file():
                for item in read_json(path)["issues"]:
                    issues.append({**item,"artifact":{**item["artifact"],"path":folder+"/"+item["artifact"]["path"]}})
    def issue(code, message, classification="missing_evidence"):
        item = {"code": code, "message": message, "classification": classification,
                "artifact": local.ref("benchmark-plan.json"), "json_pointer": ""}
        validate("Issue", item);issues.append(item)
    if failure:
        issue("BENCHMARK_STAGE_ERROR", failure, "infra_error")
    for suite in manifest["suites"]:
        if suite["applicable"] and suite["id"] not in ("fixed_turn", "asr", "latency_cost"):
            issue("APPLICABLE_SUITE_PENDING", suite["id"] + " not implemented by P6; applicability preserved")
    summary = {"report_kind": "p6-benchmark-v1", "run_id": manifest["run_id"], "fixture": manifest["fixture"],
        "status": status(issues), "quality_accepted": False, "stages": stages, "error": failure,
        "table_ref": local.ref("metrics/table.md") if result else None,
        "notice": "One-command M1 implementation path; not release/real-runtime certification. No Agent/tool retry."}
    _write(out / "benchmark-report.json", summary)
    validation = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/benchmark-validation",
                  "run_id": manifest["run_id"], "status": status(issues), "issues": issues, "coverage_refs": []}
    validate("ValidationReport", validation);_write(out / "validation.json", validation)
    close_output(out)
    return summary


def round_model_attempt_envelope(round_inputs):
    settings, settings_assets, inputs, manifest, config = round_inputs
    execution = settings_assets.resolve(config["execution_settings"], json_content=False)
    adapter = inputs.resolve(read_json(execution)["adapter"])
    extractor = inputs.resolve(inputs.ref(config["extractor"]))
    if adapter["kind"] == "test" and extractor["kind"] == "fixture_replay":
        return 0
    if adapter["kind"] != "runtime" or extractor["kind"] != "command_model" or config["asr"]["mode"] != "replay":
        raise ValueError("Live paired benchmark requires bounded runtime, command extractor and ASR replay")
    bundles = [inputs.resolve(ref) for ref in manifest["sources"] if not ref["pointer"]
               and ref["path"].endswith("product-bundle.json")]
    if len(bundles) != 1 or bundles[0].get("schema_version") != "product-bundle-v1":
        raise ValueError("Pinned product runtime budget is required before model execution")
    per_process = bundles[0].get("max_model_calls")
    extractor_max = extractor.get("max_calls")
    if any(type(value) is not int or value < 1 for value in (per_process, extractor_max)):
        raise ValueError("Invalid pinned model attempt budget")
    processes = {(call["config"], call["scenario_id"]) for call in manifest["planned_calls"]}
    return len(processes) * per_process + extractor_max

def benchmark_rounds(r0_settings, r1_settings, out, *, max_model_attempts=None):
    """Run two pinned M1 rounds through P2–P7; comparison never activates a FAQ."""
    from .rounds import cohort, compare_rounds

    def planned(settings, round_number):
        settings = Path(settings).resolve()
        config = read_json(settings)
        if set(config) != {"asset_root", "execution_settings", "extractor", "asr"}:
            raise ValueError("Both rounds require P6 benchmark settings")
        settings_assets = Assets(settings.parent / config["asset_root"])
        execution = settings_assets.resolve(config["execution_settings"], json_content=False)
        report = preflight(execution)
        if not report["execution_gate"]["allowed"]:
            raise ValueError("Round input gate blocked before model execution")
        execution_settings = read_json(execution)
        inputs = Assets(execution.parent / execution_settings["asset_root"])
        manifest = inputs.resolve(report["manifest"])
        if manifest["level"] != "M1" or manifest["round"] != round_number:
            raise ValueError("Expected M1 R0 and R1 manifests")
        return settings, settings_assets, inputs, manifest, config

    first = planned(r0_settings, 0)
    second = planned(r1_settings, 1)
    envelope = round_model_attempt_envelope(first) + round_model_attempt_envelope(second)
    if envelope:
        if type(max_model_attempts) is not int or max_model_attempts < envelope:
            raise ValueError("Paired model attempt envelope exceeds explicit hard cap")
    r0, r1 = first[3], second[3]
    if r0["run_id"] == r1["run_id"] or any(r0[key] != r1[key] for key in ("fixture", "purpose", "split")):
        raise ValueError("Rounds require distinct run IDs and the same dataset purpose/split")
    if first[4]["asr"] != second[4]["asr"] or first[4]["extractor"] != second[4]["extractor"]:
        raise ValueError("ASR and extractor plans must match before model execution")
    if cohort(first[2], r0, inputs=first[2]) != cohort(second[2], r1, inputs=second[2]):
        raise ValueError("Round cohort differs before model execution")
    for key in ("model", "parameters", "tools", "hardware", "extractor_version", "judge_version", "prompt"):
        if r0["configuration"][key] != r1["configuration"][key]:
            raise ValueError("Round control differs before model execution: " + key)
    def source_policy(inputs, manifest, schema_version):
        found = []
        for ref in manifest["sources"]:
            if ref["pointer"] or not ref["path"].endswith(".json"):
                continue
            value = inputs.resolve(ref)
            if isinstance(value, dict) and value.get("schema_version") == schema_version:
                found.append((ref, value))
        if len(found) != 1:
            raise ValueError("Exactly one pinned " + schema_version + " policy required")
        return found[0]

    if source_policy(first[2], r0, "p6-metrics-policy-v1")[1] != source_policy(second[2], r1, "p6-metrics-policy-v1")[1]:
        raise ValueError("Round metrics price policy differs before model execution")
    policy_ref, policy = source_policy(first[2], r0, "p7-round-policy-v1")
    if policy_ref not in r1["sources"]:
        raise ValueError("One identical P7 round policy must be pinned before execution")
    second[2].resolve(policy_ref)
    if set(policy) != {"schema_version", "allowed_changed_configuration"} or "kb" not in policy["allowed_changed_configuration"] or set(policy["allowed_changed_configuration"]) - {"kb"}:
        raise ValueError("FAQ experiment must allow only the KB resource to change")
    if r0["configuration"]["kb"] == r1["configuration"]["kb"]:
        raise ValueError("R1 must bind a new FAQ resource")
    if r1["candidate_hash"] != r1["configuration"]["kb"]["sha256"]:
        raise ValueError("R1 candidate hash must bind the exact FAQ resource bytes")
    if first[0] == second[0]:
        raise ValueError("Rounds must use distinct settings")
    target = _output_path(out, first[2])
    if target.is_relative_to(second[2].root):
        raise ValueError("Output cannot be inside R1 inputs")
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write(target / "pair-plan.json", {"r0_settings_sha256": hashlib.sha256(first[0].read_bytes()).hexdigest(),
                                       "r1_settings_sha256": hashlib.sha256(second[0].read_bytes()).hexdigest(),
                                       "r0_run_id": r0["run_id"], "r1_run_id": r1["run_id"],
                                       "r0_kb": r0["configuration"]["kb"], "r1_kb": r1["configuration"]["kb"],
                                       "model_attempt_envelope": envelope, "approved_hard_cap": max_model_attempts})
    stages, comparison, failure = [], None, None
    try:
        for name, settings in (("r0", first[0]), ("r1", second[0])):
            result = benchmark(settings, target / name)
            stages.append({"round": name.upper(), "status": result["status"], "metrics_ready": bool(result["table_ref"])})
            if not result["table_ref"]:
                raise ValueError(name.upper() + " has no closed metrics; next round/comparison not run")
        comparison = compare_rounds(target / "r0/metrics", target / "comparison",
                                    r1_run=target / "r1/metrics")
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        failure = str(exc)
    summary = {"report_kind": "m1-r0-r1-benchmark-v1", "r0_run_id": r0["run_id"],
               "r1_run_id": r1["run_id"], "stages": stages,
               "comparison_status": comparison["status"] if comparison else None,
               "decision": "hold", "error": failure,
               "notice": "Closed scorer evidence is diagnostic until release gate and dataset acceptance pass"}
    _write(target / "pair-report.json", summary)
    close_output(target)
    return summary

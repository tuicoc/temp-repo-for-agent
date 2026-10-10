"""P1 planned-input checks, never an Agent benchmark or advanced BTC validator."""
from datetime import date, timedelta
from pathlib import Path
import re
import wave

from .assets import Assets, read_json
from .contracts import checker, validate

DEFERRED = {"btc.validator", "btc.audio_segments"}
DEFERRED_REASON = "DEFERRED_BY_USER_2026_10_04"
PUBLIC_DISPUTES = {"SAMPLE-01": "B02", "SAMPLE-02": "B03", "SAMPLE-03": "B04"}
DISPUTES = {
    "B02": "SAMPLE-01 budget: customer input vs facts_established",
    "B03": "SAMPLE-02 promo: scenario GT vs mock/date",
    "B04": "SAMPLE-03 order ID: success_if vs seed/mock",
    "B05": "RAG Q20 answer vs policy/catalog",
    "B06": "RAG Q57 amount vs mock pricing",
    "B07": "COD boundary 10 million: policy sources disagree",
    "B15": "Legacy exchange fee / callback holiday-hour policy vs mock",
}
ADAPTER_CAPABILITIES = frozenset({
    "business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
    "snapshots", "briefs", "timestamps", "usage",
})


def execution_gate(manifest, issues, adapter):
    """Input permission to attempt P2 adapter binding, NOT runtime capability proof.

    Development may collect evidence for disputed GT. Other issues always block.
    Actual adapter binding/capability checks must still succeed before any turn.
    """
    nonblocking = [item for item in issues if item["classification"] == "dispute"
                   and manifest["purpose"] == "development"]
    blocking = [item for item in issues if item not in nonblocking]
    codes = {item["code"] for item in blocking}
    if adapter is None:
        codes.add("ADAPTER_NOT_CONFIGURED")
    elif adapter["kind"] == "test" and (not manifest["fixture"] or manifest["purpose"] == "official_eval"):
        codes.add("TEST_ADAPTER_NOT_FIXTURE")
    return {"allowed": not codes, "blocking_codes": sorted(codes),
            "nonblocking_dispute_codes": sorted({item["code"] for item in nonblocking}),
            "binding_verified": False, "runtime_checks": "NOT_RUN_PREFLIGHT_ONLY",
            "notice": "Input gate only; does not certify Agent/criteria or permit test fallback"}


def call_plan(scenario, reference_date):
    names = sorted(scenario["calls"], key=lambda name: int(name.split("_")[1]))
    if names != [f"call_{i}" for i in range(1, len(names) + 1)]:
        raise ValueError("Calls must be contiguous from call_1")
    previous, plans = date.fromisoformat(reference_date), []
    for name in names:
        spec = scenario["calls"][name]
        current = date.fromisoformat(spec["call_date"]) if "call_date" in spec else previous + timedelta(days=spec.get("days_later", 0))
        if plans and current < previous:
            raise ValueError("Call date moves backwards")
        turns = spec.get("customer_turns_asr", spec["customer_turns"])
        if len(turns) != len(spec["customer_turns"]):
            raise ValueError("Noisy/clean input lengths differ")
        plans.append({"scenario_id": scenario["scenario_id"], "call": name,
                      "on": current.isoformat(), "expected_turns": len(turns),
                      "input_field": "customer_turns_asr" if "customer_turns_asr" in spec else "customer_turns"})
        previous = current
    return plans


def preflight(settings_path, scenarios_dir=None):
    checker.verify_sources()
    settings_path = Path(settings_path).resolve()
    settings = read_json(settings_path)
    required_settings = {"asset_root", "manifest", "scope"}
    if (not isinstance(settings, dict) or not required_settings <= set(settings)
            or set(settings) - required_settings - {"adapter"}):
        raise ValueError("Settings require asset_root, manifest, scope; optional adapter AssetRef")
    assets = Assets(settings_path.parent / settings["asset_root"])
    manifest_ref = assets.ref(settings["manifest"])
    manifest = assets.resolve(manifest_ref)
    validate("Manifest", manifest)
    scope_ref = assets.ref(settings["scope"])
    scope = assets.resolve(scope_ref)
    if not isinstance(scope, dict):
        raise ValueError("Scope must be an object")
    issues, warnings, plans, scenarios, graders = [], [], [], {}, {}

    def issue(code, message, classification="schema_error", artifact=None):
        issues.append({"code": code, "artifact": artifact or manifest_ref, "json_pointer": "",
                       "message": message, "classification": classification})

    def attempt(ref, definition=None):
        try:
            data = assets.resolve(ref)
            if definition:
                if definition == "GradingContract":
                    errors = checker.errors("grading-contract.schema.json", data)
                    if errors:
                        raise ValueError("; ".join(error.message for error in errors))
                else:
                    validate(definition, data)
            return data
        except (ValueError, KeyError, IndexError, TypeError, OSError) as exception:
            issue("ASSET_OR_SCHEMA", str(exception), "missing_evidence", ref)
            return None

    adapter = None
    if "adapter" in settings:
        descriptor = attempt(settings["adapter"])
        try:
            if (not isinstance(descriptor, dict) or set(descriptor) != {"kind", "entrypoint", "code", "capabilities"}
                    or descriptor["kind"] not in ("test", "runtime")
                    or not isinstance(descriptor["entrypoint"], str)
                    or not re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*:[A-Za-z_][\w]*", descriptor["entrypoint"])):
                raise ValueError("Adapter descriptor needs kind, module:factory entrypoint, code AssetRef, capabilities")
            capabilities = descriptor["capabilities"]
            if (not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities)
                    or len(capabilities) != len(set(capabilities)) or not ADAPTER_CAPABILITIES <= set(capabilities)):
                raise ValueError("Adapter must declare all M1 lifecycle/evidence capabilities without duplicates")
            assets.resolve(descriptor["code"], json_content=False)
            if settings["adapter"] not in manifest["sources"] or descriptor["code"] not in manifest["sources"]:
                raise ValueError("Pin adapter descriptor AND implementation code in manifest.sources")
            adapter = descriptor
        except (ValueError, KeyError, TypeError, OSError) as exception:
            issue("ADAPTER_CONFIG", str(exception), "missing_evidence")

    if scope_ref not in manifest["sources"]:
        issue("SCOPE_NOT_PINNED", "Scope must be hash-pinned in manifest.sources before run")
    if manifest["fixture"] and manifest["purpose"] == "official_eval":
        issue("FIXTURE_OFFICIAL", "Synthetic fixture cannot be an official benchmark")
    deferred = scope.get("deferred", [])
    if (len(deferred) != len(DEFERRED) or {item.get("id") for item in deferred} != DEFERRED
            or any(item.get("reason") != DEFERRED_REASON for item in deferred)):
        issue("DEFERRED_SCOPE", "Keep both user-deferred BTC requirements with the exact reason")
    for ref in manifest["sources"] + list(manifest["configuration"][key] for key in ("prompt", "tools", "kb")):
        try:
            assets.resolve(ref, json_content=False)
        except (ValueError, KeyError, IndexError, TypeError, OSError) as exception:
            issue("ASSET_OR_SCHEMA", str(exception), "missing_evidence", ref)
    for ref in manifest["scenarios"]:
        scenario = attempt(ref, "Scenario")
        if scenario is None:
            continue
        sid = scenario["scenario_id"]
        if sid in scenarios:
            issue("DUPLICATE_SCENARIO", sid, artifact=ref)
            continue
        scenarios[sid] = scenario
        supported = checker.read("contracts.schema.json")["$defs"]["SuccessIf"]["properties"]
        for call, spec in scenario["calls"].items():
            success = spec.get("success_if") or {}
            if set(success) - set(supported):
                issue("UNKNOWN_SUCCESS_IF", f"{sid}/{call}: unsupported assertion keys, preserve raw for review", artifact=ref)
            for pattern in success.get("trace_must_not_match", []):
                try:
                    re.compile(pattern)
                except re.error as exception:
                    issue("INVALID_ASSERTION_REGEX", f"{sid}/{call}: {exception}", artifact=ref)
        if scenario["level"] != manifest["level"]:
            issue("LEVEL_MISMATCH", sid, artifact=ref)
        try:
            plans.extend(call_plan(scenario, manifest["reference_date"]))
        except (ValueError, KeyError, TypeError) as exception:
            issue("CALL_INPUT_DATE", f"{sid}: {exception}", artifact=ref)
    if scenarios_dir is not None:
        selected = {path.resolve() for path in Path(scenarios_dir).glob("*.json") if not path.name.startswith("_")}
        registered = {assets.path(ref["path"]) for ref in manifest["scenarios"]}
        if selected != registered:
            issue("SCENARIO_DIRECTORY", "Selected directory must exactly match pinned scenario files")
    expected = {(config, plan["scenario_id"], plan["call"]): plan["expected_turns"]
                for config in ("full", "baseline_no_memory") for plan in plans}
    observed = {}
    for plan in manifest["planned_calls"]:
        key = (plan["config"], plan["scenario_id"], plan["call"])
        if key in observed:
            issue("DUPLICATE_PLANNED_CALL", str(key))
        observed[key] = plan["expected_turns"]
        spec = scenarios.get(plan["scenario_id"], {}).get("calls", {}).get(plan["call"], {})
        needs_memory = bool(spec.get("must_carry_over") or spec.get("seed_history") or spec.get("memory_expectation"))
        if (plan["config"] == "baseline_no_memory" and plan["memory_required"]
                or plan["config"] == "full" and needs_memory and not plan["memory_required"]):
            issue("MEMORY_APPLICABILITY", "Planned memory requirement conflicts with scenario/config")
    if expected != observed:
        issue("PLANNED_COVERAGE", "Manifest calls/turns differ from both-config input plan")
    namespaces = manifest["state_namespaces"]
    if namespaces["full"] == namespaces["baseline_no_memory"]:
        issue("NAMESPACE_COLLISION", "Full and baseline require different namespaces")
    for ref in manifest["grading_contracts"]:
        grading = attempt(ref, "GradingContract")
        if grading is None:
            continue
        sid = grading["scenario_id"]
        if sid in graders:
            issue("DUPLICATE_GRADING", sid, artifact=ref)
        graders[sid] = grading
        original = attempt(grading["scenario"], "Scenario")
        if original is None or original != scenarios.get(sid):
            issue("GRADING_SCENARIO", sid, artifact=ref)
            continue
        labelled = [item["call"] for item in grading["calls"]]
        if len(labelled) != len(set(labelled)) or set(labelled) != set(original["calls"]):
            issue("GRADING_CALLS", sid, artifact=ref)
        for item in grading["calls"]:
            if item["call"] not in original["calls"]:
                continue
            success = original["calls"][item["call"]].get("success_if")
            expected_ref = {**grading["scenario"], "pointer": grading["scenario"]["pointer"] + "/calls/" + item["call"] + "/success_if"} if success is not None else None
            if item["official_success_if"] != expected_ref:
                issue("GRADING_SUCCESS_REF", sid + "/" + item["call"], artifact=ref)
            for ground in item["ground_truth"]:
                attempt(ground)
    if set(graders) != set(scenarios):
        issue("GRADING_COVERAGE", "Every pinned scenario needs one grading contract")
    suite_ids = [suite["id"] for suite in manifest["suites"]]
    if len(suite_ids) != len(set(suite_ids)):
        issue("DUPLICATE_SUITE", "Duplicate suite ID")
    applicability = {suite["id"]: suite["applicable"] for suite in manifest["suites"]}
    if not applicability.get("fixed_turn"):
        issue("FIXED_TURN_SUITE", "Fixed-turn suite must be registered as applicable")
    if manifest["purpose"] == "official_eval":
        required_suites = {"fixed_turn", "asr", "latency_cost"}
        if manifest["level"] == "M2":
            required_suites |= {"judge", "rag", "diarization", "simulator", "tool_accuracy", "voice"}
        if any(not applicability.get(suite) for suite in required_suites):
            issue("OFFICIAL_SUITE_COVERAGE", "Required level suites cannot be omitted in official_eval", "missing_evidence")
    if applicability.get("simulator") and len(manifest["simulator_seeds"]) != 3:
        issue("SIMULATOR_SEEDS", "Simulator requires three pinned seeds")
    if applicability.get("diarization") and not applicability.get("asr"):
        issue("DIARIZATION_APPLICABILITY", "Diarization requires the registered ASR/audio cohort")
    for grading in graders.values():
        for call in grading["calls"]:
            for suite in call["suites"]:
                if suite["id"] not in applicability or suite["applicable"] and not applicability[suite["id"]]:
                    issue("APPLICABILITY", "Call suite conflicts with manifest applicability")
    for key in ("asr_ids", "rag_ids"):
        if len(manifest[key]) != len(set(manifest[key])):
            issue("DUPLICATE_SUITE_INPUT", key)
    asr_assets = scope.get("asr_assets", [])
    audio_ids = [item["id"] for item in asr_assets]
    if len(audio_ids) != len(set(audio_ids)) or set(audio_ids) != set(manifest["asr_ids"]):
        issue("ASR_ASSET_COVERAGE", "Declared team audio must match asr_ids exactly", "missing_evidence")
    for item in asr_assets:
        for key in ("audio", "ground_truth"):
            if key not in item:
                issue("ASR_ASSET_MISSING", f"{item['id']}: {key}", "missing_evidence")
            else:
                try:
                    data = assets.resolve(item[key], json_content=key != "audio")
                    if key == "audio":
                        with wave.open(str(data), "rb") as audio:
                            if (audio.getnframes() <= 0 or audio.getnchannels() != 1
                                    or audio.getsampwidth() != 2 or audio.getframerate() != 16000):
                                raise ValueError("Team audio must be nonempty PCM16 mono 16kHz WAV")
                    elif not isinstance(data, dict) or sum(dialogue.get("id") == item["id"] for dialogue in data.get("dialogues", [])) != 1:
                        raise ValueError("Audio ID needs exactly one dialogue in pinned ground truth")
                except (ValueError, KeyError, TypeError, OSError, wave.Error, EOFError) as exception:
                    issue("ASR_ASSET_MISSING", str(exception), "missing_evidence")
        if applicability.get("diarization"):
            if "segments" not in item:
                issue("SEGMENTS_MISSING", item["id"], "missing_evidence")
            else:
                attempt(item["segments"], "Segments")
    if scope.get("rag_ids", []) != manifest["rag_ids"]:
        issue("RAG_INPUT_COVERAGE", "Scope RAG IDs differ from manifest", "missing_evidence")
    if applicability.get("rag"):
        labels = attempt(scope["rag_ground_truth"]) if "rag_ground_truth" in scope else None
        if labels is None:
            issue("RAG_GROUND_TRUTH", "Pin BTC RAG labels before run", "missing_evidence")
        else:
            pinned = checker.read("sources/btc/rag/qa_labeled.json")
            if labels != pinned or set(manifest["rag_ids"]) != {item["qid"] for item in pinned["questions"]}:
                issue("RAG_GROUND_TRUTH", "RAG cohort must preserve all 60 pinned BTC qids/labels")
    for suite, key in (("asr", "asr_ids"), ("rag", "rag_ids")):
        if applicability.get(suite) and not manifest[key] or manifest[key] and not applicability.get(suite):
            issue("SUITE_INPUT_APPLICABILITY", suite)
    decisions = scope.get("source_decisions", [])
    authorized_origins = []
    if not decisions:
        issue("SOURCE_RIGHTS_MISSING", "SourceDecision and PII review required", "missing_evidence")
    for decision in decisions:
        try:
            validate("SourceDecision", decision)
            assets.resolve(decision["origin"], json_content=False)
            if (decision["run_id"] != manifest["run_id"] or decision["source_split"] != manifest["split"]
                    or decision["purpose"] != "report_only" or decision["permission"] != "allow"):
                issue("SOURCE_RIGHTS", "Require explicit report-only permission for this split/run")
            else:
                authorized_origins.append(decision["origin"])
        except (ValueError, KeyError, TypeError, OSError) as exception:
            issue("SOURCE_RIGHTS", str(exception))
    required_origins = list(manifest["scenarios"])
    required_origins.extend(item[key] for item in asr_assets for key in ("audio", "ground_truth", "segments") if key in item)
    if "rag_ground_truth" in scope:
        required_origins.append(scope["rag_ground_truth"])
    if any(ref not in authorized_origins for ref in required_origins):
        issue("SOURCE_RIGHTS_COVERAGE", "Each scenario/suite asset needs a pinned SourceDecision origin", "missing_evidence")
    review = scope.get("pii_review", {})
    if review.get("status") != "approved" or not review.get("reviewed_by") or review.get("scope") not in ("synthetic", "authorized_redacted"):
        issue("PII_REVIEW", "Missing declared PII authorization/redaction review", "missing_evidence")
    elif review["scope"] == "synthetic" and not manifest["fixture"] and manifest["split"] not in ("public", "development"):
        issue("PII_REVIEW", "Synthetic fixture declaration is not authorization for production/private data")
    active_disputes = {PUBLIC_DISPUTES[sid] for sid in scenarios if sid in PUBLIC_DISPUTES}
    active_disputes.update({"B05"} if "Q20" in manifest["rag_ids"] else set())
    active_disputes.update({"B06"} if "Q57" in manifest["rag_ids"] else set())
    active_disputes.update(manifest["dispute_ids"])
    for code in sorted(active_disputes):
        issue(code, DISPUTES.get(code, "Declared unresolved dispute"), "dispute")
    normal_multi = sum(not s["hard_case"] and len(s["calls"]) >= 2 for s in scenarios.values())
    hard = sum(bool(s["hard_case"]) for s in scenarios.values())
    sufficient = normal_multi >= 20 and hard >= 5 if manifest["level"] == "M1" else len(scenarios) >= 40
    if not sufficient:
        message = "Below official dataset scale; development/fixture only, not official acceptance"
        if manifest["purpose"] == "official_eval":
            issue("DATASET_SCALE", message, "missing_evidence")
        else:
            warnings.append(message)
    trace_ids = [f"{manifest['run_id']}/{config}/{plan['scenario_id']}/{plan['call']}/{turn}"
                 for config in ("full", "baseline_no_memory") for plan in plans
                 for turn in range(1, plan["expected_turns"] + 1)]
    status = {"verdict": "UNDETERMINED" if issues else "PASS",
              "completeness": "INCOMPLETE" if issues else "COMPLETE",
              "reason_codes": sorted({item["code"] for item in issues})}
    validation = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/preflight",
                  "run_id": manifest["run_id"], "status": status, "issues": issues, "coverage_refs": []}
    validate("ValidationReport", validation)
    return {"notice": "Planned-input validation only; no Agent/runner/A11 end-to-end PASS",
            "asset_root": str(assets.root),
            "validation": validation, "manifest": manifest_ref, "scope": scope_ref,
            "configuration": manifest["configuration"], "warnings": warnings,
            "adapter": adapter, "execution_gate": execution_gate(manifest, issues, adapter),
            "coverage_plan": {"calls": plans, "expected_trace_ids": trace_ids,
                              "asr_ids": manifest["asr_ids"], "rag_ids": manifest["rag_ids"]},
            "disputes": [{"id": code, "status": "OPEN", "description": DISPUTES.get(code, "Declared dispute")} for code in sorted(active_disputes)],
            "capabilities": {"btc_worker": "IMPLEMENTED_COMPONENT_TESTS", "runtime_memory_access_gate": "NOT_RUN",
                             "after_call_barrier": "NOT_BOUND_PREFLIGHT_ONLY", "runtime_adapter": "NOT_BOUND_PREFLIGHT_ONLY"},
            "deferred": deferred, "btc_full_readiness": "INCOMPLETE"}

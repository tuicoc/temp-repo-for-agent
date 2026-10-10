"""P4 immutable evidence replay: unmodified BTC CLI plus separate hard checks."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from referencing.exceptions import Unresolvable

from .assets import Assets, parse_json, read_json
from .collector import context_key, locked_run, status
from .contracts import ROOT, checker, validate
from .extractor import digest
from .metrics import READ_ONLY_TOOLS, match_tool_calls
from .preflight import call_plan
from .runner import _output_path, _write


def new_order_verified(event, before, after):
    """BTC mock state proof, not a general production-order verifier."""
    result, args = event["result"], event["request"]["args"]
    oid = result.get("order_id") if isinstance(result, dict) else None
    order = after["_ORDERS"].get(oid)
    return (isinstance(result, dict) and result.get("status") == "created" and oid not in before["_ORDERS"]
            and isinstance(order, dict) and order.get("order_id") == oid
            and all(order.get(k) == args[k] for k in ("customer_phone", "sku", "payment", "address", "price_vnd") if k in args)
            and order.get("qty") == args.get("qty", 1) and order.get("total_vnd") == result.get("total_vnd"))


def score(run_dir, out):
    """Never invoke Agent/tools/model, alter source runs, or repair official scores."""
    source, lock = locked_run(run_dir)
    checker.verify_sources()
    manifest = read_json(source.path("manifest.json"))
    validate("Manifest", manifest)
    plan = read_json(source.path("raw/execution-plan.json"))
    if "full" not in plan["configs"]:
        raise ValueError("BTC scoring requires the full config; baseline alone is not a system run")
    target = _output_path(out, source)
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = target / "evidence"
    evidence.mkdir()
    for name in list(lock["files"]) + ["artifacts.lock.json"]:
        payload = source.path(name).read_bytes()
        if name in lock["files"] and hashlib.sha256(payload).hexdigest() != lock["files"][name]:
            raise ValueError("Source changed while snapshotting")
        path = evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
    src, _ = locked_run(evidence)
    assets, inputs = Assets(target), Assets(evidence / "raw/inputs")
    _write(target / "manifest.json", manifest)
    manifest_ref = assets.ref("manifest.json")
    issues, checks, metrics, details = [], [], [], []

    def ref(value):
        return {**value, "path": "evidence/" + value["path"]}

    def issue(code, message, classification="missing_evidence", origin=None):
        item = {"code": code, "message": message, "classification": classification,
                "artifact": origin or manifest_ref, "json_pointer": ""}
        validate("Issue", item)
        issues.append(item)
        return item

    def check(name, findings, refs):
        checks.append({"check_id": name, "status": status(findings), "evidence_refs": refs})

    def write(name, value):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, value)
        return assets.ref(name)

    def rows(name, definition):
        result = []
        try:
            path = src.path(name)
            origin = ref(src.ref(name))
        except ValueError:
            issue("EVIDENCE_FILE_MISSING", name)
            return result
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                obj = parse_json(line)
                if definition == "Trace":
                    errors = checker.errors("sources/btc/schemas/trace_log.schema.json", obj)
                    if errors:
                        raise ValueError(errors[0].message)
                else:
                    validate(definition, obj)
                    for ev in obj.get("evidence_refs", []):
                        src.resolve(ev, json_content=False)
                    if definition == "Extraction":
                        for item in obj["items"]:
                            text = src.resolve(item["source"])
                            if (not isinstance(text, str) or item["start"] < 0 or item["end"] > len(text)
                                    or item["end"] <= item["start"] or text[item["start"]:item["end"]] != item["quote"]):
                                raise ValueError("Extraction quote/span invalid")
                            pointer = item["source"]["pointer"]
                            role = item["speaker"]
                            if (role == "agent" and pointer != "/agent_text"
                                    or role == "tool" and not pointer.startswith("/tool_texts/")
                                    or role == "consultant" and not pointer.startswith("/consultant_texts/")):
                                raise ValueError("Extraction source/speaker mismatch")
                            document = read_json(src.path(item["source"]["path"]))
                            if document["context"] != obj["context"]:
                                raise ValueError("Extraction source context mismatch")
                context = obj if definition == "Trace" else obj["context"]
                file_config = ("full" if name == "full.jsonl" else "baseline_no_memory" if name == "baseline.jsonl" else name.split("/")[0])
                if context_key(context) not in expected or context["config"] != file_config or obj["run_id"] != manifest["run_id"]:
                    raise ValueError("Unknown run/config/scenario/call/turn")
                result.append(obj)
            except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
                issue("EVIDENCE_SCHEMA", f"{name}:{index}: {exc}", "schema_error", origin)
        return result

    expected = [f"{manifest['run_id']}/{p['config']}/{p['scenario_id']}/{p['call']}/{turn}"
                for p in manifest["planned_calls"] if p["config"] in plan["configs"]
                for turn in range(1, p["expected_turns"] + 1)]
    if Counter(expected) != Counter(plan["expected_ids"]) or len(set(expected)) != len(expected):
        raise ValueError("Manifest/plan coverage mismatch or duplicate planned IDs")
    prior = read_json(src.path("validation.json"))
    validate("ValidationReport", prior)
    for item in prior["issues"]:
        src.resolve(item["artifact"], json_content=False)
        issues.append({**item, "artifact": ref(item["artifact"])})
    scenarios, graders = {}, {}
    for pinned in manifest["scenarios"]:
        obj = inputs.resolve(pinned)
        validate("Scenario", obj)
        if obj["scenario_id"] in scenarios:
            raise ValueError("Duplicate planned scenario")
        scenarios[obj["scenario_id"]] = obj
    for pinned in manifest["grading_contracts"]:
        obj = inputs.resolve(pinned)
        errors = checker.errors("grading-contract.schema.json", obj)
        if errors:
            raise ValueError(errors[0].message)
        if obj["scenario_id"] in graders or inputs.resolve(obj["scenario"]) != scenarios[obj["scenario_id"]]:
            raise ValueError("Grading contract scenario mismatch/duplicate")
        graders[obj["scenario_id"]] = obj

    configs = plan["configs"]
    traces, tools, memories, extractions, briefs = {}, {}, {}, {}, {}
    for config in configs:
        traces[config] = rows("full.jsonl" if config == "full" else "baseline.jsonl", "Trace")
        tools[config] = rows(config + "/tools.jsonl", "ToolEvent")
        memories[config] = rows(config + "/memory.jsonl", "MemoryEvidence")
        extractions[config] = rows(config + "/extraction.jsonl", "Extraction")
        briefs[config] = rows(config + "/brief-evidence.jsonl", "BriefEvidence")
    observed = [context_key(r) for values in traces.values() for r in values]
    counts = Counter(observed)
    gaps = {"missing_ids": sorted(set(expected) - set(observed)),
            "duplicate_ids": sorted(k for k, n in counts.items() if n > 1),
            "unknown_ids": sorted(set(observed) - set(expected))}
    coverage_findings = []
    if Counter(observed) != Counter(expected):
        coverage_findings.append(issue("TRACE_COVERAGE", "Missing/duplicate/unknown planned turns"))
    check("planned_trace_coverage", coverage_findings, [manifest_ref])
    coverage = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/score-coverage",
                "run_id": manifest["run_id"], "scope": "btc_trace", "expected_ids": expected,
                "observed_ids": observed, **gaps, "status": status(coverage_findings)}
    validate("Coverage", coverage)
    coverage_ref = write("coverage.json", coverage)

    # BTC receives only valid trace rows, never placeholders. Partial/duplicates stay diagnostic.
    for config, values in traces.items():
        path = target / ("scorer-input/full.jsonl" if config == "full" else "scorer-input/baseline.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    for sid, obj in scenarios.items():
        write("scorer-input/scenarios/" + digest(sid) + ".json", obj)
    scorer = inputs.path("sources/btc/eval/reference_eval.py")
    canonical = ROOT / "sources/btc/eval/reference_eval.py"
    if scorer.read_bytes() != canonical.read_bytes():
        raise ValueError("Run scorer source differs from verified BTC source")
    argv = [sys.executable, "-B", str(scorer), "--scenarios", str(target / "scorer-input/scenarios"),
            "--trace", str(target / "scorer-input/full.jsonl"), "--out", str(target / "official-report.json")]
    if "baseline_no_memory" in configs:
        argv += ["--baseline", str(target / "scorer-input/baseline.jsonl")]
    try:
        process = subprocess.run(argv, cwd=target, capture_output=True, text=True, timeout=30)
        code, stdout, stderr = process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = None, str(exc.stdout or ""), str(exc.stderr or "")
    for filename, content in (("scorer.stdout.txt", stdout), ("scorer.stderr.txt", stderr)):
        with (target / filename).open("x", encoding="utf-8") as stream:
            stream.write(content)
    invocation = {"argv": argv, "returncode": code,
        "scorer": ref(src.ref("raw/inputs/sources/btc/eval/reference_eval.py")),
        "stdout": assets.ref("scorer.stdout.txt"), "stderr": assets.ref("scorer.stderr.txt"),
        "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "quality_accepted": False}
    official_ref = None
    try:
        if code != 0:
            raise ValueError(f"BTC CLI exit {code}")
        official = read_json(target / "official-report.json")
        validate("OfficialReport", official)
        official_ref = assets.ref("official-report.json")
    except (OSError, ValueError) as exc:
        issue("SCORER_INFRA", str(exc), "infra_error")

    def selected(values, config, sid, call):
        return [v for v in values[config] if (v.get("context", v)["scenario_id"], v.get("context", v)["call"]) == (sid, call)]

    def input_ref(pinned):
        inputs.resolve(pinned)
        return {**pinned, "path": "evidence/raw/inputs/" + pinned["path"]}

    def metric(mid, formula, cohort, n, d, refs, missing=False, unit="percent"):
        value = None if missing or not d else n / d * (100 if unit == "percent" else 1)
        obj = {"metric_id": mid, "formula_id": formula, "unit": unit, "value": value,
               "numerator": n, "denominator": d, "cohort_ids": cohort, "evidence_refs": refs,
               "status": "INCOMPLETE" if missing else "UNDEFINED" if not d else "MEASURED",
               "reason": "MISSING_OR_DISPUTED_EVIDENCE" if missing else "ZERO_DENOMINATOR" if not d else None,
               "currency": None}
        validate("Metric", obj)
        metrics.append(obj)

    for config in configs:
        fact_n, fact_d, fact_missing, fact_cohort, verified_orders, closed = 0, 0, False, [], [], {}
        for planned in (p for p in manifest["planned_calls"] if p["config"] == config):
            sid, call = planned["scenario_id"], planned["call"]
            spec = scenarios[sid]["calls"][call]
            call_id = f"{manifest['run_id']}/{config}/{sid}/{call}"
            trace = selected(traces, config, sid, call)
            ts, ms, es, bs = [selected(v, config, sid, call) for v in (tools, memories, extractions, briefs)]
            call_refs = [ref(src.ref(config + "/" + f)) for f in ("tools.jsonl", "memory.jsonl", "extraction.jsonl")]
            complete = Counter(context_key(r) for r in trace) == Counter(call_id + "/" + str(t) for t in range(1, planned["expected_turns"] + 1))
            call_findings = []
            if not complete:
                call_findings.append(issue("CALL_COVERAGE", call_id))
            grader = next((g for g in graders.get(sid, {}).get("calls", []) if g["call"] == call), None)
            disputed = bool(grader and grader["dispute_ids"])
            if disputed:
                call_findings.append(issue("GT_DISPUTED", call_id, "dispute"))
            available_roles = {"trace": bool(trace), "memory": bool(ms), "tools": bool(ts),
                               "tool_events": bool(ts), "extraction": bool(es),
                               "call_brief": any(b["kind"] == "call_brief" for b in bs),
                               "handoff_brief": any(b["kind"] == "handoff_brief" for b in bs)}
            if grader is None:
                call_findings.append(issue("GRADING_MISSING", call_id))
            elif grader["mode"] != "assertion_only":
                call_findings.append(issue("JUDGE_PENDING", call_id + "/" + grader["mode"]))
            if grader and not any(c["kind"] == "tool_accuracy" for c in grader["checks"]):
                call_findings.append(issue("TOOL_EXPECTATIONS_NOT_LABELLED", call_id))
            for role in graders.get(sid, {}).get("required_evidence", []):
                if not available_roles.get(role, False):
                    call_findings.append(issue("REQUIRED_EVIDENCE_MISSING", call_id + "/" + role))

            # Validate invocation outcome separately from TCA and official TSR.
            tool_findings = []
            tool_complete = Counter(digest(t) for r in trace for t in r["tool_calls"]) == Counter(
                digest({**e["request"], "result": e["result"]}) for e in ts)
            # A complete empty log proves no invocation; it is not missing evidence.
            log_present = (src.root / config / "tools.jsonl").is_file()
            available_roles["tools"] = available_roles["tool_events"] = complete and tool_complete and log_present
            extraction_complete = Counter(context_key(e["context"]) for e in es) == Counter(
                call_id + "/" + str(t) for t in range(1, planned["expected_turns"] + 1))
            if not tool_complete:
                tool_findings.append(issue("TOOL_EVIDENCE_COVERAGE", call_id))
            if not extraction_complete:
                call_findings.append(issue("EXTRACTION_COVERAGE", call_id))
            for row in trace:
                extracted = [e for e in es if e["context"] == {k: row[k] for k in ("run_id", "config", "scenario_id", "call", "turn")}]
                if len(extracted) != 1:
                    continue
                atomics = extracted[0]["items"]
                claims = [{"field": i["slot_or_field"], "value": i["value"], "text": i["quote"]}
                          for i in atomics if i["kind"] == "claim" and i["speaker"] == "agent"]
                questions = [{"slot": i["slot_or_field"], "type": i["question_type"], "text": i["quote"]}
                             for i in atomics if i["kind"] == "question" and i["speaker"] == "agent"]
                if row["claims"] != claims or row["questions"] != questions or row.get("facts_used", []) != [i["slot_or_field"] for i in atomics if i["kind"] == "fact_usage"]:
                    call_findings.append(issue("TRACE_EXTRACTION_MISMATCH", call_id, "schema_error"))
            for event in ts:
                evref = ref(src.ref(config + "/tools.jsonl"))
                if event["outcome"] == "business_error":
                    tool_findings.append(issue("TOOL_BUSINESS_ERROR", event["event_id"], "agent_violation", evref))
                    continue
                if event["outcome"] != "success":
                    tool_findings.append(issue("TOOL_EXECUTION_UNKNOWN", event["event_id"], "infra_error", evref))
                    continue
                result = event["result"]
                if isinstance(result, dict) and result.get("error"):
                    tool_findings.append(issue("TOOL_OUTCOME_CONTRADICTION", event["event_id"], "schema_error", evref))
                    continue
                try:
                    if len(event["evidence_refs"]) != 1:
                        raise ValueError("Unique audit required")
                    audit = src.resolve(event["evidence_refs"][0])["data"]
                    raw_event = audit["event"]
                    if any(raw_event[k] != event[k] for k in event if k != "evidence_refs"):
                        raise ValueError("Audit/event mismatch")
                    before, after = audit["state_before"], audit["state_after"]
                    if (before != after) != event["side_effect"]:
                        raise ValueError("State delta/side_effect mismatch")
                    if event["request"]["name"] == "order.create":
                        if not new_order_verified(event, before, after):
                            tool_findings.append(issue("ORDER_STATE_UNVERIFIED", event["event_id"], "agent_violation", evref))
                        else:
                            verified_orders.append(event["event_id"])
                            closed[sid] = min(closed.get(sid, 4), int(call.split("_")[1]))
                    elif event["request"]["name"] in ("schedule.callback", "handoff.transfer", "order.cancel_or_return"):
                        state_name = "_CALLBACKS" if event["request"]["name"] == "schedule.callback" else "_TICKETS"
                        added = [v for v in after[state_name] if v not in before[state_name]]
                        if not isinstance(result, dict) or not any(all(v.get(k) == val for k, val in result.items()) for v in added):
                            tool_findings.append(issue("TOOL_RESULT_STATE_MISMATCH", event["event_id"], "agent_violation", evref))
                    elif event["request"]["name"] not in READ_ONLY_TOOLS and before == after:
                        tool_findings.append(issue("TOOL_STATE_MISSING", event["event_id"], origin=evref))
                except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError) as exc:
                    tool_findings.append(issue("TOOL_STATE_EVIDENCE", str(exc), origin=evref))
            check(call_id + "/tool_execution_state", tool_findings, call_refs[:1])

            memory_findings = []
            before_mem = [m for m in ms if m["phase"] == "before_call"]
            after_mem = [m for m in ms if m["phase"] == "after_call"]
            if len(before_mem) != 1 or len(after_mem) != 1:
                memory_findings.append(issue("MEMORY_PHASE_COVERAGE", call_id))
            on = next(p["on"] for p in call_plan(scenarios[sid], manifest["reference_date"]) if p["call"] == call)
            at = datetime.fromisoformat(on + "T00:00:00+07:00")
            for snapshot in ms:
                namespace = f"{manifest['state_namespaces'][config]}/{manifest['run_id']}/{sid}"
                if snapshot["namespace"] != namespace or before_mem and snapshot["customer_id"] != before_mem[0]["customer_id"]:
                    memory_findings.append(issue("MEMORY_SCOPE_PROFILE", call_id, "agent_violation"))
                active = [f for f in snapshot["facts"] if f["state"] == "active"]
                if len({f["key"] for f in active}) != len(active):
                    memory_findings.append(issue("MEMORY_MULTIPLE_ACTIVE", call_id, "agent_violation"))
                for item in snapshot["facts"] + snapshot["writes"]:
                    if item["customer_id"] != snapshot["customer_id"]:
                        memory_findings.append(issue("MEMORY_WRONG_PROFILE", call_id, "agent_violation"))
                    try:
                        src.resolve(item["source"])
                    except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
                        memory_findings.append(issue("MEMORY_SOURCE_MISSING", str(exc)))
                for fact in active:
                    start = datetime.fromisoformat(fact["valid_from"])
                    end = datetime.fromisoformat(fact["valid_until"]) if fact["valid_until"] else None
                    if start > at or end is not None and end <= at:
                        memory_findings.append(issue("MEMORY_INACTIVE_VALUE_EXPOSED", call_id, "agent_violation"))
                for write_item in snapshot["writes"]:
                    same = [f for f in active if f["key"] == write_item["key"]]
                    if write_item["op"] == "delete" and same or write_item["op"] in ("set", "supersede") and not any(f["value"] == write_item["value"] for f in same):
                        memory_findings.append(issue("MEMORY_WRITE_STATE", call_id, "agent_violation"))
            check(call_id + "/memory_integrity", memory_findings, call_refs[1:2])

            fact_findings = []
            items = [i for e in es for i in e["items"] if i["kind"] == "fact_usage" and i["speaker"] in ("agent", "tool")]
            for slot in spec.get("must_carry_over", []):
                fact_d += 1
                fact_cohort.append(call_id + "/" + slot)
                used = [i for i in items if i["slot_or_field"] == slot]
                gt = spec.get("ground_truth_facts", {})
                if disputed or slot not in gt or not complete or not extraction_complete:
                    fact_missing = True
                    fact_findings.append(issue("FACT_GT_OR_USAGE_MISSING", call_id + "/" + slot, "dispute" if disputed else "missing_evidence"))
                elif not used or any(i["value"] != gt[slot] for i in used):
                    fact_findings.append(issue("FACT_VALUE_WRONG_OR_UNUSED", call_id + "/" + slot, "agent_violation"))
                elif memory_findings:
                    fact_missing = True
                    fact_findings.append(issue("FACT_PROFILE_UNVERIFIED", call_id + "/" + slot))
                else:
                    fact_n += 1
            check(call_id + "/fact_carryover", fact_findings, call_refs)

            # Claims outside settled GT are unknown, never silently proven correct.
            claim_findings = []
            for row in trace:
                for claim in row["claims"]:
                    gt = spec.get("ground_truth_facts", {})
                    if disputed or claim["field"] not in gt:
                        claim_findings.append(issue("CLAIM_GT_MISSING", call_id + "/" + claim["field"], "dispute" if disputed else "missing_evidence"))
                    elif claim["value"] != gt[claim["field"]]:
                        claim_findings.append(issue("CLAIM_VALUE_WRONG", call_id + "/" + claim["field"], "agent_violation"))
            check(call_id + "/claim_gt_coverage", claim_findings, call_refs[2:])
            for brief in bs:
                brief_object = src.resolve(brief["object_ref"])
                schema = "sources/btc/schemas/" + ("call_brief" if brief["kind"] == "call_brief" else "handoff_brief") + ".schema.json"
                if brief["validation"]["verdict"] == "FAIL" or checker.errors(schema, brief_object):
                    call_findings.append(issue("BRIEF_INVALID", call_id, "agent_violation", ref(brief["object_ref"])))
                if not isinstance(brief_object, dict):
                    continue
                if brief_object.get("customer_phone") != scenarios[sid]["customer_phone"]:
                    call_findings.append(issue("BRIEF_WRONG_PROFILE", call_id, "agent_violation", ref(brief["object_ref"])))
                content = brief_object.get("profile_facts", {}) if brief["kind"] == "call_brief" else brief_object.get("facts_confirmed", {})
                for field, value in content.items():
                    gt = spec.get("ground_truth_facts", {})
                    if field in gt and not disputed and value != gt[field]:
                        call_findings.append(issue("BRIEF_FACT_WRONG", call_id + "/" + field, "agent_violation", ref(brief["object_ref"])))
                if brief["kind"] == "handoff_brief":
                    call_findings.append(issue("HANDOFF_CONTENT_REVIEW_PENDING", call_id, origin=ref(brief["object_ref"])))
            if (spec.get("success_if") or {}).get("tool_called") == "handoff.transfer" or spec.get("expected_outcome") == "chuyen_may":
                if not any(b["kind"] == "handoff_brief" for b in bs):
                    call_findings.append(issue("HANDOFF_EVIDENCE_MISSING", call_id))
            if not grader or not any(c["kind"] == "guardrail" for c in grader["checks"]):
                call_findings.append(issue("PII_POLICY_NOT_LABELLED", call_id))
            if grader:
                for assertion in grader["checks"]:
                    findings = []
                    params, kind = assertion["params"], assertion["kind"]
                    try:
                        for role in assertion["required_evidence"]:
                            if not available_roles.get(role, False):
                                findings.append(issue("ASSERTION_EVIDENCE_MISSING", call_id + "/" + role))
                        if not complete:
                            findings.append(issue("ASSERTION_COVERAGE", call_id))
                        if disputed:
                            findings.append(issue("ASSERTION_GT_DISPUTED", call_id, "dispute"))
                        elif kind == "tool_success":
                            matching = [e for e in ts if e["request"]["name"] == params["tool_name"]]
                            if not matching:
                                    findings.append(issue("REQUIRED_TOOL_MISSING", call_id, "agent_violation" if complete and tool_complete else "missing_evidence"))
                            for event in matching:
                                actual = event["outcome"] if params["expected_status"] == "success" else (event["result"].get("status") if isinstance(event["result"], dict) else None)
                                if event["outcome"] == "business_error" or actual != params["expected_status"]:
                                    findings.append(issue("REQUIRED_TOOL_FAILED", event["event_id"], "agent_violation" if event["outcome"] in ("success", "business_error") else "infra_error"))
                        elif kind == "fact_value":
                            expected_value = inputs.resolve(params["expected_source"])
                            required = [i for i in items if i["slot_or_field"] == params["slot"]]
                            if not required or any(i["value"] != expected_value for i in required):
                                findings.append(issue("FACT_ASSERTION", call_id, "agent_violation" if complete and es else "missing_evidence"))
                        elif kind == "claim_grounding":
                            gt = inputs.resolve(params["ground_truth"])
                            for row in trace:
                                for item in row["claims"]:
                                    if item["field"] not in params["fields"]:
                                        continue
                                    if item["field"] not in gt:
                                        findings.append(issue("CLAIM_ASSERTION_GT_MISSING", call_id))
                                    elif item["value"] != gt[item["field"]]:
                                        findings.append(issue("CLAIM_ASSERTION_WRONG", call_id, "agent_violation"))
                        elif kind == "guardrail":
                            blob = json.dumps([{"agent_text": r["agent_text"], "tools": r["tool_calls"], "writes": r.get("memory_writes")} for r in trace], ensure_ascii=False)
                            if not params["patterns"]:
                                findings.append(issue("GUARDRAIL_POLICY_EMPTY", call_id))
                            for pattern in params["patterns"]:
                                if re.search(pattern, blob):
                                    findings.append(issue("GUARDRAIL_PATTERN", call_id, "agent_violation"))
                        elif kind == "memory":
                            expectation = inputs.resolve(params["expectation"])
                            latest = {f["key"]: f["value"] for m in after_mem for f in m["facts"] if f["state"] == "active"}
                            for key, value in expectation.items():
                                if key == "superseded" and isinstance(value, dict):
                                    for slot, old_value in value.items():
                                        if latest.get(slot) == old_value:
                                            findings.append(issue("MEMORY_SUPERSEDED_ACTIVE", call_id + "/" + slot, "agent_violation"))
                                        elif not any(f["key"] == slot and f["value"] == old_value and f["state"] == "superseded" for m in after_mem for f in m["facts"]):
                                            findings.append(issue("MEMORY_SUPERSEDE_HISTORY_MISSING", call_id + "/" + slot))
                                elif key == "must_not_write_to" and isinstance(value, (str, list)):
                                    forbidden = [value] if isinstance(value, str) else value
                                    for m in ms:
                                        if any(w["customer_id"] in forbidden for w in m["writes"]):
                                            findings.append(issue("MEMORY_FORBIDDEN_PROFILE_WRITE", call_id, "agent_violation"))
                                elif key in ("superseded", "must_not_write_to", "address_ttl_check", "profile_state"):
                                    findings.append(issue("MEMORY_EXPECTATION_SEMANTICS_PENDING", call_id + "/" + key))
                                elif key not in latest or latest[key] != value:
                                    findings.append(issue("MEMORY_EXPECTATION_WRONG", call_id + "/" + key, "agent_violation" if after_mem else "missing_evidence"))
                        elif kind == "schema":
                            # ToolArgs contract validates the named request (name+args).
                            roles = {"trace": trace, "tool_args": [e["request"] for e in ts],
                                     "call_brief": [src.resolve(b["object_ref"]) for b in bs if b["kind"] == "call_brief"],
                                     "handoff_brief": [src.resolve(b["object_ref"]) for b in bs if b["kind"] == "handoff_brief"]}
                            objects = roles[params["artifact_role"]]
                            schema_name = params["schema_ref"].split("#", 1)[0]
                            if not schema_name or not (ROOT / schema_name).resolve().is_relative_to(ROOT) or not (ROOT / schema_name).is_file():
                                raise ValueError("Schema must name a local evaluator contract")
                            if not objects:
                                findings.append(issue("SCHEMA_OBJECT_MISSING", call_id))
                            for obj in objects:
                                errors = checker.errors(params["schema_ref"], obj)
                                if errors:
                                    findings.append(issue("SCHEMA_ASSERTION", errors[0].message, "agent_violation"))
                        elif kind == "tool_accuracy":
                            labels = inputs.resolve(params["expected_calls"])
                            if any(labels["context"][k] != value for k, value in (("run_id", manifest["run_id"]), ("config", config), ("scenario_id", sid), ("call", call))):
                                raise ValueError("Expected tool labels belong to another run/config/call; never relabel after execution")
                            matched = match_tool_calls(labels, [e for e in ts if e["context"] == labels["context"]])
                            details.append({"check_id": call_id + "/" + assertion["check_id"], "matching": matched,
                                            "labels": input_ref(params["expected_calls"])})
                            metric(call_id + "/tool_accuracy", "tool-accuracy.v2", [context_key(labels["context"])], matched["tp"], matched["tp"] + matched["fp"] + matched["fn"], call_refs, not complete)
                            if matched["fp"] or matched["fn"]:
                                findings.append(issue("TOOL_ACCURACY", call_id, "agent_violation" if complete else "missing_evidence"))
                            if matched["status"] == "UNDEFINED":
                                findings.append(issue("TOOL_ACCURACY_UNDEFINED", call_id))
                        else:
                            raise ValueError("Unsupported assertion kind")
                    except (ValueError, KeyError, TypeError, OSError, IndexError, re.error, Unresolvable) as exc:
                        findings.append(issue("ASSERTION_CONFIG_OR_EVIDENCE", str(exc)))
                    check(call_id + "/" + assertion["check_id"], findings, call_refs)
                    call_findings.extend(findings)
            check(call_id + "/grading", call_findings, call_refs)
        metric(config + "/fact_value", "fact-value.v1", fact_cohort, fact_n, fact_d,
               [ref(src.ref(config + "/extraction.jsonl"))], fact_missing)
        write(config + "/verified-orders.json", {"event_ids": verified_orders,
            "first_close_call_by_scenario": closed,
            "notice": "Only new orders proven in audit state; never seed orders or invocation-only close"})
        metric(config + "/verified_calls_to_close", "ratio.v1", [manifest["run_id"] + "/" + config + "/" + sid for sid in scenarios],
               sum(closed.values()), len(closed), [assets.ref(config + "/verified-orders.json")],
               Counter(context_key(r) for r in traces[config]) != Counter(k for k in expected if k.startswith(manifest["run_id"] + "/" + config + "/")), unit="count")

    if official_ref is not None:
        report = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/supplemental",
                  "run_id": manifest["run_id"], "status": status(issues), "checks": checks,
                  "metrics": metrics, "coverage_refs": [coverage_ref], "official_report": official_ref}
        validate("SupplementalReport", report)
        write("supplemental-report.json", report)
    validation = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/score-validation",
                  "run_id": manifest["run_id"], "status": status(issues), "issues": issues, "coverage_refs": [coverage_ref]}
    validate("ValidationReport", validation)
    write("validation.json", validation)
    write("assertion-details.json", details)
    write("scorer-invocation.json", {**invocation, "diagnostic_only": bool(issues)})
    summary = {"run_id": manifest["run_id"], "fixture": manifest["fixture"], "status": status(issues),
               "official_report_available": official_ref is not None, "diagnostic_only": bool(issues),
               "quality_accepted": False, "deferred": read_json(src.path("collector-report.json"))["deferred"],
               "btc_full_readiness": "INCOMPLETE", "notice": "P4 offline scoring, not runtime/DB or acceptance certification"}
    write("score-report.json", summary)
    write("artifacts.lock.json", {"files": {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in sorted(target.rglob("*")) if p.is_file()}})
    locked_run(run_dir)
    checker.verify_sources()
    return summary

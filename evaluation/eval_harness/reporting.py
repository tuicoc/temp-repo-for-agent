"""P6 immutable M1 metrics/comparison; official BTC output is never repaired."""
from collections import Counter, defaultdict
from fractions import Fraction
import importlib.util
import json
from math import isclose
import shutil
import sys

from .assets import Assets, parse_json, read_json
from .collector import context_key, locked_run, milliseconds, status
from .contracts import ROOT, checker, validate
from .datasets import close_output
from .extractor import digest
from .metrics import cost_per_completed_call
from .p6_evidence import import_casebook, reconcile_usage
from .runner import _output_path, _write

CONFIGS = ("baseline_no_memory", "full")
COMPONENTS = ("llm_input", "llm_output", "asr", "tts", "tool")


def validate_policy(policy):
    if set(policy) != {"schema_version", "currency", "prices"} or policy["schema_version"] != "p6-metrics-policy-v1" or set(policy["prices"]) != set(COMPONENTS):
        raise ValueError("P6 price policy requires explicit all-runtime component prices")
    for rate in policy["prices"].values():
        if rate is not None and rate != "not_used" and (type(rate) not in (int, float) or rate < 0):
            raise ValueError("Price must be a nonnegative per-unit number, null or not_used")
    currency = policy["currency"]
    if currency is not None and (not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha() or not currency.isupper()):
        raise ValueError("ISO currency required")


def btc_module():
    checker.verify_sources()
    spec = importlib.util.spec_from_file_location("btc_p6", ROOT / "sources/btc/eval/reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


def make_metric(mid, formula, unit, cohort, refs, *, n=None, d=None, value=None, incomplete=None, currency=None):
    state, reason = "MEASURED", None
    if incomplete:
        value, state, reason = None, "INCOMPLETE", incomplete
    elif d == 0 or (d is None and value is None):
        value, state, reason = None, "UNDEFINED", "ZERO_DENOMINATOR_OR_NO_SAMPLES"
    elif d is not None:
        value = n / d * (100 if unit == "percent" else 1)
    obj = {"metric_id": mid, "formula_id": formula, "unit": unit, "value": value,
           "numerator": n, "denominator": d, "cohort_ids": cohort, "evidence_refs": refs,
           "status": state, "reason": reason, "currency": currency}
    validate("Metric", obj)
    return obj


def timing_metrics(expected, records, warmup, minimum, refs):
    """Expected order defines warmup; missing samples never move the boundary."""
    counts = Counter(context_key(r["context"]) for r in records)
    problems = []
    if counts != Counter(expected):
        problems.append("TIMING_COVERAGE")
    by_id = {context_key(r["context"]): r for r in records}
    warmup_ids, effective_ids = expected[:warmup], expected[warmup:]
    values = {"ttft": [], "total": []}
    for key in expected:
        row = by_id.get(key)
        if row is None:
            continue
        validate("TimingEvidence", row)
        if row["warmup"] != (key in warmup_ids):
            problems.append("WARMUP_TAG_MISMATCH")
        try:
            total = milliseconds(row["request_at"], row["completed_at"])
            first = milliseconds(row["request_at"], row["first_token_at"])
            if first is None or total is None or first > total:
                raise ValueError("Missing/inconsistent backend timestamps")
            if key in effective_ids:
                values["ttft"].append(first)
                values["total"].append(total)
        except ValueError:
            problems.append("TIMING_INVALID_OR_MISSING")
    if any(len(xs) < minimum for xs in values.values()):
        problems.append("LATENCY_SAMPLE_QUOTA")
    btc = btc_module()
    metrics = [make_metric("agent." + key + ".effective_p95", "latency-p95.v1", "ms", effective_ids, refs,
                           value=btc.p95(xs), incomplete=",".join(sorted(set(problems))) or None)
               for key, xs in values.items()]
    return metrics, {"expected_raw_count": len(expected), "observed_raw_count": len(records),
                     "warmup_ids": warmup_ids, "effective_ids": effective_ids,
                     "valid_effective_counts": {key: len(v) for key, v in values.items()},
                     "minimum_effective": minimum, "problems": sorted(set(problems))}


def runtime_cost(records, expected, calls, policy, raw_assets):
    """Recompute pinned per-unit prices; include warmup and failed-call usage.

    Non-LLM units are supplied in raw usage.cost_units (audio minutes, TTS chars,
    tool invocations). None prices mean unknown; explicitly 'not_used' means zero
    for that declared component, not zero compute cost or missing usage.
    """
    prices, currency = policy["prices"], policy["currency"]
    if currency is None or any(prices[k] is None for k in COMPONENTS):
        return None, "PRICE_OR_COST_SCOPE_MISSING"
    if Counter(context_key(r["context"]) for r in records) != Counter(expected):
        return None, "COST_USAGE_COVERAGE"
    total = 0.0
    for row in records:
        if any(row[k] is None for k in ("input_tokens", "output_tokens", "cost", "currency")) or row["currency"] != currency:
            return None, "USAGE_OR_CURRENCY_MISSING_OR_MIXED"
        if len(row["evidence_refs"]) != 1:
            return None, "COST_RECEIPT_MISSING"
        raw = raw_assets.resolve(row["evidence_refs"][0])
        usage = raw.get("data", {}).get("result", {}).get("usage", {})
        if usage.get("cost_scope") != "all_agent_runtime" or usage.get("pricing_sha256") != digest(prices):
            return None, "COST_SCOPE_OR_PRICE_RECEIPT_MISSING"
        units = {"llm_input": row["input_tokens"], "llm_output": row["output_tokens"], **usage.get("cost_units", {})}
        if units["llm_input"] != row["input_tokens"] or units["llm_output"] != row["output_tokens"]:
            return None, "TOKEN_UNIT_MISMATCH"
        charge = 0.0
        for key in COMPONENTS:
            rate = prices[key]
            if rate == "not_used":
                if units.get(key, 0) != 0:
                    return None, "COST_NOT_USED_CONTRADICTION"
                continue
            unit = units.get(key)
            if type(unit) not in (int, float) or unit < 0:
                return None, "COST_COMPONENT_USAGE_MISSING"
            charge += rate * unit
        if not isclose(charge, row["cost"], rel_tol=1e-9, abs_tol=1e-12):
            return None, "COST_RECEIPT_PRICE_MISMATCH"
        total += charge
    # A failed hook can incur charges outside successful run_turn receipts.
    if any(c["failed"] for c in calls):
        return None, "FAILED_CALL_ADDITIONAL_USAGE_UNRECONCILED"
    return total, None


def comparison_rows(base, full):
    b = {m["metric_id"]: m for m in base}
    s = {m["metric_id"]: m for m in full}
    rows = []
    for mid in sorted(set(b) | set(s)):
        bm, sm = b.get(mid), s.get(mid)
        bv, sv = bm["value"] if bm else None, sm["value"] if sm else None
        kind = "relative_reduction" if mid == "agent.rqr" else "system_minus_baseline"
        incomplete = not bm or not sm or any(m["status"] == "INCOMPLETE" for m in (bm, sm) if m)
        mismatch = bool(bm and sm and (bm["unit"] != sm["unit"] or bm["currency"] != sm["currency"]))
        state, reason, delta = "MEASURED", None, None
        if incomplete or mismatch:
            state, reason = "INCOMPLETE", "MISSING_METRIC_EVIDENCE_OR_UNIT_CURRENCY_MISMATCH"
        elif bv is None or sv is None or kind == "relative_reduction" and bv == 0:
            state, reason = "UNDEFINED", "MISSING_VALUE_OR_ZERO_BASELINE"
        else:
            if kind == "relative_reduction" and bm["denominator"] and sm["denominator"]:
                # Exact raw ratios avoid a genuine 40% boundary becoming 39.999... .
                base = Fraction(str(bm["numerator"])) / Fraction(str(bm["denominator"]))
                full = Fraction(str(sm["numerator"])) / Fraction(str(sm["denominator"]))
                delta = float((base - full) / base * 100)
            else:
                delta = (bv - sv) / bv * 100 if kind == "relative_reduction" else sv - bv
        unit = (sm or bm)["unit"]
        rows.append({"metric_id": mid, "baseline": bv, "system": sv, "delta": delta,
                     "delta_kind": kind, "unit": "percent" if kind == "relative_reduction" else "percentage_points" if unit == "percent" else unit,
                     "status": state, "reason": reason})
    return rows


def render_table(comparison, summary, asr=None):
    def number(value):
        return "—" if value is None else format(value, ".4g")
    lines = ["# A.6 — P6 evaluation", "", "Status: " + summary["status"]["verdict"] + " / " + summary["status"]["completeness"],
             "", "Pipeline/fixture output, not release or full BTC acceptance.", "",
             "| Metric | Baseline | System | Delta | Delta unit/type | Coverage / status |",
             "| --- | ---: | ---: | ---: | --- | --- |"]
    for row in comparison["rows"]:
        coverage = summary["metric_coverage"].get(row["metric_id"], {})
        label = str(coverage.get("baseline", "—")) + "/" + str(coverage.get("system", "—"))
        lines.append("| " + " | ".join([row["metric_id"], number(row["baseline"]), number(row["system"]), number(row["delta"]),
                     row["unit"] + " / " + row["delta_kind"], label + " · " + row["status"]]) + " |")
    lines += ["", "## Checks", "", "| Check | Verdict | Completeness |", "| --- | --- | --- |"]
    for check in summary["checks"]:
        lines.append(f"| {check['check_id']} | {check['status']['verdict']} | {check['status']['completeness']} |")
    lines += ["", "Casebook qualifying real cases: " + str(summary["casebook"]["qualifying_real_cases"]) + "/10; analysis complete: " + str(summary["casebook"]["analysis_complete"]),
              "", "Deferred: " + json.dumps(summary["deferred"], ensure_ascii=False), ""]
    return "\n".join(lines)


def copy_run(source, target):
    assets, lock = locked_run(source)
    target.mkdir(parents=True, exist_ok=False)
    for name in list(lock["files"]) + ["artifacts.lock.json"]:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(assets.path(name), path)
    return locked_run(target)[0]


def report_metrics(run_dir, out, *, usage_run=None, casebook_run=None):
    source, _ = locked_run(run_dir)
    manifest = read_json(source.path("manifest.json"))
    validate("Manifest", manifest)
    if manifest["level"] != "M1":
        raise ValueError("P6 currently implements M1 reporting only")
    target = _output_path(out, source)
    for extra in (usage_run, casebook_run):
        if extra is not None and target.is_relative_to(locked_run(extra)[0].root):
            raise ValueError("Do not write inside optional source evidence")
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    score = copy_run(source.root, target / "score")
    usage_assets = copy_run(usage_run, target / "usage") if usage_run is not None else None
    case_assets = copy_run(casebook_run, target / "casebook-review") if casebook_run is not None else None
    ledger = read_json(usage_assets.path("usage-ledger.json")) if usage_assets else None
    local, evidence = Assets(target), Assets(target / "score/evidence")
    inputs = Assets(evidence.root / "raw/inputs")
    _write(target / "manifest.json", manifest)
    consumption_refs=[]
    for config in CONFIGS:
        name="score/evidence/"+config+"/raw-records.json"
        if (target/name).exists():
            for i,event in enumerate(read_json(target/name)):
                if event.get("data",{}).get("event",{}).get("kind")=="candidate_consumed" and event["data"]["event"].get("candidate_hash")==manifest["candidate_hash"]:
                    consumption_refs.append(local.ref(name,"/"+str(i)))
    _write(target/"consumption.json",{"candidate_hash":manifest["candidate_hash"],"evidence_refs":consumption_refs})
    issues = []
    for item in read_json(score.path("validation.json"))["issues"]:
        score.resolve(item["artifact"], json_content=False)
        issues.append({**item, "artifact": {**item["artifact"], "path": "score/" + item["artifact"]["path"]}})

    def issue(code, message, classification="missing_evidence", origin="manifest.json"):
        item = {"code": code, "message": message, "classification": classification, "artifact": local.ref(origin), "json_pointer": ""}
        validate("Issue", item)
        issues.append(item)

    def rows(name, definition, assets=evidence):
        result = []
        try:
            for line in assets.path(name).read_text().splitlines():
                obj = parse_json(line)
                validate(definition, obj)
                for ref in obj.get("evidence_refs", []):
                    assets.resolve(ref, json_content=False)
                result.append(obj)
        except (OSError, ValueError, KeyError) as exc:
            issue("P6_EVIDENCE_INVALID", name + ": " + str(exc))
        return result

    policies = []
    for ref in manifest["sources"]:
        if ref["pointer"] == "" and ref["path"].endswith(".json"):
            obj = inputs.resolve(ref)
            if isinstance(obj, dict) and obj.get("schema_version") == "p6-metrics-policy-v1":
                policies.append((ref, obj))
    policy = {"schema_version": "p6-metrics-policy-v1", "currency": None, "prices": dict.fromkeys(COMPONENTS)}
    if len(policies) == 1:
        policy = policies[0][1]
        validate_policy(policy)
    else:
        issue("PRICE_POLICY_NOT_PINNED", "Exactly one price policy must be pinned in manifest.sources before execution")
    _write(target / "metrics-policy.json", policy)
    btc = btc_module()
    scenarios = {inputs.resolve(ref)["scenario_id"]: inputs.resolve(ref) for ref in manifest["scenarios"]}
    runner = read_json(evidence.path("raw/runner-report.json"))
    execution = read_json(evidence.path("raw/execution-plan.json"))
    official = read_json(score.path("official-report.json")) if (score.root / "official-report.json").is_file() else None
    if official:
        validate("OfficialReport", official)
    else:
        issue("OFFICIAL_REPORT_MISSING", "No fabricated official metrics")
    official_ref = local.ref("score/official-report.json") if official else local.ref("score/score-report.json")
    all_metrics, timing_details, completion, coverage_refs = {}, {}, {}, []
    for config in CONFIGS:
        expected = [key for key in execution["expected_ids"] if key.split("/")[1] == config]
        planned = [p for p in manifest["planned_calls"] if p["config"] == config]
        registered = [context_key({"run_id":manifest["run_id"], **{k:p[k] for k in ("config","scenario_id","call")},"turn":t})
                      for p in planned for t in range(1,p["expected_turns"]+1)]
        if Counter(expected) != Counter(registered):
            raise ValueError("Execution expected IDs differ from pinned manifest coverage")
        trace_name = "scorer-input/" + ("full.jsonl" if config == "full" else "baseline.jsonl")
        trace = []
        if (score.root / trace_name).is_file():
            trace = [parse_json(line) for line in score.path(trace_name).read_text().splitlines()]
        observed = [context_key(row) for row in trace]
        count = Counter(observed)
        gaps = {"missing_ids": sorted(set(expected) - set(observed)), "duplicate_ids": sorted(k for k,n in count.items() if n>1),
                "unknown_ids": sorted(set(observed) - set(expected))}
        complete = bool(expected) and Counter(observed) == Counter(expected)
        if not complete:
            issue("P6_TRACE_COVERAGE", config)
        cv = {"schema_version": "1.0.0", "artifact_id": "p6/" + config + "/coverage", "run_id": manifest["run_id"],
              "scope": config + "/trace", "expected_ids": expected, "observed_ids": observed, **gaps,
              "status": status([] if complete else [issues[-1]])}
        validate("Coverage", cv)
        _write(target / (config + "-coverage.json"), cv)
        coverage_refs.append(local.ref(config + "-coverage.json"))
        grouped = defaultdict(list)
        for row in trace:
            grouped[(row["scenario_id"], row["call"])].append(row)
        section = official.get("system" if config == "full" else "baseline") if official else None
        if section and btc.evaluate(scenarios, grouped) != section:
            raise ValueError("Official report does not match pinned BTC trace/scenarios")
        refs = [official_ref, local.ref(config + "-coverage.json")]
        ms = []
        def ratio(mid, n, d, formula="percent.v1", unit="percent", cohort=None, missing=None):
            ms.append(make_metric(mid, formula, unit, expected if cohort is None else cohort, refs, n=n,d=d,
                                  incomplete=missing or (None if complete and section else "TRACE_OR_OFFICIAL_COVERAGE")))
        data = section or {}
        rqr, ccr, tsr, hr = [data.get(k, {}) for k in ("repeat_question_rate", "context_carryover_rate", "task_success_rate", "hallucination_rate")]
        ratio("agent.rqr", rqr.get("redundant",0), rqr.get("total_questions",0))
        ratio("agent.ccr", ccr.get("used",0), ccr.get("required",0))
        ratio("agent.tsr", tsr.get("passed",0), tsr.get("total",0))
        ratio("agent.hr", hr.get("wrong",0), hr.get("total_claims",0))
        hp=hr.get("price_promo_only",{})
        ratio("agent.hr_price_promo",hp.get("wrong",0),hp.get("total",0))
        hard = [sid for sid,s in scenarios.items() if s.get("hard_case")]
        hard_pass = sum(all(btc.check_call(spec,grouped[(sid,call)])[0] is not False for call,spec in scenarios[sid]["calls"].items()) for sid in hard)
        ratio("agent.tsr_hard",hard_pass,len(hard),cohort=hard)
        calls = [c for c in runner["calls"] if c["context"]["config"] == config]
        call_ids=[context_key({"run_id":manifest["run_id"],**{k:p[k] for k in ("config","scenario_id","call")},"turn":1}).rsplit("/",1)[0] for p in planned]
        for c in calls:
            validate("Context", c["context"])
            if context_key(c["context"]).rsplit("/",1)[0] not in call_ids or c["context"]["turn"] != 1:
                raise ValueError("Unknown lifecycle call receipt")
            if any(type(c[k]) is not bool for k in ("attempted", "completed", "barrier_complete", "failed")):
                raise ValueError("Lifecycle receipt flags must be booleans")
            if c["completed"] and (not c["attempted"] or c["failed"]):
                raise ValueError("Contradictory lifecycle receipt")
        if len({context_key(c["context"]) for c in calls}) != len(calls):
            raise ValueError("Duplicate lifecycle call receipts")
        completed = [c for c in calls if c["completed"] and c["barrier_complete"]]
        valid_completed=[]
        for c in completed:
            anchor={**c["context"],"turn":1}
            raw=read_json(evidence.path(config+"/raw-records.json"))
            barriers=[r for r in raw if r.get("kind")=="adapter_message" and r.get("phase")=="end_call"
                      and r.get("context") and all(r["context"][k]==anchor[k] for k in ("run_id","config","scenario_id","call"))
                      and r.get("data",{}).get("type")=="result" and r["data"].get("hook")=="end_call"]
            if len(barriers)==1 and barriers[0]["data"]["result"].get("completed") is True and barriers[0]["data"]["result"].get("barrier_complete") is True:
                valid_completed.append(c)
            else:
                issue("LIFECYCLE_COMPLETION_UNPROVEN",context_key(anchor))
        completed=valid_completed
        completed_scenarios=[sid for sid in scenarios if all(any(c["context"]["scenario_id"]==sid and c["context"]["call"]==p["call"] for c in completed) for p in planned if p["scenario_id"]==sid) and any(p["scenario_id"]==sid for p in planned)]
        lifecycle_missing=None if len(completed)==len(planned) else "PLANNED_CALLS_NOT_COMPLETED"
        ratio("agent.turns_per_call",len(trace),len(completed),"turns-call.v1","turns_per_call",call_ids,lifecycle_missing)
        ratio("agent.turns_per_scenario",len(trace),len(completed_scenarios),"turns-scenario.v1","turns_per_scenario",list(scenarios),lifecycle_missing)
        completion[config]={"planned":len(planned),"attempted":len(calls),"completed":len(completed),"failed":sum(c["failed"] for c in calls)}
        guard=data.get("guardrail_violations",{})
        ms.append(make_metric("agent.guardrail_violations","count.v1","count",expected,refs,value=guard.get("total"),incomplete=None if complete and section else "TRACE_OR_OFFICIAL_COVERAGE"))
        for key in ("ttft","total"):
            raw_stat=data.get("latency",{}).get(key) or {}
            ms.append(make_metric("agent."+key+".raw_p95","btc.latency-p95.v1","ms",expected,refs,value=raw_stat.get("p95_ms"),incomplete=None if complete and section else "TRACE_OR_OFFICIAL_COVERAGE"))
        timing=rows(config+"/timing.jsonl","TimingEvidence")
        timing_refs=refs+[local.ref("score/evidence/"+config+"/timing.jsonl")]
        derived,detail=timing_metrics(expected,timing,manifest["warmup_count"],100,timing_refs)
        ms+=derived; timing_details[config]=detail
        if manifest["warmup_count"] != 3:
            issue("M1_WARMUP_PROTOCOL",config+": requires 3 warmup samples")
        for problem in detail["problems"]:
            issue(problem,config)
        brief=rows(config+"/brief-evidence.jsonl","BriefEvidence")
        brief_expected=[p for p in planned if p["call"]!="call_1" and p["memory_required"]]
        brief_ids=[context_key({"run_id":manifest["run_id"],**{k:p[k] for k in ("config","scenario_id","call")},"turn":1}) for p in brief_expected]
        observed_briefs=[]
        duration=[]
        for b in brief:
            if b["kind"]=="call_brief":
                observed_briefs.append(context_key(b["context"]))
                evidence.resolve(b["object_ref"])
                try:
                    value=milliseconds(b["identified_at"],b["ready_at"])
                    if value is not None:duration.append(value)
                except ValueError:pass
        brief_missing=len(duration)!=len(brief_expected) or Counter(observed_briefs)!=Counter(brief_ids)
        if brief_missing:issue("BRIEF_TIMING_COVERAGE",config)
        ms.append(make_metric("agent.brief.max","max.v1","ms",[p["scenario_id"]+"/"+p["call"] for p in brief_expected],refs+[local.ref("score/evidence/"+config+"/brief-evidence.jsonl")],
                              value=max(duration) if duration else None,incomplete="BRIEF_TIMING_COVERAGE" if brief_missing else None))
        reconciled = None
        if ledger is not None:
            reconciled, reason = reconcile_usage(usage_assets,ledger,evidence,config,manifest["run_id"],policy)
            charge = reconciled["cost"] if reconciled else None
            timing_refs += [local.ref("usage/usage-ledger.json")]
        else:
            charge,reason=runtime_cost(timing,expected,calls,policy,evidence)
        for key in ("input_tokens","output_tokens"):
            token_complete=bool(reconciled) if ledger is not None else Counter(context_key(r["context"]) for r in timing)==Counter(expected) and all(r[key] is not None for r in timing) and not any(c["failed"] for c in calls)
            ms.append(make_metric("agent."+key+"_per_call","tokens-call.v1","count",call_ids,timing_refs,
                                  n=(reconciled[key] if reconciled else sum(r[key] for r in timing)) if token_complete else None,d=len(completed),
                                  incomplete=None if token_complete else "TOKEN_USAGE_INCOMPLETE"))
        arithmetic=cost_per_completed_call(charge,len(completed))
        ms.append(make_metric("agent.cost_per_call","cost-call.v1","currency_per_call",call_ids,
                              timing_refs+[local.ref("metrics-policy.json")],n=charge,d=len(completed),incomplete=reason,currency=policy["currency"]))
        if arithmetic["status"]=="INCOMPLETE":issue("RUNTIME_COST_INCOMPLETE",config+": "+str(reason))
        all_metrics[config]=ms
    asr=None  # Historical report shape; text evaluation has no ASR measurement.
    if manifest["fixture"]:issue("FIXTURE_NOT_BENCHMARK","Fixture metrics cannot certify real M1")
    supplemental=read_json(score.path("supplemental-report.json")) if (score.root/"supplemental-report.json").is_file() else {"checks":[]}
    supplemental={**supplemental,"checks":[{**c,"evidence_refs":[{**r,"path":"score/"+r["path"]} for r in c["evidence_refs"]]} for c in supplemental["checks"]]}
    errors=[]
    for config in CONFIGS:
        for p in (p for p in manifest["planned_calls"] if p["config"]==config):
            ctx={"run_id":manifest["run_id"],"config":config,"scenario_id":p["scenario_id"],"call":p["call"],"turn":1}
            anchor=context_key(ctx).rsplit("/",1)[0]
            failed=[c["check_id"] for c in supplemental["checks"] if c["check_id"].startswith(anchor+"/") and c["status"]["verdict"]=="FAIL"]
            if not failed:continue
            error={"schema_version":"1.0.0","artifact_id":anchor+"/error","run_id":manifest["run_id"],"context":ctx,
                   "evidence_refs":[local.ref("score/supplemental-report.json")],"error_id":anchor,"category":"agent",
                   "expected":{"checks":"PASS"},"observed":{"failed_checks":failed},"reason":"Confirmed P4 call checks failed; root cause requires review",
                   "source_split":manifest["split"],"learning_permission":"deny" if manifest["split"] in ("frozen","hidden") else "pending",
                   "root_cause":None,"remediation":None,"retest_ref":None}
            validate("ErrorRecord",error);errors.append(error)
    reviewed = import_casebook(case_assets,errors,score,manifest) if case_assets else []
    by_id = {e["error_id"]: e for e in errors}
    for record in reviewed:
        rebased = {**record,"evidence_refs":[{**r,"path":"casebook-review/"+r["path"]} for r in record["evidence_refs"]],
                   "retest_ref":{**record["retest_ref"],"path":"casebook-review/"+record["retest_ref"]["path"]}}
        by_id[record["error_id"]] = rebased
    with (target/"errors.jsonl").open("x") as stream:
        for error in by_id.values():stream.write(json.dumps(error,ensure_ascii=False)+"\n")
    independent={(e["context"]["scenario_id"],e["context"]["call"]) for e in errors}
    reviewed_calls={(e["context"]["scenario_id"],e["context"]["call"]) for e in reviewed}
    qualifying = 0 if manifest["fixture"] else len(reviewed_calls)
    casebook={"confirmed_records":len(errors),"independent_calls":len(independent),"qualifying_real_cases":qualifying,
              "reviewed_records":len(reviewed),"reviewer":read_json(case_assets.path("casebook-review.json"))["reviewed_by"] if case_assets else None,
              "minimum":10,"analysis_complete":qualifying>=10,"notice":"Review declarations and distinct retest hashes checked; no auto-learning or reviewer-authority certification"}
    if not casebook["analysis_complete"]:issue("CASEBOOK_ANALYSIS_PENDING","At least 10 real independent errors with analysis/retest evidence required")
    _write(target/"casebook.json",casebook)
    comparison={"schema_version":"1.0.0","artifact_id":manifest["run_id"]+"/comparison","run_id":manifest["run_id"],
                "dataset_hash":digest(manifest["scenarios"]),"baseline_report":None,"system_report":None,
                "rows":comparison_rows(all_metrics[CONFIGS[0]],all_metrics[CONFIGS[1]])}
    system={m["metric_id"]:m for m in all_metrics["full"]}
    thresholds={"agent.tsr":("min",70),"agent.hr_price_promo":("max",5),"agent.ttft.effective_p95":("max",3000),
                "agent.total.effective_p95":("max",8000),"agent.brief.max":("max",5000)}
    gates=[]
    for mid,(direction,limit) in thresholds.items():
        m=system[mid];known=m["status"]=="MEASURED"
        passed=known and (m["value"]>=limit if direction=="min" else m["value"]<=limit)
        gates.append({"metric_id":mid,"threshold":limit,"direction":direction,"passed":passed,"value":m["value"],"status":m["status"]})
        if not passed:issue("M1_THRESHOLD_"+mid,str(gates[-1]),"agent_violation" if known and not manifest["fixture"] else "missing_evidence")
    reduction=next(r for r in comparison["rows"] if r["metric_id"]=="agent.rqr")
    gates.append({"metric_id":"agent.rqr.reduction","threshold":40,"value":reduction["delta"],"passed":reduction["status"]=="MEASURED" and reduction["delta"]>=40})
    if not gates[-1]["passed"]:issue("RQR_REDUCTION_GATE","Undefined or less than 40% relative reduction","agent_violation" if reduction["status"]=="MEASURED" and not manifest["fixture"] else "missing_evidence")
    for config in CONFIGS:
        report={"schema_version":"1.0.0","artifact_id":manifest["run_id"]+"/p6/"+config,"run_id":manifest["run_id"],
                "status":status(issues),"metrics":all_metrics[config],"checks":supplemental["checks"],"coverage_refs":coverage_refs,"official_report":official_ref}
        # Missing official output is not a fabricated OfficialReport or supplemental link.
        if official:
            validate("SupplementalReport",report);_write(target/(config+"-report.json"),report)
        else:_write(target/(config+"-report.json"),{"report_kind":"p6-partial-metrics","metrics":all_metrics[config]})
    comparison["baseline_report"]=local.ref(CONFIGS[0]+"-report.json")
    comparison["system_report"]=local.ref(CONFIGS[1]+"-report.json")
    validate("Comparison",comparison);_write(target/"comparison.json",comparison)
    validation={"schema_version":"1.0.0","artifact_id":manifest["run_id"]+"/p6/validation","run_id":manifest["run_id"],
                "status":status(issues),"issues":issues,"coverage_refs":coverage_refs}
    validate("ValidationReport",validation);_write(target/"validation.json",validation)
    summary={"report_kind":"p6-m1-metrics-v1","run_id":manifest["run_id"],"fixture":manifest["fixture"],"status":status(issues),
             "quality_accepted":False,"btc_full_readiness":"INCOMPLETE","deferred":read_json(score.path("score-report.json"))["deferred"],
             "checks":supplemental["checks"],"gates":gates,"completion":completion,"timing":timing_details,"casebook":casebook,
             "metric_coverage":{m["metric_id"]:{"baseline":len(next(b for b in all_metrics[CONFIGS[0]] if b["metric_id"]==m["metric_id"])["cohort_ids"]),"system":len(m["cohort_ids"])} for m in all_metrics["full"]},
             "comparison_ref":local.ref("comparison.json"),"notice":"P6 metrics, not P7 release; fixture/provisional/runtime audit limitations retained"}
    _write(target/"metrics-report.json",summary)
    with (target/"table.md").open("x") as stream:stream.write(render_table(comparison,summary,asr))
    locked_run(run_dir)
    for extra in (usage_run,casebook_run):
        if extra is not None:locked_run(extra)
    checker.verify_sources();close_output(target)
    return summary

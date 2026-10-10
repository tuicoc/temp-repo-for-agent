"""P7 verified release recommendation; never mutates a production pointer."""
from datetime import datetime
import hashlib
import hmac
import os
from fractions import Fraction

from .assets import read_json
from .collector import locked_run, status
from .contracts import validate
from .datasets import close_output
from .extractor import digest
from .reporting import copy_run
from .runner import _output_path, _write


def mandatory_metrics_pass(base,new):
    for report in (base,new):validate("SupplementalReport",report)
    b,s=({m["metric_id"]:m for m in r["metrics"]} for r in (base,new))
    if any(len(r["metrics"])!=len({m["metric_id"] for m in r["metrics"]}) for r in (base,new)):return False
    def ratio(metric):
        if not metric or metric["status"]!="MEASURED" or not metric["denominator"] or metric["unit"]!="percent":return None
        if metric["numerator"] is None or not 0<=metric["numerator"]<=metric["denominator"]:return None
        raw=100*Fraction(str(metric["numerator"]))/Fraction(str(metric["denominator"]))
        if abs(float(raw)-metric["value"])>1e-9:return None
        return raw
    tsr,hr=ratio(s.get("agent.tsr")),ratio(s.get("agent.hr_price_promo"))
    old,full=ratio(b.get("agent.rqr")),ratio(s.get("agent.rqr"))
    if any(x is None for x in (tsr,hr,old,full)) or old==0 or tsr<70 or hr>5 or (old-full)/old*100<40:return False
    for mid,limit in (("agent.ttft.effective_p95",3000),("agent.total.effective_p95",8000),("agent.brief.max",5000)):
        m=s.get(mid)
        if not m or m["status"]!="MEASURED" or m["unit"]!="ms" or m["value"] is None or not 0<=m["value"]<=limit:return False
    return True


def inspect_candidate(assets, candidate, approval, manifest, attestation, policy):
    validate("Candidate",candidate);validate("ApprovalRecord",approval);validate("Manifest",manifest)
    content=assets.resolve(candidate["content"],json_content=False)
    if candidate["content"]["pointer"]:raise ValueError("Candidate content must bind whole bytes")
    actual=hashlib.sha256(content.read_bytes()).hexdigest()
    reasons=[]
    if actual!=approval["candidate_hash"] or actual!=manifest["candidate_hash"]:reasons.append("CANDIDATE_HASH_MISMATCH")
    if candidate["run_id"]!=manifest["run_id"] or approval["run_id"]!=manifest["run_id"]:reasons.append("APPROVAL_RUN_MISMATCH")
    if approval["decision"]!="approve":reasons.append("APPROVAL_NOT_APPROVE")
    if datetime.fromisoformat(approval["reviewed_at"])>datetime.fromisoformat(manifest["created_at"]):reasons.append("APPROVAL_AFTER_EXECUTION")
    secret=os.environ.get("EVALUATION_APPROVAL_HMAC_KEY")
    if not secret or approval["reviewer"] not in policy["reviewers"]:
        reasons.append("REVIEWER_AUTHORITY_UNVERIFIED")
    else:
        expected=hmac.new(secret.encode(),digest({"approval":approval,"policy":policy}).encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,attestation["signature"]):reasons.append("APPROVAL_SIGNATURE_INVALID")
    if not candidate["source_decisions"]:reasons.append("CANDIDATE_SOURCE_MISSING")
    for ref in candidate["source_decisions"]:
        source=assets.resolve(ref);validate("SourceDecision",source)
        assets.resolve(source["origin"],json_content=False)
        if source["purpose"]!="learning" or source["permission"]!="allow" or source["source_split"] in ("frozen","hidden"):
            reasons.append("SOURCE_NOT_ALLOWED_FOR_LEARNING")
    for ref in candidate["growth_cases"]:assets.resolve(ref)
    for ref in approval["policy_sources"]:assets.resolve(ref,json_content=False)
    return actual,sorted(set(reasons))


def release_gate(bundle_run, out):
    source,_=locked_run(bundle_run)
    target=_output_path(out,source)
    target.mkdir(parents=True,mode=0o700)
    assets=copy_run(source.root,target/"inputs")
    candidate=read_json(assets.path("candidate.json"))
    approval=read_json(assets.path("approval.json"))
    attestation=read_json(assets.path("approval-attestation.json"))
    policy=read_json(assets.path("authority-policy.json"))
    if set(attestation)!={"signature"} or not isinstance(attestation["signature"],str):raise ValueError("Invalid approval attestation")
    if set(policy)!={"schema_version","reviewers","release_scope"} or policy["schema_version"]!="p7-authority-v1" or policy["release_scope"] not in ("current_declared","full_btc") or not isinstance(policy["reviewers"],list) or not policy["reviewers"]:
        raise ValueError("Explicit reviewer/scope policy required")
    measured,_=locked_run(assets.root/"r1")
    manifest=read_json(measured.path("manifest.json"))
    actual,reasons=inspect_candidate(assets,candidate,approval,manifest,attestation,policy)
    r0,_=locked_run(assets.root/"r0")
    old_manifest=read_json(r0.path("manifest.json"));validate("Manifest",old_manifest)
    # Authority policy and candidate must be pinned by the producer before R1.
    for name in ("candidate.json","authority-policy.json","approval.json"):
        if assets.ref(name) not in manifest["sources"]:reasons.append("RELEASE_INPUT_NOT_PINNED_"+name)
    provenance=read_json(measured.path("metrics-report.json"))
    if manifest["fixture"] or manifest["split"]!="frozen" or manifest["round"]!=1:reasons.append("NOT_REAL_FROZEN_R1")
    package_casebook_complete=False
    if (assets.root/"casebook-review.json").exists() and (assets.root/"casebook-attestation.json").exists():
        from .assets import parse_json
        from .p6_evidence import import_casebook
        from .assets import Assets
        review=read_json(assets.path("casebook-review.json"))
        signature=read_json(assets.path("casebook-attestation.json"))["signature"]
        secret=os.environ.get("EVALUATION_APPROVAL_HMAC_KEY")
        authorized=bool(secret) and review["reviewed_by"] in policy["reviewers"]
        if authorized:
            expected=hmac.new(secret.encode(),digest({"casebook":review,"policy":policy}).encode(),hashlib.sha256).hexdigest()
            authorized=hmac.compare_digest(signature,expected)
        if not authorized:reasons.append("CASEBOOK_REVIEW_AUTHORITY_UNVERIFIED")
        else:
            errors=[parse_json(line) for line in r0.path("errors.jsonl").read_text().splitlines()]
            reviewed=import_casebook(assets,errors,Assets(r0.root/"score"),old_manifest)
            cases={(e["context"]["scenario_id"],e["context"]["call"]) for e in reviewed}
            package_casebook_complete=not old_manifest["fixture"] and len(cases)>=10
            for record in reviewed:
                if assets.resolve(record["retest_ref"])["run_id"]!=manifest["run_id"] or assets.path(record["retest_ref"]["path"])!=measured.path("score/supplemental-report.json") or record["retest_ref"]["sha256"]!=measured.ref("score/supplemental-report.json")["sha256"]:
                    package_casebook_complete=False
    validation=read_json(measured.path("validation.json"));validate("ValidationReport",validation)
    validate("Status",provenance["status"])
    if validation["run_id"]!=manifest["run_id"] or validation["status"]!=status(validation["issues"]) or provenance["status"]!=validation["status"]:
        reasons.append("MEASUREMENT_STATUS_INCONSISTENT")
    for issue in validation["issues"]:measured.resolve(issue["artifact"],json_content=False)
    effective_issues=validation["issues"]
    if package_casebook_complete:
        effective_issues=[i for i in effective_issues if i["code"]!="CASEBOOK_ANALYSIS_PENDING"]
    effective_status=status(effective_issues)
    if effective_status!={"verdict":"PASS","completeness":"COMPLETE","reason_codes":[]}:
        reasons.append("MEASUREMENT_NOT_PASS_COMPLETE")
    gate_ids={"agent.tsr","agent.hr_price_promo","agent.ttft.effective_p95","agent.total.effective_p95","agent.brief.max","agent.rqr.reduction"}
    gates=provenance["gates"]
    if len(gates)!=len(gate_ids) or {g.get("metric_id") for g in gates}!=gate_ids or not all(g.get("passed") is True for g in gates):reasons.append("MANDATORY_THRESHOLD_GATE_COVERAGE")
    base_config=read_json(measured.path("baseline_no_memory-report.json"))
    system_config=read_json(measured.path("full-report.json"))
    if not mandatory_metrics_pass(base_config,system_config):reasons.append("MANDATORY_THRESHOLDS_NOT_MET")
    if policy["release_scope"]=="full_btc" and provenance["btc_full_readiness"]!="COMPLETE":reasons.append("FULL_BTC_DEFERRED_OR_MISSING")
    if manifest["dispute_ids"]:reasons.append("DISPUTES_OPEN")
    if not package_casebook_complete:reasons.append("PACKAGE_CASEBOOK_INCOMPLETE")
    comparison=read_json(assets.path("round-comparison.json"))
    validate("Comparison",comparison)
    if comparison["run_id"]!=manifest["run_id"]:reasons.append("ROUND_COMPARISON_RUN_MISMATCH")
    from .rounds import cohort
    if old_manifest["round"]!=0 or old_manifest["run_id"]==manifest["run_id"] or cohort(r0,old_manifest)!=cohort(measured,manifest):reasons.append("ROUND_COHORT_OR_ID_MISMATCH")
    for key in ("model","parameters","tools","hardware","extractor_version","judge_version"):
        if old_manifest["configuration"][key]!=manifest["configuration"][key]:reasons.append("ROUND_CONTROL_MISMATCH_"+key)
    if read_json(r0.path("metrics-policy.json"))!=read_json(measured.path("metrics-policy.json")):reasons.append("ROUND_COST_POLICY_MISMATCH")
    policies=[]
    from .assets import Assets
    old_inputs=Assets(r0.root/"score/evidence/raw/inputs")
    new_inputs=Assets(measured.root/"score/evidence/raw/inputs")
    for ref in old_manifest["sources"]:
        if not ref["pointer"] and ref["path"].endswith(".json"):
            obj=old_inputs.resolve(ref)
            if isinstance(obj,dict) and obj.get("schema_version")=="p7-round-policy-v1":policies.append((ref,obj))
    allowed=[]
    if len(policies)!=1 or policies[0][0] not in manifest["sources"]:reasons.append("ROUND_POLICY_NOT_PINNED")
    else:
        ref,round_policy=policies[0]
        new_inputs.resolve(ref)
        if set(round_policy)!={"schema_version","allowed_changed_configuration"} or not isinstance(round_policy["allowed_changed_configuration"],list) or not set(round_policy["allowed_changed_configuration"])<={"prompt","kb"}:raise ValueError("Invalid controlled-change policy")
        allowed=round_policy["allowed_changed_configuration"]
    for key in ("prompt","kb"):
        if old_manifest["configuration"][key]!=manifest["configuration"][key] and key not in allowed:reasons.append("UNDECLARED_IMPROVEMENT_CHANGE_"+key)
    # Read actual reports through hash references; do not trust delta strings.
    from .rounds import no_regression
    old=assets.resolve(comparison["baseline_report"]);new=assets.resolve(comparison["system_report"])
    validate("SupplementalReport",old);validate("SupplementalReport",new)
    if old!=read_json(r0.path("full-report.json")):reasons.append("COMPARISON_NOT_MEASURED_R0")
    if new!=read_json(measured.path("full-report.json")):reasons.append("COMPARISON_NOT_MEASURED_R1")
    if not all(c["passed"] for c in no_regression(old["metrics"],new["metrics"])):reasons.append("HARMFUL_OR_UNDEFINED_REGRESSION")
    consumption=read_json(measured.path("consumption.json")) if (measured.root/"consumption.json").exists() else None
    if consumption is None:reasons.append("RUNTIME_CANDIDATE_CONSUMPTION_MISSING")
    else:
        # Each proof must resolve an actual recorded product resource event.
        if set(consumption)!={"candidate_hash","evidence_refs"} or consumption["candidate_hash"]!=actual or not consumption["evidence_refs"]:
            reasons.append("CANDIDATE_CONSUMPTION_UNPROVEN")
        else:
            expected_scopes={(p["config"],p["scenario_id"],p["call"],turn) for p in manifest["planned_calls"] for turn in range(1,p["expected_turns"]+1)}
            observed_scopes=set()
            resource="prompt" if candidate["kind"]=="prompt" else "kb"
            if manifest["configuration"][resource]["sha256"]!=actual:reasons.append("CANDIDATE_NOT_BOUND_TO_RESOURCE")
            for ref in consumption["evidence_refs"]:
                event=measured.resolve(ref)
                data=event.get("data",{});body=data.get("event",{});ctx=event.get("context",{})
                scope=tuple(ctx.get(k) for k in ("config","scenario_id","call","turn"))
                if event.get("kind")!="adapter_message" or event.get("phase")!="run_turn" or data.get("type")!="event" or body.get("kind")!="candidate_consumed" or body.get("resource")!=resource or body.get("candidate_hash")!=actual or ctx.get("run_id")!=manifest["run_id"] or scope not in expected_scopes:
                    reasons.append("CANDIDATE_CONSUMPTION_UNPROVEN")
                else:observed_scopes.add(scope)
            if observed_scopes!=expected_scopes:reasons.append("CANDIDATE_CONSUMPTION_COVERAGE")
    local_ref=lambda name: {**assets.ref(name),"path":"inputs/"+name}
    results=[]
    for suite in manifest["suites"]:
        supported=manifest["level"]=="M1" and suite["id"] in ("fixed_turn","asr","latency_cost")
        if suite["applicable"] and not supported:reasons.append("APPLICABLE_RELEASE_SUITE_UNVERIFIED_"+suite["id"])
        results.append({"suite":suite["id"],"applicable":suite["applicable"],
                        "status":effective_status if suite["applicable"] and supported else {"verdict":"UNDETERMINED","completeness":"INCOMPLETE","reason_codes":["APPLICABLE_SUITE_NOT_VERIFIED"]} if suite["applicable"] else {"verdict":"NOT_APPLICABLE","completeness":"NOT_APPLICABLE","reason_codes":[suite["reason"]]},
                        "report":local_ref("r1/metrics-report.json") if suite["applicable"] and supported else None})
    if not results or not any(r["applicable"] for r in results):reasons.append("SUITE_RESULTS_EMPTY")
    reasons=sorted(set(reasons))
    decision={"schema_version":"1.0.0","artifact_id":manifest["run_id"]+"/release","run_id":manifest["run_id"],"level":manifest["level"],
              "decision":"hold" if reasons else "active","candidate_hash":actual,"approved_hash":approval["candidate_hash"],"evaluated_hash":manifest["candidate_hash"],
              "approval_ref":local_ref("approval.json"),"suite_results":results,"dispute_ids":manifest["dispute_ids"],"reason_codes":reasons,
              "previous_version":candidate["parent_version"]}
    validate("ReleaseDecision",decision)
    _write(target/"release.json",decision)
    locked_run(bundle_run);close_output(target)
    return decision

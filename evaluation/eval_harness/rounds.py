"""P7 offline round comparison/readiness; no production activation authority."""
from fractions import Fraction

from .assets import Assets, read_json
from .collector import locked_run, status
from .contracts import validate
from .datasets import close_output
from .extractor import digest
from .reporting import comparison_rows, copy_run
from .runner import _output_path, _write


def cohort(assets, manifest, *, inputs=None):
    inputs = inputs or Assets(assets.root / "score/evidence/raw/inputs")
    return {"scenarios": sorted((inputs.resolve(r) for r in manifest["scenarios"]),key=lambda s:s["scenario_id"]),
            "grading": sorted((inputs.resolve(r) for r in manifest["grading_contracts"]),key=lambda g:g["scenario_id"]),
            "planned_calls": sorted(manifest["planned_calls"],key=lambda p:(p["config"],p["scenario_id"],p["call"])),
            "asr_ids": manifest["asr_ids"], "rag_ids":manifest["rag_ids"], "suites":manifest["suites"],
            "reference_date":manifest["reference_date"],"timezone":manifest["timezone"],"warmup_count":manifest["warmup_count"]}


def no_regression(base, new):
    """Raw fractions, not rounded table values. Undefined is never a PASS."""
    rows = []
    b, s = ({m["metric_id"]:m for m in metrics} for metrics in (base,new))
    for mid,direction in (("agent.rqr","max"),("agent.tsr","min"),("agent.hr_price_promo","max")):
        bm,sm = b.get(mid),s.get(mid)
        known = all(m and m["status"]=="MEASURED" and m["denominator"] for m in (bm,sm))
        passed = False
        if known:
            old = Fraction(str(bm["numerator"]))/Fraction(str(bm["denominator"]))
            current = Fraction(str(sm["numerator"]))/Fraction(str(sm["denominator"]))
            passed = current<=old if direction=="max" else current>=old
        rows.append({"metric_id":mid,"direction":direction,"known":bool(known),"passed":passed})
    return rows


def compare_rounds(r0_run, out, *, r1_run=None):
    source,_ = locked_run(r0_run)
    r0_manifest = read_json(source.path("manifest.json"))
    validate("Manifest",r0_manifest)
    if r0_manifest["round"]!=0 or r0_manifest["level"]!="M1":
        raise ValueError("Expected M1 R0 metrics run")
    if read_json(source.path("metrics-report.json"))["report_kind"]!="p6-m1-metrics-v1":
        raise ValueError("Expected closed P6 metrics evidence")
    if r1_run is not None:
        other,_ = locked_run(r1_run)
        r1_manifest = read_json(other.path("manifest.json"))
        validate("Manifest",r1_manifest)
        if r1_manifest["round"]!=1 or r1_manifest["level"]!="M1" or r1_manifest["run_id"]==r0_manifest["run_id"]:
            raise ValueError("R1 must be a distinct M1 run with round=1")
        if read_json(other.path("metrics-report.json"))["report_kind"]!="p6-m1-metrics-v1":
            raise ValueError("Expected closed P6 R1 metrics evidence")
    target = _output_path(out,source)
    if r1_run is not None and target.is_relative_to(other.root):
        raise ValueError("Do not write into R1 evidence")
    target.mkdir(mode=0o700,parents=True,exist_ok=False)
    local = Assets(target)
    r0 = copy_run(source.root,target/"r0")
    _write(target/"manifest.json",r0_manifest)
    issues = []
    def issue(code,message,classification="missing_evidence"):
        issues.append({"code":code,"message":message,"classification":classification,"artifact":local.ref("manifest.json"),"json_pointer":""})
    for prefix,assets in (("r0",r0),):
        for item in read_json(assets.path("validation.json"))["issues"]:
            assets.resolve(item["artifact"],json_content=False)
            issues.append({**item,"artifact":{**item["artifact"],"path":prefix+"/"+item["artifact"]["path"]}})
    comparison = None
    checks = []
    if r1_run is None:
        issue("R1_EXECUTION_MISSING","Provide a new actual R1 run; R0 regrade is not an improvement experiment")
    else:
        r1 = copy_run(other.root,target/"r1")
        for item in read_json(r1.path("validation.json"))["issues"]:
            r1.resolve(item["artifact"],json_content=False)
            issues.append({**item,"artifact":{**item["artifact"],"path":"r1/"+item["artifact"]["path"]}})
        same = cohort(r0,r0_manifest)==cohort(r1,r1_manifest)
        if not same:issue("ROUND_COHORT_MISMATCH","Inputs/GT/grading/plans/date/suite scope differ")
        if read_json(r0.path("metrics-policy.json"))!=read_json(r1.path("metrics-policy.json")):
            same=False;issue("ROUND_COST_POLICY_MISMATCH","Do not compare charges under different unit prices/scope/currency")
        if any(m["fixture"] or m["split"]!="frozen" for m in (r0_manifest,r1_manifest)):
            issue("ROUND_NOT_REAL_FROZEN","Fixture/development comparison is diagnostic, not release evidence")
        for key in ("model","parameters","hardware","tools","extractor_version","judge_version"):
            if r0_manifest["configuration"][key]!=r1_manifest["configuration"][key]:
                same=False;issue("ROUND_CONTROL_MISMATCH",key)
        # Improvement changes must have permission pinned BEFORE both runs.
        policies=[]
        inputs=Assets(r0.root/"score/evidence/raw/inputs")
        for ref in r0_manifest["sources"]:
            if ref["pointer"]=="" and ref["path"].endswith(".json"):
                obj=inputs.resolve(ref)
                if isinstance(obj,dict) and obj.get("schema_version")=="p7-round-policy-v1":
                    policies.append((ref,obj))
        allowed=[]
        if len(policies)!=1 or policies[0][0] not in r1_manifest["sources"]:
            issue("ROUND_POLICY_NOT_PINNED","Exactly one identical improvement policy must be pinned in R0/R1 sources")
        else:
            ref,policy=policies[0]
            Assets(r1.root/"score/evidence/raw/inputs").resolve(ref)
            if set(policy)!={"schema_version","allowed_changed_configuration"} or not isinstance(policy["allowed_changed_configuration"],list) or not set(policy["allowed_changed_configuration"])<={"prompt","kb"}:
                raise ValueError("Invalid P7 controlled-change policy")
            allowed=policy["allowed_changed_configuration"]
        for key in ("prompt","kb"):
            if r0_manifest["configuration"][key]!=r1_manifest["configuration"][key] and key not in allowed:
                same=False;issue("UNDECLARED_IMPROVEMENT_CHANGE",key)
        for assets,manifest in ((r0,r0_manifest),(r1,r1_manifest)):
            raw=read_json(assets.path("score/evidence/raw/runner-report.json"))
            if raw["run_id"]!=manifest["run_id"]:
                raise ValueError("Round report reuses raw run identity")
        base=read_json(r0.path("full-report.json"));new=read_json(r1.path("full-report.json"))
        validate("SupplementalReport",base);validate("SupplementalReport",new)
        rows=comparison_rows(base["metrics"],new["metrics"])
        if not same:
            rows=[{**row,"delta":None,"status":"INCOMPLETE","reason":"CONFOUNDED_ROUND_COMPARISON"} for row in rows]
        comparison={"schema_version":"1.0.0","artifact_id":r1_manifest["run_id"]+"/R0-R1","run_id":r1_manifest["run_id"],
                    "dataset_hash":digest(cohort(r0,r0_manifest)),"baseline_report":local.ref("r0/full-report.json"),
                    "system_report":local.ref("r1/full-report.json"),"rows":rows}
        validate("Comparison",comparison);_write(target/"comparison.json",comparison)
        checks=no_regression(base["metrics"],new["metrics"]) if same else []
        for check in checks:
            if not check["passed"]:issue("REGRESSION_"+check["metric_id"],str(check),"agent_violation" if check["known"] else "missing_evidence")
    # ponytail: diagnostic gate only; add verified authority/consumption and package gates before release.
    issue("CANDIDATE_APPROVAL_AUTHORITY_PENDING","Candidate bytes, approval, reviewer authority and runtime-consumption evidence not integrated; no release authorization inferred")
    summary={"report_kind":"p7-round-readiness-v1","run_id":r0_manifest["run_id"],"status":status(issues),"decision":"hold",
             "comparison_ref":local.ref("comparison.json") if comparison else None,"no_regression":checks,
             "notice":"Diagnostic comparison only, not a typed ReleaseDecision or production activation. P7 release integration pending."}
    validation={"schema_version":"1.0.0","artifact_id":r0_manifest["run_id"]+"/p7/validation","run_id":r0_manifest["run_id"],
                "status":status(issues),"issues":issues,"coverage_refs":[]}
    validate("ValidationReport",validation);_write(target/"validation.json",validation)
    _write(target/"round-readiness.json",summary)
    lines=["# P7 — R0/R1 diagnostic comparison","","Release readiness: hold. Not release authorization.","",
           "| Metric | R0 full | R1 full | Delta | Delta unit/type | Status |","| --- | ---: | ---: | ---: | --- | --- |"]
    for row in comparison["rows"] if comparison else []:
        number=lambda x:"—" if x is None else format(x,".4g")
        lines.append("| "+" | ".join([row["metric_id"],number(row["baseline"]),number(row["system"]),number(row["delta"]),row["unit"]+" / "+row["delta_kind"],row["status"]])+" |")
    if comparison is None:lines+=["","INCOMPLETE: no real R1 execution supplied."]
    with (target/"table.md").open("x") as stream:stream.write("\n".join(lines)+"\n")
    locked_run(r0_run)
    if r1_run is not None:locked_run(r1_run)
    close_output(target)
    return summary

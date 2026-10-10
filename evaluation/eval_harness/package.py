"""P10 reproducible evidence handoff; missing acceptance stays NOT_RUN."""
import platform
import sys

from .assets import read_json
from .collector import locked_run
from .datasets import close_output
from .reporting import copy_run
from .runner import _output_path, _write


def handoff_package(bundle_run,out):
    source,_=locked_run(bundle_run)
    plan=read_json(source.path("package-plan.json"))
    if set(plan)!={"schema_version","runs","acceptance"} or plan["schema_version"]!="p10-package-v1" or not isinstance(plan["runs"],dict):
        raise ValueError("Explicit package runs/acceptance plan required")
    target=_output_path(out,source);target.mkdir(parents=True,mode=0o700)
    assets=copy_run(source.root,target/"inputs")
    reports={};rounds={}
    for name,relative in plan["runs"].items():
        path=(assets.root/relative).resolve()
        if not path.is_relative_to(assets.root):raise ValueError("Package input escapes root")
        run,_=locked_run(path)
        manifest=read_json(run.path("manifest.json")) if (path/"manifest.json").exists() else None
        if manifest is not None:rounds[name]={"round":manifest["round"],"run_id":manifest["run_id"],"fixture":manifest["fixture"]}
        report_path=next((f for f in ("metrics-report.json","suite-report.json","round-readiness.json","smoke-report.json") if (path/f).exists()),None)
        reports[name]={"manifest":manifest,"report":read_json(path/report_path) if report_path else None}
    required=["A"+str(i).zfill(2) for i in range(1,19)]
    if set(plan["acceptance"])-set(required):raise ValueError("Unknown acceptance ID")
    acceptance=[]
    for aid in required:
        ref=plan["acceptance"].get(aid)
        if ref is None:
            acceptance.append({"id":aid,"execution":"NOT_RUN","reason":"REAL_RUNTIME_ACCEPTANCE_EVIDENCE_MISSING"})
            continue
        obj=assets.resolve(ref)
        if not isinstance(obj,dict) or obj.get("acceptance_id")!=aid or not obj.get("evidence_refs"):
            raise ValueError("Acceptance artifact role/evidence mismatch")
        for evidence in obj["evidence_refs"]:assets.resolve(evidence,json_content=False)
        # Presence/hash is not independent verification of a live PASS.
        acceptance.append({"id":aid,"execution":"EVIDENCE_PRESENT_UNVERIFIED","ref":{**ref,"path":"inputs/"+ref["path"]},
                           "reason":"ACCEPTANCE_VERIFIER_NOT_IMPLEMENTED_FOR_THIS_ARTIFACT"})
    missing=[a["id"] for a in acceptance if a["execution"]=="NOT_RUN"]
    real_rounds=all(name in rounds and rounds[name]["round"]==i and not rounds[name]["fixture"] for i,name in enumerate(("R0","R1","R2")))
    distinct=len({rounds[name]["run_id"] for name in ("R0","R1","R2") if name in rounds})==3
    report={"report_kind":"p10-handoff-v1","quality_accepted":False,"status":{"verdict":"UNDETERMINED","completeness":"INCOMPLETE", "reason_codes":["LIVE_ACCEPTANCE_VERIFICATION_PENDING"]},
            "acceptance":acceptance,"missing_acceptance_ids":missing,"real_r0_r1_r2_present":real_rounds and distinct,
            "components":list(reports),"environment":{"python":sys.version,"platform":platform.platform()},
            "notice":"Recoverable verified-byte handoff, not benchmark or release certification. No production pointer mutations."}
    _write(target/"package-report.json",report)
    _write(target/"components.json",reports)
    with (target/"README.md").open("x") as stream:
        stream.write("# Evaluation evidence handoff\n\nStatus: INCOMPLETE; live acceptance verification pending.\n\n"
                     "Read package-report.json and inputs/package-plan.json. All source snapshots are retained with immutable locks.\n"
                     "Do not replace missing A01–A18 with fixture PASS, regrade R0 as R1/R2, or mutate active production.\n")
    locked_run(bundle_run);close_output(target)
    return report

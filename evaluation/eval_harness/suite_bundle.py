"""P8–P10 closed producer-evidence adapters, not fabricated live suite execution."""
from collections import Counter

from .assets import parse_json, read_json
from .collector import context_key, locked_run, status
from .contracts import ROOT, checker, validate
from .datasets import close_output
from .judging import selections, judge_record, agreement, hybrid, prompt
from .m2_metrics import rag_report, diarization_report, voice_report
from .metrics import match_tool_calls
from .reporting import copy_run
from .runner import _output_path, _write
from .simulation import seed_statistics


def evaluate_bundle(inputs_run,out):
    source,_=locked_run(inputs_run)
    manifest=read_json(source.path("manifest.json"));validate("Manifest",manifest)
    target=_output_path(out,source);target.mkdir(parents=True,mode=0o700)
    assets=copy_run(source.root,target/"inputs")
    expected_suites=[s["id"] for s in manifest["suites"] if s["applicable"]]
    issues=[];suite_results={};coverage_refs=[]
    def issue(code,message,classification="missing_evidence"):
        issues.append({"code":code,"message":message,"classification":classification,
                       "artifact":{**assets.ref("manifest.json"),"path":"inputs/manifest.json"},"json_pointer":""})
    def save(name,report):
        _write(target/(name+"-report.json"),report);suite_results[name]=report
    for ref in manifest["sources"]+manifest["scenarios"]+manifest["grading_contracts"]:
        try:assets.resolve(ref,json_content=False)
        except (OSError,ValueError,KeyError,IndexError) as exc:issue("MANIFEST_REGISTERED_ASSET_MISSING",str(exc))
    if (assets.root/"judge-input.json").exists():
        data=read_json(assets.path("judge-input.json"))
        if set(data)!={"schema_version","version","requests","human_labels","sampling_seed"} or data["schema_version"]!="p8-judge-bundle-v1" or data["version"]!=manifest["configuration"]["judge_version"]:
            raise ValueError("Pinned judge version/request schema mismatch")
        expected=[context_key({"run_id":manifest["run_id"],**{k:p[k] for k in ("config","scenario_id","call")},"turn":1}) for p in manifest["planned_calls"]]
        observed=[];records=[];prompts=[]
        for req in data["requests"]:
            if set(req)!={"context","scenario_ref","trace_ref","signals","responses","assertion_ref"}:raise ValueError("Judge request shape invalid")
            ctx=req["context"];validate("Context",ctx);key=context_key(ctx);observed.append(key)
            if key not in expected:raise ValueError("Unknown judge call")
            if req["scenario_ref"] not in manifest["scenarios"]:raise ValueError("Judge scenario not pinned")
            scenario=assets.resolve(req["scenario_ref"])
            if scenario["scenario_id"]!=ctx["scenario_id"]:raise ValueError("Judge context/scenario mismatch")
            spec=scenario["calls"][ctx["call"]]
            trace=assets.resolve(req["trace_ref"])
            if not trace:issue("JUDGE_TRACE_MISSING",key)
            for row in trace:
                errors=checker.errors("sources/btc/schemas/trace_log.schema.json",row)
                if errors or any(row[k]!=ctx[k] for k in ("run_id","config","scenario_id","call")):raise ValueError("Judge trace wrong role/context/schema")
            plan=next(p for p in manifest["planned_calls"] if p["config"]==ctx["config"] and p["scenario_id"]==ctx["scenario_id"] and p["call"]==ctx["call"])
            trace_complete=Counter(r["turn"] for r in trace)==Counter(range(1,plan["expected_turns"]+1))
            if not trace_complete:issue("JUDGE_TURN_COVERAGE",key)
            selection=selections(ctx["call"],spec,trace,req["signals"])
            allowed={s["criterion"]["id"] for s in selection}
            if set(req["responses"])-allowed:raise ValueError("Unknown judge criterion")
            refs=[{**req["trace_ref"],"path":"inputs/"+req["trace_ref"]["path"]}]
            for choice in selection:
                mid=choice["criterion"]["id"]
                attempts=[assets.resolve(r) for r in req["responses"].get(mid,[])]
                attempt_refs=[{**r,"path":"inputs/"+r["path"]} for r in req["responses"].get(mid,[])]
                record=judge_record(ctx,choice,attempts,refs+attempt_refs,data["version"],trace)
                if not trace_complete and record["applicable"]:
                    if record["status"]["verdict"]=="FAIL":record["status"]={"verdict":"FAIL","completeness":"INCOMPLETE","reason_codes":["JUDGE_TRACE_COVERAGE","JUDGE_CRITERION_FAIL"]}
                    else:record.update(status={"verdict":"UNDETERMINED","completeness":"INCOMPLETE","reason_codes":["JUDGE_TRACE_COVERAGE"]},verdict=None,error="JUDGE_TRACE_COVERAGE")
                validate("JudgeRecord",record)
                records.append(record)
            assertion=assets.resolve(req["assertion_ref"])
            validate("SupplementalReport",assertion)
            if assertion["run_id"]!=manifest["run_id"]:raise ValueError("Assertion/judge run mismatch")
            joined=hybrid(assertion["status"],[r for r in records if r["context"]==ctx])
            if joined["verdict"]=="FAIL":issue("JUDGE_HYBRID_FAIL",key,"agent_violation")
            if joined["completeness"]!="COMPLETE":issue("JUDGE_EVIDENCE_INCOMPLETE",key)
            prompts.append({"context":ctx,"prompt":prompt(spec,trace,[s["criterion"] for s in selection if s["applicable"] is not False])})
        if Counter(expected)!=Counter(observed):issue("JUDGE_CALL_COVERAGE","Missing/duplicate registered calls")
        agreement_report=agreement(records,data["human_labels"],data["sampling_seed"])
        if not agreement_report["complete"]:issue("HUMAN_AGREEMENT_QUOTA","Need >=20 randomly selected independently human-labelled pairs")
        if agreement_report["analysis_required"]:issue("JUDGE_KAPPA_ANALYSIS_REQUIRED","Kappa below0.6")
        save("judge",{"records":records,"agreement":agreement_report,"expected_ids":expected,"observed_ids":observed,
                      "notice":"Raw producer attempts preserved; human authority/inference provenance not certified by file hashes"})
        _write(target/"judge-prompts.json",prompts)
    if (assets.root/"rag-results.json").exists():
        review_names=("rag-review.json","rag-attestation.json","rag-review-policy.json")
        review_present=[(assets.root/name).exists() for name in review_names]
        if any(review_present) and not all(review_present):
            raise ValueError("RAG QA review requires review, attestation and policy together")
        if all(review_present) and any(assets.ref(name) not in manifest["sources"] for name in review_names):
            raise ValueError("RAG QA review inputs must be pinned in manifest sources")
        review_paths=dict(zip(("review_path","attestation_path","policy_path"),
                              (assets.path(name) for name in review_names))) if all(review_present) else {}
        save("rag",rag_report(ROOT/"sources/btc/rag/qa_labeled.json",assets.path("rag-results.json"),**review_paths))
        if not suite_results["rag"]["complete"]:issue("RAG_QID_COVERAGE","Keep all60 BTC qids")
        if suite_results["rag"]["answer_version_status"]!="COMPLETE":
            issue("RAG_ANSWER_VERSION_PENDING","Q20/Q57 disputed; answer/version labels need independent rubric and sources")
    if (assets.root/"diarization/ground_truth.json").exists():
        save("diarization",diarization_report(assets.root/"diarization",manifest["asr_ids"]))
        if not suite_results["diarization"]["complete"]:issue("DIARIZATION_INCOMPLETE","Missing prediction/segment registered cohort")
        issue("DIARIZATION_AUDIO_PROVENANCE_PENDING","Producer audio/inference lineage not certified by midpoint scorer")
    if (assets.root/"simulator-results.json").exists():
        data=read_json(assets.path("simulator-results.json"))
        scenarios=[assets.resolve(r)["scenario_id"] for r in manifest["scenarios"]]
        save("simulator",seed_statistics(data,scenarios,tuple(manifest["simulator_seeds"])))
        if not suite_results["simulator"]["complete"]:issue("SIMULATOR_COHORT_INCOMPLETE","All pinned scenarios/seeds required")
        elif not suite_results["simulator"]["stable"]:issue("SIMULATOR_UNSTABLE","TSR seed range >10percentage points","agent_violation")
        issue("SIMULATOR_RUNTIME_PROOF_PENDING","Imported passed booleans need real Agent execution/scorer logs, not self-declared wins")
    if (assets.root/"voice-input.json").exists():
        data=read_json(assets.path("voice-input.json"))
        if assets.ref("voice-plan.json") not in manifest["sources"]:raise ValueError("Voice session/turn plan must be pinned before execution")
        plan=read_json(assets.path("voice-plan.json"))
        save("voice",voice_report(plan["expected_ids"],data["sessions"],planned_turns=plan["turn_ids"]))
        if not suite_results["voice"]["complete"]:issue("VOICE_EVIDENCE_INCOMPLETE",str(suite_results["voice"]["reason_codes"]))
        elif not suite_results["voice"]["passed"]:issue("VOICE_LATENCY_FAIL","TTFA/brief mandatory thresholds failed","agent_violation")
        issue("VOICE_PLAYBACK_ISOLATION_PROOF_PENDING","Timestamp labels and namespace strings do not prove played byte/runtime isolation")
    if (assets.root/"tool-input.json").exists():
        data=read_json(assets.path("tool-input.json"));results=[]
        expected=[context_key({"run_id":manifest["run_id"],**{k:p[k] for k in ("config","scenario_id","call")},"turn":t}) for p in manifest["planned_calls"] for t in range(1,p["expected_turns"]+1)]
        observed=[]
        for group in data:
            labels=assets.resolve(group["labels"]);events=assets.resolve(group["events"])
            if group["labels"] not in manifest["sources"]:raise ValueError("Tool labels must be pinned before execution")
            observed.append(context_key(labels["context"]))
            for event in events:
                for ref in event["evidence_refs"]:assets.resolve(ref,json_content=False)
            matched=match_tool_calls(labels,events);results.append(matched)
            if matched["execution_failures"]:issue("TOOL_EXECUTION_FAIL","Invocation TP does not prove execution success","agent_violation")
            if matched["execution_incomplete"]:issue("TOOL_EXECUTION_UNDETERMINED","Side effects unknown")
        if Counter(expected)!=Counter(observed):issue("TOOL_LABEL_COVERAGE","Every registered turn needs labels/no-tool declaration")
        save("tool_accuracy",{"contexts":results,"expected_ids":expected,"observed_ids":observed})
    for suite in expected_suites:
        if suite not in suite_results:issue("APPLICABLE_SUITE_NOT_RUN",suite)
    # Imports are component measurements, never proof of new inference or complete M2.
    issue("PRODUCER_RUNTIME_ACCEPTANCE_PENDING","Closed evidence adapters implemented; live runtime/A01–A18 and source authority still required")
    if manifest["fixture"]:issue("FIXTURE_NOT_BENCHMARK","Do not count fixture results as real acceptance")
    validation={"schema_version":"1.0.0","artifact_id":manifest["run_id"]+"/suite-validation","run_id":manifest["run_id"],
                "status":status(issues),"issues":issues,"coverage_refs":coverage_refs}
    validate("ValidationReport",validation);_write(target/"validation.json",validation)
    report={"report_kind":"p8-p10-evidence-adapters-v1","run_id":manifest["run_id"],"status":status(issues),
            "quality_accepted":False,"suite_reports":{k:k+"-report.json" for k in suite_results},"applicable_suites":expected_suites,
            "notice":"Independent suites, no merging simulator/judge counts into fixed-turn BTC metrics, no production activation"}
    _write(target/"suite-report.json",report)
    locked_run(inputs_run);checker.verify_sources();close_output(target)
    return report

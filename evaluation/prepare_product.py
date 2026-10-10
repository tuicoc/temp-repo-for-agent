"""Prepare new pinned development assets for product P2; never calls a model."""
import argparse
import json
from pathlib import Path
import subprocess
import hashlib

from product_smoke import PRODUCT, FILES, tool_specs
from eval_harness.assets import Assets, read_json
from eval_harness.contracts import ROOT, checker
from eval_harness.preflight import preflight
from eval_harness.runner import _output_path, _write


def prepare(out, with_extractor=False, provider=None, model=None, max_model_calls=3, extractor_calls=3, storage="sqlite_unit", scenarios_dir=None, policy=False, qa=False):
    if storage not in ("sqlite_unit", "postgresql"):raise ValueError("Explicit known storage required")
    if type(max_model_calls) is not int or not 1<=max_model_calls<=64 or type(extractor_calls) is not int or not 1<=extractor_calls<=64:raise ValueError("Explicit bounded budgets1–64 required")
    if bool(provider)!=bool(model):raise ValueError("Provider and model must be selected together")
    checker.verify_sources()
    out=_output_path(out,Assets(PRODUCT))
    out.mkdir(parents=True,mode=0o700)
    files=[]
    assets=Assets(out)
    for name in FILES:
        target=out/"product"/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((PRODUCT/name).read_bytes())
        files.append(assets.ref("product/"+name))
    (out/"product_adapter.py").write_bytes((ROOT.parent/"product_adapter.py").read_bytes())
    python=PRODUCT/".venv/bin/python"
    selection="get_models_config().llm_config("+repr(provider)+","+repr(model)+")" if provider else "get_models_config().agent_llm_config('advisor')"
    command="import json; from src.config.config_manager import get_models_config; print(json.dumps("+selection+"))"
    config=json.loads(subprocess.run([str(python),"-B","-c",command],cwd=PRODUCT,capture_output=True,text=True,check=True,timeout=15).stdout)
    config.update(temperature=0,max_retries=0,tracing=False,timeout=30)
    config["memory_output_strategy"] = "json_mode" if config["provider"] == "groq" else "json_schema"
    config["memory_span_strategy"] = "unique_quote_v1"
    if config["provider"] not in ("google_genai","groq"):raise ValueError("Runtime requires explicit SDK retry control")
    criteria=checker.read("sources/btc/eval/llm_judge_rubric.json")["criteria"] if qa else []
    bundle={"schema_version":"product-bundle-v1","files":files,"tools":tool_specs(),
            "features":{"policy":bool(policy),"qa":bool(qa)},"qa_criteria":criteria,
            "storage":storage,
            "python":str(python.absolute()),"max_model_calls":max_model_calls,"full_run":max_model_calls>3,"llm_config":config,
            "notice":"Development only; environment credentials only; no production database; explicit per-process budget pinned"}
    _write(out/"product-bundle.json",bundle)
    descriptor={"kind":"runtime","entrypoint":"product_adapter:factory","code":assets.ref("product_adapter.py"),
                "capabilities":["business_tools","memory_isolation","memory_read_gate","after_call_barrier","snapshots","briefs","timestamps","usage"]}
    _write(out/"adapter.json",descriptor)
    # The five generated cases remain diagnostic; no automatic conversion grants QA approval.
    (out/"fixtures").mkdir()
    if scenarios_dir is None:
        for name in ("scenario.json","grading.json"):
            (out/"fixtures"/name).write_bytes((ROOT/"fixtures"/name).read_bytes())
        scenario_refs=[assets.ref("fixtures/scenario.json")]
        grading_refs=[assets.ref("fixtures/grading.json")]
        scenarios=[assets.resolve(scenario_refs[0])]
    else:
        from eval_harness.contracts import validate
        from eval_harness.preflight import call_plan
        source=Path(scenarios_dir).resolve()
        paths=sorted(source.glob("*.json"))
        if not paths or len(paths)!=5 or not (source.parent/"conversion-report.json").is_file():
            raise ValueError("Require the five diagnostic revision files")
        conversion=read_json(source.parent/"conversion-report.json")
        if conversion.get("official_gt_approved") is not False or len(conversion.get("files",[]))!=len(paths):
            raise ValueError("Diagnostic conversion report missing or mislabelled")
        for path,record in zip(paths,conversion["files"]):
            original=ROOT.parent/record["source"]
            if (record["derived"]!="scenarios/"+path.name or not original.is_file()
                    or hashlib.sha256(original.read_bytes()).hexdigest()!=record["source_sha256"]):
                raise ValueError("Scenario conversion provenance changed")
            from normalize_output1 import convert
            if read_json(path)!=convert(read_json(original))[0]:
                raise ValueError("Derived scenario differs from pinned normalization")
        _write(out/"conversion-report.json",conversion)
        (out/"scenarios").mkdir()
        (out/"grading").mkdir()
        scenario_refs=[];grading_refs=[];scenarios=[]
        for path in paths:
            item=read_json(path);validate("Scenario",item)
            (out/"scenarios"/path.name).write_bytes(path.read_bytes())
            ref=assets.ref("scenarios/"+path.name)
            scenario_refs.append(ref);scenarios.append(item)
            grader=read_json(ROOT/"fixtures/grading.json")
            grader["scenario"]=ref;grader["scenario_id"]=item["scenario_id"];grader["level"]=item["level"]
            grader["calls"]=[]
            for call in item["calls"]:
                template=read_json(ROOT/"fixtures/grading.json")["calls"][0]
                template["call"]=call
                template["official_success_if"]={**ref,"pointer":"/calls/"+call+"/success_if"}
                template["ground_truth"]=[ref]
                template["suites"][0]["reason"]="Generated diagnostic GT pending QA"
                grader["calls"].append(template)
            _write(out/"grading"/path.name,grader)
            grading_refs.append(assets.ref("grading/"+path.name))
    manifest=read_json(ROOT/"fixtures/p6-manifest.json")
    manifest["artifact_id"]="PRODUCT-DEV-Manifest"
    manifest["configuration"]["model"]=config["model"]
    manifest["configuration"]["parameters"]={k:config[k] for k in ("provider","temperature","max_tokens","timeout","max_retries","memory_output_strategy","memory_span_strategy")}
    manifest["configuration"]["parameters"]["runtime_storage"]=storage
    # A new prepared bundle must not resume/overwrite a previous PostgreSQL run.
    suffix=hashlib.sha256(str(out).encode()).hexdigest()[:16]
    manifest["run_id"]="PRODUCT-DEV-"+suffix
    scope=read_json(ROOT/"fixtures/p1-scope.json")
    if scenarios_dir is not None:
        scope["notice"]="Generated diagnostic scenarios; labels pending independent QA; report-only synthetic test"
        scope["source_decisions"]=[{**scope["source_decisions"][0],"origin":ref,
                                    "artifact_id":manifest["run_id"]+"/source-decision/"+str(index),
                                    "reason":"User-provided generated data; report-only diagnostic; GT not approved"}
                                   for index,ref in enumerate(scenario_refs)]
    for decision in scope["source_decisions"]:
        decision["run_id"]=manifest["run_id"]
        if scenarios_dir is None:decision["artifact_id"]=manifest["run_id"]+"/source-decision"
    _write(out/"fixtures/p1-scope.json",scope)
    manifest["state_namespaces"]={key:"product/"+suffix+"/"+key for key in manifest["state_namespaces"]}
    manifest["configuration"]["hardware"]="local-product-subprocess"
    refs=[]
    for key in ("prompt","tools","kb"):
        ref=manifest["configuration"][key]
        target=out/ref["path"]
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/ref["path"]).read_bytes())
        refs.append(ref)
    manifest["scenarios"]=scenario_refs
    manifest["grading_contracts"]=grading_refs
    if scenarios_dir is not None:
        manifest["level"]="M2"
        manifest["planned_calls"]=[{"config":config,"scenario_id":item["scenario_id"],"call":plan["call"],
                                    "expected_turns":plan["expected_turns"],
                                    "memory_required":config=="full" and bool(item["calls"][plan["call"]].get("must_carry_over"))}
                                   for config in ("full","baseline_no_memory") for item in scenarios
                                   for plan in call_plan(item,manifest["reference_date"])]
    (out/"metrics-policy.json").write_bytes((ROOT/"fixtures/p6-metrics-policy.json").read_bytes())
    manifest["sources"]=[assets.ref("fixtures/p1-scope.json"),*refs,assets.ref("adapter.json"),descriptor["code"],assets.ref("product-bundle.json"),assets.ref("metrics-policy.json"),*files]
    if scenarios_dir is not None:manifest["sources"].append(assets.ref("conversion-report.json"))
    if with_extractor:
        (out/"extractor-prompt.txt").write_bytes((ROOT.parent/"extractor-prompt.txt").read_bytes())
        extractor_config=dict(config)
        # Gemini 3.x can spend a 512-token output cap on reasoning and return no visible JSON.
        extractor_config["max_tokens"]=2048
        extractor={"kind":"command_model","version":"product-extractor-v1","python":str(python.absolute()),"backend":"product",
                   "code":assets.ref("product/src/agents/evaluation_model.py"),"files":files,"config":extractor_config,
                   "prompt":assets.ref("extractor-prompt.txt"),"max_calls":extractor_calls}
        _write(out/"extractor.json",extractor)
        manifest["sources"] += [assets.ref("extractor-prompt.txt"),assets.ref("extractor.json")]
        manifest["configuration"]["extractor_version"]=extractor["version"]
    _write(out/"manifest.json",manifest)
    _write(out/"settings.json",{"asset_root":".","manifest":"manifest.json","scope":"fixtures/p1-scope.json","adapter":assets.ref("adapter.json")})
    report=preflight(out/"settings.json")
    _write(out/"preparation-report.json",report)
    if scenarios_dir is not None:
        _write(out/"diagnostic-readiness.json",{
            "schema_version":"output1-json-readiness-v1","run_id":manifest["run_id"],
            "configs":["full","baseline_no_memory"],"scenarios":len(scenarios),
            "planned_calls":len(report["coverage_plan"]["calls"]),
            "planned_trace_rows":len(report["coverage_plan"]["expected_trace_ids"]),
            "observed_trace_rows":None,"m1_score":None,"m2_score":None,
            "status":"INCOMPLETE","reasons":["GT_QA_PENDING","RUNTIME_TRACE_NOT_RUN",
                                                "EXTRACTOR_AND_SCORER_NOT_RUN","M2_PRODUCERS_NOT_RUN","ASR_DEFERRED"],
            "notice":"Preflight is input-only; no Agent/model, trace, scoring, or M2 producer evidence was fabricated",
        })
    return {"settings":str(out/"settings.json"),"execution_gate":report["execution_gate"],
            "notice":"No execution performed. Fixture scope only; real extractor "+("pinned" if with_extractor else "not configured")+"; separate API budget authorization required for paired run/extraction."}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--with-extractor",action="store_true",help="Pin real extractor; does not call it; explicit collect consumes separate model budget")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--max-model-calls",type=int,default=3)
    parser.add_argument("--extractor-calls",type=int,default=3)
    parser.add_argument("--storage",choices=("postgresql","sqlite_unit"),default="postgresql",help="PostgreSQL required for durable integration; sqlite_unit only component diagnostics")
    parser.add_argument("--scenarios-dir",type=Path,help="Five derived JSON scenarios for diagnostic paired M1/M2 input planning")
    parser.add_argument("--policy",action="store_true",help="Enable bounded M2 soft guard; consumes additional model calls")
    parser.add_argument("--qa",action="store_true",help="Enable M2 post-call QA on predeclared applicable BTC criteria")
    args=parser.parse_args()
    print(json.dumps(prepare(args.out,args.with_extractor,args.provider,args.model,args.max_model_calls,args.extractor_calls,args.storage,args.scenarios_dir,args.policy,args.qa),ensure_ascii=False,indent=2))

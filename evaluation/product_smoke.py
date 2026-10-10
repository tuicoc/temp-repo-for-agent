"""Run the existing product Advisor with isolated BTC tools, not an M1 benchmark."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import sys
import time

from eval_harness.assets import Assets, read_json
from eval_harness.contracts import ROOT, checker
from eval_harness.datasets import close_output
from eval_harness.environment import MockEnvironment
from eval_harness.runner import _output_path, _write
from product_adapter import read_message, stop_process, model_environment

PRODUCT = ROOT.parent.parent / "backend"
if not PRODUCT.is_dir():
    PRODUCT = ROOT.parent.parent / "temp-repo-for-agent/backend"
FILES = ("src/agents/base.py","src/agents/advisor.py","src/agents/evaluation_bridge.py",
         "src/agents/memory.py","src/agents/call_runtime.py",
         "src/agents/orchestrator.py","src/agents/policy.py","src/agents/qa.py",
         "src/agents/runtime_store.py","src/agents/pii.py","src/agents/mcp_business.py",
         "src/agents/mcp_memory.py",
         "src/agents/evaluation_model.py",
         "src/config/config_manager.py","src/llm/factory.py","src/llm/callback_handler.py",
         "src/llm/rate_limiter.py","src/llm/token_ledger.py","src/llm/tracing.py",
         "config/models.yaml","requirements.txt")


def tool_specs():
    descriptions = {r["name"]:r.get("description",r["name"]) for r in read_json(ROOT/"sources/btc/schemas/tools.schema.json")["tools"]}
    specs = [{"name":r["properties"]["name"]["const"],
             "description":descriptions[r["properties"]["name"]["const"]],
             "schema":r["properties"]["args"]}
            for r in read_json(ROOT/"contracts.schema.json")["$defs"]["ToolArgs"]["oneOf"]]
    for spec in specs:
        if spec["name"] == "handoff.transfer":
            spec["schema"]["properties"]["brief"] = read_json(ROOT/"sources/btc/schemas/handoff_brief.schema.json")
    return specs


def smoke(out, python, maximum=3):
    checker.verify_sources()
    if type(maximum) is not int or not 1 <= maximum <= 3:
        raise ValueError("Budget must be 1–3 model calls")
    assets = Assets(PRODUCT)
    out = _output_path(out, assets)
    out.mkdir(parents=True,mode=0o700)
    pins = {name:assets.ref(name) for name in FILES}
    plan = {"kind":"product-advisor-diagnostic-v1","max_model_calls":maximum,
            "tools":tool_specs(),"llm_config":{"temperature":0},"product_sources":pins,
            "bridge_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "btc_source_lock":read_json(ROOT/"sources.lock.json"),"on":"2026-10-15",
            "inputs":["Chào em, em là người thật hay trợ lý tự động?",
                      "Em kiểm tra tồn kho SKU-AP-PRO giúp chị, chưa tạo đơn nhé."],
            "notice":"No GT/oracle/memory supplied; separate product interpreter; no production DB or tools"}
    _write(out/"plan.json",plan)
    for name in FILES:
        target=out/"product-snapshot"/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(assets.path(name).read_bytes())
        if hashlib.sha256(target.read_bytes()).hexdigest()!=pins[name]["sha256"]:
            raise ValueError("Product source changed during snapshot")
    runtime_probe="import json,sys,importlib.metadata as m; print(json.dumps({'python':sys.version,'packages':{n:m.version(n) for n in ['langchain','langchain-core','langgraph','pydantic','langchain-google-genai','langchain-groq']}}))"
    runtime=subprocess.run([str(Path(python).absolute()),"-B","-c",runtime_probe],capture_output=True,text=True,timeout=15,check=True)
    _write(out/"product-runtime.json",json.loads(runtime.stdout))
    records=[]
    def send(process, data):
        process.stdin.write((json.dumps(data,ensure_ascii=False)+"\n").encode("utf-8"));process.stdin.flush()
    def receive(process, deadline):
        value=read_message(process,deadline)
        records.append(value)
        return value
    error=None
    process=None
    tool_events=[]
    with (out/"product-stderr.log").open("x") as stderr:
        try:
            with MockEnvironment(out.name,"PRODUCT-SMOKE","full") as env:
                bootstrap="from dotenv import load_dotenv; import runpy,os; load_dotenv("+repr(str(PRODUCT/".env"))+",override=False); os.environ.pop('EVALUATION_APPROVAL_HMAC_KEY',None); runpy.run_module('src.agents.evaluation_bridge',run_name='__main__')"
                process=subprocess.Popen([str(Path(python).absolute()),"-B","-c",bootstrap],
                    cwd=out/"product-snapshot",stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,bufsize=0,env=model_environment())
                send(process,{k:plan[k] for k in ("max_model_calls","tools","llm_config")})
                # Keys remain environment-only; snapshot contains no .env.
                ready=receive(process,time.monotonic()+45)
                if ready["type"]!="ready":raise ValueError("Product startup failed: "+ready.get("error_type","invalid handshake"))
                for turn,text in enumerate(plan["inputs"],1):
                    send(process,{"type":"turn","text":text})
                    deadline=time.monotonic()+90
                    while True:
                        msg=receive(process,deadline)
                        if msg["type"]=="model_attempt":
                            if type(msg["model_calls"]) is not int or not 1<=msg["model_calls"]<=maximum:
                                raise ValueError("Invalid/exceeded model-call counter")
                            continue
                        if msg["type"]=="tool":
                            try:
                                result=env.call_tool(msg["name"],msg["args"],call="call_1",turn=turn,on=plan["on"])
                                send(process,{"type":"tool_result","result":result})
                            except (ValueError,KeyError,TypeError):
                                send(process,{"type":"tool_result","error":"Tool arguments rejected; no retry"})
                        elif msg["type"]=="result":break
                        elif msg["type"]=="error":
                            error="Product model error: "+msg["error_type"]
                            break
                        else:raise ValueError("Unexpected bridge message")
                    if error:break
                tool_events=env.events
                if process.poll() is None and not error:send(process,{"type":"close"})
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            error=str(exc)
        finally:
            if process:
                stop_process(process)
    _write(out/"raw-messages.json",records)
    _write(out/"tool-events.json",tool_events)
    for ref in pins.values():assets.resolve(ref,json_content=False)
    report={"kind":"product-advisor-diagnostic-v1","error":error,"quality_accepted":False,
            "completed_turns":sum(r["type"]=="result" for r in records),
            "model_calls":max((r.get("model_calls",0) for r in records),default=0),
            "readiness":"INCOMPLETE","limits":["MEMORY_RUNTIME_MISSING","REAL_EXTRACTOR_MISSING","PRICE_USAGE_RECONCILIATION_PENDING"],
            "notice":"Wiring smoke only; not paired full/baseline, not P2/P6 acceptance"}
    _write(out/"smoke-report.json",report)
    checker.verify_sources();close_output(out)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--product-python",type=Path,default=PRODUCT/".venv/bin/python")
    parser.add_argument("--max-model-calls",type=int,choices=(1,2,3),default=3)
    args=parser.parse_args()
    result=smoke(args.out,args.product_python,args.max_model_calls)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(2 if result["error"] else 0)

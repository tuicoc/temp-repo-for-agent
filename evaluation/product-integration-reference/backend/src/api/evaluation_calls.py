"""Authenticated local M1 sandbox call endpoints; never use the app database for runtime state."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import re
import json
import subprocess
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agents.advisor import AdvisorAgent
from ..agents.call_runtime import CallRuntime
from ..agents.evaluation_bridge import CallMeter
from ..agents.memory import MemoryAgent
from ..agents.runtime_store import RuntimeStore
from ..config.config_manager import get_models_config
from .auth import CurrentUser

router = APIRouter(prefix="/api/evaluation-calls", tags=["evaluation-sandbox"])
_lock = threading.RLock()
_active: dict[str, dict] = {}
_completed: dict[str, dict] = {}


class StartCall(BaseModel):
    customer_phone: str = Field(min_length=9, max_length=24)
    channel: str = Field(default="web", pattern="^(web|phone|zalo|facebook)$")
    honorific: str | None = Field(default=None, max_length=12)
    candidate_id: str | None = Field(default=None,max_length=80)
    conversation_id: int | None = Field(default=None,ge=1)
    anonymous: bool = False
    model_call_budget: int = Field(default=12,ge=1,le=12)


class Turn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class Reconcile(BaseModel):
    reason: str = Field(min_length=5,max_length=500)


@router.get("/capabilities")
def capabilities(user: CurrentUser):
    _enabled()
    llm=_advisor_bundle()
    return {"shared_runtime":True,"model":llm["model"],"provider":llm["provider"]}


def _enabled():
    if os.environ.get("EVALUATION_WEB_CALLS_ENABLED") != "1":
        raise HTTPException(404, "Evaluation sandbox is disabled")
    dsn = os.environ.get("EVALUATION_DATABASE_URL")
    if not dsn:
        raise HTTPException(503, "Evaluation sandbox PostgreSQL is not configured")
    try:
        store = RuntimeStore("health-check", dsn)
        store.close()
    except Exception:
        raise HTTPException(503, "Evaluation sandbox requires the isolated local PostgreSQL database") from None
    return dsn


def _workspace():
    import sys
    from pathlib import Path
    workspace = Path(__file__).resolve().parents[4]
    if not (workspace / "evaluation/eval_harness/environment.py").is_file():
        raise RuntimeError("Pinned BTC sandbox assets are not installed")
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))
    if str(workspace / "evaluation") not in sys.path:
        sys.path.insert(0, str(workspace / "evaluation"))
    return workspace


def _environment(run_id, scenario_id):
    workspace=_workspace()
    python=workspace/"evaluation/asr/.venv/bin/python"
    bridge=workspace/"evaluation/web_tool_worker.py"
    if not python.is_file() or not bridge.is_file():
        raise RuntimeError("Pinned BTC worker runtime is unavailable")
    from evaluation.product_adapter import read_message, stop_process
    tool_env={key:os.environ[key] for key in ("PATH","TMPDIR","TEMP","LANG","LC_ALL") if key in os.environ}
    tool_env["PYTHONDONTWRITEBYTECODE"]="1"
    process=subprocess.Popen([str(python),"-B",str(bridge)],cwd=workspace,stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,env=tool_env)
    process.stdin.write((json.dumps({"run_id":run_id,"scenario_id":scenario_id})+"\n").encode())
    process.stdin.flush()
    try:
        ready=read_message(process,time.monotonic()+20)
    except Exception:
        stop_process(process)
        raise RuntimeError("BTC worker startup failed or timed out") from None
    if ready.get("type")!="ready":
        stop_process(process)
        raise RuntimeError("BTC worker failed to start: "+str(ready.get("error_type","unknown")))
    class Worker:
        def call_tool(self,name,args,*,call,turn,on):
            process.stdin.write((json.dumps({"name":name,"args":args,"call":call,"turn":turn,"on":on},ensure_ascii=False)+"\n").encode())
            process.stdin.flush()
            result=read_message(process,time.monotonic()+15)
            if result.get("type")!="result":
                raise RuntimeError("BTC worker failed: "+str(result.get("error_type","unknown")))
            return result["result"]
        def close(self):
            if process.poll() is None:
                try:
                    process.stdin.write(b'{"type":"close"}\n');process.stdin.flush()
                except OSError:pass
            stop_process(process)
    return Worker()


def _tool_specs():
    workspace=_workspace()
    root=workspace/"evaluation/evaluation-contracts"
    contracts=root/"contracts.schema.json"
    btc=root/"sources/btc/schemas/tools.schema.json"
    handoff=root/"sources/btc/schemas/handoff_brief.schema.json"
    pins={contracts:"851594f4d5179e5c6a47bd024f166093b1a9c34d7076c3d963cc184b97dea071",
          btc:"4cc8935e3e7f1a37b43eab0d68d85e8383037e52423e9f7cc022da916c97d4e0",
          handoff:"d57546f15e5d18feece2d270794c99dea9dd74fdab02354cd49b3faabe7f6b8b"}
    for path,expected in pins.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError("Pinned BTC tool contract hash mismatch")
    descriptions={item["name"]:item.get("description",item["name"])
                  for item in json.loads(btc.read_text())["tools"]}
    schema=json.loads(contracts.read_text())["$defs"]["ToolArgs"]["oneOf"]
    specs=[{"name":item["properties"]["name"]["const"],
            "description":descriptions[item["properties"]["name"]["const"]],
            "schema":item["properties"]["args"]} for item in schema]
    for item in specs:
        if item["name"]=="handoff.transfer":
            item["schema"]["properties"]["brief"]=json.loads(handoff.read_text())
    return specs


def _advisor_bundle():
    llm = get_models_config().agent_llm_config("advisor")
    if llm["provider"] not in ("google_genai", "groq"):
        raise RuntimeError("Sandbox only supports providers with retry control")
    llm.update(max_retries=0, tracing=False, timeout=30, temperature=0)
    llm["memory_output_strategy"] = "json_mode" if llm["provider"] == "groq" else "json_schema"
    llm["memory_span_strategy"] = "unique_quote_v1"
    return llm


@router.post("/start", status_code=201)
def start_call(body: StartCall, user: CurrentUser):
    dsn = _enabled()
    if body.conversation_id is not None:
        from .chat import _own
        _own(body.conversation_id,user.id)
    normalized = re.sub(r"[^0-9+]", "", body.customer_phone)
    if len(re.sub(r"\D", "", normalized)) < 9:
        raise HTTPException(422, "Customer phone is not valid")
    phone_hash = hashlib.sha256(normalized.encode()).hexdigest()
    candidate=None
    if body.candidate_id:
        from .evaluation_gaps import _store,verify_approval
        gap_store=_store()
        try:candidate=gap_store.get_gap_candidate(body.candidate_id)
        finally:gap_store.close()
        if not candidate or not verify_approval(candidate):
            raise HTTPException(409,"Candidate is not currently approved and source-valid")
    candidate_suffix=f"/candidate-{candidate['content_hash'][:12]}" if candidate else ""
    namespace = f"web-demo/{user.id}/{body.channel}/{phone_hash}{candidate_suffix}"
    scenario_id = "WEB-" + phone_hash[:12]
    run_id = f"WEB-USER-{user.id}"
    with _lock:
        if namespace in _active:
            raise HTTPException(409, "This sandbox customer already has an open call")
        store = RuntimeStore(namespace, dsn)
        environment = None
        runtime = None
        try:
            environment = _environment(run_id, scenario_id)
            llm = _advisor_bundle()
            tool_specs=_tool_specs()
            call_id = str(uuid.uuid4())
            call = {"run_id": run_id, "scenario_id": scenario_id, "config": "full",
                    "call": "call_1", "on": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat(),
                    "customer_phone": normalized, "honorific": body.honorific,
                    "channel": body.channel, "memory_read_previous": True,
                    "api_call_id":call_id,"api_owner":user.id,"conversation_id":body.conversation_id,
                    "anonymous":body.anonymous,
                    "model_call_budget":body.model_call_budget,
                    "model_pin":{key:llm.get(key) for key in ("provider","model","temperature","max_tokens","timeout","max_retries","memory_output_strategy","memory_span_strategy")},
                    "tool_contract_hash":hashlib.sha256(json.dumps(tool_specs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
            context = {"run_id": run_id, "scenario_id": scenario_id, "config": "full",
                       "namespace": namespace, "seed_history": [], "resources": {},"candidate":candidate}
            def call_tool(name, args):
                active = runtime.call if runtime and runtime.call else call
                is_turn=bool(runtime and runtime.call)
                event_index=runtime.tool_event_index+1 if is_turn else 0
                if is_turn:
                    runtime.tool_event_index=event_index
                from ..agents.pii import mask_pii
                def safe_json(value):
                    masked,_=mask_pii(json.dumps(value,ensure_ascii=False))
                    return json.loads(masked)
                event_base={"tool":name,"args":safe_json(args),"source":{"run_id":run_id,"scenario_id":scenario_id,
                            "call":active["call"],"turn":runtime.turn if is_turn else 0,"event_index":event_index}}
                if is_turn:
                    store.write_business_event(runtime.customer_id,active["call"],runtime.turn,event_index,{**event_base,"outcome":"attempted"})
                try:
                    result = environment.call_tool(name, args, call=active["call"],
                                                   turn=runtime.turn if is_turn else 1, on=active["on"])
                except Exception:
                    if is_turn:
                        store.write_business_event(runtime.customer_id,active["call"],runtime.turn,event_index,{**event_base,"outcome":"unknown"})
                    raise
                # Apply the same deny-list used by the evaluator before tool output reaches the model.
                from evaluation.product_adapter import customer_visible
                visible = customer_visible(result)
                if is_turn:
                    safe_result=safe_json(visible)
                    store.write_business_event(runtime.customer_id,active["call"],runtime.turn,event_index,{**event_base,"outcome":"completed","result":safe_result})
                    runtime.tool_results.append({"tool":name,"result":safe_result})
                return safe_result if is_turn else visible
            from ..agents.mcp_business import LocalMCPBusinessBus
            call_tool=LocalMCPBusinessBus(call_tool).call_tool
            from langchain_core.tools import StructuredTool
            tools=[]
            tool_counts={}
            tool_lock=threading.Lock()
            lane_tools={"IDENTITY_RESOLUTION":set(),"OUT_OF_SCOPE":set(),
                        "SALES":{"catalog.search","pricing.get_quote","inventory.check","schedule.callback","handoff.transfer"},
                        "CONTINUITY":{"catalog.search","pricing.get_quote","inventory.check","order.create","schedule.callback","handoff.transfer"},
                        "POST_SALE":{"crm.get_customer","order.status","order.create","inventory.check","handoff.transfer"},
                        "SCHEDULING":{"schedule.callback","handoff.transfer"}}
            limits={"catalog.search":1,"pricing.get_quote":1,"inventory.check":1,"crm.get_customer":1,
                    "order.status":1,"order.create":1,"schedule.callback":1,"handoff.transfer":1}
            for spec in tool_specs:
                name=spec["name"]
                def invoke(_name=name,**args):
                    with tool_lock:
                        if runtime.lane not in lane_tools or _name not in lane_tools[runtime.lane]:
                            return {"error":"Tool is unavailable in this routed lane; no retry."}
                        used=tool_counts.get(_name,0)
                        if used>=limits.get(_name,0):
                            return {"error":"Per-turn tool limit reached; no retry."}
                        tool_counts[_name]=used+1
                        return call_tool(_name,args)
                tools.append(StructuredTool.from_function(invoke,name=name,description=spec["description"],args_schema=spec["schema"]))
            advisor = AdvisorAgent(llm_config=llm, toolset=tools, strict_output=True)
            memory = MemoryAgent(llm)
            meter = CallMeter(body.model_call_budget,full_run=True)
            runtime_events=[]
            def emit(event):
                runtime_events.append(event)
                if candidate and event.get("kind")=="candidate_consumed" and event.get("candidate_hash")==candidate["content_hash"]:
                    from .evaluation_gaps import _store
                    gap_store=_store()
                    try:gap_store.append_gap_event(str(uuid.uuid4()),candidate["candidate_id"],
                        {"action":"sandbox_consumed","run_id":run_id,"scenario_id":scenario_id,
                         "call":call["call"],"call_id":call_id,"turn":runtime.turn,
                         "hash":candidate["content_hash"],"resource":event["resource"]})
                    finally:gap_store.close()
            runtime = CallRuntime(context, advisor, memory, call_tool,
                                  {"config": {"callbacks": [meter], "recursion_limit": 12}}, store=store,emit=emit)
            call_num = runtime.last_call + 1
            call["call"] = f"call_{call_num}"
            tool_counts.clear()
            started = runtime.start_call(call)
            store.initialize_model_budget(started["customer_id"],call["call"])
            def reserve_model_attempt(_count):
                store.claim_model_attempt(started["customer_id"],call["call"],body.model_call_budget)
            meter.notify=reserve_model_attempt
            _active[namespace] = {"call_id": call_id, "runtime": runtime, "environment": environment,
                                  "call": call, "owner": user.id, "store": store,"tool_counts":tool_counts,"meter":meter,"events":runtime_events}
            return {"call_id": call_id, "customer_id": started["customer_id"],
                    "call_brief": started["call_brief"], "memory_snapshot": started["memory_snapshot"],
                    "status": "OPEN","model":llm["model"],"model_call_budget":meter.maximum,
                    "candidate_id":candidate["candidate_id"] if candidate else None,"candidate_hash":candidate["content_hash"] if candidate else None}
        except HTTPException:
            raise
        except Exception as error:
            if runtime:
                runtime.close()
            elif store:
                store.close()
            if environment:
                environment.close()
            if isinstance(error, (ValueError, RuntimeError)):
                raise HTTPException(503, f"Could not start sandbox call ({type(error).__name__})") from None
            raise


def _entry(call_id, user_id):
    with _lock:
        for entry in _active.values():
            if entry["call_id"] == call_id and entry["owner"] == user_id:
                return entry
    record=_durable(call_id,user_id)
    if record and record["status"]=="OPEN":
        store=RuntimeStore(record["namespace"],_enabled())
        try:store.mark_web_call_interrupted(call_id)
        finally:store.close()
        raise HTTPException(409,"Call interrupted by backend restart; reconciliation required")
    if record:
        raise HTTPException(409,"Call is not open; inspect its persisted status")
    raise HTTPException(404, "Evaluation call not found")


def _durable(call_id,user_id):
    store=RuntimeStore("web-call-index",_enabled())
    try:return store.web_call(call_id,user_id)
    finally:store.close()


@router.get("/statuses")
def call_statuses(user:CurrentUser):
    dsn=_enabled()
    index=RuntimeStore("web-call-index",dsn)
    try:records=index.web_calls_for_owner(user.id)
    finally:index.close()
    with _lock:active_ids={entry["call_id"] for entry in _active.values() if entry["owner"]==user.id}
    output=[]
    for record in records:
        if record["status"]=="OPEN" and record["call_id"] not in active_ids:
            store=RuntimeStore(record["namespace"],dsn)
            try:store.mark_web_call_interrupted(record["call_id"])
            finally:store.close()
            record["status"]="RECONCILIATION_REQUIRED"
        output.append({key:record[key] for key in ("call_id","status","conversation_id","call")})
    return output


@router.post("/{call_id}/reconcile")
def reconcile_call(call_id:str,body:Reconcile,user:CurrentUser):
    from .evaluation_gaps import _reviewer
    from ..agents.pii import contains_pii
    reviewer=_reviewer(user)
    if contains_pii(body.reason):raise HTTPException(422,"Reconciliation reason contains personal identifiers")
    dsn=_enabled()
    with _lock:
        if any(item["call_id"]==call_id for item in _active.values()):
            raise HTTPException(409,"Call is still active in this worker")
        record=_durable(call_id,user.id)
        if not record:raise HTTPException(404,"Evaluation call not found")
        if record["status"]=="COMPLETED":
            return record["payload"] or {"call_id":call_id,"status":"COMPLETED",
                                         "completed":True,"barrier_complete":True}
        store=RuntimeStore(record["namespace"],dsn)
        try:
            if record["status"]=="OPEN":store.mark_web_call_interrupted(call_id)
            elif record["status"]!="RECONCILIATION_REQUIRED":
                raise HTTPException(409,"Call is not eligible for reconciliation")
            saved=store.call_record(record["customer"],record["call"])
            if not saved or saved["status"]!="OPEN":
                raise HTTPException(409,"Call barrier requires manual investigation")
            turns=store.turn_history(record["customer"],record["call"])
            last_turn=turns[-1][0] if turns else 0
            events=store.business_events(record["customer"],record["call"])
            if any(event.get("outcome")!="completed" or event.get("source",{}).get("turn",0)>last_turn for event in events):
                raise HTTPException(409,"Unknown tool outcome or incomplete turn requires manual investigation")
            writes=[{"key":fact["key"],"value":fact["value"],"customer_id":record["customer"],
                     "source":fact["source"],"op":"delete" if fact["state"]=="deleted" else "set"}
                    for fact in store.facts(record["customer"])
                    if fact["source"]["context"]["call"]==record["call"]]
            if any(item["source"]["context"]["turn"]>last_turn for item in writes):
                raise HTTPException(409,"Uncommitted memory turn requires manual investigation")
            saved_call=saved["context"]
            context={"run_id":saved_call["run_id"],"scenario_id":saved_call["scenario_id"],
                     "config":saved_call["config"],"namespace":record["namespace"],"seed_history":[],"resources":{}}
            runtime=CallRuntime(context,None,None,None,store=store)
            runtime.call=saved_call
            runtime.customer_id=record["customer"]
            runtime.turn=last_turn
            runtime.at=saved_call["on"]+"T00:00:00+07:00"
            runtime.writes=writes
            runtime.reconciliation={"reviewer":reviewer,"reason":body.reason.strip(),
                                    "at":datetime.now(timezone.utc).isoformat()}
            result={"call_id":call_id,"status":"COMPLETED","reconciled_interruption":True,**runtime.end_call()}
            try:
                from .evaluation_gaps import produce_outcome_signals
                result["outcome_signals"]=produce_outcome_signals(call_id,user.id)
            except Exception as error:
                result["outcome_signals"]={"status":"error","error_type":type(error).__name__}
            store.web_call_result(call_id,result)
            return result
        finally:store.close()


@router.post("/{call_id}/turn")
def send_turn(call_id: str, body: Turn, user: CurrentUser):
    _enabled()
    entry = _entry(call_id, user.id)
    runtime = entry["runtime"]
    with _lock:
        try:
            entry["tool_counts"].clear()
            usage_index=len(entry["meter"].responses)
            attempts_before=entry["meter"].calls
            event_index=len(entry["events"])
            result = runtime.run_turn(body.text)
            usage=entry["meter"].usage_since(usage_index,entry["meter"].calls-attempts_before)
            return {"call_id": call_id, "agent_text": result["agent_text"],
                    "request_at": result["request_at"], "first_token_at": result["first_token_at"],
                    "completed_at": result["completed_at"], "call_brief": runtime.brief,
                    "timeline": runtime.timeline,
                    "memory_snapshot": result["memory_snapshot"],"model_calls":entry["meter"].calls,
                    "events":entry["events"][event_index:],
                    "usage":{**usage,"cost":None,"currency":None},
                    "usage_missing_reason":None if all(value is not None for value in usage.values()) else "Provider omitted complete per-turn usage"}
        except Exception as error:
            raise HTTPException(502, f"Sandbox turn failed ({type(error).__name__}); call requires reconciliation") from None


@router.post("/{call_id}/end")
def end_call(call_id: str, user: CurrentUser):
    _enabled()
    with _lock:
        if call_id in _completed:
            if _completed[call_id]["owner"] != user.id:
                raise HTTPException(404, "Evaluation call not found")
            return _completed[call_id]["result"]
        if not any(entry["call_id"]==call_id and entry["owner"]==user.id for entry in _active.values()):
            record=_durable(call_id,user.id)
            if record and record["status"]=="COMPLETED":
                return record["payload"] or {"call_id":call_id,"status":"COMPLETED","completed":True,"barrier_complete":True}
            _entry(call_id,user.id)
        entry = _entry(call_id, user.id)
        try:
            result = entry["runtime"].end_call()
        except Exception as error:
            raise HTTPException(409, f"Call barrier is incomplete ({type(error).__name__})") from None
        result = {"call_id": call_id, "status": "COMPLETED", **result}
        try:
            from .evaluation_gaps import produce_outcome_signals
            result["outcome_signals"]=produce_outcome_signals(call_id,user.id)
        except Exception as error:
            result["outcome_signals"]={"status":"error","error_type":type(error).__name__}
        entry["store"].web_call_result(call_id,result)
        _completed[call_id] = {"owner": user.id, "result": result,"timeline":entry["runtime"].timeline,
                               "call":entry["call"],"namespace":entry["runtime"].context["namespace"]}
        entry["runtime"].close()
        entry["environment"].close()
        _active.pop(entry["runtime"].context["namespace"], None)
        return result


@router.get("/{call_id}/qa")
def get_qa_reviews(call_id: str, user: CurrentUser):
    record=_durable(call_id,user.id)
    if not record:raise HTTPException(404,"Evaluation call not found")
    store=RuntimeStore(record["namespace"],_enabled())
    try:return {"call_id":call_id,"reviews":store.qa_reviews(record["customer"],record["call"])}
    finally:store.close()


@router.get("/{call_id}/brief")
def get_brief(call_id: str, user: CurrentUser):
    _enabled()
    with _lock:
        entry=next((item for item in _active.values() if item["call_id"]==call_id and item["owner"]==user.id),None)
        if entry:
            return {"call_id":call_id,"call_brief":entry["runtime"].brief,
                    "timeline":entry["runtime"].timeline,"status":"FAILED" if entry["runtime"].failed else "OPEN"}
    record=_durable(call_id,user.id)
    if not record:raise HTTPException(404,"Evaluation call not found")
    store=RuntimeStore(record["namespace"],_enabled())
    try:
        if record["status"]=="OPEN":
            store.mark_web_call_interrupted(call_id)
            record["status"]="RECONCILIATION_REQUIRED"
        timeline=[]
        for turn,payload in store.turn_history(record["customer"],record["call"]):
            timeline.extend(({"role":"user","turn":turn,"content":payload["customer_text"]},
                             {"role":"assistant","turn":turn,"content":payload["agent_text"]}))
        return {"call_id":call_id,"call_brief":None,"timeline":timeline,"status":record["status"]}
    finally:store.close()

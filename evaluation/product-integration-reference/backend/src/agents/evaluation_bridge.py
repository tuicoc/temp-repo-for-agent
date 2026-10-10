"""Diagnostic Advisor bridge. No memory/barrier capability is claimed."""
import json
import sys
import re
import traceback
from datetime import datetime, timezone
from threading import Lock

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from .advisor import AdvisorAgent
from .pii import mask_pii
from ..config.config_manager import get_models_config


class CallMeter(BaseCallbackHandler):
    raise_error = True

    def __init__(self, maximum, full_run=False):
        if type(maximum) is not int or not 1 <= maximum <= (64 if full_run else 3):
            raise ValueError("Model budget requires explicit full-run authorization above3 (hard cap64)")
        self.maximum, self.calls = maximum, 0
        self.lock = Lock()
        self.responses = []
        self.notify = None

    def on_chat_model_start(self, *args, **kwargs):
        with self.lock:
            if self.calls >= self.maximum:
                raise RuntimeError("Diagnostic model-call budget exhausted; no retry")
            self.calls += 1
            if self.notify:
                self.notify(self.calls)

    def on_llm_end(self, response, **kwargs):
        usages = [getattr(g.message, "usage_metadata", None)
                  for batch in response.generations for g in batch if hasattr(g, "message")]
        usage = usages[0] if len(usages) == 1 else None
        self.responses.append(usage)

    def usage_since(self, index, attempts):
        values = self.responses[index:]
        complete = attempts > 0 and len(values) == attempts and all(isinstance(v, dict) and
            all(type(v.get(k)) is int and v[k] >= 0 for k in ("input_tokens", "output_tokens")) for v in values)
        return {k: sum(v[k] for v in values) if complete else None for k in ("input_tokens", "output_tokens")}


SEND_LOCK = Lock()


def send(value):
    with SEND_LOCK:
        sys.stdout.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()


def receive():
    line = sys.stdin.readline()
    if not line:
        raise EOFError("Evaluator disconnected")
    return json.loads(line)


def provider_error_details(exc):
    body=getattr(exc,"body",None)
    body=body.get("error",body) if isinstance(body,dict) else {}
    code=body.get("code") if isinstance(body,dict) else None
    if not isinstance(code,str) or not re.fullmatch(r"[\w.-]{1,80}",code):code=None
    message=body.get("message","") if isinstance(body,dict) else ""
    message = str(message) + " " + str(exc)
    hints=[token for token in ("tool_use_failed","max_tokens","tool_choice","function","schema","context_length","reasoning","json-only","no text","non-text","not found","not_found","invalid_argument","api key","quota","permission","validation","json","quote/span","duplicate/unsupported","memory value","nonfinite","sensitive id") if token in message.lower()]
    return {"status_code":getattr(exc,"status_code",None),"provider_code":code,"error_hints":hints}


def main():
    config = receive()
    meter = CallMeter(config["max_model_calls"],full_run=config.get("full_run",False))
    meter.notify = lambda calls: send({"type":"model_attempt","model_calls":calls})
    llm = get_models_config().agent_llm_config("advisor")
    llm.update(config["llm_config"])
    if llm["provider"] not in ("google_genai", "groq"):
        raise ValueError("Diagnostic bridge only supports SDKs with explicit max_retries=0")
    llm.update(max_retries=0, tracing=False, timeout=30)
    tools = []
    tool_lock = Lock()
    tool_counts = {}
    def direct_tool_function(name):
        def invoke(**args):
            # ToolNode may execute calls concurrently; IPC replies are ordered.
            with tool_lock:
                if lifecycle is not None and lifecycle.call is not None:
                    lane_tools={
                        "IDENTITY_RESOLUTION":set(),
                        "OUT_OF_SCOPE":set(),
                        "SALES":{"catalog.search","pricing.get_quote","inventory.check","crm.get_customer","schedule.callback","handoff.transfer"},
                        "CONTINUITY":{"catalog.search","pricing.get_quote","inventory.check","order.create","schedule.callback","handoff.transfer"},
                        "POST_SALE":{"crm.get_customer","order.status","order.create","inventory.check","handoff.transfer"},
                        "SCHEDULING":{"schedule.callback","handoff.transfer"},
                    }
                    if lifecycle.tier != "verified":
                        lane_tools["SALES"].discard("crm.get_customer")
                        lane_tools["SALES"].discard("schedule.callback")
                    if name not in lane_tools.get(lifecycle.lane,set()):
                        send({"type":"runtime_event","event":{"kind":"tool_lane_rejected","tool":name,"lane":lifecycle.lane}})
                        return {"error":"Tool is not available in this routed lane; do not retry it."}
                    limit = {"catalog.search":1,"pricing.get_quote":1,"inventory.check":1,
                             "crm.get_customer":1,"order.status":1,"schedule.callback":1,"order.create":1,
                             "handoff.transfer":1}.get(name, 0)
                    used = tool_counts.get(name, 0)
                    if used >= limit:
                        send({"type":"runtime_event","event":{"kind":"tool_limit_rejected","tool":name,"limit":limit,"attempt":used+1}})
                        return {"error":"Per turn lookup limit reached; explain the limitation and offer a safe handoff.","retryable":False}
                    tool_counts[name] = used + 1
                    event_index=lifecycle.tool_event_index+1
                    lifecycle.tool_event_index=event_index
                    def safe_json(value):
                        encoded=json.dumps(value,ensure_ascii=False)
                        masked,_=mask_pii(encoded)
                        return json.loads(masked)
                    base={"tool":name,"args":safe_json(args),"source":{"run_id":lifecycle.call["run_id"],"scenario_id":lifecycle.call["scenario_id"],"call":lifecycle.call["call"],"turn":lifecycle.turn,"event_index":event_index}}
                    lifecycle.store.write_business_event(lifecycle.customer_id,lifecycle.call["call"],lifecycle.turn,event_index,{**base,"outcome":"attempted"})
                try:
                    send({"type":"tool", "name":name, "args":args})
                    reply = receive()
                except Exception:
                    if lifecycle is not None and lifecycle.call is not None:
                        lifecycle.store.write_business_event(lifecycle.customer_id,lifecycle.call["call"],lifecycle.turn,event_index,{**base,"outcome":"unknown"})
                    raise
            if reply["type"] != "tool_result":
                if lifecycle is not None and lifecycle.call is not None:
                    lifecycle.store.write_business_event(lifecycle.customer_id,lifecycle.call["call"],lifecycle.turn,event_index,{**base,"outcome":"unknown"})
                raise RuntimeError("Unexpected tool protocol")
            if "error" in reply:
                if lifecycle is not None and lifecycle.call is not None:
                    lifecycle.store.write_business_event(lifecycle.customer_id,lifecycle.call["call"],lifecycle.turn,event_index,
                                                         {**base,"outcome":"unknown" if reply.get("reconciliation_required") else "business_error"})
                raise RuntimeError(reply["error"])
            if lifecycle is not None and lifecycle.call is not None:
                visible=safe_json(reply["result"])
                business_error=isinstance(visible,dict) and bool(visible.get("error"))
                lifecycle.store.write_business_event(lifecycle.customer_id,lifecycle.call["call"],lifecycle.turn,event_index,
                                                     {**base,"outcome":"business_error" if business_error else "completed","result":visible})
                if not business_error:lifecycle.tool_results.append({"tool":name,"result":visible})
                return visible
            return reply["result"]
        return invoke
    from .mcp_business import LocalMCPBusinessBus
    mcp_bus=LocalMCPBusinessBus(lambda name,args: direct_tool_function(name)(**args))
    def tool_function(name):
        def invoke(**args):
            return mcp_bus.call_tool(name,args)
        return invoke
    for spec in config["tools"]:
        tools.append(StructuredTool.from_function(tool_function(spec["name"]), name=spec["name"],
            description=spec["description"], args_schema=spec["schema"]))
    agent = AdvisorAgent(llm_config=llm, toolset=tools, strict_output=True)
    lifecycle = None
    if config.get("mode") == "lifecycle":
        from .memory import MemoryAgent
        from .call_runtime import CallRuntime
        from .runtime_store import RuntimeStore
        import os
        storage = config.get("storage", "sqlite_unit")
        if storage not in ("sqlite_unit", "postgresql"):
            raise ValueError("Unknown pinned runtime storage")
        dsn = os.environ.get("EVALUATION_DATABASE_URL") if storage == "postgresql" else None
        if storage == "postgresql" and not dsn:
            raise ValueError("Explicit evaluation PostgreSQL DSN missing; no SQLite fallback")
        store = RuntimeStore(config["context"]["namespace"], dsn)
        def business_tool(name,args):
            return tool_function(name)(**args)
        features=config.get("features",{})
        from .policy import PolicyAgent
        from .qa import QaAgent
        lifecycle = CallRuntime(config["context"],agent,MemoryAgent(llm),business_tool,
                                {"config":{"callbacks":[meter],"recursion_limit":12}},
                                emit=lambda event:send({"type":"runtime_event","event":event}), store=store,
                                policy=PolicyAgent(llm) if features.get("policy") else None,
                                qa=QaAgent(llm) if features.get("qa") else None)
    send({"type":"ready", "provider":llm["provider"], "model":llm["model"],
          "parameters":{**{k:llm.get(k) for k in ("temperature","max_tokens","timeout","max_retries","memory_output_strategy","memory_span_strategy")},
                        "runtime_storage":"postgresql" if lifecycle and lifecycle.store.postgres else "sqlite_unit",
                        "features":config.get("features",{})}})
    history = []
    while True:
        command = receive()
        if command["type"] == "close":
            if lifecycle:lifecycle.close()
            break
        if lifecycle is not None:
            if command["type"] == "turn":tool_counts.clear()
            index, attempts = len(meter.responses), meter.calls
            try:
                if command["type"] == "start_call":
                    lifecycle.context["qa_criteria"]=[criterion for criterion in config["context"].get("qa_criteria",[])
                        if criterion["id"]!="J01_opening_continuity" or int(command["context"]["call"].split("_")[1])>=2]
                    result=lifecycle.start_call(command["context"])
                elif command["type"] == "turn":result=lifecycle.run_turn(command["text"])
                elif command["type"] == "end_call":result=lifecycle.end_call()
                else:raise ValueError("Unknown lifecycle hook")
                result["usage"]={**meter.usage_since(index,meter.calls-attempts),"cost":None,"currency":None}
                send({"type":"result","result":result,"model_calls":meter.calls})
            except Exception as exc:
                frames=traceback.extract_tb(exc.__traceback__)
                location={"file":frames[-1].filename.rsplit("/",1)[-1],"line":frames[-1].lineno,"function":frames[-1].name} if frames else None
                send({"type":"error","error_type":type(exc).__name__,"model_calls":meter.calls,
                      "error_location":location,"reconciliation_required":True,**provider_error_details(exc)})
                lifecycle.close()
                break
            continue
        started = datetime.now(timezone.utc).isoformat()
        index, attempts = len(meter.responses), meter.calls
        history.append(HumanMessage(content=command["text"]))
        try:
            updates = agent.process({"messages":history,"tier":"unknown","lane":"SALES"},
                                    config={"callbacks":[meter],"recursion_limit":12})
            draft = updates["draft"]
            history.append(AIMessage(content=draft["reply"]))
            completed = datetime.now(timezone.utc).isoformat()
            send({"type":"result","agent_text":draft["reply"],"draft":draft,"mode":"nonstream",
                  "request_at":started,"completed_at":completed,"first_token_at":completed,
                  "usage":{**meter.usage_since(index,meter.calls-attempts),"cost":None,"currency":None},
                  "model_calls":meter.calls,"notice":"Diagnostic single-call working context; no cross-session memory/barrier"})
        except Exception as exc:
            # Never send provider error bodies (which may contain credentials).
            send({"type":"error","error_type":type(exc).__name__,"model_calls":meter.calls,
                  "request_at":started,"completed_at":datetime.now(timezone.utc).isoformat(),
                  "usage":meter.usage_since(index,meter.calls-attempts),"reconciliation_required":True,**provider_error_details(exc)})
            break


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        from traceback import extract_tb
        location = extract_tb(exc.__traceback__)[-1]
        send({"type":"startup_error","error_type":type(exc).__name__,
              "error_location":{"file":location.filename.rsplit("/",1)[-1],"line":location.lineno},
              "notice":"Check configured provider key/dependencies; no fallback or retry"})

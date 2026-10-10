"""P2 hook adapter for pinned product bundle; no product code imported in evaluator."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time


def read_message(process, deadline):
    buffer=getattr(process,"_evaluation_buffer",b"")
    while b"\n" not in buffer:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            if not selector.select(max(0,deadline-time.monotonic())):
                raise TimeoutError("Product message deadline exceeded; no retry")
        chunk=os.read(process.stdout.fileno(),65536)
        if not chunk:raise RuntimeError("Product child exited with missing/partial message")
        buffer+=chunk
        if len(buffer)>4*1024*1024:raise ValueError("Product message exceeds 4MiB")
    line,buffer=buffer.split(b"\n",1)
    process._evaluation_buffer=buffer
    return json.loads(line.decode("utf-8"))


def stop_process(process):
    if process is None:return
    try:process.wait(timeout=.2)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:process.wait(timeout=.3)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=.3)
    for stream in (process.stdin,process.stdout):
        if stream:stream.close()


def model_environment():
    env=dict(os.environ)
    env.pop("EVALUATION_APPROVAL_HMAC_KEY",None)
    return env


def backend_env_path(python):
    path=Path(python)
    if path.parts[-3:] != (".venv","bin","python"):
        raise ValueError("Product Python must be the backend venv executable")
    return path.parents[2]/".env"


def customer_visible(value):
    """Hide evaluator/internal fields from the LLM while raw tool events retain them."""
    if isinstance(value, dict):
        hidden_terms=("internal","supplier_cost","margin","floor","cost_price","cost_vnd","wholesale","secret")
        return {key:customer_visible(item) for key,item in value.items()
                if not key.startswith("_") and not any(term in key.lower() for term in hidden_terms)}
    if isinstance(value, list):
        return [customer_visible(item) for item in value]
    if isinstance(value,str):
        for pattern in (re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])",re.I),
                        re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .()-]*\d){8,10}(?!\d)"),
                        re.compile(r"(?<!\d)\d{12}(?!\d)"),re.compile(r"(?<!\d)\d{16,19}(?!\d)")):
            value=pattern.sub(lambda match:"█"*len(match.group(0)),value)
    return value


class ProductAdapter:
    capabilities = ("business_tools","memory_isolation","memory_read_gate","after_call_barrier",
                    "snapshots","briefs","timestamps","usage")
    retry = {"agent":0,"tool":0}

    def __init__(self):
        self.process=None
        def stop(signum, frame):
            stop_process(self.process)
            raise SystemExit("Product adapter interrupted")
        signal.signal(signal.SIGTERM,stop)

    def receive(self, timeout=60):
        deadline=time.monotonic()+timeout
        while True:
            msg=read_message(self.process,deadline)
            if msg["type"]=="tool":
                try:
                    result=self.runtime["call_tool"](msg["name"],msg["args"])
                    self.send({"type":"tool_result","result":customer_visible(result)})
                except Exception as exc:
                    self.send({"type":"tool_result","error":"Tool rejected/failed; no retry",
                               "reconciliation_required":bool(getattr(exc,"reconciliation_required",False))})
            elif msg["type"]=="model_attempt":
                self.runtime["emit"]({"kind":"product_model_attempt","model_calls":msg["model_calls"]})
            elif msg["type"]=="runtime_event":
                self.runtime["emit"](msg["event"])
            elif msg["type"] in ("error","startup_error"):
                self.runtime["emit"]({"kind":"product_provider_error",**{k:msg.get(k) for k in ("error_type","error_location","status_code","provider_code","error_hints","model_calls")}})
                location=msg.get("error_location") or {}
                suffix=f" at {location.get('file')}:{location.get('line')}" if location else ""
                raise RuntimeError("Product hook failed: "+msg["error_type"]+suffix)
            else:return msg

    def send(self, obj):
        self.process.stdin.write((json.dumps(obj,ensure_ascii=False)+"\n").encode("utf-8"))
        self.process.stdin.flush()

    def open_scenario(self, context):
        self.runtime=context
        root=Path(__file__).resolve().parent
        bundle=json.loads((root/"product-bundle.json").read_text())
        for ref in bundle["files"]:
            path=(root/ref["path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=ref["sha256"]:
                raise ValueError("Product bundle hash/path mismatch")
        # No original product files, secrets or deployment DB are copied/imported.
        # The pinned snapshot excludes .env; read credentials only in the child process.
        env_path=backend_env_path(bundle["python"])
        bootstrap=("from dotenv import load_dotenv; import runpy; "
                   "load_dotenv("+repr(str(env_path))+",override=False); "
                   "runpy.run_module('src.agents.evaluation_bridge',run_name='__main__')")
        self.process=subprocess.Popen([bundle["python"],"-B","-c",bootstrap],
            cwd=root/"product",stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,env=model_environment())
        safe_context={k:context[k] for k in ("run_id","config","scenario_id","namespace","seed_history")}
        safe_context["resources"]=context["resources"]
        if bundle.get("features",{}).get("qa"):
            safe_context["qa_criteria"]=[criterion for criterion in bundle.get("qa_criteria",[])
                                         if criterion["applies_to"]=="all" or criterion["id"]=="J01_opening_continuity"]
        self.send({"mode":"lifecycle","context":safe_context,"tools":bundle["tools"],
                   "features":bundle.get("features",{}),
                   "storage":bundle.get("storage","sqlite_unit"),
                   "max_model_calls":bundle["max_model_calls"],"full_run":bundle.get("full_run",False),"llm_config":bundle["llm_config"]})
        msg=self.receive()
        if msg["type"]!="ready":raise ValueError("Product handshake failed")
        loaded={"provider":msg["provider"],**msg["parameters"]}
        if msg["model"]!=context["configuration"]["model"] or any(loaded.get(k)!=v for k,v in context["configuration"]["parameters"].items()):
            raise ValueError("Loaded product model/parameters differ from manifest")

    def start_call(self, context):
        self.send({"type":"start_call","context":context})
        return self.receive()["result"]

    def run_turn(self, text):
        self.send({"type":"turn","text":text})
        return self.receive()["result"]

    def end_call(self):
        self.send({"type":"end_call"})
        return self.receive()["result"]

    def close_scenario(self):
        if self.process:
            if self.process.poll() is None:
                try:self.send({"type":"close"})
                except OSError:pass
            stop_process(self.process)


def factory():
    return ProductAdapter()

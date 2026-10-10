"""P2 hook adapter for the team's agent.

The harness binds this file and calls its five hooks. No product code is imported
here: the agent runs in its own process, ``backend/src/pipeline/eval/bridge.py``
under the backend's virtualenv, and the two talk JSON lines over a pipe.

Every business tool the agent calls comes back through this adapter to the
harness's ``call_tool``, the harness's own copy of the organisers' mock, which
records the call and the state it changed. Nothing is retried, here or in the
agent (``retry`` below is what the harness checks; the bridge builds the agent
with retries off).

``product-bundle.json``, written by ``product.prepare`` beside this file,
names the backend and its interpreter and holds a hash of the agent's code:
a run refuses to start if the code changed after preparation.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

#: What the agent is made of: hashed at preparation, checked at every start.
TREE = ("src", "config")
SUFFIXES = (".py", ".yaml", ".yml", ".json")


def tree_sha256(backend):
    digest = hashlib.sha256()
    for top in TREE:
        for path in sorted((Path(backend) / top).rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES and "__pycache__" not in path.parts:
                digest.update(str(path.relative_to(backend)).encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def read_message(process, deadline):
    buffer = getattr(process, "_evaluation_buffer", b"")
    while b"\n" not in buffer:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(max(0, deadline - time.monotonic())):
                raise TimeoutError("Product message deadline exceeded; no retry")
        chunk = os.read(process.stdout.fileno(), 65536)
        if not chunk:
            raise RuntimeError("Product child exited with missing/partial message")
        buffer += chunk
        if len(buffer) > 4 * 1024 * 1024:
            raise ValueError("Product message exceeds 4MiB")
    line, buffer = buffer.split(b"\n", 1)
    process._evaluation_buffer = buffer
    return json.loads(line.decode("utf-8"))


def stop_process(process):
    if process is None:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in (process.stdin, process.stdout):
        if stream:
            stream.close()


def model_environment():
    env = dict(os.environ)
    env.pop("EVALUATION_APPROVAL_HMAC_KEY", None)
    env["MCP_TRANSPORT"] = "stdio"
    return env


class ProductAdapter:
    capabilities = ("business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                    "snapshots", "briefs", "timestamps", "usage")
    retry = {"agent": 0, "tool": 0}

    #: Seconds a hook may take: starting five MCP servers, or a turn waiting on the provider's rate limit.
    TIMEOUT = 300

    def __init__(self):
        self.process = None
        self.runtime = None

        def stop(signum, frame):
            stop_process(self.process)
            raise SystemExit("Product adapter interrupted")
        signal.signal(signal.SIGTERM, stop)

    def send(self, obj):
        self.process.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def receive(self):
        deadline = time.monotonic() + self.TIMEOUT
        while True:
            message = read_message(self.process, deadline)
            kind = message.get("type")
            if kind == "tool":
                try:
                    result = self.runtime["call_tool"](message["name"], message["args"])
                    self.send({"type": "tool_result", "result": result})
                except Exception as exception:
                    self.send({"type": "tool_result", "error": f"{type(exception).__name__}: {exception}",
                               "reconciliation_required": type(exception).__name__ == "ToolOutcomeUnknown"})
            elif kind == "event":
                self.runtime["emit"](message["event"])
            elif kind == "error":
                raise RuntimeError(f"Product failed: {message.get('error_type')}: {message.get('message')}")
            else:
                return message

    def open_scenario(self, context):
        self.runtime = context
        bundle = json.loads((Path(__file__).resolve().parent / "product-bundle.json").read_text(encoding="utf-8"))
        if tree_sha256(bundle["backend"]) != bundle["tree_sha256"]:
            raise ValueError("The agent's code changed after preparation; prepare a new run")
        self.process = subprocess.Popen(
            [bundle["python"], "-B", "-m", "src.pipeline.eval.bridge"], cwd=bundle["backend"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0, env=model_environment(),
        )
        safe = {k: context[k] for k in ("run_id", "config", "scenario_id", "namespace", "seed_history")}
        self.send({"mode": "lifecycle", "context": safe, "llm": bundle["llm"]})
        ready = self.receive()
        if ready.get("type") != "ready":
            raise ValueError("Product handshake failed")
        expected = context["configuration"]
        if ready["model"] != expected["model"] or ready["parameters"] != expected["parameters"]:
            raise ValueError("Loaded model or parameters differ from the manifest")

    def start_call(self, context):
        self.send({"type": "start_call", "context": context})
        return self.receive()["result"]

    def run_turn(self, text):
        self.send({"type": "turn", "text": text})
        return self.receive()["result"]

    def end_call(self):
        self.send({"type": "end_call"})
        return self.receive()["result"]

    def close_scenario(self):
        if self.process:
            if self.process.poll() is None:
                try:
                    self.send({"type": "close"})
                except OSError:
                    pass
            stop_process(self.process)


def factory():
    return ProductAdapter()

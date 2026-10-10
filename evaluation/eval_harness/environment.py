"""One spawned BTC worker per scenario/config; trusted evaluator interface only."""
import copy
from datetime import date, datetime, timezone
import importlib.util
import inspect
import multiprocessing
import os
import sys
import time

from .contracts import ROOT, checker, validate

STATE = ("_ORDERS", "_CALLBACKS", "_TICKETS", "_ONCE_USED")


def _state(module):
    return copy.deepcopy({name: sorted(getattr(module, name)) if name == "_ONCE_USED"
                          else getattr(module, name) for name in STATE})


def _visible(result, config):
    result = copy.deepcopy(result)
    if config == "baseline_no_memory" and isinstance(result, dict):
        if "sessions" in result:
            result["sessions"] = []
        for candidate in result.get("candidates", []):
            if "sessions" in candidate:
                candidate["sessions"] = []
    return result


def _worker(connection, config):
    sys.dont_write_bytecode = True
    try:
        checker.verify_sources()
        spec = importlib.util.spec_from_file_location("isolated_btc_mock", ROOT / "sources/btc/eval/mock_tools.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Seed once. Function globals/indexes remain coherent inside this worker.
        for name in ("PRODUCTS", "PROMOS", "CRM", "INV") + STATE:
            setattr(module, name, copy.deepcopy(getattr(module, name)))
        module._BY_SKU = {p["sku"]: p for p in module.PRODUCTS}
        module._VAR = {v["variant_sku"]: (p, v) for p in module.PRODUCTS for v in p["variants"]}
        connection.send({"ready": True, "pid": os.getpid()})
        while True:
            command = connection.recv()
            if command["op"] == "close":
                break
            if command["op"] == "snapshot":
                connection.send({"state": _state(module)})
                continue
            try:
                request, context, on = command["request"], command["context"], command["on"]
                validate("ToolArgs", request)
                function = module.TOOLS[request["name"]]
                args = copy.deepcopy(request["args"])
                signature = inspect.signature(function)
                if "on" in signature.parameters:
                    if "on" in args and args["on"] != on:
                        raise ValueError("Request on differs from planned call date")
                    args["on"] = on
                signature.bind(**args)  # Reject unsupported kwargs; never silently drop them.
                before, started = _state(module), datetime.now(timezone.utc).isoformat()
                clock = time.monotonic()
                outcome, error = "success", None
                try:
                    result = function(**args)
                    if isinstance(result, dict) and "error" in result:
                        outcome = "business_error"
                        error = {"code": str(result["error"]), "message": "BTC mock business error"}
                except Exception as exception:
                    result, outcome = None, "transport_error"
                    error = {"code": type(exception).__name__, "message": str(exception)}
                elapsed, finished, after = (time.monotonic() - clock) * 1000, datetime.now(timezone.utc).isoformat(), _state(module)
                event = {"schema_version": "1.0.0", "artifact_id": command["event_id"],
                         "run_id": context["run_id"], "context": context, "evidence_refs": [],
                         "event_id": command["event_id"], "request": request, "on": on,
                         "started_at": started, "finished_at": finished, "outcome": outcome,
                         "result": copy.deepcopy(result), "error": error,
                         "side_effect": before != after, "attempt": 1}
                validate("ToolEvent", event)
                visible = _visible(result, config) if request["name"] == "crm.get_customer" else copy.deepcopy(result)
                connection.send({"event": event, "visible_result": visible, "effective_args": args,
                                 "state_before": before, "state_after": after, "elapsed_ms": elapsed})
            except (ValueError, TypeError, KeyError) as exception:
                connection.send({"rejected": str(exception), "raw_request": command.get("request")})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exception:
        connection.send({"startup_error": f"{type(exception).__name__}: {exception}"})
    finally:
        connection.close()


class MockEnvironment:
    """call_tool returns only access-filtered data; events/audit are evaluator-only.

    No ledger/brief/cache routes exist here. Runtime P2 must gate those separately.
    On timeout the worker is killed, with unknown side effects; no retry/restart.
    """
    def __init__(self, run_id, scenario_id, config, *, timeout=30):
        if config not in ("full", "baseline_no_memory") or not run_id or not scenario_id or timeout <= 0:
            raise ValueError("Invalid worker identity/config/timeout")
        checker.verify_sources()
        self.run_id, self.scenario_id, self.config = run_id, scenario_id, config
        self.timeout, self.events, self.audit, self.failures = timeout, [], [], []
        self.closed = False
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_worker, args=(child, config))
        self.process.start()
        child.close()
        ready = self._receive()
        if not ready.get("ready"):
            self.close()
            raise RuntimeError(ready)
        self.pid = ready["pid"]

    def _receive(self):
        if not self.connection.poll(self.timeout):
            self.failures.append({"code": "WORKER_TIMEOUT", "reconciliation_required": True,
                                  "message": "Side effects unknown; worker terminated without retry"})
            self.close()
            raise TimeoutError("BTC worker timeout; reconciliation required")
        try:
            return self.connection.recv()
        except EOFError as exception:
            self.close()
            raise RuntimeError("BTC worker exited without evidence") from exception

    def _send(self, message):
        if self.closed:
            raise RuntimeError("Worker is closed; never restart after timeout")
        self.connection.send(message)
        return self._receive()

    def call_tool(self, name, args, *, call, turn, on):
        if date.fromisoformat(on).isoformat() != on:
            raise ValueError("on must be YYYY-MM-DD")
        context = {"run_id": self.run_id, "config": self.config, "scenario_id": self.scenario_id,
                   "call": call, "turn": turn}
        validate("Context", context)
        request = {"name": name, "args": copy.deepcopy(args)}
        event_id = f"{self.run_id}/{self.config}/{self.scenario_id}/{call}/{turn}/{len(self.audit)+1}"
        raw = {"op": "invoke", "request": request, "context": context, "on": on, "event_id": event_id}
        self.audit.append({"raw_request": copy.deepcopy(raw)})  # Before validation/execution.
        response = self._send(raw)
        self.audit[-1].update(response)
        if "rejected" in response:
            raise ValueError(response["rejected"])
        if "event" not in response:
            raise RuntimeError(response)
        self.events.append(response["event"])
        return copy.deepcopy(response["visible_result"])

    def snapshot(self):
        return self._send({"op": "snapshot"})["state"]

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.is_alive():
            try:
                self.connection.send({"op": "close"})
            except (BrokenPipeError, OSError):
                pass
            self.process.join(timeout=0.2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
        self.connection.close()
        self.process.join(timeout=2)
        self.process.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

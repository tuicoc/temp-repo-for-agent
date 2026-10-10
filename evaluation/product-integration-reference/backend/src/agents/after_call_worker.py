"""Recover interrupted sandbox after-call jobs without touching production data."""
import os
import logging

from .call_runtime import CallRuntime
from .evaluation_bridge import CallMeter
from .memory import MemoryAgent
from .runtime_store import RuntimeStore

logger=logging.getLogger(__name__)


def recover_one(store, customer, call, memory, options=None):
    runtime=CallRuntime.resume_persist_job(store,customer,call,memory,options)
    return runtime.end_call()


def poll_once(dsn, *, limit=10):
    index=RuntimeStore("after-call-worker-index",dsn)
    try:
        jobs=index.recoverable_web_jobs(limit)
    finally:
        index.close()
    results=[]
    for job in jobs:
        store=RuntimeStore(job["namespace"],dsn)
        try:
            saved=store.call_record(job["customer"],job["call"])
            if not saved or not store.has_model_budget(job["customer"],job["call"]):
                store.set_job_status(job["customer"],job["call"],"persist","FAILED")
                store.fail(job["customer"],job["call"])
                results.append({**job,"status":"RECONCILIATION_REQUIRED","reason":"Missing pinned budget"})
                continue
            pin=saved["context"].get("model_pin") or {}
            budget=saved["context"].get("model_call_budget")
            if pin.get("provider") not in ("google_genai","groq") or type(budget) is not int or not 1<=budget<=12:
                store.set_job_status(job["customer"],job["call"],"persist","FAILED")
                store.fail(job["customer"],job["call"])
                results.append({**job,"status":"RECONCILIATION_REQUIRED","reason":"Invalid model pin/budget"})
                continue
            meter=CallMeter(budget,full_run=True)
            meter.calls=store.model_attempt_count(job["customer"],job["call"])
            meter.notify=lambda _count, s=store, j=job, b=budget: s.claim_model_attempt(j["customer"],j["call"],b)
            memory=MemoryAgent({**pin,"max_retries":0})
            try:
                result=recover_one(store,job["customer"],job["call"],memory,
                                   {"config":{"callbacks":[meter],"recursion_limit":12}})
            except RuntimeError as exc:
                if "already running" in str(exc):
                    results.append({**job,"status":"BUSY"})
                    continue
                raise
            row=store.execute("SELECT call_id FROM web_calls WHERE namespace=? AND customer=? AND call=?",
                              (job["namespace"],job["customer"],job["call"])).fetchone()
            if row:
                store.web_call_result(row[0],{"call_id":row[0],"status":"COMPLETED",**result})
            results.append({**job,"status":"COMPLETED"})
        except Exception as exc:
            if store.job_status(job["customer"],job["call"],"persist")!="COMPLETED":
                store.set_job_status(job["customer"],job["call"],"persist","FAILED")
                store.fail(job["customer"],job["call"])
            results.append({**job,"status":"FAILED","error_type":type(exc).__name__})
        finally:
            store.close()
    return results


def run_forever(dsn, stop):
    while not stop.is_set():
        try:
            for result in poll_once(dsn):
                if result["status"] not in ("COMPLETED","BUSY"):
                    logger.error("After-call recovery %s (%s)",result["status"],result.get("error_type",result.get("reason","unknown")))
        except Exception as exc:
            logger.error("After-call worker poll failed (%s)",type(exc).__name__)
        stop.wait(5)


def main():
    import threading
    if os.environ.get("EVALUATION_WEB_CALLS_ENABLED")!="1" or not os.environ.get("EVALUATION_DATABASE_URL"):
        raise RuntimeError("Explicit sandbox DB and web-call enablement required")
    run_forever(os.environ["EVALUATION_DATABASE_URL"],threading.Event())


if __name__=="__main__":
    main()

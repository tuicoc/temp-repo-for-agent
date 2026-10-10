"""Run the 60 BTC RAG questions against local sandbox PostgreSQL and one real model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from eval_harness.assets import Assets, parse_json, read_json
from eval_harness.contracts import ROOT
from eval_harness.datasets import close_output
from eval_harness.m2_metrics import rag_report
from eval_harness.rag_corpus import chunk_catalog, postgres_search
from eval_harness.rag_runner import answer_questions
from eval_harness.runner import _write
from product_smoke import PRODUCT


def run(out, provider, model, maximum, resume=None, question_limit=60):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    if type(maximum) is not int or not 0<=maximum<=100:
        raise ValueError("Explicit RAG model-attempt cap 0–100 required")
    dsn=os.environ.get("EVALUATION_DATABASE_URL")
    settings=conninfo_to_dict(dsn or "")
    if settings.get("host") not in ("127.0.0.1","localhost","::1") or settings.get("port")!="55433" or settings.get("dbname")!="agent_eval_dev":
        raise ValueError("Only local evaluation PostgreSQL is permitted")
    out=Path(out).absolute()
    if out.exists():raise ValueError("RAG output must be a new directory")
    qa_path=ROOT/"sources/btc/rag/qa_labeled.json"
    qa=read_json(qa_path)["questions"]
    if len(qa)!=60 or type(question_limit) is not int or not 1<=question_limit<=60:
        raise ValueError("Pinned BTC RAG set requires 60 questions and bounded prefix")
    selected=qa[:question_limit]
    catalog=chunk_catalog()
    source=Assets(ROOT).ref("sources/btc/rag/qa_labeled.json")
    corpus=[catalog[key]["source_ref"] for key in sorted(catalog)]
    prior={}
    if resume is not None:
        previous=Assets(resume)
        previous_manifest=read_json(previous.path("manifest.json"))
        if any(previous_manifest[key]!=value for key,value in (("provider",provider),("model",model),
                                                                ("source",source),("corpus",corpus))):
            raise ValueError("RAG resume changes model or source controls")
        attempts=read_json(previous.path("attempts.json"))
        prior={row["qid"]:row for row in attempts if isinstance(row.get("raw"),str)}
        if len(prior)!=len([row for row in attempts if isinstance(row.get("raw"),str)]):
            raise ValueError("Duplicate prior RAG attempts")
    if len(selected)-len(prior)>maximum:
        raise ValueError("Remaining RAG questions exceed new attempt cap")
    out.mkdir(parents=True,mode=0o700)
    python=PRODUCT/".venv/bin/python"
    command=("import json; from src.config.config_manager import get_models_config; "
             "print(json.dumps(get_models_config().llm_config("+repr(provider)+","+repr(model)+")))")
    config=parse_json(subprocess.run([str(python),"-B","-c",command],cwd=PRODUCT,
                                     capture_output=True,text=True,timeout=15,check=True).stdout)
    config.update(temperature=0,max_retries=0,tracing=False,timeout=30,max_tokens=1024)
    _write(out/"manifest.json",{"kind":"m2-rag-diagnostic-v1","provider":provider,"model":model,
                                  "max_model_attempts":maximum,"source":source,"corpus":corpus,
                                  "reused_from":str(Path(resume).absolute()) if resume else None,
                                  "planned_qids":[q["qid"] for q in selected],
                                  "producer_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                  "retriever_sha256":hashlib.sha256((Path(__file__).parent/"eval_harness/rag_corpus.py").read_bytes()).hexdigest(),
                                  "answer_runner_sha256":hashlib.sha256((Path(__file__).parent/"eval_harness/rag_runner.py").read_bytes()).hexdigest(),
                                  "model_adapter_sha256":hashlib.sha256((PRODUCT/"src/agents/evaluation_model.py").read_bytes()).hexdigest(),
                                  "notice":"Synthetic BTC questions; retrieval+answer diagnostic, not M2 acceptance"})
    receipts=[]
    def invoke(prompt):
        if provider=="groq" and receipts:
            time.sleep(30)  # Groq sandbox quota is 6k input/1k output tokens per minute.
        payload=json.dumps({"config":config,"prompt":prompt},ensure_ascii=False)
        try:
            process=subprocess.run([str(python),"-B","-m","src.agents.evaluation_model"],cwd=PRODUCT,
                                   input=payload,text=True,capture_output=True,timeout=75)
        except subprocess.TimeoutExpired:
            receipts.append({"error_type":"TimeoutExpired","usage":None,"reconciliation_required":True})
            raise
        response=parse_json(process.stdout)
        receipts.append({"error_type":response.get("error_type"),"status_code":response.get("status_code"),
                         "provider_code":response.get("provider_code"),"error_hints":response.get("error_hints",[]),
                         "usage":response.get("usage"),"reconciliation_required":process.returncode!=0})
        if process.returncode!=0 or response.get("model_calls")!=1 or not isinstance(response.get("raw"),str):
            raise ValueError("RAG provider failed; no retry")
        return response["raw"]
    with psycopg.connect(dsn,autocommit=True,connect_timeout=5) as db:
        with db.cursor() as cursor:
            cursor.execute("SET default_transaction_read_only = on")
            produced=answer_questions(selected,catalog,lambda question:postgres_search(cursor,catalog,question,limit=5),
                                      invoke,maximum=maximum,prior=prior)
    _write(out/"rag-results.json",produced["results"])
    _write(out/"attempts.json",produced["attempts"])
    _write(out/"receipts.json",receipts)
    _write(out/"rag-report.json",rag_report(qa_path,out/"rag-results.json"))
    close_output(out)
    return {"complete":produced["complete"] and question_limit==60,"new_model_attempts":len(receipts),
            "reused_attempts":len(prior),"answered":len(produced["results"]),"planned":question_limit,
            "output":str(out)}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True)
    parser.add_argument("--provider",required=True,choices=("google_genai","groq"))
    parser.add_argument("--model",required=True)
    parser.add_argument("--max-model-attempts",required=True,type=int)
    parser.add_argument("--resume",help="Closed previous RAG diagnostic with identical model/corpus")
    parser.add_argument("--question-limit",type=int,default=60,help="Diagnostic first N BTC qids; default 60")
    args=parser.parse_args()
    print(json.dumps(run(args.out,args.provider,args.model,args.max_model_attempts,args.resume,args.question_limit),ensure_ascii=False))

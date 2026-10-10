"""QA-reviewed, source-backed Knowledge Gap candidates for the local sandbox."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import unicodedata
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agents.pii import contains_pii
from ..agents.runtime_store import RuntimeStore
from . import evaluation_calls
from .auth import CurrentUser

router=APIRouter(prefix="/api/evaluation-gaps",tags=["evaluation-gap-loop"])
NAMESPACE="evaluation/knowledge-gap-loop"
ALLOWED_SOURCES={"policy/faq.md","policy/chinh-sach-doi-tra.md","policy/chinh-sach-bao-hanh.md",
                 "policy/chinh-sach-van-chuyen-thanh-toan.md","policy/dieu-khoan-khuyen-mai.md",
                 "policy/spec-gia-dung.md","policy/playbook-telesale.md"}


class Signal(BaseModel):
    call_id:str
    question:str=Field(min_length=4,max_length=500)
    intent:str=Field(min_length=2,max_length=80)
    signal_kind:str=Field(pattern="^(customer_repeat|out_of_scope|outcome|qa_feedback)$")
    turn:int|None=Field(default=None,ge=1)
    note:str=Field(default="",max_length=1000)


class CandidateEdit(BaseModel):
    answer:str=Field(min_length=10,max_length=3000)
    source_path:str
    source_excerpt:str=Field(min_length=10,max_length=2000)


class Decision(BaseModel):
    reason:str=Field(min_length=3,max_length=1000)


class CompareRound(BaseModel):
    r0_call_id:str
    r1_call_id:str


class PairRun(BaseModel):
    candidate_id:str=Field(min_length=1,max_length=80)
    turns:list[str]=Field(min_length=1,max_length=12)
    model_call_budget:int=Field(default=3,ge=1,le=12)


def _store():
    dsn=evaluation_calls._enabled()
    return RuntimeStore(NAMESPACE,dsn)


def _reviewer(user):
    configured={item.strip().lower() for item in os.environ.get("EVALUATION_QA_REVIEWERS","").split(",") if item.strip()}
    if not configured and os.environ.get("EVALUATION_WEB_CALLS_ENABLED")=="1":
        from .settings import get_settings
        owner=(get_settings().seed_user_email or "").strip().lower()
        if owner:configured={owner}
    if user.email.lower() not in configured:
        raise HTTPException(403,"QA reviewer role is required")
    return user.email.lower()


def _signing_key():
    if key:=os.environ.get("EVALUATION_APPROVAL_HMAC_KEY"):
        return key
    if os.environ.get("EVALUATION_WEB_CALLS_ENABLED")=="1":
        from .settings import get_settings
        secret=get_settings().jwt_secret
        if secret:
            return hmac.new(secret.encode(),b"sudo-evaluation-knowledge-gap-approval-v1",hashlib.sha256).hexdigest()
    return None


def _source(source_path):
    if source_path not in ALLOWED_SOURCES:
        raise HTTPException(422,"Source is not on the public FAQ allowlist")
    root=evaluation_calls._workspace()/"evaluation/evaluation-contracts"
    base=(root/"sources/btc").resolve()
    path=(base/source_path).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(422,"Pinned source is unavailable")
    lock=json.loads((root/"sources.lock.json").read_text())
    relative="sources/btc/"+source_path
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=lock.get("files",{}).get(relative):
        raise HTTPException(409,"Pinned source hash changed; create a new evaluation revision")
    return path,content.decode("utf-8")


def normalize_question(question):
    folded=unicodedata.normalize("NFKC",question).casefold()
    return " ".join(re.findall(r"[\w]+",folded,flags=re.UNICODE))


def _content_hash(candidate):
    content={key:candidate.get(key) for key in ("question","intent","answer","source_path","source_excerpt")}
    raw=json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_approval(candidate):
    approval=candidate.get("approval")
    key=_signing_key()
    if not key or candidate.get("status")!="APPROVED" or not isinstance(approval,dict):return False
    if candidate.get("content_hash")!=_content_hash(candidate) or approval.get("content_hash")!=candidate.get("content_hash"):
        return False
    unsigned={name:value for name,value in approval.items() if name!="signature"}
    raw=json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    expected=hmac.new(key.encode(),raw.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,str(approval.get("signature",""))):return False
    try:
        path,source=_source(candidate["source_path"])
    except Exception:return False
    return hashlib.sha256(path.read_bytes()).hexdigest()==candidate.get("source_hash") and candidate.get("source_excerpt") in source


def _call_evidence(call_id,user_id,turn):
    with evaluation_calls._lock:
        entry=next((item for item in evaluation_calls._active.values()
                    if item["call_id"]==call_id and item["owner"]==user_id),None)
        if entry:
            raise HTTPException(409,"QA signals require a completed call")
        else:
            item=evaluation_calls._completed.get(call_id)
            if item and item["owner"]==user_id:
                timeline=item["timeline"]
                call=item["call"]
                namespace=item["namespace"]
            else:
                record=evaluation_calls._durable(call_id,user_id)
                if not record or record["status"]!="COMPLETED":
                    raise HTTPException(404,"Completed sandbox call not found")
                source=RuntimeStore(record["namespace"],evaluation_calls._enabled())
                try:
                    saved=source.call_record(record["customer"],record["call"])
                    if not saved or saved["status"]!="COMPLETED":
                        raise HTTPException(409,"Call evidence is not committed")
                    timeline=[{"role":"user","turn":number,"content":payload["customer_text"]}
                              for number,payload in source.turn_history(record["customer"],record["call"])]
                    call=saved["context"]
                    namespace=record["namespace"]
                finally:source.close()
    user_turns=[message for message in timeline if message.get("role")=="user"]
    selected=next((message for message in user_turns if message.get("turn")==turn),None) if turn else None
    if turn is not None and selected is None:
        raise HTTPException(422,"Requested customer turn is not present in this call")
    if selected is None:
        selected=next((message for message in reversed(user_turns)
                       if normalize_question(message["content"])),None)
    if selected is None:
        raise HTTPException(422,"No customer turn is available as evidence")
    return selected,call,namespace


def _record_signal(store,signal):
    normalized=normalize_question(signal["question"])
    if not normalized or any(contains_pii(str(signal.get(key,""))) for key in ("question","quote","intent","note")):
        raise HTTPException(422,"Signal evidence must be normalized and free of personal identifiers")
    intent=signal["intent"].strip().casefold()
    with store.transaction():
        if store.postgres:
            store.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))",(NAMESPACE+normalized+intent,))
        candidate=next((item for item in store.list_gap_candidates()
                        if item["question_norm"]==normalized and item["intent"]==intent),None)
        if candidate is None:
            candidate={"candidate_id":"GAP-"+uuid.uuid4().hex[:12],"question":signal["question"],
                       "question_norm":normalized,"intent":intent,"answer":"","source_path":"",
                       "source_excerpt":"","source_hash":"","signals":[],"approval":None,"status":"OPEN","version":1}
        if not any(item["signal_id"]==signal["signal_id"] for item in candidate["signals"]):
            candidate["signals"].append(signal)
            candidate["content_hash"]=_content_hash(candidate)
            store.save_gap_candidate(candidate)
            store.append_gap_event(str(uuid.uuid4()),candidate["candidate_id"],
                                   {"action":"signal_added","signal":signal,"content_hash":candidate["content_hash"]})
    return {"candidate_id":candidate["candidate_id"],"status":candidate["status"],
            "signal_count":len(candidate["signals"]),"content_hash":candidate["content_hash"]}


@router.post("/signals",status_code=201)
def submit_signal(body:Signal,user:CurrentUser):
    reviewer=_reviewer(user)
    store=_store()
    try:
        normalized=normalize_question(body.question)
        if not normalized or contains_pii(body.question) or contains_pii(body.intent) or contains_pii(body.note):
            raise HTTPException(422,"Question must be normalized and free of personal identifiers")
        selected,call,namespace=_call_evidence(body.call_id,user.id,body.turn)
        if normalized not in normalize_question(selected["content"]):
            raise HTTPException(422,"Question must be supported by a customer turn in this call")
        quote=selected["content"]
        if contains_pii(quote):
            raise HTTPException(422,"Customer turn contains PII and cannot be copied into a review artifact")
        signal={"signal_id":str(uuid.uuid4()),"call_id":body.call_id,"run_id":call["run_id"],
                "scenario_id":call["scenario_id"],"call":call["call"],"turn":selected["turn"],
                "question":body.question,"quote":quote,"intent":body.intent.strip(),
                "signal_kind":body.signal_kind,"note":body.note,"submitted_by":reviewer,
                "created_at":datetime.now(timezone.utc).isoformat()}
        return _record_signal(store,signal)
    finally:store.close()


def produce_outcome_signals(call_id,owner):
    record=evaluation_calls._durable(call_id,owner)
    if not record or record["status"]!="COMPLETED":
        raise HTTPException(409,"Outcome producer requires a completed call")
    source=RuntimeStore(record["namespace"],evaluation_calls._enabled())
    queue=_store()
    try:
        saved=source.call_record(record["customer"],record["call"])
        turns=source.turn_history(record["customer"],record["call"])
        events=source.business_events(record["customer"],record["call"])
        if not saved or saved["status"]!="COMPLETED":raise HTTPException(409,"Call evidence is not committed")
        call=saved["context"]
        by_turn={number:payload["customer_text"] for number,payload in turns}
        signals=[]
        seen={}
        def add(kind,intent,turn,quote,note,ref=None):
            if not quote or contains_pii(quote):return
            question=quote[:500]
            signal_id=str(uuid.uuid5(uuid.NAMESPACE_URL,
                f"{call_id}/{kind}/{turn}/{json.dumps(ref,sort_keys=True) if ref else ''}"))
            signals.append({"signal_id":signal_id,"call_id":call_id,"run_id":call["run_id"],
                            "scenario_id":call["scenario_id"],"call":record["call"],"turn":turn,
                            "question":question,"quote":quote,"intent":intent,"signal_kind":kind,
                            "note":note,"tool_event_ref":ref,"submitted_by":"rule-producer-v1",
                            "created_at":datetime.now(timezone.utc).isoformat()})
        for number,payload in turns:
            text=payload["customer_text"]
            normalized=normalize_question(text)
            if normalized in seen and len(normalized)>=8:
                add("customer_repeat","repeated_question",number,text,"Same normalized customer question appeared earlier")
            seen[normalized]=number
            if any(term in text.casefold() for term in ("dự báo thời tiết","chứng khoán","bóng đá","viết code","bài tập toán")):
                add("out_of_scope","out_of_scope",number,text,"Deterministic out-of-scope route")
        outcomes={"order.create":("order_id","order_outcome"),"schedule.callback":("callback_id","callback_outcome"),
                  "handoff.transfer":("ticket_id","handoff_outcome")}
        for event in events:
            tool=event.get("tool")
            if tool not in outcomes or event.get("outcome")!="completed":continue
            key,intent=outcomes[tool]
            result=event.get("result",{})
            if not isinstance(result,dict) or result.get("error") or not result.get(key):continue
            src=event.get("source",{})
            turn=src.get("turn")
            quote=by_turn.get(turn,"")
            ref={"call":record["call"],"turn":turn,"event_index":src.get("event_index"),"tool":tool}
            add("outcome",intent,turn,quote,f"Verified {tool} completion",ref)
        for signal in signals:_record_signal(queue,signal)
        return {"status":"complete","signal_count":len(signals),"signal_ids":[item["signal_id"] for item in signals]}
    finally:queue.close();source.close()


@router.post("/produce/{call_id}")
def produce_for_qa(call_id:str,user:CurrentUser):
    _reviewer(user)
    result=produce_outcome_signals(call_id,user.id)
    record=evaluation_calls._durable(call_id,user.id)
    store=RuntimeStore(record["namespace"],evaluation_calls._enabled())
    try:
        stored={**record["payload"],"outcome_signals":result}
        store.web_call_result(call_id,stored)
    finally:store.close()
    return result


@router.post("/compare",status_code=201)
def compare_sandbox_rounds(body:CompareRound,user:CurrentUser):
    _reviewer(user)
    if body.r0_call_id==body.r1_call_id:raise HTTPException(422,"R0 and R1 must be distinct calls")
    records=[evaluation_calls._durable(call_id,user.id) for call_id in (body.r0_call_id,body.r1_call_id)]
    if any(not record or record["status"]!="COMPLETED" for record in records):
        raise HTTPException(409,"Both calls must have completed barriers")
    evidence=[]
    for record in records:
        store=RuntimeStore(record["namespace"],evaluation_calls._enabled())
        try:
            saved=store.call_record(record["customer"],record["call"])
            if not saved or saved["status"]!="COMPLETED":raise HTTPException(409,"Call episode is not committed")
            evidence.append({"record":record,"context":saved["context"],
                             "turns":store.turn_history(record["customer"],record["call"]),
                             "sessions":store.sessions(record["customer"])})
        finally:store.close()
    base,new=evidence
    conditions={key:base["context"].get(key)==new["context"].get(key)
                for key in ("run_id","scenario_id","config","on","channel","customer_phone_hash","model_pin","model_call_budget","tool_contract_hash","anonymous")}
    conditions["same_call_position"]=base["record"]["call"]==new["record"]["call"]=="call_1"
    conditions["same_customer_inputs"]=[payload["customer_text"] for _,payload in base["turns"]]==[
        payload["customer_text"] for _,payload in new["turns"]]
    conditions["fresh_isolated_namespaces"]=base["record"]["namespace"]!=new["record"]["namespace"] and all(
        len(item["sessions"])==1 for item in evidence)
    conditions["r0_candidate_off"]=not base["context"].get("candidate_id")
    candidate_id=new["context"].get("candidate_id")
    queue=_store()
    try:
        candidate=queue.get_gap_candidate(candidate_id) if candidate_id else None
        conditions["r1_approved_hash"]=bool(candidate and verify_approval(candidate) and
            candidate["content_hash"]==new["context"].get("candidate_hash"))
        history=queue.gap_event_history(candidate_id) if candidate else []
        conditions["r1_consumed_hash"]=any(event.get("action")=="sandbox_consumed" and
            event.get("call_id")==body.r1_call_id and event.get("hash")==candidate["content_hash"] and
            event.get("resource")=="knowledge_gap_candidate" for event in history) if candidate else False
        replies_equal=[payload["agent_text"] for _,payload in base["turns"]]==[
            payload["agent_text"] for _,payload in new["turns"]]
        controls_pass=all(conditions.values())
        report={"comparison_id":str(uuid.uuid4()),"schema_version":"knowledge-gap-r0-r1-diagnostic-v1",
                "r0_call_id":body.r0_call_id,"r1_call_id":body.r1_call_id,
                "candidate_id":candidate_id,"candidate_hash":candidate["content_hash"] if candidate else None,
                "controls":conditions,"controls_pass":controls_pass,
                "input_hash":hashlib.sha256(json.dumps([payload["customer_text"] for _,payload in base["turns"]],
                                             ensure_ascii=False).encode()).hexdigest(),
                "reply_changed":not replies_equal if controls_pass else None,
                "decision":"no-change/hold" if controls_pass and replies_equal else "hold",
                "quality_status":"UNDETERMINED","reason":"Controlled sandbox diagnostic; score closed evaluator R0/R1 runs before release",
                "created_at":datetime.now(timezone.utc).isoformat()}
        queue.save_gap_comparison(report)
        return report
    finally:queue.close()


@router.post("/run-pair",status_code=201)
def run_sandbox_pair(body:PairRun,user:CurrentUser):
    _reviewer(user)
    if any(not text.strip() or len(text)>4000 or contains_pii(text) for text in body.turns):
        raise HTTPException(422,"Paired inputs must be nonempty synthetic text without personal identifiers")
    queue=_store()
    try:candidate=queue.get_gap_candidate(body.candidate_id)
    finally:queue.close()
    if not candidate or not verify_approval(candidate):
        raise HTTPException(409,"Candidate must have current QA approval and pinned source")
    phone="000"+str(uuid.uuid4().int%10**12).zfill(12)
    completed=[]
    for label,candidate_id in (("R0",None),("R1",body.candidate_id)):
        started=evaluation_calls.start_call(evaluation_calls.StartCall(
            customer_phone=phone,channel="web",anonymous=True,candidate_id=candidate_id,
            model_call_budget=body.model_call_budget),user)
        call_id=started["call_id"]
        try:
            for text in body.turns:evaluation_calls.send_turn(call_id,evaluation_calls.Turn(text=text),user)
            evaluation_calls.end_call(call_id,user)
        except Exception as error:
            raise HTTPException(409,{"failed_round":label,"call_id":call_id,"completed_calls":completed,
                                     "error_type":type(error).__name__,"notice":"No retry; inspect persisted call status"}) from None
        completed.append(call_id)
    return compare_sandbox_rounds(CompareRound(r0_call_id=completed[0],r1_call_id=completed[1]),user)


@router.get("/comparisons/{comparison_id}")
def get_sandbox_comparison(comparison_id:str,user:CurrentUser):
    _reviewer(user)
    store=_store()
    try:
        report=store.gap_comparison(comparison_id)
        if not report:raise HTTPException(404,"Comparison not found")
        return report
    finally:store.close()


@router.get("")
def list_candidates(user:CurrentUser):
    _reviewer(user)
    store=_store()
    try:return store.list_gap_candidates()
    finally:store.close()


@router.get("/approved")
def approved_candidates(user:CurrentUser):
    _reviewer(user)
    store=_store()
    try:
        return [{"candidate_id":item["candidate_id"],"question":item["question"],"intent":item["intent"],
                 "answer":item["answer"],"content_hash":item["content_hash"]}
                for item in store.list_gap_candidates() if verify_approval(item)]
    finally:store.close()


@router.get("/{candidate_id}/history")
def review_history(candidate_id:str,user:CurrentUser):
    _reviewer(user)
    store=_store()
    try:
        if not store.get_gap_candidate(candidate_id):raise HTTPException(404,"Candidate not found")
        return store.gap_event_history(candidate_id)
    finally:store.close()


@router.put("/{candidate_id}")
def edit_candidate(candidate_id:str,body:CandidateEdit,user:CurrentUser):
    reviewer=_reviewer(user)
    if contains_pii(body.answer) or contains_pii(body.source_excerpt):
        raise HTTPException(422,"Candidate content must not contain personal identifiers")
    path,source=_source(body.source_path)
    if body.source_excerpt not in source:
        raise HTTPException(422,"Source excerpt does not match the pinned document")
    store=_store()
    try:
        candidate=store.get_gap_candidate(candidate_id)
        if not candidate:raise HTTPException(404,"Candidate not found")
        old_hash=candidate["content_hash"]
        candidate.update(answer=body.answer.strip(),source_path=body.source_path,
                         source_excerpt=body.source_excerpt,source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                         status="PENDING_REVIEW",approval=None,version=candidate["version"]+1)
        candidate["content_hash"]=_content_hash(candidate)
        store.save_gap_candidate(candidate)
        store.append_gap_event(str(uuid.uuid4()),candidate_id,{"action":"edited","reviewer":reviewer,
                               "old_hash":old_hash,"new_hash":candidate["content_hash"],"approval_invalidated":True})
        return candidate
    finally:store.close()


@router.post("/{candidate_id}/approve")
def approve_candidate(candidate_id:str,body:Decision,user:CurrentUser):
    reviewer=_reviewer(user)
    key=_signing_key()
    if not key:raise HTTPException(503,"Trusted approval signing key is not configured")
    store=_store()
    try:
        candidate=store.get_gap_candidate(candidate_id)
        if not candidate:raise HTTPException(404,"Candidate not found")
        if not candidate["answer"] or not candidate["source_hash"] or candidate["status"]=="REJECTED":
            raise HTTPException(409,"Candidate needs a source-backed answer before approval")
        path,source=_source(candidate["source_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=candidate["source_hash"] or candidate["source_excerpt"] not in source:
            raise HTTPException(409,"Candidate source changed; edit/review it again before approval")
        policy={"schema_version":"knowledge-gap-qa-v1","reviewer":reviewer,"scope":"sandbox-only"}
        approval={"candidate_id":candidate_id,"content_hash":candidate["content_hash"],"decision":"approve",
                  "reviewer":reviewer,"reason":body.reason.strip(),"reviewed_at":datetime.now(timezone.utc).isoformat(),
                  "policy":policy}
        payload=json.dumps(approval,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        approval["signature"]=hmac.new(key.encode(),payload.encode(),hashlib.sha256).hexdigest()
        candidate.update(status="APPROVED",approval=approval)
        store.save_gap_candidate(candidate)
        store.append_gap_event(str(uuid.uuid4()),candidate_id,{"action":"approved","reviewer":reviewer,
                               "content_hash":candidate["content_hash"],"signature":approval["signature"],"reason":body.reason.strip()})
        return {"candidate_id":candidate_id,"status":"APPROVED","content_hash":candidate["content_hash"],"signature":approval["signature"]}
    finally:store.close()


@router.post("/{candidate_id}/reject")
def reject_candidate(candidate_id:str,body:Decision,user:CurrentUser):
    reviewer=_reviewer(user)
    store=_store()
    try:
        candidate=store.get_gap_candidate(candidate_id)
        if not candidate:raise HTTPException(404,"Candidate not found")
        previous=candidate.get("approval")
        candidate.update(status="REJECTED",approval=None)
        store.save_gap_candidate(candidate)
        store.append_gap_event(str(uuid.uuid4()),candidate_id,{"action":"rejected","reviewer":reviewer,
                               "content_hash":candidate["content_hash"],"invalidated_approval":bool(previous),"reason":body.reason.strip()})
        return {"candidate_id":candidate_id,"status":"REJECTED"}
    finally:store.close()

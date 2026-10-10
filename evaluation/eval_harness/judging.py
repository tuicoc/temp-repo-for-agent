"""P8 BTC rubric selection, raw-attempt validation and human agreement."""
from collections import Counter
import random

from .assets import parse_json_block
from .collector import context_key
from .contracts import ROOT, checker, validate


def rubric():
    checker.verify_sources()
    return checker.read("sources/btc/eval/llm_judge_rubric.json")


def selections(call, spec, trace, signals):
    tools={t["name"] for r in trace for t in r.get("tool_calls",[])}
    conditions={"J01_opening_continuity":int(call.split("_")[1])>=2,
                "J02_no_fabrication":True,"J06_tone_vietnamese":True,"J08_over_confirmation":True,
                "J07_closing_summary":"order.create" in tools}
    conditions["J05_escalation_quality"]=True if spec.get("expected_outcome")=="chuyen_may" or "handoff.transfer" in tools else signals.get("handoff")
    for mid,key in (("J03_conflict_handling","conflict"),("J04_identity_check","identity"),("J09_pii_handling","pii"),
                    ("J10_honest_ai","asked_ai"),("J11_budget_transparency","budget_cod"),("J12_out_of_stock","out_of_stock")):
        conditions[mid]=signals.get(key)
    if any(v is not None and type(v) is not bool for v in conditions.values()):raise ValueError("Selector signals must be bool or unresolved null")
    return [{"criterion":c,"applicable":conditions[c["id"]],"reason":"UNRESOLVED_APPLICABILITY" if conditions[c["id"]] is None else c["applies_to"]} for c in rubric()["criteria"]]


def prompt(spec, trace, criteria):
    import json
    text=rubric()["judge_prompt_template"]
    for token,value in (("scenario_json",spec),("transcript",trace),("criteria",criteria)):
        text=text.replace("{"+token+"}",json.dumps(value,ensure_ascii=False))
    return (text + "\nChỉ chấm tiêu chí được đưa vào. Nếu thiếu bằng chứng trong lời Agent, "
            "không lấy lời khách, tool hoặc ground truth làm câu trích evidence. "
            "Không được đảo một hard FAIL của kiểm tra tất định thành PASS.")


def judge_record(context, selection, responses, refs, version, transcript):
    mid=selection["criterion"]["id"]
    verdict,error,attempts=None,None,0
    known=selection["applicable"]
    if known is False:
        if responses:raise ValueError("Nonapplicable criterion must not have judge attempts")
        state={"verdict":"NOT_APPLICABLE","completeness":"NOT_APPLICABLE","reason_codes":["PREDECLARED_NONAPPLICABLE"]}
    else:
        if len(responses)>2:raise ValueError("Maximum two raw judge attempts")
        if known is None:error="UNRESOLVED_APPLICABILITY"
        else:
            for index,raw in enumerate(responses):
                attempts=index+1
                try:
                    obj=parse_json_block(raw["raw"])
                    validate("JudgeVerdict",obj)
                    if obj["criterion_id"]!=mid:raise ValueError("Unknown/wrong criterion")
                    # Exact quote must occur in an actual agent utterance, not GT/tool text.
                    quote=obj["evidence"]
                    if not quote or not any(quote in row["agent_text"] for row in transcript):raise ValueError("Evidence quote not in Agent transcript")
                    verdict=obj;error=None
                    if index+1!=len(responses):raise ValueError("Unexpected retry after valid verdict")
                    break
                except (ValueError,KeyError,TypeError) as exc:
                    if verdict is not None:raise
                    error=str(exc)
        if verdict is None:
            error=error or "JUDGE_RESPONSE_MISSING"
            state={"verdict":"UNDETERMINED","completeness":"INCOMPLETE","reason_codes":["JUDGE_INVALID_OR_MISSING"]}
        else:state={"verdict":verdict["verdict"],"completeness":"COMPLETE","reason_codes":[] if verdict["verdict"]=="PASS" else ["JUDGE_CRITERION_FAIL"]}
    result={"schema_version":"1.0.0","artifact_id":context_key(context)+"/"+mid,"run_id":context["run_id"],"context":context,
            "evidence_refs":refs,"criterion_id":mid,"applicable":known is not False,"selection_reason":selection["reason"],
            "attempts":attempts,"status":state,"verdict":verdict,"error":error,"judge_version":version,"human_verdict":None}
    validate("JudgeRecord",result)
    return result


def produce_judge(context, selection, spec, transcript, refs, version, invoke):
    """Schedule at most one format/evidence repair; provider failures are not retried."""
    responses=[]
    if selection["applicable"] is True:
        request=prompt(spec,transcript,[selection["criterion"]])
        for attempt in range(2):
            raw=invoke(request)
            if not isinstance(raw,str):raise ValueError("Judge provider must return raw text")
            responses.append({"raw":raw})
            record=judge_record(context,selection,responses,refs,version,transcript)
            if record["verdict"] is not None:return record,responses
            request=(prompt(spec,transcript,[selection["criterion"]])+
                     "\n\n[INVALID_PREVIOUS_RESPONSE]\n"+raw[:2000]+
                     "\n[VALIDATION_ERROR]\n"+str(record["error"])+
                     "\nChỉ sửa lỗi định dạng/evidence. Trả đúng một JSON object, không giải thích.")
    return judge_record(context,selection,responses,refs,version,transcript),responses


def judge_batch(cases, invoke, *, version, maximum):
    """Bound a real Judge producer before execution; raw attempts remain separate evidence."""
    selected=[]
    for case in cases:
        choices=selections(case["context"]["call"],case["spec"],case["trace"],case["signals"])
        selected.extend((case,choice) for choice in choices)
    envelope=2*sum(choice["applicable"] is True for _,choice in selected)
    if type(maximum) is not int or maximum<envelope:
        raise ValueError("Judge worst-case two-attempt envelope exceeds approved budget")
    calls=0
    records=[];raw_attempts=[]
    def bounded(prompt):
        nonlocal calls
        if calls>=maximum:raise ValueError("Judge model budget exhausted")
        calls+=1
        return invoke(prompt)
    for case,choice in selected:
        record,attempts=produce_judge(case["context"],choice,case["spec"],case["trace"],
                                      case["refs"],version,bounded)
        records.append(record)
        if attempts:raw_attempts.append({"artifact_id":record["artifact_id"],"responses":attempts})
    return {"records":records,"raw_attempts":raw_attempts,"model_attempts":calls,
            "notice":"Human agreement requires independently supplied labels; no release inferred"}


def agreement(records, labels, seed=0, sample_size=20):
    frame=sorted(r["artifact_id"] for r in records if r["applicable"] and r["verdict"] is not None)
    selected=random.Random(seed).sample(frame,min(sample_size,len(frame)))
    mapping={r["artifact_id"]:r["verdict"]["verdict"] for r in records if r["verdict"] is not None}
    if len(mapping)!=len([r for r in records if r["verdict"] is not None]):raise ValueError("Duplicate judge pair")
    if set(labels)-set(selected):raise ValueError("Human labels outside frozen random sample")
    if any(v not in ("PASS","FAIL") for v in labels.values()):raise ValueError("Invalid human label")
    pairs=[(mapping[k],labels[k]) for k in selected if k in labels]
    n=len(pairs); matches=sum(a==b for a,b in pairs)
    po=matches/n if n else None
    a,b=Counter(x for x,_ in pairs),Counter(y for _,y in pairs)
    pe=sum(a[k]*b[k] for k in ("PASS","FAIL"))/(n*n) if n else None
    return {"sampling_frame":frame,"sampling_seed":seed,"selected_ids":selected,"missing_ids":sorted(set(selected)-set(labels)),
            "n":n,"agreement_pct":100*po if po is not None else None,"kappa":(po-pe)/(1-pe) if pe is not None and pe!=1 else None,
            "complete":n>=20 and len(selected)==n,"analysis_required":pe is not None and pe!=1 and (po-pe)/(1-pe)<.6}


def hybrid(assertion_status, judge_records):
    # AND preserves confirmed hard FAIL even while judge evidence is missing.
    failed=assertion_status["verdict"]=="FAIL" or any(r["status"]["verdict"]=="FAIL" for r in judge_records)
    missing=assertion_status["completeness"]!="COMPLETE" or any(r["applicable"] and r["status"]["completeness"]!="COMPLETE" for r in judge_records)
    return {"verdict":"FAIL" if failed else "UNDETERMINED" if missing else "PASS","completeness":"INCOMPLETE" if missing else "COMPLETE",
            "reason_codes":(["HYBRID_FAIL"] if failed else [])+(["HYBRID_EVIDENCE_MISSING"] if missing else [])}

"""P9/P10 evidence metrics; uses BTC algorithms, never substitute fake timing."""
from collections import Counter
from datetime import datetime

from .collector import milliseconds
from .contracts import validate
from .reporting import btc_module


def rag_report(qa_path, results_path, *, review_path=None, attestation_path=None, policy_path=None):
    from .assets import read_json
    qa=read_json(qa_path)["questions"];results=read_json(results_path)
    validate("RagResults",results)
    expected=[q["qid"] for q in qa]
    if len(expected)!=len(set(expected)):raise ValueError("Duplicate ground-truth qid")
    missing=sorted(set(expected)-set(results));unknown=sorted(set(results)-set(expected))
    review=None
    if any(path is not None for path in (review_path,attestation_path,policy_path)):
        if any(path is None for path in (review_path,attestation_path,policy_path)):
            raise ValueError("RAG QA review, attestation and policy must be supplied together")
        from .rag_review import review_answers
        review=review_answers(qa,results,read_json(review_path),read_json(attestation_path),read_json(policy_path))
    return {"official":btc_module().rag_eval(str(qa_path),str(results_path)),"complete":not missing and not unknown,
            "expected_ids":expected,"observed_ids":list(results),"missing_ids":missing,"unknown_ids":unknown,
            "answer_version_status":"COMPLETE" if review and review["complete"] else "INCOMPLETE",
            "answer_review":review,"disputed_ids":review["disputes_open"] if review else [q for q in ("Q20","Q57") if q in expected],
            "notice":"BTC retrieval/abstain separate from authenticated human answer/version review; no exact-string heuristic."}


def diarization_report(asr_directory, expected_ids):
    from pathlib import Path
    from .assets import read_json
    directory=Path(asr_directory)
    ground=read_json(directory/"ground_truth.json")["dialogues"]
    hyp=read_json(directory/"hypotheses.json")
    gaps=[];samples=0
    ids=[g["id"] for g in ground]
    if Counter(ids)!=Counter(expected_ids) or set(hyp)!=set(expected_ids):gaps.append("DIARIZATION_ID_COVERAGE")
    for key in expected_ids:
        path=directory/"audio"/(key+".segments.json")
        if not path.exists():gaps.append("SEGMENTS_MISSING");continue
        segments=read_json(path);validate("Segments",segments)
        turns=hyp.get(key,{}).get("turns")
        if not turns:gaps.append("DIARIZATION_PREDICTIONS_MISSING");continue
        validate("Segments",{"segments":turns})
        for seq in (segments["segments"],turns):
            if any(t["end"]<=t["start"] for t in seq):raise ValueError("Invalid diarization interval")
        samples+=len(segments["segments"])
    native=btc_module().wer_cer(str(directory))
    return {"official":native,"midpoint_speaker_accuracy":native["diarization_turn_accuracy"] if not gaps else None,
            "complete":not gaps and samples>0,"n_segments":samples,"reason_codes":sorted(set(gaps)),"notice":"BTC midpoint accuracy, not DER; audio producer/inference authenticity separately checked"}


def voice_report(expected, sessions, minimum=100, warmup=3, planned_turns=None):
    ids=[s["session_id"] for s in sessions]
    errors=[]
    if Counter(ids)!=Counter(expected):errors.append("VOICE_SESSION_COVERAGE")
    if planned_turns is None:
        errors.append("VOICE_TURN_PLAN_MISSING");planned_turns={key:[] for key in expected}
    if set(planned_turns)!=set(expected):raise ValueError("Voice turn plan/session mismatch")
    flat=[key+"/"+str(tid) for key in expected for tid in planned_turns[key]]
    if len(flat)!=len(set(flat)) or any(not isinstance(tid,str) or not tid for ids in planned_turns.values() for tid in ids):raise ValueError("Voice plan requires unique nonempty turn IDs")
    values={};briefs=[];intervals=[];raw_count=0
    for index,key in enumerate(expected):
        rows=[s for s in sessions if s["session_id"]==key]
        if len(rows)!=1:continue
        row=rows[0]
        try:
            start=datetime.fromisoformat(row["started_at"]);end=datetime.fromisoformat(row["ended_at"])
            milliseconds(row["started_at"],row["ended_at"])
            ids=[t["turn_id"] for t in row["turns"]];raw_count+=len(ids)
            if Counter(ids)!=Counter(planned_turns[key]):errors.append("VOICE_TURN_COVERAGE")
            pairs=[(t["vad_end_at"],t["first_played_audio_at"]) for t in row["turns"]]
            if len(pairs)!=len(set(pairs)):errors.append("VOICE_DUPLICATE_TIMING")
            if any(t.get("backend_kind")!="played_audio" for t in row["turns"]):raise ValueError("Require first played byte, not generated TTS")
            for t in row["turns"]:
                duration=milliseconds(t["vad_end_at"],t["first_played_audio_at"])
                if duration is None or not start<=datetime.fromisoformat(t["vad_end_at"])<=datetime.fromisoformat(t["first_played_audio_at"])<=end:
                    raise ValueError("Voice clocks outside session")
                tid=key+"/"+t["turn_id"]
                if tid in values:errors.append("VOICE_DUPLICATE_TURN")
                if tid in flat:values[tid]=duration
            brief=milliseconds(row["identified_at"],row["brief_ready_at"])
            if brief is None or not start<=datetime.fromisoformat(row["identified_at"])<=datetime.fromisoformat(row["brief_ready_at"])<=end:raise ValueError("Brief clock missing/outside session")
            briefs.append(brief);intervals.append((row["namespace"],start,end))
        except (ValueError,KeyError,TypeError) as exc:errors.append("VOICE_TIMING_INVALID:"+str(exc))
    warmup_ids=flat[:warmup];effective_ids=flat[warmup:]
    effective=[values[k] for k in effective_ids if k in values]
    if len(effective)<minimum:errors.append("VOICE_SAMPLE_QUOTA")
    overlap=any(ns!=other and max(a,c)<min(b,d) for i,(ns,a,b) in enumerate(intervals) for other,c,d in intervals[i+1:])
    if not overlap:errors.append("TWO_OVERLAPPING_SESSIONS_MISSING")
    if len({ns for ns,_,_ in intervals})!=len(intervals):errors.append("VOICE_NAMESPACE_REUSE")
    p95=btc_module().p95(effective) if effective and not errors else None
    maximum=max(briefs) if briefs and not errors else None
    return {"complete":not errors,"raw_count":raw_count,"effective_count":len(effective),"warmup_ids":warmup_ids,"effective_ids":effective_ids,
            "ttfa_p95_ms":p95,"brief_max_ms":maximum,"overlap":overlap,"passed":not errors and p95<=2500 and maximum<=3000,
            "reason_codes":errors,"notice":"Evidence timestamps only; namespace names/overlap do not prove backend data-store isolation"}

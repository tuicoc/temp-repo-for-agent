"""Independent QA import for RAG answer/version; no model output self-grading."""
import hashlib
import hmac
import os

from .extractor import digest
from .contracts import validate


def review_answers(questions, results, review, attestation, policy):
    validate("RagResults",results)
    expected={q["qid"]:q for q in questions}
    if len(expected)!=len(questions) or set(results)!=set(expected):
        raise ValueError("RAG answer review requires exact question coverage")
    if set(review)!={"schema_version","reviewer","entries"} or review["schema_version"]!="m2-rag-qa-v1":
        raise ValueError("Invalid RAG QA review")
    if not isinstance(policy,dict) or not isinstance(policy.get("reviewers"),list) or review["reviewer"] not in policy["reviewers"]:
        raise ValueError("RAG QA reviewer not authorized")
    secret=os.environ.get("EVALUATION_APPROVAL_HMAC_KEY")
    if not secret or not isinstance(attestation,dict) or set(attestation)!={"signature"} or not isinstance(attestation["signature"],str):
        raise ValueError("RAG QA attestation missing")
    signature=hmac.new(secret.encode(),digest({"review":review,"policy":policy}).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,attestation["signature"]):
        raise ValueError("RAG QA signature invalid")
    entries=review["entries"]
    if not isinstance(entries,list) or len(entries)!=len(expected) or len({row["qid"] for row in entries})!=len(entries):
        raise ValueError("RAG QA label coverage/duplicates invalid")
    if {row["qid"] for row in entries}!=set(expected):
        raise ValueError("RAG QA labels do not match questions")
    for row in entries:
        if set(row)!={"qid","result_hash","answer_correct","source_supported","version_correct","dispute_adjudicated"}:
            raise ValueError("RAG QA entry shape invalid")
        qid=row["qid"]
        if row["result_hash"]!=digest(results[qid]):raise ValueError("RAG QA label not bound to result bytes")
        if any(type(row[key]) is not bool for key in ("answer_correct","source_supported","dispute_adjudicated")):
            raise ValueError("RAG QA verdict must be boolean")
        if expected[qid]["type"]=="version_conflict":
            if type(row["version_correct"]) is not bool:raise ValueError("Version case needs explicit verdict")
        elif row["version_correct"] is not None:
            raise ValueError("Non-version case must not claim version verdict")
    by_id={row["qid"]:row for row in entries}
    disputes=[qid for qid in ("Q20","Q57") if qid in expected and not by_id[qid]["dispute_adjudicated"]]
    versions=[row for row in entries if expected[row["qid"]]["type"]=="version_conflict"]
    return {"complete":not disputes,"reviewer":review["reviewer"],
            "answer_correct":sum(row["answer_correct"] for row in entries),"answer_total":len(entries),
            "source_supported":sum(row["source_supported"] for row in entries),
            "version_correct":sum(row["version_correct"] for row in versions),"version_total":len(versions),
            "disputes_open":disputes,"notice":"Authenticated QA labels, not automatic answer truth; no release without other gates"}

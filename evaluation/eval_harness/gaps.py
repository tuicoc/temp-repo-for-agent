"""Evaluation-side knowledge gap intake; never activates product knowledge."""

import hashlib
import json
from pathlib import Path
import re

from .collector import locked_run
from .runner import _write

UNKNOWN = re.compile(r"(?:chưa|không) (?:có|đủ) thông tin|không (?:biết|thể trả lời|thể xác nhận)", re.I)


def candidates(traces, evidence: Path, *, source_split="unknown"):
    transcripts = {}
    for config in traces:
        for path in (evidence / config / "transcripts").glob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            context = document["context"]
            transcripts[(config, context["scenario_id"], context["call"], context["turn"])] = document
    found = []
    for config, rows in traces.items():
        if config != "full":
            continue
        for row in rows:
            handoffs = [tool for tool in row["tool_calls"] if tool["name"] == "handoff.transfer"
                        and isinstance(tool.get("result"), dict) and tool["result"].get("ticket_id")]
            admitted_unknown = bool(UNKNOWN.search(row["agent_text"]))
            if not handoffs and not admitted_unknown:
                continue
            sid, call, turn = row["scenario_id"], row["call"], row["turn"]
            document = transcripts.get((config, sid, call, turn), {})
            identity = f"{row['run_id']}/{config}/{sid}/{call}/{turn}"
            found.append({"gap_id": "GAP-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                          "source": identity, "customer_question": row["customer_text"],
                          "source_split": source_split,
                          "consultant_answers": document.get("consultant_texts", []),
                          "status": "REVIEW_REQUIRED", "signals": {
                              "handoff_success": bool(handoffs), "agent_admitted_unknown": admitted_unknown},
                          "reason": "Signals alone do not prove a reusable knowledge gap"})
    return {"report_kind": "knowledge-gap-candidates-v1", "candidates": found,
            "notice": "Handoffs and explicit uncertainty are review candidates, not approved FAQ or test labels"}


def scan(evidence: Path, out: Path):
    source, _ = locked_run(evidence)
    rows = [json.loads(line) for line in source.path("full.jsonl").read_text(encoding="utf-8").splitlines()]
    report = candidates({"full": rows}, source.root,
                        source_split=json.loads(source.path("manifest.json").read_text())["split"])
    _write(Path(out), report)
    return report


def publish(candidate_file: Path, review_file: Path, out: Path):
    source = json.loads(candidate_file.read_text(encoding="utf-8"))
    review = json.loads(review_file.read_text(encoding="utf-8"))
    if source.get("report_kind") != "knowledge-gap-candidates-v1":
        raise ValueError("Expected knowledge gap candidates")
    matches = [item for item in source["candidates"] if item["gap_id"] == review.get("gap_id")]
    if len(matches) != 1:
        raise ValueError("Review must identify exactly one captured handoff")
    if matches[0].get("source_split") not in ("development", "public"):
        raise ValueError("FAQ learning requires a declared development/public source")
    required = ("reviewer", "general_question", "general_answer", "evidence", "decision")
    if any(not isinstance(review.get(key), str) or not review[key].strip() for key in required):
        raise ValueError("Human reviewer, generalized FAQ, evidence and decision required")
    if review["decision"] != "approve_faq":
        raise ValueError("Only explicit human FAQ approval may publish a candidate")
    if not review.get("policy_checked") or not review.get("consultant_answer_verified"):
        raise ValueError("Policy and consultant answer must be verified")
    terms = review.get("must_say_any")
    if not isinstance(terms, list) or not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
        raise ValueError("Human reviewer must provide nonempty test phrases")
    answer = review["general_answer"].strip()
    question = review["general_question"].strip()
    if any(re.search(pattern, question + " " + answer, re.I) for pattern in
           (r"\b0\d{9,10}\b", r"\b\w+@\w+\.\w+\b")):
        raise ValueError("FAQ contains a possible phone number or email")
    out = Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    _write(out / "decision.json", {"gap": matches[0], "review": review,
                                   "candidate_sha256": hashlib.sha256(candidate_file.read_bytes()).hexdigest()})
    (out / "faq.md").write_text(f"## [{review['gap_id']}] {question}\n\n{answer}\n", encoding="utf-8")
    _write(out / "growth-case.json", {"case_id": review["gap_id"], "question": question,
                                      "expected_answer": answer, "source": matches[0]["source"],
                                      "reviewer": review["reviewer"], "split": "growth",
                                      "must_say_any": terms,
                                      "golden_set_unchanged": True})
    return {"status": "CANDIDATE_READY", "out": str(out.resolve()),
            "notice": "FAQ is not in the live KB; product integration and R0/R1 retest remain required"}


def check(growth_root: Path, responses_file: Path):
    responses = json.loads(responses_file.read_text(encoding="utf-8"))
    if not isinstance(responses, dict):
        raise ValueError("Responses must map case_id to agent response text")
    rows = []
    for path in sorted(growth_root.glob("*/growth-case.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        reply = responses.get(case["case_id"])
        if reply is not None and not isinstance(reply, str):
            raise ValueError("Agent response must be text")
        expected = case["must_say_any"]
        if not expected or not all(isinstance(term, str) and term.strip() for term in expected):
            raise ValueError("Growth case has no valid approved assertion")
        outcome = "MISSING" if reply is None else "PASS" if any(term.casefold() in reply.casefold() for term in expected) else "FAIL"
        rows.append({"case_id": case["case_id"], "outcome": outcome, "source": str(path)})
    return {"report_kind": "growth-check-v1", "rows": rows,
            "counts": {status: sum(row["outcome"] == status for row in rows) for status in ("PASS", "FAIL", "MISSING")},
            "notice": "Diagnostic text assertions; response provenance and semantic correctness need independent review"}

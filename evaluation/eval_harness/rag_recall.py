"""Retrieval-only BTC Recall@3/@5 through the product's kb_search."""
import hashlib
import json
from pathlib import Path
import subprocess

from .contracts import ROOT, checker
from .rag_corpus import chunk_catalog
from .reporting import btc_module


def validate_retrieval(questions, results):
    expected = {q["qid"] for q in questions}
    if len(expected) != 60 or set(results) != expected:
        raise ValueError("RAG result must cover exactly all 60 BTC questions")
    if any(type(ids) is not list or len(ids) > 5 or len(ids) != len(set(ids))
           or any(type(chunk) is not str or not chunk for chunk in ids)
           for ids in results.values()):
        raise ValueError("RAG top-5 contains duplicate or invalid chunk IDs")
    return True


def run(out: Path, *, on: str):
    checker.verify_sources()
    catalog = chunk_catalog()
    qa = json.loads((ROOT / "sources/btc/rag/qa_labeled.json").read_text(encoding="utf-8"))
    backend = ROOT.parents[1] / "backend"
    product_policy = backend / "data/btc/policy"
    pinned_policy = ROOT / "sources/btc/policy"
    for source in sorted(pinned_policy.glob("*.md")):
        other = product_policy / source.name
        if not other.is_file() or hashlib.sha256(other.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
            raise ValueError("Product policy differs from pinned BTC corpus: " + source.name)
    if set(p.name for p in product_policy.glob("*.md")) != set(p.name for p in pinned_policy.glob("*.md")):
        raise ValueError("Product policy file set differs from pinned BTC corpus")
    questions = [{"qid": q["qid"], "question": q["question"], "on": on} for q in qa["questions"]]
    process = subprocess.run([str(backend / ".venv/bin/python"), "-B",
                              str(ROOT.parent / "product_rag_retrieval.py")],
                             input=json.dumps(questions, ensure_ascii=False), text=True,
                             capture_output=True, timeout=120, cwd=backend)
    if process.returncode:
        raise RuntimeError("Product kb_search failed; no Recall reported: " + process.stderr[-1200:])
    results = json.loads(process.stdout)
    validate_retrieval(qa["questions"], results)
    other_ids = sorted({chunk for ids in results.values() for chunk in ids if chunk not in catalog})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / "retrieval.json").write_text(
        json.dumps({qid: {"retrieved_chunk_ids": ids} for qid, ids in results.items()},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    # BTC rag_eval reads retrieved_chunk_ids for Recall; answer/abstain are not supplied or reported here.
    official = btc_module().rag_eval(str(ROOT / "sources/btc/rag/qa_labeled.json"),
                                     str(out / "retrieval.json"))
    metrics = {key: official[key] for key in ("recall@3", "recall@5",
               "multi_hop_full_recall@3", "multi_hop_full_recall@5")}
    report = {"report_kind": "product-rag-recall-v1", "retriever": "backend/src/mcp/servers/knowledge.py:kb_search",
              "corpus": "BTC policy bytes match pinned evaluation corpus", "on": on,
              "status": "DIAGNOSTIC", "scorer": "BTC reference_eval.py:rag_eval", "metrics": metrics,
              "non_btc_chunk_ids": other_ids,
              "notice": "Retrieval only; answer, abstention, DB KB version and response quality not certified."}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

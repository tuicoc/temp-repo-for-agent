"""Jev against chat models on this project's own decisions: time and accuracy.

    cd backend
    .venv/bin/python lab/jev/run.py                   every backend, whatever the cache lacks
    .venv/bin/python lab/jev/run.py --backends gemini one backend
    .venv/bin/python lab/jev/run.py --score           score the cache only, no calls

Every answer is appended to ``cache.jsonl`` the moment it arrives, so an
interrupted run resumes where it stopped and scoring costs nothing. Results
go to ``backend/workbench/reports/jev/results.json``; ``report.py`` turns them
into a page.

Timing is the call alone. Our own rate limiter paces the calls, but the wait
for a slot happens before the clock starts: what is measured is what a
customer would wait for if the system were idle.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from pydantic import Field, create_model  # noqa: E402

from src.config.config_manager import get_models_config  # noqa: E402
from src.llm import jev  # noqa: E402
from src.llm.callback_handler import is_rate_limit_error, retry_after_seconds  # noqa: E402
from src.llm.factory import LLMFactory, limiter_for  # noqa: E402

from tasks import FAQ, POLICY_LABELS, REPEAT, TASKS  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache.jsonl"
RESULTS = HERE.parents[1] / "workbench" / "reports" / "jev" / "results.json"

BACKENDS: dict[str, dict[str, str]] = {
    "jev": {"kind": "jev", "label": "Jev", "model": "typesafe-ai/jev"},
    "gemini": {"kind": "chat", "label": "Gemini 3.5 Flash-Lite", "provider": "google_genai", "model": "gemini-3.5-flash-lite"},
    "groq": {"kind": "chat", "label": "GPT-OSS 20B (Groq)", "provider": "groq", "model": "openai/gpt-oss-20b"},
}


class Blocked(RuntimeError):
    """The backend refuses every call (no card, no key): stop asking it."""


# ── cache ─────────────────────────────────────────────────────────────────


def _load_cache() -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[row["key"]] = row
    return cache


def _key(backend: str, variant: str, task: str, item: str, rep: int, state: Any, questions: dict) -> str:
    dumped = {k: q.model_dump(exclude_none=True) for k, q in questions.items()}
    raw = json.dumps([backend, BACKENDS[backend]["model"], variant, task, item, rep, state, dumped],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _append(row: dict[str, Any]) -> None:
    with CACHE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── backends ──────────────────────────────────────────────────────────────


async def call_jev(state: Any, questions: dict) -> dict[str, Any]:
    for _ in range(30):
        try:
            decision = await jev.evaluate("orchestrator", state, questions, timeout=30)
        except jev.JevUnavailable as error:
            if error.code == "THROTTLED":
                await asyncio.sleep(2)
                continue
            if error.code == "RATE_LIMITED":
                await asyncio.sleep(15)
                continue
            if error.code in {"customer_verification_required", "permission_denied", "NO_KEY"}:
                raise Blocked(str(error)) from error
            return {"error": str(error)[:300]}
        return {
            "answers": {k: a.model_dump(exclude_none=True) for k, a in decision.answers.items()},
            "seconds": decision.seconds,
            "input_tokens": decision.input_tokens,
        }
    return {"error": "still throttled after 30 attempts"}


def _schema(questions: dict) -> Any:
    fields: dict[str, Any] = {}
    for name, q in questions.items():
        if q.type == "choice":
            options = "; ".join(f"{k} = {v}" for k, v in q.criteria.items())
            fields[name] = (Literal[tuple(q.criteria)], Field(description=f"{q.instructions} Options: {options}"))
        elif q.type == "boolean":
            extra = f" True: {q.criteria['true']}. False: {q.criteria['false']}." if q.criteria else ""
            fields[name] = (bool, Field(description=q.instructions + extra))
        else:
            scale = "; ".join(f"{i} = {c}" for i, c in enumerate(q.criteria))
            fields[name] = (int, Field(ge=0, le=len(q.criteria) - 1, description=f"{q.instructions} Scale: {scale}"))
    return create_model("Answers", **fields)


def _prompt(state: Any, questions: dict) -> list[Any]:
    lines = []
    for name, q in questions.items():
        if q.type == "choice":
            lines.append(f"- {name}: {q.instructions} Pick one of: " + "; ".join(f"{k} ({v})" for k, v in q.criteria.items()))
        elif q.type == "boolean":
            extra = f" True: {q.criteria['true']}. False: {q.criteria['false']}." if q.criteria else ""
            lines.append(f"- {name} (true or false): {q.instructions}{extra}")
        else:
            lines.append(f"- {name} (0 to {len(q.criteria) - 1}): {q.instructions} " + "; ".join(f"{i} = {c}" for i, c in enumerate(q.criteria)))
    return [
        SystemMessage(content=(
            "You answer typed questions about a piece of state taken from the customer chat of a "
            "Vietnamese shop. Answer every field, and nothing else."
        )),
        HumanMessage(content="State:\n" + json.dumps(state, ensure_ascii=False, indent=1)
                     + "\n\nQuestions:\n" + "\n".join(lines)),
    ]


class ChatBackend:
    def __init__(self, provider: str, model: str) -> None:
        config = get_models_config().llm_config(provider, model)
        self.limiter = limiter_for(provider, config["rate_limits"])
        # The limiter paces the calls from outside, so its wait is not timed.
        self.llm = LLMFactory.create_llm(config, agent_name="jev-lab", rate_limited=False)
        # Each model gets its best shot at structured output. GPT-OSS on Groq
        # spent Groq's 800-token output cap on reasoning and returned broken
        # JSON for a 25-field answer, through tool calls and json_schema alike;
        # low reasoning effort leaves room for the answer.
        self.method = "json_schema" if provider == "groq" else None
        if provider == "groq":
            self.llm = self.llm.model_copy(update={"reasoning_effort": "low"})
        # The same for Gemini: the least thinking it allows, which is how a
        # router on the hot path would run it.
        if provider == "google_genai":
            self.llm = self.llm.model_copy(update={"reasoning_effort": "minimal"})

    async def call(self, state: Any, questions: dict) -> dict[str, Any]:
        options = {"method": self.method} if self.method else {}
        structured = self.llm.with_structured_output(_schema(questions), include_raw=True, **options)
        messages = _prompt(state, questions)
        for _ in range(6):
            await self.limiter.aacquire()
            started = time.perf_counter()
            try:
                result = await structured.ainvoke(messages)
            except Exception as error:  # noqa: BLE001 - every failure is a data point
                if is_rate_limit_error(error):
                    self.limiter.record_rate_limited(retry_after_seconds(error))
                    continue
                return {"error": f"{type(error).__name__}: {str(error)[:240]}",
                        "seconds": time.perf_counter() - started}
            seconds = time.perf_counter() - started
            usage = getattr(result.get("raw"), "usage_metadata", None) or {}
            self.limiter.record_request(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            parsed = result.get("parsed")
            if parsed is None:
                return {"error": f"unparsed: {str(result.get('parsing_error'))[:240]}", "seconds": seconds}
            answers = {}
            for name, value in parsed.model_dump().items():
                kind = questions[name].type
                if kind == "choice":
                    answers[name] = {"type": "choice", "choice": value}
                elif kind == "boolean":
                    answers[name] = {"type": "boolean", "probability": 1.0 if value else 0.0}
                else:
                    answers[name] = {"type": "score", "score": float(value)}
            return {"answers": answers, "seconds": seconds,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0)}
        return {"error": "rate limited six times"}


# ── running ───────────────────────────────────────────────────────────────


def _plan(backend: str) -> list[tuple[str, str, dict[str, Any], int]]:
    """Every (task, variant, item, rep) this backend should answer."""
    plan = []
    for task in TASKS.values():
        variants = task.variants if BACKENDS[backend]["kind"] == "jev" else ("en",)
        for variant in variants:
            for item in task.items:
                plan.append((task.name, variant, item, 0))
    if backend in {"jev", "gemini"}:
        task_name, ids = REPEAT
        for item in TASKS[task_name].items:
            if item["id"] in ids:
                for rep in (1, 2):
                    plan.append((task_name, "en", item, rep))
    return plan


async def run_backend(backend: str, cache: dict[str, dict[str, Any]]) -> None:
    spec = BACKENDS[backend]
    chat = ChatBackend(spec["provider"], spec["model"]) if spec["kind"] == "chat" else None
    plan = _plan(backend)
    done = 0
    for task_name, variant, item, rep in plan:
        task = TASKS[task_name]
        questions = task.questions(variant, item)
        state = task.state(item)
        key = _key(backend, variant, task_name, item["id"], rep, state, questions)
        if key in cache:
            continue
        try:
            outcome = await (call_jev(state, questions) if chat is None else chat.call(state, questions))
        except Blocked as error:
            print(f"[{backend}] blocked, stopping: {str(error)[:120]}", flush=True)
            return
        row = {"key": key, "backend": backend, "variant": variant, "task": task_name,
               "item": item["id"], "rep": rep, "at": datetime.now(timezone.utc).isoformat(), **outcome}
        cache[key] = row
        _append(row)
        done += 1
        status = "ERR " + outcome["error"][:60] if "error" in outcome else "ok"
        print(f"[{backend}] {done:3d} {task_name:8s} {variant} {item['id']} r{rep} "
              f"{outcome.get('seconds', 0):6.2f}s {status}", flush=True)
    await jev.close()


# ── scoring ───────────────────────────────────────────────────────────────


def _bool(answer: dict[str, Any] | None) -> bool | None:
    if not answer:
        return None
    return float(answer.get("probability", 0.0)) >= 0.5


def _latency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seconds = sorted(r["seconds"] for r in rows if "error" not in r and "seconds" in r)
    if not seconds:
        return {"n": 0}
    p95 = seconds[min(len(seconds) - 1, math.ceil(0.95 * len(seconds)) - 1)]
    tokens = [r.get("input_tokens", 0) for r in rows if "error" not in r]
    return {"n": len(seconds), "p50": statistics.median(seconds), "p95": p95,
            "mean": statistics.fmean(seconds), "max": seconds[-1],
            "input_tokens_mean": statistics.fmean(tokens) if tokens else 0,
            "input_tokens_max": max(tokens) if tokens else 0}


def _score_route(item, answers):
    out = []
    for field in ("intent", "wants_human", "needs_tool"):
        gold = item[field]
        if gold is None:
            continue
        answer = (answers or {}).get(field)
        if field == "intent":
            pred = answer.get("choice") if answer else None
            detail = answer.get("probabilities") if answer else None
        else:
            pred = _bool(answer)
            detail = answer.get("probability") if answer else None
        out.append({"field": field, "gold": gold, "pred": pred, "ok": pred == gold, "detail": detail})
    return out


def _score_simple(field, gold_key):
    def score(item, answers):
        answer = (answers or {}).get(field)
        pred = _bool(answer)
        return [{"field": field, "gold": item[gold_key], "pred": pred, "ok": pred == item[gold_key],
                 "detail": answer.get("probability") if answer else None}]
    return score


def _score_policy(item, answers):
    out = []
    for label in POLICY_LABELS:
        gold = label in item["violations"]
        answer = (answers or {}).get(label)
        pred = _bool(answer)
        out.append({"field": label, "gold": gold, "pred": pred, "ok": pred == gold,
                    "detail": answer.get("probability") if answer else None})
    return out


OOS_BELOW = 1.5  # expected score under "partly answers" everywhere means nothing answers


def _faq_rank(answers: dict[str, Any]) -> list[tuple[str, float]]:
    order = [entry["id"] for entry in FAQ]
    scored = [(pid, float((answers.get(pid) or {}).get("score", 0.0))) for pid in order]
    # Stable sort: ties keep the corpus order, the same for every backend.
    return sorted(scored, key=lambda pair: -pair[1])


def _score_faq(item, answers):
    if not answers:
        return [{"field": "top1", "gold": item["relevant"], "pred": None, "ok": False, "detail": None}]
    ranking = _faq_rank(answers)
    top_id, top_score = ranking[0]
    predicted_oos = top_score < OOS_BELOW
    gold_oos = not item["relevant"]
    out = [{"field": "out_of_scope", "gold": gold_oos, "pred": predicted_oos, "ok": predicted_oos == gold_oos,
            "detail": round(top_score, 2)}]
    if not gold_oos:
        rank = next((i for i, (pid, _) in enumerate(ranking[:5], 1) if pid in item["relevant"]), None)
        out.append({"field": "top1", "gold": item["relevant"], "pred": top_id, "ok": top_id in item["relevant"],
                    "detail": {"rr": 1 / rank if rank else 0.0, "top3": [pid for pid, _ in ranking[:3]]}})
    return out


SCORERS = {
    "route": _score_route,
    "identity": _score_simple("confirms", "confirms"),
    "policy": _score_policy,
    "faq": _score_faq,
    "rqr": _score_simple("asks_known", "asks_known"),
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def bm25_faq() -> dict[str, Any]:
    """The free baseline: BM25 over the same passages, no model at all."""
    docs = {entry["id"]: _tokens(entry["title"] + " " + entry["text"]) for entry in FAQ}
    n = len(docs)
    avg = statistics.fmean(len(d) for d in docs.values())
    df: dict[str, int] = {}
    for words in docs.values():
        for word in set(words):
            df[word] = df.get(word, 0) + 1
    k1, b = 1.5, 0.75
    rows = []
    for item in TASKS["faq"].items:
        if not item["relevant"]:
            continue
        scores = []
        for pid, words in docs.items():
            s = 0.0
            for q in set(_tokens(item["query"])):
                if q not in df:
                    continue
                tf = words.count(q)
                idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
                s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(words) / avg))
            scores.append((pid, s))
        ranking = sorted(scores, key=lambda pair: -pair[1])
        rank = next((i for i, (pid, _) in enumerate(ranking[:5], 1) if pid in item["relevant"]), None)
        rows.append({"id": item["id"], "ok": ranking[0][0] in item["relevant"], "rr": 1 / rank if rank else 0.0})
    return {"top1": sum(r["ok"] for r in rows) / len(rows), "mrr5": statistics.fmean(r["rr"] for r in rows),
            "n": len(rows)}


GRID = [round(0.05 * i, 2) for i in range(1, 20)]


def _tune_thresholds(run: dict[str, Any]) -> None:
    """Jev's booleans, each item judged at a threshold chosen without it.

    A probability is only useful against a threshold, and TypeSafe's advice
    is to pick one per question from your own data. Picking it on the very
    items being scored would flatter the model, so each item gets the
    threshold that works best on all the *other* items (leave one out), and
    that is written as ``tuned`` next to the plain 0.5 prediction.
    """
    fields: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
    for item in run["items"]:
        for check in item["checks"]:
            # Only probabilities: the FAQ's out-of-scope check carries a 0-3 score.
            if (isinstance(check["gold"], bool) and isinstance(check["detail"], (int, float))
                    and check["field"] != "out_of_scope"):
                fields.setdefault(check["field"], []).append((item["id"], check))
    for field, pairs in fields.items():
        for index, (_, check) in enumerate(pairs):
            others = [c for j, (_, c) in enumerate(pairs) if j != index]

            def accuracy(threshold: float) -> float:
                return sum((c["detail"] >= threshold) == c["gold"] for c in others)

            best = max(GRID, key=lambda th: (accuracy(th), -abs(th - 0.5)))
            check["tuned"] = check["detail"] >= best
            check["tuned_threshold"] = best
    checks = [c for it in run["items"] for c in it["checks"]]
    for check in checks:
        check["tuned_ok"] = (check["tuned"] == check["gold"]) if "tuned" in check else bool(check["ok"])
    run["accuracy_tuned"] = sum(c["tuned_ok"] for c in checks) / len(checks) if checks else None


def score(cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by = {(r["backend"], r["variant"], r["task"], r["item"], r["rep"]): r for r in cache.values()}
    results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backends": {k: {"label": v["label"], "model": v["model"]} for k, v in BACKENDS.items()},
        "tasks": {},
        "calls": len(cache),
        "errors": sum(1 for row in cache.values() if "error" in row),
    }
    for task in TASKS.values():
        runs = {}
        for backend, spec in BACKENDS.items():
            variants = task.variants if spec["kind"] == "jev" else ("en",)
            for variant in variants:
                rows = [by.get((backend, variant, task.name, it["id"], 0)) for it in task.items]
                if not any(rows):
                    continue
                items, checks = [], []
                for it, row in zip(task.items, rows):
                    answers = (row or {}).get("answers")
                    scored = SCORERS[task.name](it, answers)
                    checks.extend(scored)
                    items.append({"id": it["id"], "why": it.get("why"),
                                  "text": it.get("customer_said") or it.get("reply") or it.get("query") or it.get("agent_question"),
                                  "error": (row or {}).get("error") if row else "not run",
                                  "seconds": (row or {}).get("seconds"), "checks": scored})
                fields: dict[str, dict[str, int]] = {}
                for check in checks:
                    f = fields.setdefault(check["field"], {"ok": 0, "n": 0, "tp": 0, "fp": 0, "fn": 0})
                    f["n"] += 1
                    f["ok"] += bool(check["ok"])
                    if isinstance(check["gold"], bool):
                        f["tp"] += bool(check["gold"] and check["pred"])
                        f["fp"] += bool(not check["gold"] and check["pred"])
                        f["fn"] += bool(check["gold"] and not check["pred"])
                ran = [r for r in rows if r]
                runs[f"{backend}:{variant}"] = {
                    "backend": backend, "variant": variant,
                    "accuracy": sum(bool(c["ok"]) for c in checks) / len(checks) if checks else None,
                    "fields": fields,
                    "errors": sum(1 for r in ran if "error" in r),
                    "missing": sum(1 for r in rows if not r),
                    "latency": _latency(ran),
                    "items": items,
                }
        results["tasks"][task.name] = {"title": task.title, "n": len(task.items), "runs": runs}

    for task in results["tasks"].values():
        for run in task["runs"].values():
            if run["backend"] == "jev":
                _tune_thresholds(run)

    results["tasks"]["faq"]["bm25"] = bm25_faq()
    for run in results["tasks"]["faq"]["runs"].values():
        top = [c for it in run["items"] for c in it["checks"] if c["field"] == "top1"]
        run["mrr5"] = statistics.fmean(c["detail"]["rr"] if c["detail"] else 0.0 for c in top) if top else None

    task_name, ids = REPEAT
    repeat = {}
    for backend in ("jev", "gemini"):
        same, total, drift = 0, 0, []
        for item in ids:
            reps = [by.get((backend, "en", task_name, item, rep)) for rep in (0, 1, 2)]
            if not all(r and "answers" in r for r in reps):
                continue
            for field in ("intent", "wants_human", "needs_tool"):
                values = [r["answers"][field] for r in reps]
                decided = [v.get("choice", v.get("probability", 0) >= 0.5) for v in values]
                total += 1
                same += len(set(map(str, decided))) == 1
                probs = [v.get("probability") for v in values if "probability" in v]
                if len(probs) == 3:
                    drift.append(max(probs) - min(probs))
        if total:
            repeat[backend] = {"agree": same / total, "n": total,
                               "max_probability_drift": max(drift) if drift else None}
    results["repeat"] = repeat
    return results


def print_table(results: dict[str, Any]) -> None:
    print(f"\n{'task':9s} {'run':12s} {'acc':>6s} {'p50 s':>7s} {'p95 s':>7s} {'err':>4s} {'tok':>6s}")
    for name, task in results["tasks"].items():
        for run_id, run in task["runs"].items():
            lat = run["latency"]
            acc = f"{run['accuracy']:.0%}" if run["accuracy"] is not None else "-"
            if run.get("accuracy_tuned") is not None:
                acc += f" ({run['accuracy_tuned']:.0%})"
            print(f"{name:9s} {run_id:12s} {acc:>6s} {lat.get('p50', 0):7.2f} {lat.get('p95', 0):7.2f} "
                  f"{run['errors']:4d} {lat.get('input_tokens_mean', 0):6.0f}")
    bm = results["tasks"]["faq"]["bm25"]
    print(f"faq       bm25         top1 {bm['top1']:.0%}  mrr@5 {bm['mrr5']:.2f}")
    for backend, rep in results["repeat"].items():
        print(f"repeat    {backend:12s} same answer {rep['agree']:.0%} of {rep['n']}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backends", default="jev,gemini,groq")
    parser.add_argument("--score", action="store_true", help="score the cache only")
    args = parser.parse_args()

    cache = _load_cache()
    if not args.score:
        chosen = [b.strip() for b in args.backends.split(",") if b.strip()]
        await asyncio.gather(*(run_backend(b, cache) for b in chosen))
    results = score(cache)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print_table(results)
    print(f"\nresults: {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

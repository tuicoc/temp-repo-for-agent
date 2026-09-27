"""Turn results.json into one self-contained page.

    cd backend
    .venv/bin/python lab/jev/report.py

Reads ``workbench/reports/jev/results.json`` (from ``run.py``) and, when it
exists, ``verdict.json`` beside this file: the judgement per task, written by
a person after reading the numbers, since a recommendation is not something
to compute. Writes ``workbench/reports/jev/jev-bench.html``.

The page is Vietnamese, like the architecture notes: it is a report to the
team, not product interface. Charts are HTML bars, so their text stays legible
at phone width; the three models are told apart by fill and texture plus a
label, never by colour alone.
"""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parents[1] / "workbench" / "reports" / "jev"
RESULTS = REPORTS / "results.json"
VERDICT = HERE / "verdict.json"
OUT = REPORTS / "jev-bench.html"

SERIES = [
    ("jev:en", "Jev", "s-jev"),
    ("gemini:en", "Gemini 3.5 Flash-Lite", "s-gemini"),
    ("groq:en", "GPT-OSS 20B trên Groq", "s-groq"),
]
TASK_NAMES = {
    "route": "Định tuyến",
    "identity": "Xác nhận danh tính",
    "policy": "Kiểm tra chính sách",
    "faq": "Xếp hạng FAQ",
    "rqr": "Chấm câu hỏi lặp",
}
TASK_METRIC = {
    "route": "đúng trên mọi nhãn (ý định, đòi gặp người, cần tool)",
    "identity": "đúng câu trả lời có xác nhận hay không",
    "policy": "đúng quyết định chặn hay cho qua từng câu nháp",
    "faq": "đoạn đứng đầu đúng, trên 15 câu có đáp án",
    "rqr": "đúng câu hỏi có hỏi lại điều đã biết hay không",
}
FIELD_NAMES = {
    "intent": "Ý định", "wants_human": "Đòi gặp người", "needs_tool": "Cần tra tool",
    "confirms": "Có xác nhận", "asks_known": "Hỏi lại điều đã biết",
    "free_shipping": "Hứa miễn phí ship", "returns": "Hứa đổi trả quá chính sách",
    "claims_human": "Nhận là người", "tier_disclosure": "Lộ thông tin khi chưa xác minh",
    "delivery_promise": "Hứa ngày giao", "price_not_in_tool": "Giá không có trong tool",
    "top1": "Đoạn đứng đầu", "out_of_scope": "Nhận ra ngoài phạm vi",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def num(x: float, digits: int = 2) -> str:
    """Vietnamese decimal comma, to match the prose."""
    return f"{x:.{digits}f}".replace(".", ",")


def secs(x: float | None) -> str:
    return "–" if x is None else (f"{x * 1000:.0f} ms" if x < 1 else f"{num(x)} s")


# ── headline numbers ──────────────────────────────────────────────────────


def headline(task: str, run: dict[str, Any], *, tuned: bool = False) -> float | None:
    """The one accuracy figure per task, as TASK_METRIC words it.

    ``tuned`` uses Jev's leave-one-out thresholds instead of 0.5; for a run
    without them it is the same as untuned.
    """
    items = run["items"]
    if tuned and "accuracy_tuned" not in run:
        return None
    pick = (lambda c: c.get("tuned", c["pred"])) if tuned else (lambda c: c["pred"])
    if task == "policy":
        verdicts = []
        for it in items:
            if not it["checks"] or any(c["pred"] is None for c in it["checks"]):
                verdicts.append(False)
                continue
            verdicts.append(any(c["gold"] for c in it["checks"]) == any(pick(c) for c in it["checks"]))
        return sum(verdicts) / len(verdicts) if verdicts else None
    if task == "faq":
        top = [c for it in items for c in it["checks"] if c["field"] == "top1"]
        return sum(bool(c["ok"]) for c in top) / len(top) if top else None
    return run["accuracy_tuned"] if tuned else run["accuracy"]


def field_stats(run: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    tuned: dict[str, list[bool]] = {}
    for it in run["items"]:
        for c in it["checks"]:
            if "tuned_ok" in c:
                tuned.setdefault(c["field"], []).append(bool(c["tuned_ok"]))
    out = {}
    for field, f in run["fields"].items():
        recall = f["tp"] / (f["tp"] + f["fn"]) if (f["tp"] + f["fn"]) else None
        precision = f["tp"] / (f["tp"] + f["fp"]) if (f["tp"] + f["fp"]) else None
        t = tuned.get(field)
        out[field] = {"acc": f["ok"] / f["n"] if f["n"] else None, "recall": recall, "precision": precision,
                      "tuned": sum(t) / len(t) if t else None}
    return out


# ── pieces ────────────────────────────────────────────────────────────────


def legend() -> str:
    keys = "".join(
        f'<span class="key"><span class="swatch {cls}"></span>{esc(label)}</span>' for _, label, cls in SERIES
    )
    return f'<div class="legend" aria-label="Chú giải">{keys}</div>'


def bar_chart(rows: list[dict[str, Any]], *, maximum: float, unit: str) -> str:
    """Grouped horizontal bars: one group per task, one bar per model.

    ``rows``: {"task", "title", "bars": [(series_class, label, value, tip, extra_tick)], "ref": (value, label)}.
    """
    groups = []
    for row in rows:
        bars = []
        for cls, label, value, tip, tick in row["bars"]:
            if value is None:
                bars.append(f'<div class="bar-row"><span class="bar-label">{esc(label)}</span>'
                            f'<div class="track"></div><span class="bar-value muted">không chạy</span></div>')
                continue
            width = max(0.5, min(100.0, value / maximum * 100))
            tick_html, clipped = "", ""
            if tick is not None:
                left = min(100.0, tick / maximum * 100)
                over = tick > maximum
                tick_html = f'<span class="tick{" over" if over else ""}" style="left:calc({left:.2f}% - 2px)"></span>'
                if over and unit != "pct":
                    clipped = f'<span class="clipped">p95 {secs(tick)}</span>'
            shown = pct(value) if unit == "pct" else secs(value)
            bars.append(
                f'<div class="bar-row"><span class="bar-label">{esc(label)}</span>'
                f'<div class="track"><span class="bar {cls}" style="width:{width:.2f}%" tabindex="0" '
                f'data-tip="{esc(tip)}"></span>{tick_html}</div>'
                f'<span class="bar-value">{shown}{clipped}</span></div>'
            )
        ref = ""
        if row.get("ref"):
            value, label = row["ref"]
            left = min(100.0, value / maximum * 100)
            ref = (f'<div class="bar-row ref"><span class="bar-label">{esc(label)}</span>'
                   f'<div class="track"><span class="ref-line" style="left:{left:.2f}%"></span></div>'
                   f'<span class="bar-value muted">{pct(value)}</span></div>')
        groups.append(f'<div class="group"><div class="group-title">{esc(row["title"])}</div>{"".join(bars)}{ref}</div>')
    return f'<div class="bars">{"".join(groups)}</div>'


def pred_text(check: dict[str, Any]) -> str:
    pred, detail = check["pred"], check["detail"]
    if pred is None:
        return "lỗi"
    if isinstance(pred, bool):
        text = "có" if pred else "không"
        if isinstance(detail, (int, float)) and 0 < detail < 1:
            text += f" ({num(detail)})"
        return text
    if check["field"] == "intent" and isinstance(detail, dict) and detail:
        return f"{pred} ({num(detail.get(pred, 0))})"
    return str(pred)


def gold_text(check: dict[str, Any]) -> str:
    gold = check["gold"]
    if isinstance(gold, bool):
        return "có" if gold else "không"
    if isinstance(gold, list):
        return ", ".join(gold) or "ngoài phạm vi"
    return str(gold)


def misses_table(task: str, runs: dict[str, Any]) -> str:
    present = [(rid, label) for rid, label, _ in SERIES if rid in runs]
    by_run = {rid: {it["id"]: it for it in runs[rid]["items"]} for rid, _ in present}
    first = runs[present[0][0]]["items"]
    body = []
    for item in first:
        per_field: dict[str, dict[str, Any]] = {}
        for rid, _ in present:
            for check in by_run[rid][item["id"]]["checks"]:
                per_field.setdefault(check["field"], {})[rid] = check
        for field, checks in per_field.items():
            if all(c["ok"] for c in checks.values()) and len(checks) == len(present):
                continue
            gold = gold_text(next(iter(checks.values())))
            cells = []
            for rid, _ in present:
                c = checks.get(rid)
                if c is None:
                    cells.append('<td class="muted">–</td>')
                else:
                    mark = "ok" if c["ok"] else "miss"
                    cells.append(f'<td class="{mark}">{esc(pred_text(c))}</td>')
            body.append(
                f'<tr><td class="mono">{esc(item["id"])}</td><td class="said">{esc(item["text"])}'
                f'<div class="why">{esc(item.get("why") or "")}</div></td>'
                f'<td>{esc(FIELD_NAMES.get(field, field))}</td><td>{esc(gold)}</td>{"".join(cells)}</tr>'
            )
    if not body:
        return '<p class="muted">Không model nào sai ca nào.</p>'
    head = "".join(f"<th>{esc(label)}</th>" for _, label in present)
    return (f'<div class="pane"><table><thead><tr><th>Mã</th><th>Nội dung</th><th>Nhãn</th><th>Đúng là</th>'
            f'{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def field_table(runs: dict[str, Any]) -> str:
    present = [(rid, label) for rid, label, _ in SERIES if rid in runs]
    stats = {rid: field_stats(runs[rid]) for rid, _ in present}
    fields = list(runs[present[0][0]]["fields"])
    head = "".join(f"<th>{esc(label)}</th>" for _, label in present)
    rows = []
    for field in fields:
        cells = []
        for rid, _ in present:
            s = stats[rid].get(field) or {}
            extra = f'<div class="sub">bắt được {pct(s.get("recall"))}</div>' if s.get("recall") is not None else ""
            if s.get("tuned") is not None and s.get("tuned") != s.get("acc"):
                extra += f'<div class="sub">ngưỡng chỉnh: {pct(s.get("tuned"))}</div>'
            cells.append(f"<td>{pct(s.get('acc'))}{extra}</td>")
        rows.append(f"<tr><td>{esc(FIELD_NAMES.get(field, field))}</td>{''.join(cells)}</tr>")
    return (f'<div class="pane short"><table class="num"><thead><tr><th>Nhãn</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def variant_table(name: str, task: dict[str, Any]) -> str:
    en, vi = task["runs"].get("jev:en"), task["runs"].get("jev:vi")
    if not (en and vi):
        return ""
    se, sv = field_stats(en), field_stats(vi)
    rows = "".join(
        f"<tr><td>{esc(FIELD_NAMES.get(f, f))}</td><td>{pct(se[f]['acc'])}</td><td>{pct(sv[f]['acc'])}</td></tr>"
        for f in en["fields"]
    )
    return ('<h4>Jev: câu hỏi viết tiếng Anh so với tiếng Việt</h4>'
            f'<div class="pane short"><table class="num"><thead><tr><th>Nhãn</th><th>Tiếng Anh</th>'
            f'<th>Tiếng Việt</th></tr></thead><tbody>{rows}'
            f'<tr class="total"><td>Số chính, ngưỡng 0,5</td><td>{pct(headline(name, en))}</td><td>{pct(headline(name, vi))}</td></tr>'
            f'<tr class="total"><td>Số chính, ngưỡng chỉnh</td><td>{pct(headline(name, en, tuned=True))}</td><td>{pct(headline(name, vi, tuned=True))}</td></tr>'
            f'</tbody></table></div>')


# ── page ──────────────────────────────────────────────────────────────────


def build(results: dict[str, Any], verdict: dict[str, Any]) -> str:
    tasks = results["tasks"]
    order = [t for t in TASK_NAMES if t in tasks and tasks[t]["runs"]]

    calls = results.get("calls") or sum(run["latency"].get("n", 0) for t in tasks.values() for run in t["runs"].values())
    all_lat = {rid: [] for rid, _, _ in SERIES}
    for t in tasks.values():
        for rid in all_lat:
            run = t["runs"].get(rid)
            if run:
                all_lat[rid].extend(it["seconds"] for it in run["items"] if it.get("seconds") and not it.get("error"))

    # Figures row: median latency per model across every task.
    tiles = []
    for rid, label, cls in SERIES:
        values = all_lat[rid]
        med = statistics.median(values) if values else None
        acc = [headline(t, tasks[t]["runs"][rid]) for t in order if rid in tasks[t]["runs"]]
        acc = [a for a in acc if a is not None]
        tuned = [headline(t, tasks[t]["runs"][rid], tuned=True) for t in order if rid in tasks[t]["runs"]]
        tuned = [a for a in tuned if a is not None]
        tuned_line = (f'<div class="tile-sub">{pct(statistics.fmean(tuned))} với ngưỡng chỉnh</div>'
                      if tuned and len(tuned) == len(acc) else "")
        tiles.append(
            f'<div class="tile"><div class="tile-label"><span class="swatch {cls}"></span>{esc(label)}</div>'
            f'<div class="tile-value">{secs(med)}</div><div class="tile-sub">trung vị mỗi lời gọi</div>'
            f'<div class="tile-value small">{pct(statistics.fmean(acc)) if acc else "–"}</div>'
            f'<div class="tile-sub">độ chính xác trung bình của 5 bài</div>{tuned_line}</div>'
        )

    latency_rows, accuracy_rows = [], []
    for t in order:
        runs = tasks[t]["runs"]
        lb, ab = [], []
        for rid, label, cls in SERIES:
            run = runs.get(rid)
            lat = run["latency"] if run else {}
            p50, p95 = lat.get("p50"), lat.get("p95")
            lb.append((cls, label, p50, f"{label} · {TASK_NAMES[t]}: p50 {secs(p50)}, p95 {secs(p95)}, "
                                        f"{lat.get('input_tokens_mean', 0):.0f} token vào", p95))
            acc = headline(t, run) if run else None
            tuned = headline(t, run, tuned=True) if run else None
            tip = f"{label} · {TASK_NAMES[t]}: {pct(acc)}"
            if tuned is not None:
                tip += f", với ngưỡng chỉnh {pct(tuned)}"
            ab.append((cls, label, acc, tip, tuned))
        latency_rows.append({"title": TASK_NAMES[t], "bars": lb})
        ref = ("faq" == t and tasks[t].get("bm25")) and (tasks[t]["bm25"]["top1"], "BM25, không model")
        accuracy_rows.append({"title": TASK_NAMES[t], "bars": ab, "ref": ref or None})
    # The scale follows the medians, not the slowest outlier: a p95 past the
    # edge is drawn at the edge and written out beside the value.
    max_lat = max([b[2] or 0 for r in latency_rows for b in r["bars"]] + [1.0]) * 1.4

    verdict_rows = []
    for t in order:
        v = (verdict.get("tasks") or {}).get(t)
        if not v:
            continue
        verdict_rows.append(
            f'<tr><td>{esc(TASK_NAMES[t])}</td><td><span class="pill pill-{esc(v["kind"])}">{esc(v["decision"])}</span></td>'
            f'<td>{esc(v["reason"])}</td></tr>'
        )
    verdict_html = ""
    if verdict_rows:
        verdict_html = (f'<section><h2>Có nên thay không</h2><p class="lede">{esc(verdict.get("summary", ""))}</p>'
                        f'<div class="pane short"><table class="verdict"><thead><tr><th>Việc</th><th>Kết luận</th>'
                        f'<th>Vì sao</th></tr></thead><tbody>{"".join(verdict_rows)}</tbody></table></div></section>')

    tabs, panels = [], []
    for i, t in enumerate(order):
        task = tasks[t]
        runs = task["runs"]
        extra = ""
        if t == "faq":
            bm = task["bm25"]
            mrr = " · ".join(f"{label}: MRR@5 {num(runs[rid].get('mrr5') or 0)}" for rid, label, _ in SERIES if rid in runs)
            extra = (f'<p class="note">BM25 không dùng model: đứng đầu đúng {pct(bm["top1"])}, MRR@5 {num(bm["mrr5"])}. '
                     f'{esc(mrr)}. Ngoài phạm vi: điểm cao nhất dưới "trả lời một phần" thì coi là không đoạn nào trả lời được.</p>')
        panels.append(
            f'<div class="panel" id="p-{t}" role="tabpanel" {"hidden" if i else ""}>'
            f'<p class="note">{task["n"]} mẫu. Số chính: {esc(TASK_METRIC[t])}.</p>{extra}'
            f'<div class="split"><div><h4>Theo từng nhãn</h4>{field_table(runs)}</div>'
            f'<div>{variant_table(t, task)}</div></div>'
            f'<h4>Những ca có model sai</h4>{misses_table(t, runs)}</div>'
        )
        tabs.append(f'<button class="tab" role="tab" id="tab-{t}" aria-controls="p-{t}" '
                    f'aria-selected="{"true" if i == 0 else "false"}">{esc(TASK_NAMES[t])}</button>')

    rep = results.get("repeat") or {}
    rep_rows = "".join(
        f'<tr><td>{esc(label)}</td><td>{pct(rep[b]["agree"])} trên {rep[b]["n"]} quyết định</td>'
        f'<td>{("xác suất lệch tối đa " + num(rep[b]["max_probability_drift"])) if rep[b].get("max_probability_drift") is not None else "chỉ trả đúng hoặc sai, không có xác suất"}</td></tr>'
        for b, label in (("jev", "Jev"), ("gemini", "Gemini 3.5 Flash-Lite")) if b in rep
    )

    notes = "".join(f"<li>{esc(n)}</li>" for n in verdict.get("method", []))

    return TEMPLATE.format(
        generated=esc(results["generated_at"][:16].replace("T", " ")),
        calls=calls,
        legend=legend(),
        tiles="".join(tiles),
        verdict=verdict_html,
        latency=bar_chart(latency_rows, maximum=max_lat * 1.05, unit="s"),
        accuracy=bar_chart(accuracy_rows, maximum=1.0, unit="pct"),
        tabs="".join(tabs),
        panels="".join(panels),
        repeat=rep_rows,
        notes=notes,
    )


TEMPLATE = """<title>Jev Decision Bench</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap">
<style>
:root {{
  --surface: #FFFFFF; --ink: #000000; --ink-2: #5F6368; --ink-3: #80868B;
  --rule: #E1E3E6; --fill: #F2F3F5; --accent: #2F5D8A;
  --s-jev: #2F5D8A; --s-gemini: #A3AAB2; --s-groq: #5F6368; --track: #F2F3F5;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --surface: #15171A; --ink: #F1F3F4; --ink-2: #AEB3B9; --ink-3: #8A9097;
    --rule: #2C3035; --fill: #1E2125; --accent: #8DB3DB;
    --s-jev: #8DB3DB; --s-gemini: #5C636B; --s-groq: #AEB3B9; --track: #1E2125;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface: #15171A; --ink: #F1F3F4; --ink-2: #AEB3B9; --ink-3: #8A9097;
  --rule: #2C3035; --fill: #1E2125; --accent: #8DB3DB;
  --s-jev: #8DB3DB; --s-gemini: #5C636B; --s-groq: #AEB3B9; --track: #1E2125;
}}
* {{ box-sizing: border-box; }}
body {{ background: var(--surface); color: var(--ink); margin: 0;
  font: 13px/1.55 "Be Vietnam Pro", system-ui, -apple-system, "Segoe UI", sans-serif; }}
.page {{ max-width: 1080px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 56px;
  display: grid; gap: 32px; }}
header h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px; text-wrap: balance; }}
header p {{ margin: 0; color: var(--ink-2); max-width: 72ch; }}
h2 {{ font-size: 13px; font-weight: 600; margin: 0 0 10px; padding-bottom: 8px; border-bottom: 1px solid var(--rule); }}
h4 {{ font-size: 12px; font-weight: 600; margin: 16px 0 8px; color: var(--ink-2); }}
.lede {{ margin: 0 0 12px; max-width: 80ch; }}
.note {{ margin: 0 0 8px; color: var(--ink-2); font-size: 12px; max-width: 90ch; }}
.muted {{ color: var(--ink-3); }}
.mono {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11.5px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.tile {{ border: 1px solid var(--rule); border-radius: 6px; padding: 14px 16px; display: grid; gap: 2px; }}
.tile-label {{ display: flex; align-items: center; gap: 8px; font-weight: 500; margin-bottom: 6px; }}
.tile-value {{ font-size: 20px; font-weight: 600; }}
.tile-value.small {{ margin-top: 8px; }}
.tile-sub {{ color: var(--ink-2); font-size: 11.5px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 0 0 12px; color: var(--ink-2); font-size: 12px; }}
.key {{ display: inline-flex; align-items: center; gap: 6px; }}
.swatch {{ width: 14px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }}
.s-jev {{ background: var(--s-jev); }}
.s-gemini {{ background: var(--s-gemini); }}
.s-groq {{ background-color: var(--surface);
  background-image: repeating-linear-gradient(45deg, var(--s-groq) 0 1.5px, transparent 1.5px 4px);
  box-shadow: inset 0 0 0 1px var(--s-groq); }}
.charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 28px; }}
.chart-title {{ font-weight: 500; margin: 0 0 2px; }}
.chart-sub {{ color: var(--ink-2); font-size: 12px; margin: 0 0 12px; }}
.bars {{ display: grid; gap: 14px; }}
.group-title {{ font-size: 12px; color: var(--ink-2); margin-bottom: 4px; }}
.bar-row {{ display: grid; grid-template-columns: minmax(96px, 150px) 1fr 76px; align-items: center; gap: 8px;
  min-height: 18px; }}
.bar-label {{ font-size: 12px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.track {{ position: relative; height: 12px; background: var(--track); border-radius: 0 3px 3px 0; }}
.bar {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 0 3px 3px 0; outline: none; }}
.bar:hover, .bar:focus-visible {{ filter: brightness(1.12); box-shadow: 0 0 0 2px var(--surface), 0 0 0 3px var(--ink-3); }}
.tick {{ position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--ink); border-radius: 1px; }}
.ref .track {{ background: none; border-top: 1px dashed transparent; }}
.ref-line {{ position: absolute; top: -2px; bottom: -2px; width: 0; border-left: 2px solid var(--ink-3); }}
.bar-value {{ font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }}
.clipped {{ display: block; font-size: 11.5px; color: var(--ink-3); white-space: nowrap; }}
.tick.over {{ width: 3px; }}
.tabs {{ display: flex; flex-wrap: wrap; gap: 4px; border-bottom: 1px solid var(--rule); margin-bottom: 14px; }}
.tab {{ font: inherit; font-size: 12px; background: none; border: 0; border-bottom: 2px solid transparent;
  padding: 8px 10px; color: var(--ink-2); cursor: pointer; }}
.tab[aria-selected="true"] {{ color: var(--ink); border-bottom-color: var(--accent); font-weight: 500; }}
.tab:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.split {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
.pane {{ max-height: 62vh; overflow: auto; border: 1px solid var(--rule); border-radius: 6px; }}
.pane.short {{ max-height: none; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th {{ position: sticky; top: 0; background: var(--surface); text-align: left; font-weight: 500; color: var(--ink-2);
  border-bottom: 1px solid var(--rule); padding: 8px 10px; white-space: nowrap; }}
td {{ border-bottom: 1px solid var(--rule); padding: 8px 10px; vertical-align: top; }}
tbody tr:last-child td {{ border-bottom: 0; }}
table.num td:not(:first-child) {{ font-variant-numeric: tabular-nums; }}
tr.total td {{ font-weight: 600; }}
td.said {{ min-width: 220px; max-width: 420px; }}
.why, .sub {{ color: var(--ink-3); font-size: 11.5px; margin-top: 2px; }}
td.miss {{ font-weight: 500; box-shadow: inset 2px 0 0 var(--accent); }}
td.ok {{ color: var(--ink-2); }}
.pill {{ display: inline-block; font-size: 11.5px; padding: 2px 8px; border-radius: 10px; white-space: nowrap;
  border: 1px solid var(--ink-3); color: var(--ink); }}
.pill-yes {{ background: var(--accent); border-color: var(--accent); color: var(--surface); }}
.pill-both {{ border-color: var(--accent); color: var(--accent); }}
table.verdict td:first-child {{ white-space: nowrap; font-weight: 500; }}
ul.method {{ margin: 0; padding-left: 18px; color: var(--ink-2); max-width: 90ch; display: grid; gap: 4px; }}
.tooltip {{ position: fixed; z-index: 10; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--rule); border-radius: 4px; padding: 6px 8px; font-size: 12px; max-width: 280px; }}
@media (max-width: 520px) {{
  .bar-row {{ grid-template-columns: 1fr 56px; }}
  .bar-label {{ grid-column: 1 / -1; }}
  .track {{ grid-column: 1; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
<div class="page">
<header>
  <h1>Jev so với model sinh chữ</h1>
  <p>Năm quyết định của agent tổng đài, mỗi model trả lời cùng một bộ câu hỏi có kiểu trên cùng dữ liệu mock tiếng Việt,
  toàn ca khó. Đo thời gian mỗi lời gọi và độ chính xác so với nhãn. {calls} lời gọi, chấm lúc {generated} UTC.</p>
</header>
<section class="tiles">{tiles}</section>
{verdict}
<section>
  <h2>Thời gian và độ chính xác theo việc</h2>
  {legend}
  <div class="charts">
    <div><p class="chart-title">Thời gian mỗi lời gọi</p>
      <p class="chart-sub">Thanh là trung vị, vạch đen là p95; p95 vượt khung thì nằm ở mép phải và ghi số bên cạnh.
      Chỉ tính thời gian của lời gọi, không tính thời gian chờ hạn mức.</p>
      {latency}</div>
    <div><p class="chart-title">Độ chính xác</p>
      <p class="chart-sub">Số chính của từng việc, ghi ở phần chi tiết bên dưới. Thanh của Jev dùng ngưỡng 0,5;
      vạch đen là Jev với ngưỡng chọn riêng cho từng câu hỏi bằng leave-one-out.</p>
      {accuracy}</div>
  </div>
</section>
<section>
  <h2>Chi tiết từng việc</h2>
  <div class="tabs" role="tablist">{tabs}</div>
  {panels}
</section>
<section>
  <h2>Hỏi lại có ra cùng câu trả lời không</h2>
  <p class="note">Mười câu định tuyến, mỗi câu chạy ba lần, không dùng cache.</p>
  <div class="pane short"><table><thead><tr><th>Model</th><th>Giống nhau</th><th>Ghi chú</th></tr></thead>
  <tbody>{repeat}</tbody></table></div>
</section>
<section>
  <h2>Cách đo và giới hạn</h2>
  <ul class="method">{notes}</ul>
</section>
</div>
<div class="tooltip" id="tip" hidden></div>
<script>
(() => {{
  const tip = document.getElementById("tip");
  const show = (el, x, y) => {{
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(window.innerWidth - w - 8, x + 12) + "px";
    tip.style.top = Math.max(8, y - h - 10) + "px";
  }};
  document.querySelectorAll(".bar[data-tip]").forEach(el => {{
    el.addEventListener("pointermove", e => show(el, e.clientX, e.clientY));
    el.addEventListener("pointerleave", () => {{ tip.hidden = true; }});
    el.addEventListener("focus", () => {{ const r = el.getBoundingClientRect(); show(el, r.right, r.top); }});
    el.addEventListener("blur", () => {{ tip.hidden = true; }});
  }});
  const tabs = [...document.querySelectorAll(".tab")];
  const select = tab => {{
    tabs.forEach(t => {{
      const on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    }});
  }};
  tabs.forEach(t => t.addEventListener("click", () => select(t)));
  const wanted = location.hash.replace("#", "");
  const start = tabs.find(t => t.id === "tab-" + wanted);
  if (start) select(start);
}})();
</script>
"""


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    verdict = json.loads(VERDICT.read_text(encoding="utf-8")) if VERDICT.exists() else {}
    OUT.write_text(build(results, verdict), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

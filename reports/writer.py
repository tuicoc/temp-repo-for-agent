"""Writing test-run reports to disk so runs can be compared.

Reports live beside this file, one directory per kind of run, because there
will be more kinds than one: a provider comparison today, a golden-set
evaluation later. A directory named for what it reports makes that obvious
without opening anything.

    reports/
      writer.py
      provider-probe/
        20260917-045301.md      the newest run
        20260917-045301.json
        archive/                everything it replaced
          20260917-043103.md

Only the newest run sits at the top level. Writing a new one pushes whatever
was there into ``archive/``, so the current answer is always the one file you
see and the history is still there to diff against.

Charts are Mermaid ``xychart-beta`` blocks rather than images: GitHub renders
Mermaid inline, ``docs/diagrams.md`` already uses it, and a chart that is text
shows up in a diff where a PNG would not.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPORTS_DIR = Path(__file__).resolve().parent
ROOT = REPORTS_DIR.parent


def _num(value: float | int | None, places: int = 2) -> str:
    """Format a measurement, or an em dash when there is not one."""
    if not value:
        return "—"
    return f"{value:.{places}f}"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def run_id(now: datetime | None = None) -> str:
    """A sortable identifier, so a directory listing is chronological."""
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")


def _rotate(directory: Path, keeping: str) -> int:
    """Move every report except *keeping* into ``archive/``. Returns how many."""
    archive = directory / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in directory.glob("*.*"):
        if path.is_dir() or path.stem == keeping:
            continue
        shutil.move(str(path), str(archive / path.name))
        moved += 1
    return moved


def _mermaid_bar(title: str, axis_label: str, pairs: list[tuple[str, float]]) -> str:
    """One bar chart. Empty string when there is nothing to plot."""
    pairs = [(label, value) for label, value in pairs if value]
    if not pairs:
        return ""
    labels = ", ".join(f'"{label}"' for label, _ in pairs)
    values = ", ".join(f"{value:.1f}" for _, value in pairs)
    ceiling = max(1.0, max(value for _, value in pairs) * 1.15)
    return (
        "```mermaid\nxychart-beta\n"
        f'    title "{title}"\n'
        f"    x-axis [{labels}]\n"
        f'    y-axis "{axis_label}" 0 --> {ceiling:.0f}\n'
        f"    bar [{values}]\n```\n"
    )


def _per_model(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse per-prompt rows into one entry per model."""
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = models.setdefault(
            row["model"],
            {
                "provider": row["provider"],
                "ttft": [],
                "total": [],
                "rate": [],
                "ok": 0,
                "failed": 0,
                "scored": 0,
                "passed": 0,
            },
        )
        if row.get("error"):
            entry["failed"] += 1
            continue
        entry["ok"] += 1
        if row.get("passed") is not None:
            entry["scored"] += 1
            entry["passed"] += bool(row["passed"])
        for field in ("ttft", "total"):
            if row.get(field):
                entry[field].append(row[field])
        out_tokens = (row.get("tokens") or [0, 0])[1]
        if out_tokens and row.get("total"):
            entry["rate"].append(out_tokens / row["total"])
    return models


def _recommendation(models: dict[str, dict[str, Any]]) -> list[str]:
    """Name a model to use, and say by what rule.

    Correctness first, then time to first token. A model that answers quickly
    and wrongly is worse than no model, and on the hot path of ``docs/flow.md``
    a customer is waiting, so the tie-break is latency and not throughput.
    """
    usable = [
        (name, entry)
        for name, entry in models.items()
        if entry["failed"] == 0 and entry["scored"] and entry["passed"] == entry["scored"]
    ]
    lines = ["## Recommendation", ""]

    if not usable:
        lines += [
            "No model passed every scored prompt without also failing a call, so "
            "this run does not support a recommendation. Widen the model list or "
            "rerun once the failures below are understood.",
            "",
        ]
        return lines

    ranked = sorted(usable, key=lambda pair: _mean(pair[1]["ttft"]) or float("inf"))
    best, entry = ranked[0]
    ttft = _mean(entry["ttft"])
    lines += [
        f"**Use `{best}` ({entry['provider']}).** It answered every scored prompt "
        f"correctly, failed no calls, and reached a first token in "
        f"{_num(ttft)}s on average — the fastest of the models that were also "
        f"right.",
        "",
        "The rule: correctness first, then time to first token. A model that is "
        "quick and wrong is worse than none, and on the hot path a customer is "
        "waiting, so the tie-break is latency rather than throughput.",
        "",
    ]
    lines += [
        "What this rule cannot see: daily quota. It counts the calls in this "
        "run and nothing else, so a model that is fastest over a handful of "
        "prompts may still be the wrong choice for an evaluation sweep of a "
        "few thousand. Check the failures below for quota refusals before "
        "committing to a provider for bulk work.",
        "",
    ]

    if len(ranked) > 1:
        alternatives = ", ".join(
            f"`{name}` ({_num(_mean(e['ttft']))}s)" for name, e in ranked[1:]
        )
        lines += [f"Also correct, and slower: {alternatives}.", ""]

    recommended = {name for name, _ in usable}
    rejected = [
        (name, entry) for name, entry in models.items() if name not in recommended
    ]
    if rejected:
        lines += ["Not recommended from this run:", ""]
        for name, entry in sorted(rejected):
            if entry["failed"]:
                why = f"{entry['failed']} call(s) failed"
            elif entry["scored"] and entry["passed"] < entry["scored"]:
                why = f"{entry['scored'] - entry['passed']} scored prompt(s) wrong"
            else:
                why = "nothing was scored"
            lines.append(f"- `{name}` — {why}")
        lines.append("")
    return lines


def write(
    results: Sequence[Any],
    prompts: Sequence[Any],
    *,
    kind: str,
    identifier: str | None = None,
    notes: str = "",
) -> tuple[Path, Path]:
    """Write one run's JSON and Markdown reports under ``reports/<kind>/``.

    Anything already there is moved into ``archive/`` first. Returns both paths.
    """
    directory = REPORTS_DIR / kind
    directory.mkdir(parents=True, exist_ok=True)
    identifier = identifier or run_id()
    archived = _rotate(directory, keeping=identifier)

    rows = [asdict(r) if is_dataclass(r) else dict(r) for r in results]
    models = _per_model(rows)

    (directory / f"{identifier}.json").write_text(
        json.dumps(
            {
                "kind": kind,
                "run_id": identifier,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "notes": notes,
                "results": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines: list[str] = [
        f"# {kind}: {identifier}",
        "",
        f"{len(models)} models, {len(prompts)} prompts each, "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC.",
        "",
        "One machine, one day, a free tier. The ranking is indicative; the "
        "absolute numbers will not reproduce elsewhere.",
        "",
    ]
    if notes:
        lines += [notes, ""]
    if archived:
        lines += [f"Replaced {archived} earlier file(s), now under `archive/`.", ""]

    lines += _recommendation(models)

    lines += [
        "## Summary by model",
        "",
        "| model | provider | scored | ok | failed | mean ttft s | mean tok/s |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, entry in sorted(models.items()):
        score = (
            f"{entry['passed']}/{entry['scored']}" if entry["scored"] else "—"
        )
        lines.append(
            f"| `{name}` | {entry['provider']} | {score} | {entry['ok']} "
            f"| {entry['failed']} | {_num(_mean(entry['ttft']))} "
            f"| {_num(_mean(entry['rate']), 0)} |"
        )

    lines += [
        "",
        "## Charts",
        "",
        _mermaid_bar(
            "Output tokens per second (higher is better)",
            "tok/s",
            sorted(
                ((n, _mean(e["rate"])) for n, e in models.items()),
                key=lambda p: p[1] or 0,
                reverse=True,
            ),
        ),
        "",
        _mermaid_bar(
            "Time to first token (lower is better)",
            "seconds",
            sorted(
                ((n, _mean(e["ttft"])) for n, e in models.items()),
                key=lambda p: p[1] or 0,
            ),
        ),
        "",
    ]

    scored = [r for r in rows if r.get("passed") is not None or r.get("error")]
    if scored:
        lines += [
            "## Scored prompts",
            "",
            "| model | prompt | result | detail |",
            "|---|---|---|---|",
        ]
        for row in scored:
            verdict = (
                "error" if row.get("error") else ("pass" if row["passed"] else "FAIL")
            )
            detail = (
                row["error"][:100]
                if row.get("error")
                else ", ".join(row.get("wrong_fields") or []) or "—"
            )
            lines.append(
                f"| `{row['model']}` | {row['prompt_key']} | {verdict} | {detail} |"
            )
        lines.append("")

    lines += [
        "## Every call",
        "",
        "| model | prompt | ttft s | total s | in tok | out tok | tok/s |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        tokens = row.get("tokens") or [0, 0]
        rate = tokens[1] / row["total"] if tokens[1] and row.get("total") else None
        lines.append(
            f"| `{row['model']}` | {row['prompt_key']} "
            f"| {_num(row.get('ttft'))} | {_num(row.get('total'))} "
            f"| {_num(tokens[0], 0)} | {_num(tokens[1], 0)} | {_num(rate, 0)} |"
        )

    failures = [r for r in rows if r.get("error")]
    if failures:
        lines += ["", "## Failures", ""]
        for row in failures:
            lines.append(
                f"- `{row['model']}` {row['prompt_key']}: {row['error']}"
            )

    lines += ["", "## Answers", ""]
    for prompt in prompts:
        lines += [
            f"### {prompt.key} — {prompt.probes}",
            "",
            "> " + prompt.text.strip().replace("\n", "\n> "),
            "",
        ]
        for row in rows:
            if row["prompt_key"] != prompt.key or row.get("error"):
                continue
            lines += [f"**{row['model']}**", "", "```", row["answer"], "```", ""]

    md_path = directory / f"{identifier}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory / f"{identifier}.json", md_path

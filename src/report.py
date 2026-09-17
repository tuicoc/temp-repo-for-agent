"""Writing probe results to disk so runs can be compared.

Two files per run, both under ``reports/``:

- ``<run-id>.json`` — every measurement, for a later run to diff against.
- ``<run-id>.md`` — the same thing readable, with charts.

Charts are Mermaid ``xychart-beta`` blocks rather than images. GitHub renders
Mermaid inline, ``docs/diagrams.md`` already uses it, and a chart that is text
shows up in a diff — a PNG does not, so a regression in a committed chart would
be invisible in review.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"


def _num(value: float | int | None, places: int = 2) -> str:
    """Format a measurement, or an em dash when there is not one."""
    if not value:
        return "—"
    return f"{value:.{places}f}"


def run_id(now: datetime | None = None) -> str:
    """A sortable identifier, so the directory listing is chronological."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S")


def _rows(results: Sequence[Any]) -> list[dict[str, Any]]:
    return [asdict(r) if is_dataclass(r) else dict(r) for r in results]


def _mermaid_bar(title: str, axis_label: str, pairs: list[tuple[str, float]]) -> str:
    """One bar chart. Returns an empty string when there is nothing to plot."""
    pairs = [(label, value) for label, value in pairs if value is not None]
    if not pairs:
        return ""
    labels = ", ".join(f'"{label}"' for label, _ in pairs)
    values = ", ".join(f"{value:.1f}" for _, value in pairs)
    top = max(value for _, value in pairs)
    # Round the axis up so the tallest bar does not touch the top.
    ceiling = max(1.0, top * 1.15)
    return (
        "```mermaid\n"
        "xychart-beta\n"
        f'    title "{title}"\n'
        f"    x-axis [{labels}]\n"
        f'    y-axis "{axis_label}" 0 --> {ceiling:.0f}\n'
        f"    bar [{values}]\n"
        "```\n"
    )


def _per_model(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse per-prompt rows into one entry per model."""
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['provider']}/{row['model']}"
        entry = models.setdefault(
            key, {"ttft": [], "total": [], "rate": [], "ok": 0, "failed": 0}
        )
        if row.get("error"):
            entry["failed"] += 1
            continue
        entry["ok"] += 1
        for field in ("ttft", "total"):
            if row.get(field) is not None:
                entry[field].append(row[field])
        out_tokens = (row.get("tokens") or [0, 0])[1]
        if out_tokens and row.get("total"):
            entry["rate"].append(out_tokens / row["total"])
    return models


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def write(
    results: Sequence[Any],
    prompts: Sequence[Any],
    *,
    identifier: str | None = None,
    notes: str = "",
) -> tuple[Path, Path]:
    """Write the JSON and Markdown reports. Returns both paths."""
    REPORTS_DIR.mkdir(exist_ok=True)
    identifier = identifier or run_id()
    rows = _rows(results)
    models = _per_model(rows)

    json_path = REPORTS_DIR / f"{identifier}.json"
    json_path.write_text(
        json.dumps(
            {
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
        f"# Provider probe {identifier}",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. "
        f"{len(models)} models, {len(prompts)} prompts each.",
        "",
        "Measured on one machine, on one day, on a free tier. Treat the ranking "
        "as indicative and the absolute numbers as not reproducible elsewhere.",
        "",
    ]
    if notes:
        lines += [notes, ""]

    lines += [
        "## Summary by model",
        "",
        "| model | ok | failed | mean ttft s | mean total s | mean tok/s |",
        "|---|---|---|---|---|---|",
    ]
    for name, entry in sorted(models.items()):
        ttft, total, rate = (
            _mean(entry["ttft"]),
            _mean(entry["total"]),
            _mean(entry["rate"]),
        )
        lines.append(
            f"| `{name}` | {entry['ok']} | {entry['failed']} "
            f"| {f'{ttft:.2f}' if ttft else '—'} "
            f"| {f'{total:.2f}' if total else '—'} "
            f"| {f'{rate:.0f}' if rate else '—'} |"
        )

    ranked = sorted(
        ((name, _mean(e["rate"])) for name, e in models.items()),
        key=lambda pair: pair[1] or 0,
        reverse=True,
    )
    lines += [
        "",
        "## Charts",
        "",
        _mermaid_bar(
            "Output tokens per second (higher is better)", "tok/s", ranked
        ),
        "",
        _mermaid_bar(
            "Time to first token (lower is better)",
            "seconds",
            sorted(
                ((name, _mean(e["ttft"])) for name, e in models.items()),
                key=lambda pair: pair[1] or 0,
            ),
        ),
        "",
        "## Every call",
        "",
        "| provider | model | prompt | ttft s | total s | in tok | out tok | tok/s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row.get("error"):
            lines.append(
                f"| {row['provider']} | `{row['model']}` | {row['prompt_key']} "
                f"| — | — | — | — | — |"
            )
            continue
        tokens = row.get("tokens") or [0, 0]
        rate = tokens[1] / row["total"] if tokens[1] and row.get("total") else None
        lines.append(
            f"| {row['provider']} | `{row['model']}` | {row['prompt_key']} "
            f"| {_num(row.get('ttft'))} | {_num(row.get('total'))} "
            f"| {_num(tokens[0], 0)} | {_num(tokens[1], 0)} "
            f"| {_num(rate, 0)} |"
        )

    failures = [r for r in rows if r.get("error")]
    if failures:
        lines += ["", "## Failures", ""]
        for row in failures:
            lines.append(
                f"- `{row['provider']}/{row['model']}` {row['prompt_key']}: "
                f"{row['error']}"
            )

    lines += ["", "## Answers", ""]
    for prompt in prompts:
        lines += [f"### {prompt.key} — {prompt.probes}", "", "> " + prompt.text.strip().replace("\n", "\n> "), ""]
        for row in rows:
            if row["prompt_key"] != prompt.key or row.get("error"):
                continue
            lines += [
                f"**{row['provider']} / {row['model']}**",
                "",
                "```",
                row["answer"],
                "```",
                "",
            ]

    md_path = REPORTS_DIR / f"{identifier}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path

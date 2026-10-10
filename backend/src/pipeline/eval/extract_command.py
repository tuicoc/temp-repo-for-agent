"""One extraction call for the evaluation harness in ``evaluation/``.

``evaluation/eval_harness/model_extractor.py`` runs this as a process per
agent turn: the request arrives on stdin as ``{"config", "prompt"}`` (the
harness's own instructions, ``evaluation/extractor-prompt.txt``, then the
turn's text as ``[INPUT DATA]``), and one JSON line goes to stdout:
``{"raw", "usage"}``, where ``raw`` holds ``{"items": [...]}``.

The model answers through structured output in exactly the harness's item
shape (:class:`Item`, the ``Extraction`` items of
``evaluation-contracts/contracts.schema.json`` with ``source_field`` in place
of the reference the collector derives from it), so its items go to the
harness as they are. Two things are added, both deterministic:

- **Spans.** The harness rejects an item whose ``start``/``end`` is not the
  exact slice of its quote, and a model counts characters badly. Each quote
  is located in its source: kept when it occurs once (``unique_quote_v1``,
  the strategy the harness already uses for memory spans) or when the
  model's offset names one of its occurrences; dropped otherwise, and counted.
  The speaker follows from the source field (``agent_text`` is the agent,
  ``tool_texts/...`` a tool), so it is set from there.
- **Pacing.** Each call is a new process, so the in-process rate limiter
  cannot pace them; a small lock file shared by these processes keeps them
  under the provider's requests per minute in ``config/models.yaml``.

No retry: a failed call is reported, and the harness records it.
"""

import fcntl
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ...llm import token_ledger
from ...llm.factory import LLMFactory

MARKER = "\n[INPUT DATA]\n"


class Item(BaseModel):
    """One atomic observation, in the harness's ``Extraction`` item shape."""

    kind: Literal["question", "claim", "fact_usage"]
    slot_or_field: str = Field(min_length=1, description="The slot a question or fact use is about, or the field a claim states.")
    value: str | int | float | bool | None = Field(
        description="The value: integer VND for money, a string keeping the leading zero for a phone; null when the text gives none.")
    question_type: Literal["open", "confirm"] | None = Field(description="open or confirm for a question; null otherwise.")
    speaker: Literal["agent", "tool", "consultant"]
    source_field: str = Field(description="agent_text, tool_texts/<index> or consultant_texts/<index>.")
    quote: str = Field(description="The exact words from source_field this item rests on.")
    start: int = Field(ge=0, description="Unicode code point where quote starts in source_field.")
    end: int = Field(ge=0, description="Unicode code point where quote ends, exclusive.")
    purpose: str = Field(description="For fact_usage, what the fact was used for; otherwise a short note.")


class Items(BaseModel):
    items: list[Item] = Field(description="Empty only when there is genuinely no question, claim or fact use.")


def main() -> int:
    request = json.loads(sys.stdin.read())
    config = {**request["config"], "max_retries": 0}
    pace(config)
    labeller = LLMFactory.create_llm(config, agent_name="harness-extractor").with_structured_output(Items)
    try:
        labels: Items = labeller.invoke([HumanMessage(content=request["prompt"])])
    except Exception as error:  # noqa: BLE001 - the harness keeps the failed attempt
        print(json.dumps({"raw": None, "error_type": type(error).__name__, "message": str(error)[:300]}))
        return 2
    source = json.loads(request["prompt"].split(MARKER, 1)[1])
    items, dropped = spanned([item.model_dump() for item in labels.items], source)
    spent = token_ledger.snapshot().get("harness-extractor", {})
    print(json.dumps({"raw": json.dumps({"items": items}, ensure_ascii=False), "dropped_items": dropped,
                      "usage": {"input_tokens": spent.get("input"), "output_tokens": spent.get("output")}},
                     ensure_ascii=False))
    return 0


def spanned(items: list[dict[str, Any]], source: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Items whose quote is located in its source, with exact offsets; and how many were not."""
    kept, dropped = [], 0
    for item in items:
        text = field_text(source, item.get("source_field"))
        quote = item.get("quote")
        if not isinstance(text, str) or not isinstance(quote, str) or not quote:
            dropped += 1
            continue
        starts = [m.start() for m in re.finditer(re.escape(quote), text)]
        if len(starts) == 1:
            start = starts[0]
        elif item.get("start") in starts:
            start = item["start"]
        else:
            dropped += 1
            continue
        # The source decides who spoke; the harness rejects a turn where the two disagree.
        speaker = {"agent_text": "agent", "tool_texts": "tool", "consultant_texts": "consultant"}[str(item["source_field"]).split("/")[0]]
        kept.append({**item, "speaker": speaker, "start": start, "end": start + len(quote)})
    return kept, dropped


def field_text(source: dict[str, Any], name: Any) -> str | None:
    """``agent_text``, ``tool_texts/2`` or ``consultant_texts/0`` from the input data."""
    if name == "agent_text":
        return source.get("agent_text")
    if isinstance(name, str) and "/" in name:
        key, _, index = name.partition("/")
        values = source.get(key) if key in ("tool_texts", "consultant_texts") else None
        if isinstance(values, list) and index.isdigit() and int(index) < len(values):
            return values[int(index)]
    return None


def pace(config: dict[str, Any]) -> None:
    """Wait until another call fits in the provider's minute, across processes."""
    limit = (config.get("rate_limits") or {}).get("requests_per_minute")
    if not limit:
        return
    allowed = max(1, int(limit * 0.9))
    path = Path(tempfile.gettempdir()) / f"agent-core-extractor-{config['provider']}.json"
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            stamps = [s for s in json.loads(handle.read() or "[]") if isinstance(s, (int, float))]
        except ValueError:
            stamps = []
        stamps = [s for s in stamps if time.time() - s < 60]
        if len(stamps) >= allowed:
            time.sleep(max(0.0, 60 - (time.time() - stamps[0])) + 0.5)
            stamps = [s for s in stamps if time.time() - s < 60]
        stamps.append(time.time())
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(stamps))


if __name__ == "__main__":
    sys.exit(main())

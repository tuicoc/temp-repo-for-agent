#!/usr/bin/env python3
"""Compare the LLM providers this project might use.

    python examples/probe_providers.py list      models your key can reach
    python examples/probe_providers.py run       latency, tokens and answers
    python examples/probe_providers.py limits    the rate limit, measured

``limits`` exists because the published numbers cannot be trusted. Google's
rate-limit page now tells you to read your own quota in AI Studio instead of
listing figures, NVIDIA's own forum says limits vary per model and are not
published, and the aggregator blogs contradict each other. A number this
project puts in a report has to be one it measured.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

# Run directly from the repository root: the project is not installed, so the
# root has to be importable before `src` can be.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.config_manager import (  # noqa: E402
    ModelsConfig,
    get_models_config,
    get_prompts,
    require_api_key,
)
from src import report  # noqa: E402
from src.schemas import get_schema  # noqa: E402
from src.llm import token_ledger, tracing  # noqa: E402
from src.llm.callback_handler import extract_usage, text_of  # noqa: E402
from src.llm.factory import (  # noqa: E402
    SUPPORTED_PROVIDERS,
    LLMFactory,
    limiter_for,
    limiter_stats,
)

TIMEOUT = 60.0


def num(value: float | int | None, places: int = 2) -> str:
    """Format a measurement, or an em dash when there is not one."""
    if not value:
        return "—"
    return f"{value:.{places}f}"

# Substrings that mark a refusal for hitting a quota rather than a real fault.
RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "quota",
    "resource_exhausted",
    "too many requests",
)


def is_rate_limit(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


# --------------------------------------------------------------------------- #
#  list                                                                        #
# --------------------------------------------------------------------------- #


def discover_models(provider: str, url: str) -> list[str]:
    """Ask a provider which models the current key can use."""
    key = require_api_key(provider)

    if provider == "google_genai":
        # Google takes the key as a query parameter and returns "models/<id>".
        response = httpx.get(url, params={"key": key}, timeout=TIMEOUT)
        response.raise_for_status()
        return sorted(
            entry["name"].removeprefix("models/")
            for entry in response.json().get("models", [])
            if "generateContent" in entry.get("supportedGenerationMethods", [])
        )

    # Groq and NVIDIA both speak the OpenAI listing format.
    response = httpx.get(
        url, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT
    )
    response.raise_for_status()
    return sorted(entry["id"] for entry in response.json().get("data", []))


def cmd_list(config: ModelsConfig, providers: list[str]) -> int:
    failed = False
    for name in providers:
        block = config.provider(name)
        print(f"\n## {block.label}  ({name})")
        try:
            models = discover_models(name, block.models_url)
        except Exception as error:  # noqa: BLE001 - reported, not handled
            failed = True
            print(f"  could not list models: {error}")
            continue
        print(f"  {len(models)} models reachable with your key:\n")
        for model in models:
            print(f"    {model}")
    print("\nPaste the ones worth testing into config/models.yaml.")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
#  run                                                                         #
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    provider: str
    model: str
    prompt_key: str
    ttft: float | None = None
    total: float | None = None
    tokens: tuple[int, int] = field(default=(0, 0))
    queued: float = 0.0
    answer: str = ""
    error: str = ""
    # Only set for a prompt that declares a schema: None means it was judged
    # by reading instead of scored.
    passed: bool | None = None
    wrong_fields: list[str] = field(default_factory=list)

    @property
    def output_tokens_per_second(self) -> float | None:
        if not self.total or not self.tokens[1]:
            return None
        return self.tokens[1] / self.total


def check(value: Any, expected: Any) -> bool:
    """Whether one field of a structured answer is right.

    Strings are compared case-insensitively and stripped, because "M" and "m"
    are the same size and a leading space is not a wrong answer. Numbers are
    compared loosely for the same reason: 28 and 28.0 are one answer.
    """
    if isinstance(expected, bool) or isinstance(value, bool):
        return bool(value) == bool(expected)
    if isinstance(expected, (int, float)) and isinstance(value, (int, float)):
        return abs(float(value) - float(expected)) < 0.01
    return str(value).strip().casefold() == str(expected).strip().casefold()


def run_structured(
    chat, prompt, result: Result, call_config: dict[str, Any]
) -> None:
    """Ask for a validated object and score it against the expected answer."""
    structured = chat.with_structured_output(get_schema(prompt.schema_name))
    messages: list[Any] = []
    if prompt.system:
        messages.append(SystemMessage(content=prompt.system))
    messages.append(HumanMessage(content=prompt.text))

    started = time.perf_counter()
    answer = structured.invoke(messages, config=call_config)
    result.total = time.perf_counter() - started

    if hasattr(answer, "model_dump"):
        answer = answer.model_dump()
    result.answer = json.dumps(answer, ensure_ascii=False, indent=2)

    if prompt.expect:
        result.wrong_fields = [
            f"{key}={answer.get(key)!r} (want {want!r})"
            for key, want in prompt.expect.items()
            if not check(answer.get(key), want)
        ]
        result.passed = not result.wrong_fields


def run_one(
    config: ModelsConfig, provider: str, model: str, prompt, session: str
) -> Result:
    """Stream one prompt, timing the first token and the whole response."""
    result = Result(provider=provider, model=model, prompt_key=prompt.key)
    block = config.llm_config(provider, model)
    try:
        chat = LLMFactory.create_llm(block, agent_name=f"probe:{model}")
        # One session per run groups the whole comparison in Langfuse, and the
        # tags make a single model or a single prompt filterable across runs.
        # Langfuse groups its latency percentiles by generation name and
        # truncates long ones in the table, so the distinguishing part has to
        # come first. "probe-google_genai-json" told us nothing: every Google
        # model collapsed into one row. The model's last path segment is short
        # and unique.
        short_model = model.rsplit("/", 1)[-1]
        call_config = {
            "run_name": f"{short_model}:{prompt.key}",
            "metadata": tracing.trace_metadata(
                session_id=session,
                tags=["probe", provider, prompt.key],
                provider=provider,
                model=model,
                prompt_key=prompt.key,
                probes=prompt.probes,
            ),
        }
        # Wait out our own throttling before starting the stopwatch, so the
        # figure below is the provider's latency and not our queue.
        result.queued = limiter_for(provider, block["rate_limits"]).wait_for_capacity()

        if prompt.schema_name:
            run_structured(chat, prompt, result, call_config)
            return result

        started = time.perf_counter()
        chunks = []
        for chunk in chat.stream(prompt.text, config=call_config):
            if result.ttft is None and getattr(chunk, "content", ""):
                result.ttft = time.perf_counter() - started
            chunks.append(chunk)
        result.total = time.perf_counter() - started

        if chunks:
            merged = chunks[0]
            for chunk in chunks[1:]:
                merged = merged + chunk
            result.answer = text_of(merged)
            result.tokens = extract_usage(merged)
    except Exception as error:  # noqa: BLE001 - every failure is a data point
        result.error = f"{type(error).__name__}: {error}"[:300]
    return result


def cmd_run(
    config: ModelsConfig,
    providers: list[str],
    show_answers: bool,
    only: list[str] | None = None,
) -> int:
    targets = [
        (name, model)
        for name in providers
        for model in config.provider(name).models
        if not only or model in only
    ]
    if not targets:
        print(
            "No models listed in config/models.yaml.\n"
            "Run `python examples/probe_providers.py list` first, then paste the "
            "model names in."
        )
        return 1

    prompts = get_prompts()
    session = f"probe-{report.run_id()}"
    traced, trace_message = tracing.auth_check()
    print(f"  tracing: {trace_message}", file=sys.stderr)

    results: list[Result] = []
    for provider, model in targets:
        for prompt in prompts:
            print(f"  {provider}/{model}  {prompt.key} ...", file=sys.stderr)
            results.append(run_one(config, provider, model, prompt, session))

    # Traces are batched on a background thread, so a script that just exits
    # sends nothing.
    tracing.flush()

    print("\n## Scored prompts\n")
    print("| model | prompt | correct | wrong fields |")
    print("|---|---|---|---|")
    for r in results:
        if r.passed is None and not r.error:
            continue
        verdict = "error" if r.error else ("pass" if r.passed else "FAIL")
        detail = r.error[:80] if r.error else ", ".join(r.wrong_fields) or "—"
        print(f"| `{r.model}` | {r.prompt_key} | {verdict} | {detail} |")

    print("\n## Speed\n")
    print("| provider | model | prompt | ttft s | total s | in tok | out tok | tok/s |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        # A call can succeed and still leave a measurement unset: a model that
        # streams only empty chunks never triggers the first-token timer.
        print(
            f"| {r.provider} | {r.model} | {r.prompt_key} "
            f"| {num(r.ttft)} | {num(r.total)} "
            f"| {num(r.tokens[0], 0)} | {num(r.tokens[1], 0)} "
            f"| {num(r.output_tokens_per_second, 0)} |"
        )

    errors = [r for r in results if r.error]
    if errors:
        print("\n## Failures\n")
        for r in errors:
            print(f"- `{r.provider}/{r.model}` {r.prompt_key}: {r.error}")

    if show_answers:
        print("\n## Answers\n")
        for prompt in prompts:
            print(f"\n### {prompt.key} — {prompt.probes}\n")
            for r in results:
                if r.prompt_key != prompt.key or r.error:
                    continue
                print(f"**{r.provider} / {r.model}**\n")
                print("```")
                print(r.answer)
                print("```\n")

    print("\n## Tokens by model\n")
    print(token_ledger.format_table())

    # attempts vs completed is the number that matters: a gap means calls were
    # made and thrown away, which is what the limiter exists to prevent.
    print("\n## Rate limiter\n")
    print("| provider | attempts | completed | failed | in tok | out tok |")
    print("|---|---|---|---|---|---|")
    for name, s in sorted(limiter_stats().items()):
        print(
            f"| {name} | {s['attempts']} | {s['completed']} | {s['failed']} "
            f"| {s['input_tokens']} | {s['output_tokens']} |"
        )

    notes = (
        f"Langfuse session `{session}`." if traced else "Tracing was not enabled."
    )
    json_path, md_path = report.write(
        results, prompts, identifier=session.removeprefix("probe-"), notes=notes
    )
    print(f"\nSaved {md_path.relative_to(report.ROOT)} and "
          f"{json_path.relative_to(report.ROOT)}")
    return 1 if errors else 0


# --------------------------------------------------------------------------- #
#  limits                                                                      #
# --------------------------------------------------------------------------- #


def cmd_limits(
    config: ModelsConfig, provider: str, model: str, burst: int, concurrency: int
) -> int:
    """Fire a burst of tiny requests and report where the provider pushed back."""
    print(
        f"Sending {burst} requests to {provider}/{model}, {concurrency} at a time.\n"
        f"This consumes quota, and the rate limiter is switched off on purpose:\n"
        f"the point is to reach the ceiling it normally prevents you reaching.\n"
    )
    block = config.llm_config(provider, model)
    block["max_tokens"] = 8

    def one(index: int) -> tuple[int, str]:
        try:
            chat = LLMFactory.create_llm(block, rate_limited=False)
            chat.invoke("Trả lời đúng một từ: xin chào")
            return index, "ok"
        except Exception as error:  # noqa: BLE001
            return index, "rate-limited" if is_rate_limit(error) else f"error: {error}"

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        outcomes = list(pool.map(one, range(burst)))
    elapsed = time.perf_counter() - started

    ok = sum(1 for _, status in outcomes if status == "ok")
    limited = sum(1 for _, status in outcomes if status == "rate-limited")
    failed = [(i, s) for i, s in outcomes if s.startswith("error")]

    print("| metric | value |")
    print("|---|---|")
    print(f"| requests sent | {burst} |")
    print(f"| accepted | {ok} |")
    print(f"| rate-limited | {limited} |")
    print(f"| other failures | {len(failed)} |")
    print(f"| elapsed | {elapsed:.1f} s |")
    if elapsed:
        print(f"| observed throughput | {ok / elapsed * 60:.0f} accepted req/min |")

    if limited:
        print(
            f"\nThe provider refused {limited} of {burst}. The accepted count is a "
            f"lower bound on the per-minute allowance, not the allowance itself. "
            f"Repeat with a larger burst to narrow it, then put the figure in "
            f"config/models.yaml."
        )
    else:
        print(
            f"\nNothing was refused, so the limit is above {burst} requests in "
            f"{elapsed:.1f}s. Raise --burst to find it."
        )

    for index, status in failed[:5]:
        print(f"- request {index}: {status[:200]}")
    return 0


# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="probe_providers",
        description="Compare LLM providers before committing to one.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_provider_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--provider",
            action="append",
            choices=sorted(SUPPORTED_PROVIDERS),
            help="Restrict to one provider. Repeatable. Default: all of them.",
        )

    add_provider_flag(sub.add_parser("list", help="list models your key can reach"))

    run = sub.add_parser("run", help="time the trial prompts and print the answers")
    add_provider_flag(run)
    run.add_argument(
        "--no-answers", action="store_true", help="table only, omit the replies"
    )
    run.add_argument(
        "--model",
        action="append",
        help="Only this model. Repeatable. Useful for a quick check before "
        "spending a full run.",
    )

    limits = sub.add_parser("limits", help="measure the rate limit by hitting it")
    limits.add_argument("--provider", required=True, choices=sorted(SUPPORTED_PROVIDERS))
    limits.add_argument("--model", required=True)
    limits.add_argument("--burst", type=int, default=20)
    limits.add_argument("--concurrency", type=int, default=5)

    args = parser.parse_args(argv)
    config = get_models_config()
    providers = getattr(args, "provider", None) or sorted(config.providers)

    if args.command == "list":
        return cmd_list(config, providers)
    if args.command == "run":
        return cmd_run(
            config, providers, show_answers=not args.no_answers, only=args.model
        )
    return cmd_limits(config, args.provider, args.model, args.burst, args.concurrency)


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for the rate limiter.

The case that matters is the last one. A limiter that only throttles successful
calls is worse than none, because the moment a provider starts returning errors
the limiter stops counting and the retry loop turns into a flood — exactly when
backing off matters most.

Run with:  python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.rate_limiter import AdvancedTokenRateLimiter  # noqa: E402


def limiter(**overrides) -> AdvancedTokenRateLimiter:
    settings = {
        "provider": "test",
        "requests_per_minute": 10,
        "input_tokens_per_minute": 1_000,
        "output_tokens_per_minute": 1_000,
        "input_token_price_per_million": 0.0,
        "output_token_price_per_million": 0.0,
        "buffer_percentage": 0.0,
    }
    settings.update(overrides)
    return AdvancedTokenRateLimiter(**settings)


def test_accepts_calls_below_the_limit():
    rl = limiter(requests_per_minute=5)
    for _ in range(5):
        assert rl.acquire(blocking=False) is True


def test_non_blocking_acquire_refuses_once_the_window_is_full():
    rl = limiter(requests_per_minute=3)
    for _ in range(3):
        assert rl.acquire(blocking=False) is True
    assert rl.acquire(blocking=False) is False


def test_token_usage_counts_towards_the_window():
    rl = limiter(requests_per_minute=100, output_tokens_per_minute=100)
    rl.acquire(blocking=False)
    rl.record_request(input_tokens=0, output_tokens=100)
    assert rl.acquire(blocking=False) is False


def test_blocking_acquire_waits_instead_of_letting_the_call_through():
    # One request per minute, but the window is measured in seconds, so shrink
    # it rather than making the test wait a minute.
    rl = limiter(requests_per_minute=1)
    rl.window_seconds = 0.4
    rl.acquire()
    started = time.perf_counter()
    rl.acquire()
    assert time.perf_counter() - started >= 0.3


def test_failed_calls_still_consume_the_allowance():
    """The regression this file exists for.

    A call that raises never reaches ``on_llm_end``, so nothing reports its
    token usage. If the request itself is only counted on completion, a run
    where every call fails is never throttled at all, and the retry loop
    hammers the provider. The attempt has to be counted when it is made.
    """
    rl = limiter(requests_per_minute=3)

    # Three attempts, none of which ever completes: no record_request call.
    for _ in range(3):
        assert rl.acquire(blocking=False) is True

    assert rl.acquire(blocking=False) is False, (
        "the limiter let a fourth call through after three failures, "
        "so failures are not counted"
    )


def test_a_rate_limit_response_forces_a_cooldown():
    """Being told to slow down should slow us down, not just be logged."""
    rl = limiter(requests_per_minute=100)
    rl.record_rate_limited(retry_after=0.5)
    assert rl.acquire(blocking=False) is False

    time.sleep(0.6)
    assert rl.acquire(blocking=False) is True


def test_stats_separate_attempts_from_completions():
    rl = limiter(requests_per_minute=100)
    rl.acquire(blocking=False)
    rl.acquire(blocking=False)
    rl.record_request(input_tokens=10, output_tokens=5)

    assert rl.total_attempts == 2
    assert rl.total_completed == 1
    assert rl.total_input_tokens == 10
    assert rl.total_output_tokens == 5


@pytest.mark.asyncio
async def test_async_acquire_does_not_block_the_event_loop():
    import asyncio

    rl = limiter(requests_per_minute=1)
    rl.window_seconds = 0.4
    await rl.aacquire()

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    await rl.aacquire()
    task.cancel()

    assert ticks >= 3, (
        "the event loop was blocked while waiting, so aacquire is sleeping "
        "synchronously"
    )


def test_one_limiter_is_shared_across_models_of_a_provider():
    """A limiter created per call cannot remember anything.

    Building a fresh limiter for every model throws away the sliding window and
    the cooldown with it, so a 429 teaches the next call nothing and the run
    walks straight back into the same wall. Quotas are billed per account, so
    the account is the scope.
    """
    from src.llm import factory

    factory._LIMITERS.clear()
    limits = {"requests_per_minute": 30}

    first = factory.limiter_for("groq", limits)
    second = factory.limiter_for("groq", limits)
    other = factory.limiter_for("nvidia", limits)

    assert first is second, "two models on one provider got separate limiters"
    assert first is not other, "two providers are sharing one limiter"

    first.record_rate_limited(retry_after=5)
    assert second.acquire(blocking=False) is False, (
        "a 429 on one model did not hold back the next model on the same account"
    )
    assert other.acquire(blocking=False) is True
    factory._LIMITERS.clear()

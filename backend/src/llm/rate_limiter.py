"""Sliding-window rate limiting for LLM calls.

Taken from the reference project and repaired. The original counted a request
only in ``record_request``, which the token-tracking callback calls from
``on_llm_end`` — that is, only when a call succeeded. A call that raised was
therefore invisible to the limiter, so a run in which every call failed was
never throttled at all and the retry loop hammered the provider. Backing off is
never more necessary than when things are already going wrong.

Three changes follow from that:

- ``acquire`` reserves the slot before the call is made, so an attempt counts
  whether or not it comes back.
- ``record_request`` adds token usage to the window; it no longer counts the
  request, which is already counted.
- ``record_rate_limited`` puts the limiter in a cooldown when a provider says
  429, so being told to slow down actually slows us down.

``aacquire`` also sleeps with asyncio rather than ``time.sleep``, which in the
original stalled the whole event loop — enough to serialise the parallel tool
calls that ``docs/flow.md`` section 6.4 depends on for its latency budget.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any

from langchain_core.rate_limiters import BaseRateLimiter

logger = logging.getLogger("AdvancedTokenRateLimiter")


class AdvancedTokenRateLimiter(BaseRateLimiter):
    """LangChain-compatible rate limiter with sliding-window token tracking."""

    def __init__(
        self,
        provider: str,
        requests_per_minute: int,
        input_tokens_per_minute: int,
        output_tokens_per_minute: int,
        input_token_price_per_million: float,
        output_token_price_per_million: float,
        buffer_percentage: float = 0.1,
    ):
        self.provider = provider
        self.requests_per_minute = requests_per_minute * (1 - buffer_percentage)
        self.input_tokens_per_minute = input_tokens_per_minute * (1 - buffer_percentage)
        self.output_tokens_per_minute = output_tokens_per_minute * (
            1 - buffer_percentage
        )

        self.input_token_price = input_token_price_per_million / 1_000_000
        self.output_token_price = output_token_price_per_million / 1_000_000

        # The width of the sliding window. Only the tests change it, to avoid
        # spending a real minute proving that waiting works.
        self.window_seconds = 60.0

        self.request_timestamps: deque = deque()
        self.input_token_usage: deque = deque()
        self.output_token_usage: deque = deque()

        # Set by record_rate_limited: nothing goes out before this moment.
        self._cooldown_until: float = 0.0

        self.total_attempts: int = 0
        self.total_completed: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost: float = 0.0

        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Factory                                                             #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(
        cls, provider: str, config: dict[str, Any]
    ) -> "AdvancedTokenRateLimiter":
        """Instantiate from a provider config dict (from config/models.yaml)."""
        return cls(
            provider=provider,
            requests_per_minute=config.get("requests_per_minute", 60),
            input_tokens_per_minute=config.get("input_tokens_per_minute", 100_000),
            output_tokens_per_minute=config.get("output_tokens_per_minute", 50_000),
            input_token_price_per_million=config.get(
                "input_token_price_per_million", 0.0
            ),
            output_token_price_per_million=config.get(
                "output_token_price_per_million", 0.0
            ),
        )

    # ------------------------------------------------------------------ #
    #  BaseRateLimiter interface                                           #
    # ------------------------------------------------------------------ #

    def acquire(self, *, blocking: bool = True) -> bool:
        """Claim capacity for one request, waiting for it if asked to.

        Returns True when the caller may proceed. A non-blocking call returns
        False instead of waiting, and claims nothing.
        """
        if not blocking:
            with self._lock:
                if not self._can_proceed_locked(0, 0):
                    return False
                self._reserve_locked()
            return True

        for delay in self._delays():
            time.sleep(delay)
        with self._lock:
            self._reserve_locked()
        return True

    async def aacquire(self, *, blocking: bool = True) -> bool:
        """Async counterpart of :meth:`acquire`.

        Sleeps with asyncio, so waiting here does not stop everything else on
        the loop — which matters because the hot path issues its freshness
        checks concurrently.
        """
        if not blocking:
            return self.acquire(blocking=False)

        for delay in self._delays():
            await asyncio.sleep(delay)
        with self._lock:
            self._reserve_locked()
        return True

    # ------------------------------------------------------------------ #
    #  Recording                                                           #
    # ------------------------------------------------------------------ #

    def wait_if_needed(
        self, input_tokens: int, estimated_output_tokens: int | None = None
    ) -> None:
        """Block until a call of roughly this size fits, then claim its slot."""
        if estimated_output_tokens is None:
            estimated_output_tokens = input_tokens // 2
        for delay in self._delays(input_tokens, estimated_output_tokens):
            time.sleep(delay)
        with self._lock:
            self._reserve_locked()

    def wait_for_capacity(self) -> float:
        """Block until a call would be allowed, without claiming the slot.

        For measuring: the caller can wait here, start its stopwatch, and then
        make the call, so its latency figure is the provider's and not partly
        our own queueing. The slot is claimed by the ``acquire`` that LangChain
        makes on the way out, which now returns at once.

        Returns how long the wait took.
        """
        started = time.perf_counter()
        for delay in self._delays():
            time.sleep(delay)
        return time.perf_counter() - started

    def record_request(self, input_tokens: int, output_tokens: int) -> None:
        """Record the token usage of a call that completed.

        The request itself was already counted by :meth:`acquire`, so this adds
        tokens only. Calling it is optional: a failed call simply never reports
        tokens, and its slot in the window stands.
        """
        with self._lock:
            now = time.time()
            self.input_token_usage.append((now, input_tokens))
            self.output_token_usage.append((now, output_tokens))

            self.total_completed += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

            cost = (input_tokens * self.input_token_price) + (
                output_tokens * self.output_token_price
            )
            self.total_cost += cost

            logger.info(
                "[%s] completed=%d in=%d out=%d cost=$%.6f total=$%.4f",
                self.provider,
                self.total_completed,
                input_tokens,
                output_tokens,
                cost,
                self.total_cost,
            )

    def record_rate_limited(self, retry_after: float | None = None) -> None:
        """Note that the provider refused a call for exceeding its quota.

        Our own accounting was evidently too generous, so hold everything until
        ``retry_after`` (or the rest of the window) has passed rather than
        retrying straight into the same wall.
        """
        wait = retry_after if retry_after and retry_after > 0 else self.window_seconds
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.time() + wait)
        logger.warning(
            "[%s] provider reported a rate limit; holding for %.1fs",
            self.provider,
            wait,
        )

    def record_failure(self) -> None:
        """Note a call that failed for a reason other than the quota.

        Nothing to adjust — the attempt was counted at acquire time, which is
        the whole point — but it keeps the log honest about attempts that
        produced no tokens.
        """
        logger.debug("[%s] call failed without reporting tokens", self.provider)

    # ------------------------------------------------------------------ #
    #  Internal                                                          #
    # ------------------------------------------------------------------ #

    def _reserve_locked(self) -> None:
        """Count one attempt. Caller holds the lock."""
        self.request_timestamps.append(time.time())
        self.total_attempts += 1

    def _clean_old_entries(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self.request_timestamps and self.request_timestamps[0] < cutoff:
            self.request_timestamps.popleft()
        while self.input_token_usage and self.input_token_usage[0][0] < cutoff:
            self.input_token_usage.popleft()
        while self.output_token_usage and self.output_token_usage[0][0] < cutoff:
            self.output_token_usage.popleft()

    @staticmethod
    def _window_sum(queue: deque) -> int:
        return sum(count for _, count in queue)

    def _can_proceed_locked(self, in_tk: int, out_tk: int) -> bool:
        now = time.time()
        if now < self._cooldown_until:
            return False
        self._clean_old_entries(now)
        # Requests are counted exactly, so "one more still fits" is the test.
        # Tokens are not: the size of a reply is unknown until it arrives, so
        # the test is whether any of the budget is left at all. A window that
        # has already spent its full minute of tokens waits, rather than firing
        # one more call of unknown size on top.
        return (
            len(self.request_timestamps) + 1 <= self.requests_per_minute
            and self._window_sum(self.input_token_usage) + in_tk
            < self.input_tokens_per_minute
            and self._window_sum(self.output_token_usage) + out_tk
            < self.output_tokens_per_minute
        )

    def _delays(self, input_tokens: int = 0, estimated_output_tokens: int = 0):
        """Yield how long to sleep, repeatedly, until there is room.

        A generator so the sync and async paths share the arithmetic and differ
        only in how they sleep.
        """
        while True:
            with self._lock:
                if self._can_proceed_locked(input_tokens, estimated_output_tokens):
                    return

                now = time.time()
                wait = max(0.0, self._cooldown_until - now)

                # How long until the oldest entry in each window ages out.
                for queue, is_pair in (
                    (self.request_timestamps, False),
                    (self.input_token_usage, True),
                    (self.output_token_usage, True),
                ):
                    if queue:
                        oldest = queue[0][0] if is_pair else queue[0]
                        wait = max(wait, self.window_seconds - (now - oldest))

                if wait <= 0:
                    # A single request larger than the whole per-minute budget
                    # can never fit. Waiting will not help, so let it go and let
                    # the provider be the one to refuse it.
                    logger.warning(
                        "[%s] one request exceeds the per-minute capacity; "
                        "sending it anyway",
                        self.provider,
                    )
                    return

            logger.info("[%s] rate limit reached, waiting %.2fs", self.provider, wait)
            yield min(wait, self.window_seconds)

    # ------------------------------------------------------------------ #
    #  Reporting                                                           #
    # ------------------------------------------------------------------ #

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "provider": self.provider,
                "attempts": self.total_attempts,
                "completed": self.total_completed,
                "failed": self.total_attempts - self.total_completed,
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "cost_usd": round(self.total_cost, 6),
            }

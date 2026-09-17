import re

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import LLMResult

from . import token_ledger
from .rate_limiter import AdvancedTokenRateLimiter


# Substrings that mark a refusal for exceeding a quota rather than a real fault.
RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "quota",
    "resource_exhausted",
    "too many requests",
)

# "retry after 12s", "retry-after: 12", "try again in 12.5 seconds"
_RETRY_AFTER = re.compile(
    r"(?:retry[- ]?after|try again in)\D{0,4}(\d+(?:\.\d+)?)", re.IGNORECASE
)


def is_rate_limit_error(error: BaseException) -> bool:
    """Whether this exception is the provider saying we are going too fast."""
    text = f"{type(error).__name__}: {error}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def retry_after_seconds(error: BaseException) -> float | None:
    """How long the provider asked us to wait, if it said."""
    match = _RETRY_AFTER.search(str(error))
    return float(match.group(1)) if match else None


def extract_usage(message: BaseMessage) -> tuple[int, int]:
    """Read (input_tokens, output_tokens) off a returned message.

    Current LangChain versions fill ``AIMessage.usage_metadata`` uniformly, so
    that is tried first. ``_from_response_metadata`` remains as a fallback for
    a provider that has not caught up, and is where the per-provider key
    conventions are still handled by hand.
    """
    if not isinstance(message, AIMessage):
        return 0, 0

    meta = getattr(message, "usage_metadata", None)
    if meta:
        return (
            int(meta.get("input_tokens", 0) or 0),
            int(meta.get("output_tokens", 0) or 0),
        )
    return _from_response_metadata(message.response_metadata or {})


def _from_response_metadata(metadata: dict) -> tuple[int, int]:
    """Parse (input_tokens, output_tokens) from any provider's metadata dict.

    Handles the different key conventions across providers:
      - OpenAI-shaped: token_usage    -> prompt_tokens / completion_tokens
      - Anthropic     : usage          -> input_tokens  / output_tokens
      - Gemini        : usage_metadata -> prompt_token_count / candidates_token_count
    """
    usage = metadata.get("token_usage") or metadata.get("usage") or {}
    if usage:
        input_t = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        output_t = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        if input_t or output_t:
            return int(input_t), int(output_t)

    gemini = metadata.get("usage_metadata") or {}
    if gemini:
        return (
            int(gemini.get("prompt_token_count", 0) or 0),
            int(gemini.get("candidates_token_count", 0) or 0),
        )

    return 0, 0


class TokenTrackingCallback(BaseCallbackHandler):
    """Updates the rate limiter with actual token usage after each LLM call,
    and attributes that usage to the owning agent in the process-wide ledger.

    Each agent builds its own callback (with its ``agent_name``) when it builds
    its model through ``LLMFactory.create_llm``, so per-agent token totals fall
    out for free.
    """

    def __init__(
        self, rate_limiter: AdvancedTokenRateLimiter, agent_name: str = ""
    ) -> None:
        self.rate_limiter = rate_limiter
        self.agent_name = agent_name or "unknown"

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Extract token usage from the LLM response and record it.

        Args:
            response: The LLMResult returned by LangChain after invocation.
        """
        input_tokens, output_tokens = self._tokens_from(response)
        if input_tokens or output_tokens:
            self.rate_limiter.record_request(input_tokens, output_tokens)
            token_ledger.record(self.agent_name, input_tokens, output_tokens)

    @staticmethod
    def _tokens_from(response: LLMResult) -> tuple[int, int]:
        """Prefer the message's own usage_metadata, fall back to llm_output.

        Chat models attach usage to the generated message; ``llm_output`` is
        left empty by several providers, which is why the message is read first.
        """
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                if message is None:
                    continue
                input_t, output_t = extract_usage(message)
                if input_t or output_t:
                    return input_t, output_t

        if response.llm_output:
            return _from_response_metadata(response.llm_output)
        return 0, 0

    def on_llm_error(self, error: BaseException, **kwargs) -> None:
        """Handle a call that raised.

        Without this the limiter hears nothing about failures. The attempt is
        already counted — ``acquire`` reserved its slot before the call went
        out — but a 429 says our own accounting was too generous, so it also
        triggers a cooldown instead of letting a retry run straight back into
        the same wall.
        """
        if is_rate_limit_error(error):
            self.rate_limiter.record_rate_limited(retry_after_seconds(error))
        else:
            self.rate_limiter.record_failure()


# Block types that carry a model's private reasoning rather than its answer.
_THINKING_TYPES = {"thinking", "reasoning", "redacted_thinking", "reasoning_content"}


def text_of(message: BaseMessage) -> str:
    """The answer as a plain string, whatever shape the provider used.

    ``message.content`` is a string for most providers, but Gemini 3.x returns
    a list of content blocks and reasoning models put their scratchpad in that
    list too. Taking ``str(content)`` therefore yields a Python repr of a list,
    and sometimes a fragment of the model thinking out loud instead of the
    answer. Both were observed in a probe run.

    Thinking blocks are dropped: a block whose type says so, and a block
    carrying a ``signature`` in its extras, which is how Gemini marks one.
    """
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()

    parts: list[str] = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        if block.get("type") in _THINKING_TYPES:
            continue
        if "signature" in (block.get("extras") or {}):
            continue
        text = block.get("text")
        if text:
            parts.append(text)
    return "".join(parts).strip()

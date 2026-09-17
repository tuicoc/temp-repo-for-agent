"""Creates LangChain chat-model instances from a provider config block.

Same shape and same responsibilities as the reference project's factory: read a
config block, attach a rate limiter and a token-tracking callback, hand back a
``BaseChatModel``. Two things are done differently, both for stated reasons.

**Provider dispatch.** The reference dispatches with a chain of
``if provider == "openai" ... elif provider == "gemini"``, so every new
provider edits the factory. LangChain's ``init_chat_model`` already performs
that dispatch, and ``docs/flow.md`` section 10 specifies it, so a provider here
is a line in ``config/models.yaml`` rather than a branch of code.

**The API key is not passed.** Each integration reads its own key from the
environment, and ``config_manager`` has already loaded ``.env``. The factory
only checks the key is present, so a missing one fails immediately with the
variable name instead of surfacing as the provider's own error later.

Embeddings are not built here yet. They arrive with the retrieval work; adding
them is another ``init_chat_model``-style call in this same file.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from ..config.config_manager import require_api_key
from . import tracing
from .callback_handler import TokenTrackingCallback
from .rate_limiter import AdvancedTokenRateLimiter

# Provider ids understood by init_chat_model, mapped to the package that
# provides each one, so a missing install can be reported usefully.
SUPPORTED_PROVIDERS = {
    "google_genai": "langchain-google-genai",
    "groq": "langchain-groq",
    "nvidia": "langchain-nvidia-ai-endpoints",
}

# Providers whose client accepts max_retries. ChatNVIDIA does not: it forwards
# unrecognised keyword arguments into the request body, so the server rejects
# the whole call with "Unsupported parameter(s): max_retries". Found by running
# the probe, which failed all twelve NVIDIA calls.
ACCEPTS_MAX_RETRIES = {"google_genai", "groq"}

# One limiter per provider, shared by every model built for it.
#
# A limiter created per call is no limiter at all: its sliding window and its
# cooldown are thrown away with the object, so a 429 teaches the next call
# nothing. Quotas are billed per account, so the account is the right scope.
_LIMITERS: dict[str, AdvancedTokenRateLimiter] = {}
_LIMITERS_LOCK = Lock()


def limiter_for(provider: str, config: dict[str, Any]) -> AdvancedTokenRateLimiter:
    """The shared limiter for *provider*, created on first use."""
    with _LIMITERS_LOCK:
        if provider not in _LIMITERS:
            _LIMITERS[provider] = AdvancedTokenRateLimiter.from_config(
                provider=provider, config=config
            )
        return _LIMITERS[provider]


def limiter_stats() -> dict[str, dict[str, Any]]:
    """What each provider's limiter has seen this run."""
    with _LIMITERS_LOCK:
        return {name: rl.stats() for name, rl in _LIMITERS.items()}


class LLMFactory:
    """Builds chat models from config blocks."""

    @staticmethod
    def create_llm(
        config: dict[str, Any],
        agent_name: str = "",
        *,
        rate_limited: bool = True,
    ) -> BaseChatModel:
        """Build a chat model from a provider config block.

        Args:
            config: Keys ``provider`` and ``model`` are required. ``temperature``,
                ``max_tokens``, ``timeout`` and ``rate_limits`` are optional.
            agent_name: Tags the token-tracking callback, so per-agent totals
                accrue in ``token_ledger``.
            rate_limited: Set False to skip the limiter. Only the rate-limit
                probe does this: it has to be allowed to hit the ceiling, which
                is the one thing the limiter exists to prevent.

        Returns:
            A configured ``BaseChatModel``.
        """
        provider = str(config.get("provider", "")).lower()
        model = config.get("model")

        if provider not in SUPPORTED_PROVIDERS:
            known = ", ".join(sorted(SUPPORTED_PROVIDERS))
            raise ValueError(
                f"Unsupported provider {provider!r}. Supported: {known}"
            )
        if not model:
            raise ValueError("'model' must be specified in the LLM config block.")

        # Raises naming the environment variable if the key is absent. The value
        # is not used here; the integration reads it from the environment.
        require_api_key(provider)

        kwargs: dict[str, Any] = {}
        callbacks: list[Any] = []

        if rate_limited:
            limiter = limiter_for(provider, config.get("rate_limits") or {})
            kwargs["rate_limiter"] = limiter
            callbacks.append(TokenTrackingCallback(limiter, agent_name=agent_name))

            # The SDKs retry internally, underneath LangChain, where neither the
            # limiter nor its callbacks can see it. One attempt per call keeps
            # every request visible to the limiter, which is the only thing that
            # can space them out.
            if provider in ACCEPTS_MAX_RETRIES:
                kwargs["max_retries"] = config.get("max_retries", 0)

        # None when Langfuse is not configured, which is the normal case for a
        # teammate who has not signed up.
        if (trace_handler := tracing.handler()) is not None:
            callbacks.append(trace_handler)

        if callbacks:
            kwargs["callbacks"] = callbacks

        # Some reasoning models reject temperature outright, so it is only sent
        # when the config asks for it.
        if config.get("temperature") is not None:
            kwargs["temperature"] = config["temperature"]
        if config.get("max_tokens") is not None:
            kwargs["max_tokens"] = config["max_tokens"]
        if config.get("timeout") is not None:
            kwargs["timeout"] = config["timeout"]

        try:
            return init_chat_model(model, model_provider=provider, **kwargs)
        except ImportError as error:
            package = SUPPORTED_PROVIDERS[provider]
            raise ImportError(
                f"Provider {provider!r} needs {package}. "
                f"Run: pip install -r requirements.txt"
            ) from error

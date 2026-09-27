"""Configuration management.

Same job as the reference project's ``config_manager``: find the YAML, load it,
and give the rest of the code a typed way in. Secrets are handled differently,
for a reason worth writing down.

The reference wrote ``${OPENAI_API_KEY}`` into its YAML, expanded it at load
with ``os.path.expandvars``, then replaced anything still unresolved with
``None``. A forgotten variable therefore became a ``None`` that travelled
quietly until some provider call failed with a confusing message.

Here the YAML holds no secrets and no placeholders. ``.env`` is loaded once,
into the environment, and each LangChain integration reads its own key from
there. :func:`require_api_key` is the one checkpoint, and it raises at the
moment a provider is requested, naming the variable that is missing.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# This file is at <root>/src/config/config_manager.py.
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
MODELS_YAML = CONFIG_DIR / "models.yaml"
LANES_YAML = CONFIG_DIR / "lanes.yaml"

# Loaded once, here. override=False leaves a variable that is already set
# alone, so an IDE run configuration, the shell and CI can each override .env
# without anyone editing the file.
load_dotenv(ROOT / ".env", override=False)


def btc_data_dir() -> Path:
    """The organisers' pack: catalogue, CRM seed, policy corpus, reference mock.

    ``docs/design.md`` Appendix A makes it the grading contract, and section
    6.1 has the catalogue, CRM and order servers wrap its ``mock_tools.py``.
    Its data folders are committed under ``data/btc`` so a clone and the
    deployed service both run without it; ``BTC_DATA_DIR`` points elsewhere,
    at a newer pack, without editing the repository.
    """
    raw = os.environ.get("BTC_DATA_DIR")
    return Path(raw).expanduser().resolve() if raw else ROOT / "data" / "btc"

# Provider id -> the environment variable holding its key. For the chat
# providers it is the one each LangChain integration reads by itself; the
# gateway has no integration, so src/llm/jev.py reads it through here.
PROVIDER_ENV_VAR = {
    "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "vercel_gateway": "AI_GATEWAY_API_KEY",
}


class Secrets(BaseSettings):
    """API keys, read from the environment.

    All optional: a run that touches one provider should not demand keys for
    the other two. The check happens at the point of use instead.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    google_api_key: str | None = None
    groq_api_key: str | None = None
    nvidia_api_key: str | None = None
    ai_gateway_api_key: str | None = None


class RateLimits(BaseModel):
    """What one provider is believed to allow, per minute.

    Defaults are deliberately cautious. Replace them with what was actually
    measured against the provider, not with a number from a blog post: Google's own rate-limit page no longer publishes figures,
    and NVIDIA states that limits vary per model and are unpublished.
    """

    requests_per_minute: int = 30
    input_tokens_per_minute: int = 100_000
    output_tokens_per_minute: int = 50_000
    input_token_price_per_million: float = 0.0
    output_token_price_per_million: float = 0.0


class RateLimiterSettings(BaseModel):
    """How the shared limiter behaves. One policy for the whole process.

    Not per provider: the reason for leaving headroom is that our count and the
    provider's never agree exactly, and that is true of all of them.
    """

    model_config = {"extra": "forbid"}

    buffer_percentage: float = Field(
        ge=0.0,
        lt=1.0,
        description="Fraction of every published limit left unused",
    )


class Generation(BaseModel):
    """The parameters of one model call.

    Every field is optional here so that a provider or an agent can override
    one number without restating the rest. The values themselves live in
    ``config/models.yaml``: ``defaults`` supplies each one, a provider block
    narrows it where the provider forces our hand, and an agent block sets what
    that agent needs. Nothing falls back to a number written in Python, which
    is the point — a hard number in code is a number nobody can find.

    Three rules the loader enforces, each for a failure already seen:

    - **Unknown keys are refused.** ``max_token:`` for ``max_tokens:`` would
      otherwise be ignored in silence and the call would run on the default,
      which is exactly the class of bug this block exists to prevent.
    - **Every field must be set somewhere.** A field nobody sets raises at
      load, rather than quietly handing the decision to the provider.
    - **An explicit ``null`` means "do not send this one".** ``ChatNVIDIA``
      forwards unrecognised keyword arguments into the request body, so
      ``max_retries`` has to be absent for it rather than zero.
    """

    model_config = {"extra": "forbid"}

    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None

    def merge(self, other: "Generation") -> "Generation":
        """This block, with everything *other* actually states laid over it.

        "States" means present in the YAML, so an explicit ``null`` overrides a
        number, which a plain "is it None" test could not express.
        """
        return Generation(
            **{
                **self.model_dump(exclude_unset=True),
                **other.model_dump(exclude_unset=True),
            }
        )


class ProviderConfig(BaseModel):
    """One provider block from ``config/models.yaml``."""

    label: str
    models_url: str = Field(description="Endpoint that lists the available models")
    models: list[str] = Field(default_factory=list)
    rate_limits: RateLimits = Field(default_factory=RateLimits)
    # What this provider forces on every agent routed to it. Keep it to the
    # fields the provider genuinely constrains; preferences belong to the agent.
    generation: Generation = Field(default_factory=Generation)
    # A ceiling this provider will not accept in a single request, as opposed
    # to what an agent would like. Set it only where the provider rejects the
    # request outright; the smaller of this and the agent's max_tokens is sent.
    max_output_tokens: int | None = None


class AgentModel(BaseModel):
    """Which model one agent uses, and what that agent needs from a call."""

    provider: str
    model: str
    generation: Generation = Field(default_factory=Generation)


class EvaluationProvider(BaseModel):
    """A service that hosts evaluation models: typed answers, no text."""

    model_config = {"extra": "forbid"}

    label: str
    base_url: str
    models_url: str
    models: list[str] = Field(default_factory=list)
    zero_data_retention: bool = True
    rate_limits: RateLimits = Field(default_factory=RateLimits)


class Evaluator(BaseModel):
    """Which evaluation model one component asks, and how long it waits."""

    model_config = {"extra": "forbid"}

    provider: str
    model: str
    timeout: float = Field(gt=0, description="Seconds before the caller falls back")


class VoiceConfig(BaseModel):
    """The local voice models a call starts with (``docs/design.md`` 4.11)."""

    model_config = {"extra": "forbid"}

    asr: str = "zipformer-30m"
    endpointing: str = "smart"
    barge_in_ms: int = Field(default=400, ge=100, le=2000)
    min_interruption_words: int = Field(default=2, ge=0, le=6)
    false_interruption_ms: int = Field(default=2500, ge=500, le=10000)
    tts: str = "vieneu:"
    lexicon: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(BaseModel):
    """All of ``config/models.yaml``."""

    defaults: Generation
    rate_limiter: RateLimiterSettings
    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentModel] = Field(default_factory=dict)
    evaluation_providers: dict[str, EvaluationProvider] = Field(default_factory=dict)
    evaluators: dict[str, Evaluator] = Field(default_factory=dict)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)

    def evaluator_config(self, name: str) -> dict[str, Any]:
        """The resolved block for evaluator *name*, ready for ``src.llm.jev``.

        Refuses a model its provider does not list, for the same reason the
        Admin page does: a model nobody put in the file is one nobody checked.
        """
        try:
            routing = self.evaluators[name]
        except KeyError:
            known = ", ".join(sorted(self.evaluators)) or "none"
            raise KeyError(
                f"No evaluation model configured for {name!r} in {MODELS_YAML}. "
                f"Configured: {known}"
            ) from None
        try:
            block = self.evaluation_providers[routing.provider]
        except KeyError:
            known = ", ".join(sorted(self.evaluation_providers)) or "none"
            raise KeyError(
                f"Evaluation provider {routing.provider!r} is not in {MODELS_YAML}. "
                f"Known: {known}"
            ) from None
        if routing.model not in block.models:
            raise ValueError(
                f"{MODELS_YAML}: {routing.model!r} is not listed under "
                f"evaluation_providers.{routing.provider}.models"
            )
        return {
            "provider": routing.provider,
            "model": routing.model,
            "base_url": block.base_url.rstrip("/"),
            "timeout": routing.timeout,
            "zero_data_retention": block.zero_data_retention,
            "rate_limits": {
                **block.rate_limits.model_dump(),
                "buffer_percentage": self.rate_limiter.buffer_percentage,
            },
        }

    def agent(self, name: str) -> AgentModel:
        try:
            return self.agents[name]
        except KeyError:
            known = ", ".join(sorted(self.agents)) or "none"
            raise KeyError(
                f"No model configured for agent {name!r} in {MODELS_YAML}. "
                f"Configured agents: {known}"
            ) from None

    def agent_llm_config(self, name: str) -> dict[str, Any]:
        """The config block for *name*, ready for ``LLMFactory.create_llm``."""
        routing = self.agent(name)
        return self.llm_config(routing.provider, routing.model, agent=name)

    def provider(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError:
            known = ", ".join(sorted(self.providers))
            raise KeyError(
                f"Provider {name!r} is not in {MODELS_YAML}. Known: {known}"
            ) from None

    def llm_config(
        self, provider: str, model: str, agent: str | None = None
    ) -> dict[str, Any]:
        """Build the config block ``LLMFactory.create_llm`` expects.

        Three layers, each narrower than the last: the system ``defaults``, then
        what the provider forces, then what the agent asks for. Passing *agent*
        is what keeps an agent's own numbers with it when the model picker sends
        it to a different provider, rather than silently reverting to defaults.
        """
        block = self.provider(provider)

        generation = self.defaults.merge(block.generation)
        if agent is not None:
            generation = generation.merge(self.agent(agent).generation)

        unset = [
            field
            for field in Generation.model_fields
            if field not in generation.model_fields_set
        ]
        if unset:
            raise ValueError(
                f"{MODELS_YAML}: {', '.join(unset)} is not set for "
                f"{agent or provider}. Give it a value under `defaults:`, under "
                f"the provider, or under the agent — or write `null` to send "
                f"the call without it."
            )

        settings = generation.model_dump()
        ceiling = block.max_output_tokens
        wanted = settings["max_tokens"]
        if ceiling is not None and wanted is not None and wanted > ceiling:
            # The agent asked for more than the provider will accept. Saying so
            # out loud matters: the alternative is a call refused for a reason
            # that appears nowhere near the number that caused it.
            logger.info(
                "%s caps a single request at %d output tokens; %s asked for %d",
                provider,
                ceiling,
                agent or model,
                wanted,
            )
            settings["max_tokens"] = ceiling

        return {
            "provider": provider,
            "model": model,
            **settings,
            "rate_limits": {
                **block.rate_limits.model_dump(),
                "buffer_percentage": self.rate_limiter.buffer_percentage,
            },
        }


@lru_cache(maxsize=1)
def secrets() -> Secrets:
    """The process-wide secrets, read once."""
    return Secrets()


def has_api_key(provider: str) -> bool:
    """Whether this provider is usable, without raising.

    The model picker needs to ask rather than find out: offering a model whose
    key is absent turns a choice into an error the person cannot act on.
    """
    field = PROVIDER_ENV_VAR.get(provider)
    return bool(field and getattr(secrets(), field.lower(), None))


def require_api_key(provider: str) -> str:
    """Return the key for *provider*, or say exactly what is missing."""
    env_var = PROVIDER_ENV_VAR.get(provider)
    if env_var is None:
        known = ", ".join(sorted(PROVIDER_ENV_VAR))
        raise KeyError(f"Unknown provider {provider!r}. Known providers: {known}")

    value = getattr(secrets(), env_var.lower())
    if not value:
        raise RuntimeError(
            f"{env_var} is not set, so provider {provider!r} cannot be used.\n"
            f"Add it to {ROOT / '.env'} (see .env.example), or set it in your "
            f"IDE run configuration. Run `python setup.py` to check."
        )
    return value


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def get_models_config() -> ModelsConfig:
    """Parse ``config/models.yaml``, validating its shape."""
    return ModelsConfig.model_validate(_load_yaml(MODELS_YAML))


@lru_cache(maxsize=1)
def get_lanes() -> dict[str, frozenset[str]]:
    """Parse ``config/lanes.yaml``: lane name to the tools it may call."""
    raw = _load_yaml(LANES_YAML).get("lanes") or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{LANES_YAML}: 'lanes' must be a mapping of lane to tool list")
    return {str(lane): frozenset(str(t) for t in (tools or [])) for lane, tools in raw.items()}

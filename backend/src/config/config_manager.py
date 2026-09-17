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

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file is at <root>/src/config/config_manager.py.
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
MODELS_YAML = CONFIG_DIR / "models.yaml"
PROMPTS_YAML = CONFIG_DIR / "probe_prompts.yaml"

# Loaded once, here. override=False leaves a variable that is already set
# alone, so an IDE run configuration, the shell and CI can each override .env
# without anyone editing the file.
load_dotenv(ROOT / ".env", override=False)

# LangChain provider id -> the environment variable that integration reads.
PROVIDER_ENV_VAR = {
    "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
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


class RateLimits(BaseModel):
    """What one provider is believed to allow, per minute.

    Defaults are deliberately cautious. Replace them with what
    ``examples/probe_providers.py limits`` actually measured, not with a number
    from a blog post: Google's own rate-limit page no longer publishes figures,
    and NVIDIA states that limits vary per model and are unpublished.
    """

    requests_per_minute: int = 30
    input_tokens_per_minute: int = 100_000
    output_tokens_per_minute: int = 50_000
    input_token_price_per_million: float = 0.0
    output_token_price_per_million: float = 0.0


class ProviderConfig(BaseModel):
    """One provider block from ``config/models.yaml``."""

    label: str
    models_url: str = Field(description="Endpoint that lists the available models")
    models: list[str] = Field(default_factory=list)
    rate_limits: RateLimits = Field(default_factory=RateLimits)
    # Seconds before a single call is abandoned. Without one, a model that
    # stops producing tokens mid-stream blocks the whole run indefinitely.
    timeout: float = 60.0
    # Groq rejects a request whose *expected* output exceeds the model's
    # per-minute output allowance, and the default expectation is 2048 tokens.
    # Capping it keeps short prompts from being refused before they are tried.
    max_tokens: int = 512


class AgentModel(BaseModel):
    """Which model one agent uses."""

    provider: str
    model: str


class ModelsConfig(BaseModel):
    """All of ``config/models.yaml``."""

    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentModel] = Field(default_factory=dict)

    def agent_llm_config(self, agent: str) -> dict[str, Any]:
        """The config block for *agent*, ready for ``LLMFactory.create_llm``."""
        try:
            routing = self.agents[agent]
        except KeyError:
            known = ", ".join(sorted(self.agents)) or "none"
            raise KeyError(
                f"No model configured for agent {agent!r} in {MODELS_YAML}. "
                f"Configured agents: {known}"
            ) from None
        return self.llm_config(routing.provider, routing.model)

    def provider(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError:
            known = ", ".join(sorted(self.providers))
            raise KeyError(
                f"Provider {name!r} is not in {MODELS_YAML}. Known: {known}"
            ) from None

    def llm_config(self, provider: str, model: str) -> dict[str, Any]:
        """Build the config block ``LLMFactory.create_llm`` expects."""
        block = self.provider(provider)
        return {
            "provider": provider,
            "model": model,
            "timeout": block.timeout,
            "max_tokens": block.max_tokens,
            "rate_limits": block.rate_limits.model_dump(),
        }


class Prompt(BaseModel):
    """One trial prompt from ``config/probe_prompts.yaml``.

    A prompt with a ``schema`` is asked for structured output instead of free
    text: LangChain binds the schema, the provider returns a validated object,
    and ``expect`` says what a right answer looks like. That turns "does this
    model reason well" from something to eyeball into something to score.

    A prompt without one is judged by reading it, which is the right treatment
    for tone.
    """

    key: str
    probes: str
    text: str
    schema_name: str | None = Field(default=None, alias="schema")
    system: str | None = None
    expect: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


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
def get_prompts() -> tuple[Prompt, ...]:
    """Parse ``config/probe_prompts.yaml``."""
    raw = _load_yaml(PROMPTS_YAML)
    return tuple(Prompt.model_validate(item) for item in raw.get("prompts", []))

"""What an operator may change in this process, from the Admin page.

The advisor's model and temperature, the voice channel's recogniser,
endpointing, barge-in threshold and voice, and the business day calls run
on. None of it is written back to ``config/models.yaml``: the file is the
record of what a deployment runs, and a runtime change is an experiment by
the person at the console. A restart returns to the file.

The business day exists because the organisers' catalogue, promotions and
stock are written for 2026-10-15 (``docs/design.md`` Appendix A): a live call
on today's wall clock would find October's promotions not yet started. It
defaults to that date; advancing it is how a demo shows call 2 two days
after call 1, the way the evaluation runner does with ``days_later``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from ..components.clock import REFERENCE_DAY
from ..config.config_manager import get_models_config


@dataclass(frozen=True)
class Voice:
    asr: str
    endpointing: str
    barge_in_ms: int
    min_interruption_words: int
    false_interruption_ms: int
    tts: str


@dataclass
class Options:
    advisor: dict[str, Any] = field(default_factory=dict)
    voice: Voice | None = None
    business_day: str = REFERENCE_DAY


_options = Options()


def advisor_overrides() -> dict[str, Any]:
    return dict(_options.advisor)


def set_advisor(provider: str | None, model: str | None, temperature: float | None) -> None:
    _options.advisor.clear()
    if provider and model:
        _options.advisor.update(provider=provider, model=model)
    if temperature is not None:
        _options.advisor["temperature"] = temperature


def voice() -> Voice:
    if _options.voice is None:
        config = get_models_config().voice
        return Voice(config.asr, config.endpointing, config.barge_in_ms, config.min_interruption_words,
                     config.false_interruption_ms, config.tts)
    return _options.voice


def voice_overridden() -> bool:
    return _options.voice is not None


def set_voice(**changes: Any) -> Voice:
    """Change some voice settings; ``reset=True`` returns to the file."""
    if changes.pop("reset", False):
        _options.voice = None
        return voice()
    _options.voice = replace(voice(), **{k: v for k, v in changes.items() if v is not None})
    return _options.voice


def business_day() -> str:
    return _options.business_day


def set_business_day(day: str | None) -> str:
    _options.business_day = date.fromisoformat(day).isoformat() if day else REFERENCE_DAY
    return _options.business_day

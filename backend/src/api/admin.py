"""Admin endpoints: what the operator may change at runtime, and the timings.

The advisor's model and temperature; the voice channel's recogniser,
endpointing, barge-in threshold and voice; the business day calls run on.
The choices live in this process only (``src/api/options.py``) and a restart
returns to ``config/models.yaml``. Staff only.

``/latency`` reports p50 and p95 of the organisers' four figures over the
turns recorded, computed with their own p95 (``eval/reference_eval.py``),
warm-up turns left out: the live counterpart of the evaluation's table.
"""

from __future__ import annotations

import statistics
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..components import voice as voice_component
from ..config.config_manager import get_models_config, has_api_key
from . import harness, options
from .auth import StaffUser
from .db import connection

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── the advisor's model ───────────────────────────────────────────────────


class ModelChoice(BaseModel):
    provider: str
    model: str
    label: str


class AdvisorSettings(BaseModel):
    provider: str | None
    model: str | None
    temperature: float | None
    overridden: bool
    default_provider: str
    default_model: str
    default_temperature: float | None
    choices: list[ModelChoice]


class AdvisorUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


def _advisor_report() -> AdvisorSettings:
    config = get_models_config()
    routed = config.agent_llm_config("advisor")
    current = options.advisor_overrides()
    running = harness.status()
    return AdvisorSettings(
        provider=current.get("provider") or routed["provider"],
        model=running.get("model") or current.get("model") or routed["model"],
        temperature=current.get("temperature", routed.get("temperature")),
        overridden=bool(current),
        default_provider=routed["provider"],
        default_model=routed["model"],
        default_temperature=routed.get("temperature"),
        choices=[
            ModelChoice(provider=name, model=model, label=f"{block.label}: {model}")
            for name, block in config.providers.items()
            if has_api_key(name)
            for model in block.models
        ],
    )


@router.get("/advisor", response_model=AdvisorSettings)
async def get_advisor(user: StaffUser) -> AdvisorSettings:
    return _advisor_report()


@router.post("/advisor", response_model=AdvisorSettings)
async def set_advisor(body: AdvisorUpdate, user: StaffUser) -> AdvisorSettings:
    """Rebuild the advisor on another model or temperature. An empty body
    resets to the file. Only a model the file lists under a provider this
    server holds a key for is accepted."""
    if (body.provider is None) != (body.model is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give provider and model together.")
    if body.provider is not None and not any(
        c.provider == body.provider and c.model == body.model for c in _advisor_report().choices
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That model is not available on this server.")
    try:
        await harness.rebuild_advisor(provider=body.provider, model=body.model, temperature=body.temperature)
    except Exception as error:  # noqa: BLE001 - the operator needs the reason
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not build the advisor: {error}") from error
    return _advisor_report()


# ── voice ─────────────────────────────────────────────────────────────────


class VoiceSettings(BaseModel):
    asr: str
    endpointing: str
    barge_in_ms: int
    min_interruption_words: int
    tts: str
    overridden: bool
    available: dict[str, Any]
    asr_choices: list[dict[str, Any]]
    endpointing_choices: list[dict[str, str]]
    tts_choices: list[dict[str, str]]


class VoiceUpdate(BaseModel):
    asr: str | None = None
    endpointing: str | None = None
    barge_in_ms: int | None = Field(default=None, ge=100, le=2000)
    min_interruption_words: int | None = Field(default=None, ge=0, le=6)
    tts: str | None = None
    reset: bool = False


def _voice_report() -> VoiceSettings:
    current = options.voice()
    ready = voice_component.status()
    asr_choices: list[dict[str, Any]] = []
    tts_choices: list[dict[str, str]] = [{"name": current.tts, "label": current.tts}]
    endpointing = [{"name": "smart", "label": "Smart Turn v3.2, 1.2 s ceiling"},
                   {"name": "silence-500", "label": "Silence 500 ms"},
                   {"name": "silence-800", "label": "Silence 800 ms"}]
    if ready["status"] == "ok":
        from ..components.voice import asr, tts

        asr_choices = asr.available()
        tts_choices = tts.voices()
    return VoiceSettings(
        asr=current.asr, endpointing=current.endpointing, barge_in_ms=current.barge_in_ms,
        min_interruption_words=current.min_interruption_words, tts=current.tts,
        overridden=options.voice_overridden(), available=ready, asr_choices=asr_choices,
        endpointing_choices=endpointing, tts_choices=tts_choices,
    )


@router.get("/voice", response_model=VoiceSettings)
async def get_voice(user: StaffUser) -> VoiceSettings:
    return _voice_report()


@router.post("/voice", response_model=VoiceSettings)
async def set_voice(body: VoiceUpdate, user: StaffUser) -> VoiceSettings:
    """Change the voice settings for calls placed from now on; ``reset`` returns to the file."""
    report = _voice_report()
    if body.asr and report.asr_choices and body.asr not in {c["name"] for c in report.asr_choices}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{body.asr} is not installed here.")
    if body.endpointing and body.endpointing not in {c["name"] for c in report.endpointing_choices}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown endpointing.")
    options.set_voice(asr=body.asr, endpointing=body.endpointing, barge_in_ms=body.barge_in_ms,
                      min_interruption_words=body.min_interruption_words, tts=body.tts, reset=body.reset)
    return _voice_report()


@router.post("/voice/warm")
async def warm_voice(user: StaffUser) -> dict[str, Any]:
    """Load the chosen recogniser, Smart Turn and the voice now, so the first call does not wait."""
    if voice_component.status()["status"] != "ok":
        raise HTTPException(status.HTTP_409_CONFLICT, "Voice is not ready on this server: " + str(voice_component.status()["hint"]))
    from .voice import warm

    return await warm()


# ── the business day ──────────────────────────────────────────────────────


class BusinessDay(BaseModel):
    day: str | None = Field(default=None, description="YYYY-MM-DD; empty returns to the reference day")


@router.get("/clock")
async def get_clock(user: StaffUser) -> dict[str, str]:
    return {"day": options.business_day(), "time": "10:00", "zone": "Asia/Ho_Chi_Minh"}


@router.post("/clock")
async def set_clock(body: BusinessDay, user: StaffUser) -> dict[str, str]:
    try:
        day = options.set_business_day(body.day)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the day as YYYY-MM-DD.") from error
    return {"day": day, "time": "10:00", "zone": "Asia/Ho_Chi_Minh"}


# ── latency ───────────────────────────────────────────────────────────────


def p95(values: list[int]) -> int | None:
    """``eval/reference_eval.py``'s p95, exactly."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * len(ordered) + 0.5)) - 1)]


def _stats(values: list[int]) -> dict[str, Any] | None:
    if not values:
        return None
    return {"n": len(values), "p50_ms": int(statistics.median(values)), "p95_ms": int(p95(values))}


THRESHOLDS_MS = {"ttft": 3000, "total": 8000, "ttfa": 2500, "call_brief": 3000}


@router.get("/latency")
async def latency(
    user: StaffUser,
    channel: Literal["all", "web", "zalo", "hotline", "facebook"] = "all",
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    """p50 and p95 per figure, over agent turns, warm-up excluded."""
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT t.meta->'latency' AS latency, c.channel FROM turns t JOIN calls c ON c.id = t.call_id "
            "WHERE t.speaker = 'agent' AND t.meta ? 'latency' AND t.created_at > now() - %s * interval '1 day' "
            + ("" if channel == "all" else "AND c.channel = %s "),
            (days,) if channel == "all" else (days, channel),
        )
        rows = await cursor.fetchall()
    figures: dict[str, list[int]] = {"ttft": [], "total": [], "ttfa": [], "call_brief": [], "ttfa_client": []}
    warmup = 0
    for row in rows:
        entry = row["latency"] or {}
        if entry.get("warmup"):
            warmup += 1
            continue
        for name, key in (("ttft", "ttft_ms"), ("total", "total_ms"), ("ttfa", "ttfa_ms"),
                          ("call_brief", "call_brief_latency_ms"), ("ttfa_client", "ttfa_client_ms")):
            if entry.get(key) is not None:
                figures[name].append(int(entry[key]))
    n = len(figures["ttft"])
    return {
        "turns": n,
        "warmup_excluded": warmup,
        "warning": None if n >= 100 else "Under 100 turns: the organisers ask for at least 100 before p95 means much.",
        "streaming": False,
        "thresholds_ms": THRESHOLDS_MS,
        **{name: _stats(values) for name, values in figures.items()},
    }

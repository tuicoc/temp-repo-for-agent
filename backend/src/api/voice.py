"""The voice channel's WebSocket: a simulated phone call. ``docs/design.md`` section 4.11.

One socket per call. The browser streams microphone audio up and plays what
comes down; everything that decides anything runs here:

    mic -> 16 kHz -> Silero VAD + Smart Turn -> local ASR -> lexicon
        -> harness.run_turn (the same turn as a chat message) -> TTS per sentence -> browser

Grown out of ``lab/voice``. The recogniser, the endpointing, the barge-in
threshold and the voice are the Admin page's choice (``src/api/options.py``).

**Timing**, the organisers' way (``eval/huong-dan-do-latency.md``), on the
server's monotonic clock:

- TTFA: from the end of the caller's speech (VAD) to the first audio byte of
  the answer leaving the server. Endpointing, recognition, the turn and the
  first sentence of speech are all inside it.
- TTFT and Total of the turn itself: from the transcript reaching the
  harness to the answer being ready, as for a chat message.
- The browser reports when playback actually started; that end-to-end figure
  is kept apart (``ttfa_client_ms``), as their rule 1 asks.

**Barge-in**, as LiveKit and Pipecat handle it: speech while the agent
talks *pauses* playback at once. When the words are in, a real
interruption (enough words, not just "ừ") stops the answer, and the thread
keeps only the part the caller heard; a cough or a "vâng" resumes it where
it paused (:mod:`~src.components.voice.policy`). Anything said while the
agent is still working out its answer meets the same bar before it replaces
the question.

The heavy packages are imported when a call connects, so the service runs
without them; a call then gets an error message naming what is missing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..components import voice as voice_component
from ..config.config_manager import ROOT
from ..components.voice.policy import counts_as_turn
from . import calls, harness, options
from .auth import user_from_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])

#: Said when a turn fails, so the call never goes silent (section 4.9).
FALLBACK = "Dạ em xin lỗi, hệ thống bên em đang tra cứu hơi chậm. Anh chị nói lại giúp em một lần nữa được không ạ?"


async def warm() -> dict[str, Any]:
    """Load the chosen recogniser, both turn detectors and the voice.

    Each stays cached in this process, so every later call starts at once.
    Run at startup where voice is installed, and from the Admin page after the
    settings change.
    """
    from ..components.voice import asr, tts
    from ..components.voice.turns import Silero, smart_turn

    current = options.voice()
    seconds = await asyncio.to_thread(asr.load, current.asr)
    await asyncio.to_thread(Silero)
    await asyncio.to_thread(smart_turn)
    await tts.voice(current.tts).warm()
    return {"asr": current.asr, "asr_load_seconds": round(seconds, 1), "tts": current.tts}


@router.websocket("/calls/{call_id}/voice")
async def voice_call(ws: WebSocket, call_id: int) -> None:
    await ws.accept()
    try:
        hello = json.loads(await ws.receive_text())
    except (WebSocketDisconnect, ValueError):
        return
    user = await user_from_token(str(hello.get("token") or ""))
    if user is None:
        await ws.close(code=4401)
        return
    try:
        row = await calls.call_row(call_id, user)
    except Exception:  # noqa: BLE001 - not theirs, or no such call
        await ws.close(code=4404)
        return
    ready = voice_component.status()
    if ready["status"] != "ok":
        await ws.send_text(json.dumps({"type": "error", "text": f"Voice is not ready here: {ready['hint']}"}))
        await ws.close()
        return
    # The browser matters: its echo canceller decides how much of the caller
    # survives while the assistant is speaking.
    logger.info("Call %s: voice from %s, %s Hz", call_id, ws.headers.get("user-agent", "?")[:160], hello.get("sample_rate"))
    session = Session(ws, row, user_id=str(user.id), sample_rate=float(hello.get("sample_rate") or 48_000))
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()


class Session:
    def __init__(self, ws: WebSocket, row: dict[str, Any], *, user_id: str, sample_rate: float) -> None:
        # Imported here: numpy, onnxruntime and friends are optional.
        import soxr

        from ..components.voice import tts
        from ..components.voice.lexicon import Lexicon
        from ..components.voice.turns import TurnDetector, config_for

        self.ws = ws
        self.row = row
        self.call_id = int(row["id"])
        self.user_id = user_id
        self.settings = options.voice()
        self.detector = TurnDetector(config_for(self.settings.endpointing, self.settings.barge_in_ms))
        self.voice = tts.voice(self.settings.tts)
        self.lexicon = Lexicon()
        self.resampler = soxr.ResampleStream(sample_rate, 16_000, 1, dtype="float32")
        self.timings: dict[str, dict[str, Any]] = {}
        self.spoken: dict[str, list[str]] = {}
        self.chunks: dict[str, list[dict[str, Any]]] = {}
        self.cancelled: set[str] = set()
        self.thinking: set[str] = set()
        #: Turns whose answer is being synthesised or played.
        self.speaking: set[str] = set()
        self.playing: str | None = None
        #: The turn whose playback is paused by a possible interruption.
        self.paused: str | None = None
        #: What reached the server, for the input report the page shows and
        #: the log keeps: seconds of audio, loudest level, best speech score.
        self.heard_seconds = 0.0
        self.window_peak = 0.0
        self.last_report = time.perf_counter()
        self.counts = {"speech": 0, "turns": 0, "ignored": 0, "pauses": 0}
        #: VOICE_RECORD=1 keeps what reached the server, at 16 kHz, for
        #: diagnosing a microphone; written to lab/voice/runs/calls/ (ignored by git).
        self.recording: list[Any] | None = [] if os.environ.get("VOICE_RECORD") == "1" else None
        self.sample_rate = sample_rate
        self.turn_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task[Any]] = set()
        self.hung_up = False

    # ── plumbing ──────────────────────────────────────────────────────────

    async def send(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(self._report)

    def _report(self, task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Voice task failed on call %s", self.call_id, exc_info=task.exception())
            asyncio.get_event_loop().create_task(self.send({"type": "error", "text": f"{type(task.exception()).__name__}"}))

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        from ..components.voice import asr
        from ..components.voice.turns import smart_turn

        await self.send({"type": "state", "state": "loading"})
        loaded = await asyncio.to_thread(asr.load, self.settings.asr)
        await asyncio.to_thread(smart_turn)
        await self.voice.warm()
        await self.send({"type": "status", "text": f"{self.settings.asr} ready", "load_seconds": round(loaded, 1),
                         "settings": self.settings.__dict__})
        self.spawn(self.opening())
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await self.audio(message["bytes"], time.perf_counter())
            elif message.get("text") is not None:
                if await self.control(json.loads(message["text"])) == "hangup":
                    break

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        if self.recording:
            self._save_recording()
        if not self.hung_up:
            self.hung_up = True
            await calls.hang_up(self.call_id)

    async def audio(self, data: bytes, arrived: float) -> None:
        import numpy as np

        from ..components.voice.turns import BargeIn, SpeechStarted, TurnEnded

        samples = self.resampler.resample_chunk(np.frombuffer(data, dtype=np.float32))
        if samples.size == 0:
            return
        self.heard_seconds += samples.size / 16_000
        if self.recording is not None:
            self.recording.append(samples.copy())
        self.window_peak = max(self.window_peak, float(np.sqrt(np.mean(samples * samples))))
        if arrived - self.last_report >= 2.0:
            await self.report(arrived)
        for event in await asyncio.to_thread(self.detector.feed, samples, arrived):
            if isinstance(event, SpeechStarted):
                self.counts["speech"] += 1
                await self.send({"type": "state", "state": "user"})
            elif isinstance(event, BargeIn):
                await self.pause()
            elif isinstance(event, TurnEnded):
                # Whether the agent was busy is decided now, when the caller
                # stopped speaking, not after recognition.
                self.spawn(self.turn(event, busy=self.busy()))

    def _save_recording(self) -> None:
        import numpy as np
        import soundfile

        folder = ROOT / "lab" / "voice" / "runs" / "calls"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"call-{self.call_id}-16k.wav"
        soundfile.write(path, np.concatenate(self.recording), 16_000)
        logger.info("Call %s: recorded %.1f s to %s (browser rate %s)", self.call_id,
                    sum(len(r) for r in self.recording) / 16_000, path, self.sample_rate)
        self.recording = None

    async def report(self, now: float) -> None:
        """Every two seconds: is sound arriving, how loud, does it sound like speech.

        What tells a muted or wrong microphone (level near zero) from a quiet
        one (level fine, speech score under the VAD threshold of 0.5)."""
        report = {"type": "input", "seconds": round(self.heard_seconds, 1), "level": round(self.window_peak, 4),
                  "speech_score": round(self.detector.peak_probability, 2), **self.counts}
        logger.info("Call %s input: %s", self.call_id, report)
        self.window_peak = 0.0
        self.detector.peak_probability = 0.0
        self.last_report = now
        await self.send(report)

    def busy(self) -> bool:
        return bool(self.thinking or self.speaking or self.paused)

    async def control(self, message: dict[str, Any]) -> str | None:
        kind = message.get("type")
        now = time.perf_counter()
        if kind == "playback_started":
            turn = str(message["turn"])
            self.playing = turn
            self.detector.agent_started()
            timing = self.timings.get(turn)
            if timing is not None and "play_start" not in timing:
                timing["play_start"] = now
                await self.metrics(turn)
            await self.send({"type": "state", "state": "speaking"})
        elif kind == "playback_ended":
            turn = str(message["turn"])
            self.speaking.discard(turn)
            if self.playing == turn:
                self.playing = None
                self.detector.agent_stopped()
                await self.send({"type": "state", "state": "listening"})
        elif kind == "playback_stopped":
            await self.truncated(message)
        elif kind == "hangup":
            await self.close()
            return "hangup"
        return None

    # ── turns ─────────────────────────────────────────────────────────────

    async def opening(self) -> None:
        turn_id = f"open-{uuid.uuid4().hex[:8]}"
        self.timings[turn_id] = {"kind": "opening", "origin": time.perf_counter()}
        await self.send({"type": "state", "state": "thinking"})
        outcome = await self._take(turn_id, None, self.timings[turn_id]["origin"])
        await self._answer(turn_id, outcome)

    async def turn(self, event: Any, *, busy: bool) -> None:
        from ..components.voice import asr

        heard = await asyncio.to_thread(asr.transcribe, self.settings.asr, event.audio, self.lexicon.hotwords)
        asr_done = time.perf_counter()
        text, applied = self.lexicon.correct(heard.text)
        taken, why = counts_as_turn(text, busy=busy, min_words=self.settings.min_interruption_words)
        if not taken:
            # Listening sounds, a cough, the line: not a turn. A paused answer
            # carries on where it stopped.
            self.counts["ignored"] += 1
            logger.info("Call %s: not a turn (%s): %r", self.call_id, why, text)
            await self.send({"type": "ignored", "text": text, "why": why})
            if self.paused is not None:
                await self.resume()
            elif not self.busy():
                await self.send({"type": "state", "state": "listening"})
            return
        self.counts["turns"] += 1
        logger.info("Call %s: turn %r (busy=%s)", self.call_id, text, busy)
        if self.paused is not None:
            await self.stop_paused()
        # It replaces whatever the agent was still working out.
        self.cancelled.update(self.thinking)

        turn_id = uuid.uuid4().hex
        timing: dict[str, Any] = {"kind": "turn", "speech_end": event.speech_end, "turn_end": event.decided,
                                  "asr_done": asr_done, "reason": event.reason}
        self.timings[turn_id] = timing
        self.thinking.add(turn_id)
        await self.send({"type": "state", "state": "thinking"})
        await self.send({"type": "transcript", "turn": turn_id, "text": text, "raw": heard.text,
                         "corrections": applied, "asr_ms": int(heard.seconds * 1000),
                         "audio_seconds": round(heard.audio_seconds, 2), "endpointing": event.reason})
        outcome = await self._take(turn_id, text, timing["asr_done"])
        self.thinking.discard(turn_id)
        if turn_id in self.cancelled:
            timing["superseded"] = True
            await harness.keep_heard(self.call_id, turn_id, "")
            await self.send({"type": "reply", "turn": turn_id, "text": outcome.content, "superseded": True})
            return
        await self._answer(turn_id, outcome)

    async def _take(self, turn_id: str, text: str | None, arrived: float) -> harness.Outcome:
        """One turn through the harness, one at a time, under the call's lease."""
        async with self.turn_lock:
            for _ in range(20):
                if await calls.claim_lease(self.call_id):
                    break
                await asyncio.sleep(0.25)
            else:
                return harness.Outcome("error", turn_id, error="another turn holds the call")
            try:
                return await harness.run_turn(self.row, content=text, turn_id=turn_id, arrived=arrived,
                                              user_id=self.user_id, input_mode="asr_transcript" if text else None)
            finally:
                await calls.release_lease(self.call_id)

    async def _answer(self, turn_id: str, outcome: harness.Outcome) -> None:
        timing = self.timings[turn_id]
        timing["agent_done"] = time.perf_counter()
        timing["latency"] = outcome.latency
        if outcome.kind == "waiting":
            await self.send({"type": "reply", "turn": turn_id, "text": None, "waiting": True})
            await self.send({"type": "state", "state": "listening"})
            return
        text = outcome.content if outcome.kind == "message" else FALLBACK
        await self.send({"type": "reply", "turn": turn_id, "text": text, "meta": outcome.meta,
                         "error": outcome.error})
        self.speaking.add(turn_id)
        await self.speak(turn_id, text or FALLBACK)

    async def speak(self, turn_id: str, text: str) -> None:
        from ..components.voice import tts

        parts = tts.sentences(text)
        self.spoken[turn_id] = parts
        self.chunks[turn_id] = []
        timing = self.timings[turn_id]
        offsets = [0.0] * len(parts)
        seq = 0
        async for index, speech in self._synthesise(parts):
            if turn_id in self.cancelled:
                break
            self.chunks[turn_id].append({"sentence": index, "offset": offsets[index], "duration": speech.duration})
            offsets[index] += speech.duration or 0.0
            await self.send({"type": "audio", "turn": turn_id, "seq": seq, "sentence": index, "mime": speech.mime,
                             "data": base64.b64encode(speech.audio).decode("ascii")})
            if seq == 0:
                timing["first_audio"] = time.perf_counter()
                await self._record(turn_id)
            seq += 1
        if turn_id not in self.cancelled:
            await self.send({"type": "audio_end", "turn": turn_id, "last_seq": seq - 1})

    async def _synthesise(self, parts: list[str]):
        """(sentence index, chunk) in playback order: a network voice asks for
        every sentence at once, a CPU voice streams one after another."""
        if not self.voice.parallel:
            for index, part in enumerate(parts):
                async for speech in self.voice.stream(part):
                    yield index, speech
            return

        async def collect(part: str) -> list[Any]:
            return [speech async for speech in self.voice.stream(part)]

        jobs = [asyncio.create_task(collect(part)) for part in parts]
        try:
            for index, job in enumerate(jobs):
                for speech in await job:
                    yield index, speech
        finally:
            for job in jobs:
                job.cancel()

    async def _record(self, turn_id: str) -> None:
        """TTFA at the server boundary, written onto the turn."""
        timing = self.timings[turn_id]
        figures = _figures(timing)
        if timing.get("kind") == "turn" and figures.get("ttfa_ms") is not None:
            await harness.record_ttfa(self.call_id, turn_id, figures["ttfa_ms"], {
                k: figures[k] for k in ("endpoint_ms", "asr_ms", "agent_ms", "tts_first_ms") if figures.get(k) is not None
            } | {"asr_model": self.settings.asr, "endpointing": self.settings.endpointing, "tts": self.settings.tts})

    async def pause(self) -> None:
        """Speech while the agent talks: hold the answer until the words say
        whether it was an interruption. No words in time resumes it."""
        turn = self.playing
        if turn is None or self.paused is not None:
            return
        self.paused = turn
        self.counts["pauses"] += 1
        logger.info("Call %s: speech over the answer, paused %s", self.call_id, turn)
        await self.send({"type": "pause", "turn": turn})
        self.spawn(self._false_interruption(turn))

    async def _false_interruption(self, turn: str) -> None:
        await asyncio.sleep(self.settings.false_interruption_ms / 1000)
        if self.paused != turn:
            return
        if self.detector.in_turn:
            # Still talking after all this time: that is no cough.
            await self.stop_paused()
        else:
            await self.resume()

    async def resume(self) -> None:
        turn, self.paused = self.paused, None
        if turn is None:
            return
        # Let a later cut-in be measured again.
        self.detector.agent_started()
        await self.send({"type": "resume", "turn": turn})

    async def stop_paused(self) -> None:
        turn, self.paused = self.paused, None
        if turn is None:
            return
        self.cancelled.add(turn)
        self.speaking.discard(turn)
        self.detector.agent_stopped()
        await self.send({"type": "stop", "turn": turn})

    async def truncated(self, message: dict[str, Any]) -> None:
        """What the caller actually heard before cutting in: sentences before
        the one playing whole, of that one a share by time played."""
        turn, seq = str(message["turn"]), int(message["seq"])
        parts = self.spoken.get(turn, [])
        chunks = self.chunks.get(turn, [])
        played = float(message["played_ms"]) / 1000
        if seq < len(chunks):
            chunk = chunks[seq]
            index = chunk["sentence"]
            same = [c for c in chunks if c["sentence"] == index]
            known = all(c["duration"] is not None for c in same)
            total = sum(c["duration"] for c in same) if known else float(message["duration_ms"]) / 1000
            ratio = min(1.0, (chunk["offset"] + played) / max(total, 1e-3))
        else:
            index, ratio = 0, 0.0
        current = parts[index] if index < len(parts) else ""
        heard = " ".join([*parts[:index], current[: int(len(current) * ratio)]]).strip()
        self.speaking.discard(turn)
        self.playing = None
        self.detector.agent_stopped()
        await harness.keep_heard(self.call_id, turn, heard)
        await self.send({"type": "truncated", "turn": turn, "heard": heard})

    async def metrics(self, turn_id: str) -> None:
        timing = self.timings[turn_id]
        figures = _figures(timing)
        if timing.get("kind") == "turn" and figures.get("ttfa_client_ms") is not None:
            await harness.record_ttfa(self.call_id, turn_id, figures["ttfa_ms"] or 0, {"ttfa_client_ms": figures["ttfa_client_ms"]})
        await self.send({"type": "metrics", "turn": turn_id, **figures})


def _figures(t: dict[str, Any]) -> dict[str, Any]:
    def ms(a: str, b: str) -> int | None:
        return int((t[b] - t[a]) * 1000) if a in t and b in t else None

    latency = t.get("latency") or {}
    if t.get("kind") == "opening":
        return {"kind": "opening", "agent_ms": ms("origin", "agent_done"), "tts_first_ms": ms("agent_done", "first_audio"),
                "ttfa_ms": None, "ttfa_client_ms": None, "ttft_ms": latency.get("ttft_ms"),
                "call_brief_latency_ms": latency.get("call_brief_latency_ms")}
    return {
        "kind": "turn",
        "endpoint_ms": ms("speech_end", "turn_end"),
        "asr_ms": ms("turn_end", "asr_done"),
        "agent_ms": ms("asr_done", "agent_done"),
        "tts_first_ms": ms("agent_done", "first_audio"),
        "ttfa_ms": ms("speech_end", "first_audio"),
        "ttfa_client_ms": ms("speech_end", "play_start"),
        "ttft_ms": latency.get("ttft_ms"),
        "reason": t.get("reason"),
    }

"""Voice lab: talk to the agent through local ASR and hear it answer.

One WebSocket per call. The browser streams microphone audio up and plays
what comes down; everything else happens here:

    mic -> resample to 16 kHz -> turns (VAD + Smart Turn) -> asr -> lexicon
        -> bridge (the real turn endpoint, or echo) -> tts, sentence by sentence -> browser

Every turn is timed from the moment the caller stopped speaking to the moment
the first audio of the answer started playing (TTFA, as the brief defines
it), split into the stages above. The numbers go to the page and to
``runs/<date>.jsonl``.

    uvicorn server:app --port 8100
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import soxr
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import asr
import bridge
import tts
from lexicon import Lexicon
from turns import BargeIn, SpeechStarted, TurnConfig, TurnDetector, TurnEnded, smart_turn

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
logger = logging.getLogger("lab")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="Voice lab")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# Said when the agent fails, so the call never goes silent (section 12).
FALLBACK = "Dạ em xin lỗi, hệ thống bên em đang tra cứu hơi chậm. Anh chị nói lại giúp em một lần nữa được không ạ?"

ENDPOINTING = [
    {"name": "smart", "label": "Smart Turn v3.2, 1.2 s ceiling"},
    {"name": "silence-500", "label": "Silence 500 ms"},
    {"name": "silence-800", "label": "Silence 800 ms"},
]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/options")
async def options() -> dict[str, Any]:
    return {
        "asr": asr.available(),
        "voices": tts.voices(),
        "agents": [
            {"name": "backend", "label": "Advisor, through the backend on :8000"},
            {"name": "echo", "label": "Echo, no model calls"},
        ],
        "endpointing": ENDPOINTING,
    }


@app.get("/api/advisor")
async def advisor_model() -> JSONResponse:
    """Which model the backend's advisor runs on, and what it may switch to."""
    try:
        return JSONResponse(await bridge.admin.current())
    except bridge.AgentError as error:
        return JSONResponse({"detail": str(error)}, status_code=502)


@app.post("/api/advisor")
async def switch_advisor_model(body: dict[str, Any]) -> JSONResponse:
    """Rebuild the backend's advisor on another model; an empty choice resets to the file."""
    started = time.perf_counter()
    try:
        report = await bridge.admin.switch(body.get("provider"), body.get("model"))
    except bridge.AgentError as error:
        return JSONResponse({"detail": str(error)}, status_code=502)
    return JSONResponse({**report, "rebuild_seconds": round(time.perf_counter() - started, 2)})


def _turn_config(name: str) -> TurnConfig:
    if name.startswith("silence-"):
        return TurnConfig(mode="silence", silence_ms=int(name.split("-", 1)[1]))
    return TurnConfig(mode="smart")


class Session:
    def __init__(self, ws: WebSocket, params: dict[str, str]) -> None:
        self.ws = ws
        self.asr_name = params.get("asr", "zipformer-30m")
        self.voice_name = params.get("voice", "edge:vi-VN-HoaiMyNeural")
        self.agent_name = params.get("agent", "echo")
        self.endpointing = params.get("endpointing", "smart")
        self.compare = params.get("compare") == "1"
        self.detector = TurnDetector(_turn_config(self.endpointing))
        self.agent = bridge.agent(self.agent_name)
        self.voice = tts.voice(self.voice_name)
        self.lexicon = Lexicon()
        self.resampler: soxr.ResampleStream | None = None
        self.turn_no = 0
        self.timings: dict[int, dict[str, Any]] = {}
        self.spoken: dict[int, list[str]] = {}
        self.chunks: dict[int, list[dict[str, Any]]] = {}
        self.cancelled: set[int] = set()
        self.thinking: set[int] = set()
        self.playing: int | None = None
        self.agent_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task[Any]] = set()
        RUNS.mkdir(exist_ok=True)
        self.log_path = RUNS / f"{datetime.now():%Y%m%d}.jsonl"

    # ── plumbing ──────────────────────────────────────────────────────────

    async def send(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False))

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(self._report)

    def _report(self, task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Task failed", exc_info=task.exception())
            asyncio.get_event_loop().create_task(
                self.send({"type": "error", "text": f"{type(task.exception()).__name__}: {task.exception()}"})
            )

    def record(self, entry: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.send({"type": "state", "state": "loading"})
        loaded = await asyncio.to_thread(asr.load, self.asr_name)
        await asyncio.to_thread(smart_turn)
        await self.voice.warm()
        await self.send({"type": "status", "text": f"{self.asr_name} ready (loaded in {loaded:.1f} s)"})
        try:
            await self.agent.start()
        except bridge.AgentError as error:
            await self.send({"type": "error", "text": str(error)})
            return
        self.spawn(self.opening())

        try:
            while True:
                message = await self.ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self.audio(message["bytes"], time.perf_counter())
                elif message.get("text") is not None:
                    await self.control(json.loads(message["text"]))
        finally:
            for task in list(self.tasks):
                task.cancel()
            await self.agent.end()

    async def audio(self, data: bytes, arrived: float) -> None:
        if self.resampler is None:
            return
        native = np.frombuffer(data, dtype=np.float32)
        samples = self.resampler.resample_chunk(native)
        if samples.size == 0:
            return
        for event in await asyncio.to_thread(self.detector.feed, samples, arrived):
            if isinstance(event, SpeechStarted):
                await self.send({"type": "state", "state": "user"})
            elif isinstance(event, BargeIn):
                await self.barge_in(event)
            elif isinstance(event, TurnEnded):
                self.turn_no += 1
                # A turn still thinking when the caller has said more is
                # superseded: its answer would reply to a sentence they
                # have already moved past.
                for older in list(self.thinking):
                    self.cancelled.add(older)
                self.spawn(self.turn(self.turn_no, event))

    async def control(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        now = time.perf_counter()
        if kind == "hello":
            self.resampler = soxr.ResampleStream(float(message["sample_rate"]), 16_000, 1, dtype="float32")
        elif kind == "playback_started":
            turn = int(message["turn"])
            self.playing = turn
            self.detector.agent_started()
            timing = self.timings.get(turn)
            if timing is not None and "play_start" not in timing:
                timing["play_start"] = now
                await self.metrics(turn)
            await self.send({"type": "state", "state": "speaking"})
        elif kind == "playback_ended":
            if self.playing == int(message["turn"]):
                self.playing = None
                self.detector.agent_stopped()
                await self.send({"type": "state", "state": "listening"})
        elif kind == "playback_stopped":
            await self.truncated(message)

    # ── a call ────────────────────────────────────────────────────────────

    async def opening(self) -> None:
        started = time.perf_counter()
        timing: dict[str, Any] = {"kind": "opening", "origin": started}
        self.timings[0] = timing
        await self.send({"type": "state", "state": "thinking"})
        async with self.agent_lock:
            try:
                reply = await self.agent.opening()
            except bridge.AgentError as error:
                logger.warning("Agent failed on the greeting: %s", error)
                reply = bridge.Reply(FALLBACK, 0.0, {"error": str(error)})
        timing["agent_done"] = time.perf_counter()
        timing["agent_meta"] = _meta(reply.meta)
        await self.send({"type": "reply", "turn": 0, "text": reply.text, "meta": timing["agent_meta"]})
        await self.speak(0, reply.text)

    async def turn(self, n: int, event: TurnEnded) -> None:
        timing: dict[str, Any] = {
            "kind": "turn",
            "speech_end": event.speech_end,
            "turn_end": event.decided,
            "reason": event.reason,
            "smart_probability": event.smart_probability,
            "probes": [round(p, 3) for p in event.probes],
        }
        self.timings[n] = timing
        self.thinking.add(n)
        await self.send({"type": "state", "state": "thinking"})

        heard = await asyncio.to_thread(asr.transcribe, self.asr_name, event.audio, self.lexicon.hotwords)
        timing["asr_done"] = time.perf_counter()
        text, applied = self.lexicon.correct(heard.text)
        timing.update(asr_model=self.asr_name, audio_seconds=round(heard.audio_seconds, 2), raw=heard.text, text=text)
        await self.send({
            "type": "transcript", "turn": n, "raw": heard.text, "text": text,
            "model": self.asr_name, "corrections": applied,
            "audio_seconds": round(heard.audio_seconds, 2), "asr_seconds": round(heard.seconds, 3),
            "endpointing": event.reason,
        })
        if self.compare:
            self.spawn(self.compare_models(n, event.audio))
        if not text.strip():
            self.thinking.discard(n)
            await self.send({"type": "state", "state": "listening"})
            return

        async with self.agent_lock:
            try:
                reply = await self.agent.turn(text)
            except bridge.AgentError as error:
                # docs/flow.md section 12: a failure is never silence. The
                # caller hears the fallback line; the page says what failed.
                logger.warning("Agent failed on turn %s: %s", n, error)
                reply = bridge.Reply(FALLBACK, 0.0, {"error": str(error)})
        timing["agent_done"] = time.perf_counter()
        timing["agent_meta"] = _meta(reply.meta)
        self.thinking.discard(n)
        if n in self.cancelled:
            timing["superseded"] = True
            self.record({"turn": n, **_durations(timing), "superseded": True})
            await self.send({"type": "reply", "turn": n, "text": reply.text, "superseded": True})
            return
        await self.send({"type": "reply", "turn": n, "text": reply.text, "meta": timing["agent_meta"]})
        await self.speak(n, reply.text)

    async def speak(self, n: int, text: str) -> None:
        parts = tts.sentences(text)
        self.spoken[n] = parts
        self.chunks[n] = []
        timing = self.timings[n]
        seq = 0
        offsets = [0.0] * len(parts)
        async for index, speech in self._synthesise(parts):
            if n in self.cancelled:
                break
            if seq == 0:
                timing["tts_first"] = time.perf_counter()
                timing["tts_first_byte"] = speech.first_byte
            self.chunks[n].append({"sentence": index, "offset": offsets[index], "duration": speech.duration})
            offsets[index] += speech.duration or 0.0
            await self.send({
                "type": "audio", "turn": n, "seq": seq, "sentence": index, "mime": speech.mime,
                "data": base64.b64encode(speech.audio).decode("ascii"),
            })
            seq += 1
        if n not in self.cancelled:
            await self.send({"type": "audio_end", "turn": n, "last_seq": seq - 1})

    async def _synthesise(self, parts: list[str]):
        """(sentence index, chunk) in playback order.

        A network engine gets every sentence requested at once, so the second
        is usually ready before the first has finished playing. A CPU engine
        streams one sentence after another, since parallel synthesis would
        only slow the first chunk down.
        """
        if not self.voice.parallel:
            for index, part in enumerate(parts):
                async for speech in self.voice.stream(part):
                    yield index, speech
            return

        async def collect(part: str) -> list[tts.Speech]:
            return [speech async for speech in self.voice.stream(part)]

        jobs = [asyncio.create_task(collect(part)) for part in parts]
        try:
            for index, job in enumerate(jobs):
                for speech in await job:
                    yield index, speech
        finally:
            for job in jobs:
                job.cancel()

    async def barge_in(self, event: BargeIn) -> None:
        turn = self.playing
        if turn is None:
            return
        self.cancelled.add(turn)
        self.detector.agent_stopped()
        timing = self.timings.get(turn, {})
        timing["barge_in"] = event.at
        await self.send({"type": "stop", "turn": turn})

    async def truncated(self, message: dict[str, Any]) -> None:
        """The caller cut the agent off: work out what they actually heard.

        Sentences before the one playing were heard whole; of the one playing,
        a share proportional to the time it had played. This is what the
        thread should keep, which the real system does on the agent message.
        """
        turn, seq = int(message["turn"]), int(message["seq"])
        parts = self.spoken.get(turn, [])
        chunks = self.chunks.get(turn, [])
        played = float(message["played_ms"]) / 1000
        if seq < len(chunks):
            chunk = chunks[seq]
            index = chunk["sentence"]
            same = [c for c in chunks if c["sentence"] == index]
            known = all(c["duration"] is not None for c in same)
            total = sum(c["duration"] for c in same) if known else float(message["duration_ms"]) / 1000
            into = chunk["offset"] + played
            # A sentence still being synthesised has no known total yet; the
            # share heard is then measured against what exists, a lower bound.
            ratio = min(1.0, into / max(total, 1e-3))
        else:
            index, ratio = 0, 0.0
        current = parts[index] if index < len(parts) else ""
        cut = current[: int(len(current) * ratio)]
        heard = " ".join([*parts[:index], cut]).strip()
        self.playing = None
        self.detector.agent_stopped()
        self.record({"turn": turn, "barge_in": True, "heard": heard, "full": " ".join(parts)})
        await self.send({"type": "truncated", "turn": turn, "heard": heard})

    async def compare_models(self, n: int, audio: np.ndarray) -> None:
        for other in asr.available():
            if other["name"] == self.asr_name:
                continue
            await self.send({"type": "compare", "turn": n, "model": other["name"], "pending": True})
            result = await asyncio.to_thread(asr.transcribe, other["name"], audio, self.lexicon.hotwords)
            text, _ = self.lexicon.correct(result.text)
            await self.send({
                "type": "compare", "turn": n, "model": other["name"], "text": text,
                "asr_seconds": round(result.seconds, 3), "rtf": round(result.rtf, 3),
            })
            self.record({"turn": n, "compare": other["name"], "text": text, "asr_seconds": result.seconds})

    async def metrics(self, n: int) -> None:
        timing = self.timings[n]
        durations = _durations(timing)
        self.record({
            "turn": n, "asr": self.asr_name, "voice": self.voice_name, "agent": self.agent_name,
            "endpointing": self.endpointing, **durations,
            "text": timing.get("text"), "raw": timing.get("raw"),
        })
        await self.send({"type": "metrics", "turn": n, **durations})


def _meta(meta: dict[str, Any]) -> dict[str, Any]:
    tools = meta.get("tool_calls") or meta.get("tools") or []
    return {
        "model": meta.get("model"),
        "ttft_content": meta.get("ttft_content"),
        "tools": [t.get("name") for t in tools if isinstance(t, dict)] if isinstance(tools, list) else [],
        "error": meta.get("error"),
    }


def _durations(t: dict[str, Any]) -> dict[str, Any]:
    def gap(a: str, b: str) -> float | None:
        return round(t[b] - t[a], 3) if a in t and b in t else None

    if t.get("kind") == "opening":
        return {
            "kind": "opening",
            "agent": gap("origin", "agent_done"),
            "tts": gap("agent_done", "tts_first"),
            "delivery": gap("tts_first", "play_start"),
            "ttfa": gap("origin", "play_start"),
            "tts_first_byte": t.get("tts_first_byte"),
            "agent_meta": t.get("agent_meta"),
        }
    return {
        "kind": "turn",
        "endpoint": gap("speech_end", "turn_end"),
        "asr": gap("turn_end", "asr_done"),
        "agent": gap("asr_done", "agent_done"),
        "tts": gap("agent_done", "tts_first"),
        "delivery": gap("tts_first", "play_start"),
        "ttfa": gap("speech_end", "play_start"),
        "reason": t.get("reason"),
        "smart_probability": t.get("smart_probability"),
        "audio_seconds": t.get("audio_seconds"),
        "tts_first_byte": t.get("tts_first_byte"),
        "agent_meta": t.get("agent_meta"),
    }


@app.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    await ws.accept()
    session = Session(ws, dict(ws.query_params))
    try:
        await session.run()
    except WebSocketDisconnect:
        pass

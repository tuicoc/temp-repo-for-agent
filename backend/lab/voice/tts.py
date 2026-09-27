"""Text to speech, streamed.

The reply is split into sentences. Each sentence is synthesised as a stream
of audio chunks where the engine allows it, and every chunk goes to the
browser as soon as it exists, so the caller hears the answer begin while the
rest is still being made. That is the lever on time to first audio that does
not need a speech-to-speech model.

Engines:

- ``vieneu``: VieNeu-TTS on CPU through ONNX Runtime, fully local. Streams:
  on this laptop the first chunk is ready in about 0.35 s and synthesis runs
  faster than playback, so the stream never starves.
- ``edge``: Microsoft's neural voices (vi-VN HoaiMy, NamMinh) through the free
  endpoint behind Edge's read-aloud. The same voices Azure Speech sells, but
  the free endpoint refuses a large share of requests without audio, so it is
  here to hear the voices, not to time them. One chunk per sentence.
"""

from __future__ import annotations

import asyncio
import io
import re
import threading
import time
import wave
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np


@dataclass
class Speech:
    audio: bytes
    mime: str
    elapsed: float  # since synthesis of this sentence began
    first_byte: float | None  # until the engine returned its first audio for this sentence
    duration: float | None = None  # seconds of audio in this chunk, when known


class EdgeVoice:
    """One request per sentence; refusals are retried inside the measured time."""

    ATTEMPTS = 4
    parallel = True  # network-bound: all sentences may be requested at once

    def __init__(self, voice: str) -> None:
        self.voice = voice

    async def warm(self) -> None:
        return None

    async def stream(self, text: str) -> AsyncIterator[Speech]:
        import edge_tts

        started = time.perf_counter()
        for attempt in range(self.ATTEMPTS):
            first: float | None = None
            chunks: list[bytes] = []
            try:
                async for chunk in edge_tts.Communicate(text, self.voice).stream():
                    if chunk["type"] == "audio":
                        if first is None:
                            first = time.perf_counter() - started
                        chunks.append(chunk["data"])
                break
            except edge_tts.exceptions.NoAudioReceived:
                if attempt == self.ATTEMPTS - 1:
                    raise
                await asyncio.sleep(0.3)
        yield Speech(b"".join(chunks), "audio/mpeg", time.perf_counter() - started, first)


class VieNeuVoice:
    """Local and streaming. One engine per process, used by one sentence at a time."""

    parallel = False  # CPU-bound: sentences in parallel would only slow each other
    _engine = None
    _lock = threading.Lock()

    def __init__(self, voice: str | None) -> None:
        self.voice = voice

    def _load(self):
        if VieNeuVoice._engine is None:
            from vieneu import Vieneu

            VieNeuVoice._engine = Vieneu()
        return VieNeuVoice._engine

    async def warm(self) -> None:
        """Load the model and synthesise one word, outside any timed turn."""

        def run() -> None:
            with VieNeuVoice._lock:
                self._load().infer("Dạ.")

        await asyncio.to_thread(run)

    async def stream(self, text: str) -> AsyncIterator[Speech]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()
        stop = threading.Event()
        started = time.perf_counter()

        def work() -> None:
            try:
                with VieNeuVoice._lock:
                    engine = self._load()
                    kwargs = {"voice": self.voice} if self.voice else {}
                    for chunk in engine.infer_stream(text, **kwargs):
                        if stop.is_set():
                            break
                        audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
                        loop.call_soon_threadsafe(queue.put_nowait, (audio, engine.sample_rate))
            except Exception as error:  # noqa: BLE001 - re-raised on the loop below
                loop.call_soon_threadsafe(queue.put_nowait, error)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = loop.run_in_executor(None, work)
        first: float | None = None
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, Exception):
                    raise item
                audio, rate = item
                if first is None:
                    first = time.perf_counter() - started
                yield Speech(_wav(audio, rate), "audio/wav", time.perf_counter() - started, first, len(audio) / rate)
        finally:
            # The caller stopped listening (a barge-in): let the thread finish
            # its current chunk and quit instead of voicing the whole sentence.
            stop.set()
            await worker


def _wav(audio: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _vieneu_installed() -> bool:
    try:
        import vieneu  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not offered"
        return False
    return True


def voices() -> list[dict[str, str]]:
    offered = []
    if _vieneu_installed():
        offered.append({"name": "vieneu:", "label": "VieNeu-TTS · local CPU, streaming"})
    offered += [
        {"name": "edge:vi-VN-HoaiMyNeural", "label": "HoaiMy · Microsoft neural, free endpoint (unreliable)"},
        {"name": "edge:vi-VN-NamMinhNeural", "label": "NamMinh · Microsoft neural, free endpoint (unreliable)"},
    ]
    return offered


def voice(name: str) -> EdgeVoice | VieNeuVoice:
    engine, _, rest = name.partition(":")
    if engine == "edge":
        return EdgeVoice(rest)
    if engine == "vieneu":
        return VieNeuVoice(rest or None)
    raise ValueError(f"Unknown voice {name!r}")


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str, *, shortest: int = 18) -> list[str]:
    """Split on sentence ends; fold fragments shorter than *shortest* into the next.

    A lone "Dạ." costs a synthesis round trip for half a second of audio, so
    it rides with the sentence after it.
    """
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    merged: list[str] = []
    carry = ""
    for part in parts:
        carry = f"{carry} {part}".strip()
        if len(carry) >= shortest:
            merged.append(carry)
            carry = ""
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged

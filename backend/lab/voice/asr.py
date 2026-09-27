"""Local speech recognisers behind one call: ``transcribe(samples) -> text``.

Two engines, both CPU-only because the brief requires ASR that runs on a
laptop or a free Colab:

- sherpa-onnx transducers: the Vietnamese Zipformer models. Small, fast on CPU.
- faster-whisper (CTranslate2): PhoWhisper and Whisper, quantised to int8 when
  loaded. Greedy decoding, so the timing is the fastest the model can do.

A recogniser is loaded once and shared; loading is slow (seconds), decoding
is what the lab measures. Every call blocks, so the server runs it in a thread.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODELS = Path(__file__).resolve().parent / "models"
THREADS = int(os.environ.get("LAB_ASR_THREADS", "4"))


@dataclass
class Transcript:
    model: str
    text: str
    seconds: float  # decoding time
    audio_seconds: float

    @property
    def rtf(self) -> float:
        return self.seconds / self.audio_seconds if self.audio_seconds else 0.0


class SherpaTransducer:
    def __init__(self, directory: Path) -> None:
        import sherpa_onnx

        def one(pattern: str) -> str:
            found = sorted(directory.glob(pattern))
            if not found:
                raise FileNotFoundError(f"{pattern} in {directory}")
            return str(found[0])

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=one("encoder*.onnx"),
            decoder=one("decoder*.onnx"),
            joiner=one("joiner*.onnx"),
            tokens=one("tokens.txt"),
            num_threads=THREADS,
            sample_rate=16_000,
            feature_dim=80,
            decoding_method="greedy_search",
        )

    def transcribe(self, samples: np.ndarray, hotwords: list[str]) -> str:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(16_000, samples)
        self._recognizer.decode_stream(stream)
        # The Zipformer vocabularies are upper case; the agent, the lexicon
        # and the WER bench all read lower case.
        return stream.result.text.strip().lower()


class FasterWhisper:
    def __init__(self, directory: Path) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(str(directory), device="cpu", compute_type="int8", cpu_threads=THREADS)

    def transcribe(self, samples: np.ndarray, hotwords: list[str]) -> str:
        segments, _ = self._model.transcribe(
            samples,
            language="vi",
            beam_size=1,
            without_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=False,
            hotwords=", ".join(hotwords) if hotwords else None,
        )
        return "".join(segment.text for segment in segments).strip()


#: name -> (label, engine, directory under ./models)
CATALOG: dict[str, tuple[str, type, str]] = {
    "zipformer-30m": (
        "Zipformer 30M int8 · sherpa-onnx",
        SherpaTransducer,
        "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09",
    ),
    "zipformer-2025": (
        "Zipformer vi 2025-04 int8 · sherpa-onnx",
        SherpaTransducer,
        "sherpa-onnx-zipformer-vi-int8-2025-04-20",
    ),
    "phowhisper-small": (
        "PhoWhisper small int8 · faster-whisper",
        FasterWhisper,
        "phowhisper-small",
    ),
    "whisper-turbo": (
        "Whisper large-v3-turbo int8 · faster-whisper",
        FasterWhisper,
        "whisper-large-v3-turbo",
    ),
}

_loaded: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {name: threading.Lock() for name in CATALOG}


def available() -> list[dict[str, str]]:
    return [
        {"name": name, "label": label, "loaded": name in _loaded}
        for name, (label, _, folder) in CATALOG.items()
        if (MODELS / folder).is_dir()
    ]


def load(name: str) -> float:
    """Load *name* if needed. Returns the seconds spent loading (0 if cached)."""
    if name in _loaded:
        return 0.0
    with _locks[name]:
        if name in _loaded:
            return 0.0
        _, engine, folder = CATALOG[name]
        started = time.perf_counter()
        _loaded[name] = engine(MODELS / folder)
        return time.perf_counter() - started


def transcribe(name: str, samples: np.ndarray, hotwords: list[str] | None = None) -> Transcript:
    load(name)
    started = time.perf_counter()
    text = _loaded[name].transcribe(samples, hotwords or [])
    return Transcript(name, text, time.perf_counter() - started, len(samples) / 16_000)

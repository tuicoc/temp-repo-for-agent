"""When the caller has finished speaking, and when they are cutting the agent off.

Three layers, as production voice stacks do it:

1. Silero VAD scores every 32 ms window for speech.
2. After a short silence, Smart Turn v3.2 (audio in, 23 languages including
   Vietnamese) says whether the utterance sounds finished or the caller is
   only pausing to think.
3. A ceiling on silence ends the turn regardless.

``mode="silence"`` skips layer 2 and ends the turn after a fixed silence, which
is the baseline to compare Smart Turn against.

Barge-in is continuous speech while the agent is talking. Anything shorter
than ``barge_in_ms`` is treated as a backchannel ("dạ", "vâng", "ừ") and
ignored; longer speech pauses the agent, and the recognised words decide
whether it was an interruption (:mod:`.policy`). The browser's echo cancellation is what keeps the agent's own voice
out of the microphone; headphones remove the question entirely.

Timestamps are on the server's ``perf_counter`` clock. Audio arrives in real
time, so the end of a window is estimated from when its batch arrived. The
end of the caller's speech (``TurnEnded.speech_end``) is where TTFA starts
(``eval/huong-dan-do-latency.md``).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor

from . import models_dir

RATE = 16_000
WINDOW = 512  # samples: 32 ms, what Silero expects at 16 kHz
WINDOW_MS = WINDOW * 1000 // RATE


def _session(path: Path) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


class Silero:
    """Silero VAD v5 or later, run directly on ONNX Runtime.

    The model is stateful across windows and wants the last 64 samples of the
    previous window prepended, which is what the reference wrapper does.
    """

    CONTEXT = 64
    _shared: ort.InferenceSession | None = None

    def __init__(self) -> None:
        if Silero._shared is None:
            Silero._shared = _session(models_dir() / "silero_vad.onnx")
        self._session = Silero._shared
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)
        self._rate = np.array(RATE, dtype=np.int64)

    def __call__(self, window: np.ndarray) -> float:
        x = np.concatenate([self._context, window.reshape(1, -1)], axis=1).astype(np.float32)
        out, self._state = self._session.run(None, {"input": x, "state": self._state, "sr": self._rate})
        self._context = x[:, -self.CONTEXT:]
        return float(out[0][0])


class SmartTurn:
    """Pipecat's Smart Turn v3.2: probability that the utterance is complete."""

    SECONDS = 8

    def __init__(self) -> None:
        self._session = _session(models_dir() / "smart-turn-v3.2-cpu.onnx")
        self._features = WhisperFeatureExtractor(chunk_length=self.SECONDS)

    def __call__(self, audio: np.ndarray) -> float:
        audio = audio[-self.SECONDS * RATE:]
        inputs = self._features(
            audio,
            sampling_rate=RATE,
            return_tensors="np",
            padding="max_length",
            max_length=self.SECONDS * RATE,
            truncation=True,
            do_normalize=True,
        )
        features = inputs.input_features.squeeze(0).astype(np.float32)[None]
        return float(self._session.run(None, {"input_features": features})[0][0].item())


_smart_turn: SmartTurn | None = None


def smart_turn() -> SmartTurn:
    global _smart_turn
    if _smart_turn is None:
        _smart_turn = SmartTurn()
    return _smart_turn


@dataclass
class TurnConfig:
    """How turns end. Built from the endpointing name the Admin page chose."""

    mode: str = "smart"  # "smart" or "silence"
    threshold: float = 0.5  # speech probability to start; continuing uses threshold - 0.15
    min_speech_ms: int = 160  # shorter blips never open a turn
    probe_ms: int = 200  # silence before Smart Turn is asked
    max_silence_ms: int = 1200  # the turn ends after this much silence whatever Smart Turn said
    silence_ms: int = 700  # the fixed endpoint when mode == "silence"
    barge_in_ms: int = 400  # continuous speech that interrupts the agent
    preroll_ms: int = 320  # audio kept from before the speech onset
    max_turn_s: int = 30


def config_for(endpointing: str, barge_in_ms: int) -> TurnConfig:
    """``smart`` or ``silence-<ms>``, as ``config/models.yaml`` names them."""
    if endpointing.startswith("silence-"):
        return TurnConfig(mode="silence", silence_ms=int(endpointing.split("-", 1)[1]), barge_in_ms=barge_in_ms)
    return TurnConfig(mode="smart", barge_in_ms=barge_in_ms)


ENDPOINTING = [
    {"name": "smart", "label": "Smart Turn v3.2, 1.2 s ceiling"},
    {"name": "silence-500", "label": "Silence 500 ms"},
    {"name": "silence-800", "label": "Silence 800 ms"},
]


@dataclass
class SpeechStarted:
    at: float


@dataclass
class BargeIn:
    at: float


@dataclass
class TurnEnded:
    audio: np.ndarray
    speech_end: float  # end of the last voiced window: when the caller stopped talking
    decided: float  # when the detector declared the turn over
    reason: str  # smart, timeout, silence, length
    smart_probability: float | None = None
    probes: list[float] = field(default_factory=list)


class TurnDetector:
    """Feed 16 kHz float32 audio in; get speech, turn and barge-in events out."""

    def __init__(self, config: TurnConfig) -> None:
        self.config = config
        self.agent_speaking = False
        self.peak_probability = 0.0
        self._vad = Silero()
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque(maxlen=max(1, config.preroll_ms // WINDOW_MS))
        self._turn: list[np.ndarray] = []
        self._in_turn = False
        self._voiced_ms = 0
        self._silence_ms = 0
        self._last_voice_at = 0.0
        self._last_voice_index = 0
        self._probed = False
        self._probes: list[float] = []
        self._barged = False

    @property
    def in_turn(self) -> bool:
        """Whether the caller is speaking now."""
        return self._in_turn

    def agent_started(self) -> None:
        self.agent_speaking = True
        self._barged = False

    def agent_stopped(self) -> None:
        self.agent_speaking = False

    def feed(self, samples: np.ndarray, arrived: float) -> list[object]:
        """Process one batch that reached the server at *arrived*."""
        audio = np.concatenate([self._pending, samples]) if self._pending.size else samples
        whole = len(audio) // WINDOW
        self._pending = audio[whole * WINDOW:]
        events: list[object] = []
        for i in range(whole):
            window = audio[i * WINDOW:(i + 1) * WINDOW]
            # Samples still behind this window in the batch had not been spoken yet.
            behind = len(audio) - (i + 1) * WINDOW
            at = arrived - behind / RATE
            events.extend(self._window(window, at))
        return events

    def _window(self, window: np.ndarray, at: float) -> list[object]:
        config = self.config
        probability = self._vad(window)
        # For the session's input report: the loudest speech score since it last looked.
        self.peak_probability = max(self.peak_probability, probability)
        threshold = config.threshold - 0.15 if self._in_turn else config.threshold
        voiced = probability >= threshold
        events: list[object] = []

        self._voiced_ms = self._voiced_ms + WINDOW_MS if voiced else 0
        if (
            self.agent_speaking
            and not self._barged
            and self._voiced_ms >= config.barge_in_ms
        ):
            self._barged = True
            events.append(BargeIn(at=at))

        if not self._in_turn:
            self._preroll.append(window)
            if self._voiced_ms >= config.min_speech_ms:
                self._in_turn = True
                self._turn = list(self._preroll)
                self._silence_ms = 0
                self._probed = False
                self._probes = []
                self._last_voice_at = at
                self._last_voice_index = len(self._turn)
                events.append(SpeechStarted(at=at - self._voiced_ms / 1000))
            return events

        self._turn.append(window)
        if voiced:
            self._silence_ms = 0
            self._probed = False
            self._last_voice_at = at
            self._last_voice_index = len(self._turn)
        else:
            self._silence_ms += WINDOW_MS

        if len(self._turn) * WINDOW_MS >= config.max_turn_s * 1000:
            events.append(self._end(at, "length"))
        elif config.mode == "silence":
            if self._silence_ms >= config.silence_ms:
                events.append(self._end(at, "silence"))
        else:
            if self._silence_ms >= config.probe_ms and not self._probed:
                self._probed = True
                p = smart_turn()(np.concatenate(self._turn[: self._last_voice_index]))
                self._probes.append(p)
                if p >= 0.5:
                    events.append(self._end(at, "smart", p))
            if self._in_turn and self._silence_ms >= config.max_silence_ms:
                events.append(self._end(at, "timeout"))
        return events

    def _end(self, at: float, reason: str, probability: float | None = None) -> TurnEnded:
        # Keep 160 ms after the last voiced window: enough for a trailing
        # syllable, without handing the recogniser a second of silence.
        keep = self._last_voice_index + 160 // WINDOW_MS
        audio = np.concatenate(self._turn[:keep]).astype(np.float32)
        event = TurnEnded(
            audio=audio,
            speech_end=self._last_voice_at,
            # Wall time, not the window's: Smart Turn has just run, and its
            # inference is part of the wait for the end of the turn.
            decided=max(at, time.perf_counter()),
            reason=reason,
            smart_probability=probability,
            probes=list(self._probes),
        )
        self._in_turn = False
        self._turn = []
        self._preroll.clear()
        self._voiced_ms = 0
        self._silence_ms = 0
        return event

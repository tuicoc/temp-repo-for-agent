"""The voice channel: a live call, heard and spoken locally. ``docs/design.md`` section 4.11.

    mic -> 16 kHz -> Silero VAD + Smart Turn -> local ASR -> lexicon
        -> the same turn as a chat message -> TTS, sentence by sentence -> speaker

Grown out of ``lab/voice``, where the recognisers, endpointing and voices
were compared; the lab stays as the place to try the next ones.

- :mod:`.turns`: when the caller has finished, and when they cut the agent off;
- :mod:`.asr`: the local recognisers behind one call;
- :mod:`.lexicon`: brand names as hints, and fixes for words misheard;
- :mod:`.tts`: speech, streamed per sentence.

The packages are in ``requirements.txt``, so every machine, the deployment
included, has them. The weights (about 1 GB, and VieNeu's own 1.4 GB in the
Hugging Face cache) are fetched by ``python -m src.components.voice.fetch``
into ``models/voice`` (or ``VOICE_MODELS_DIR``), which the API also runs when
it starts. Until they are there the service runs, chat works, and the call
page says what is missing. :func:`status` reports which.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from ...config.config_manager import ROOT

PACKAGES = ("numpy", "soxr", "onnxruntime", "transformers", "sherpa_onnx", "faster_whisper")


def models_dir() -> Path:
    raw = os.environ.get("VOICE_MODELS_DIR")
    return Path(raw).expanduser().resolve() if raw else ROOT / "models" / "voice"


def status() -> dict[str, object]:
    """What the voice channel has: packages, weights, and therefore whether it can run."""
    missing = [name for name in PACKAGES if importlib.util.find_spec(name) is None]
    folder = models_dir()
    weights = {
        "vad": (folder / "silero_vad.onnx").exists(),
        "smart_turn": (folder / "smart-turn-v3.2-cpu.onnx").exists(),
    }
    ready = not missing and all(weights.values())
    return {
        "status": "ok" if ready else "unavailable",
        "missing_packages": missing,
        "models_dir": str(folder),
        "weights": weights,
        "hint": None if ready else (
            "pip install -r requirements.txt" if missing else
            "the weights download when the API starts (python -m src.components.voice.fetch by hand)"
        ),
    }

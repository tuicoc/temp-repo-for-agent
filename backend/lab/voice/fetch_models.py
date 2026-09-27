"""Download every model the voice lab uses into ./models.

Run once. Files already present are skipped, so it is safe to run again.
Whisper-family models are CTranslate2 conversions from Hugging Face; the two
Zipformer models are the sherpa-onnx packages of Vietnamese transducers.

    python fetch_models.py              # the default set
    python fetch_models.py --turbo      # also Whisper large-v3-turbo (1.6 GB)
"""

from __future__ import annotations

import argparse
import tarfile
import urllib.request
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

MODELS = Path(__file__).resolve().parent / "models"

SHERPA_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
SHERPA_PACKAGES = [
    "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09",
    "sherpa-onnx-zipformer-vi-int8-2025-04-20",
]
SILERO_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
WHISPER_REPOS = {"phowhisper-small": "diepho/PhoWhisper-small-ct2"}
TURBO_REPO = ("whisper-large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo")


def fetch(url: str, target: Path) -> None:
    if target.exists():
        print(f"have {target.name}")
        return
    print(f"get  {url}")
    partial = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, partial)
    partial.rename(target)


def fetch_sherpa(name: str) -> None:
    if (MODELS / name).is_dir():
        print(f"have {name}")
        return
    archive = MODELS / f"{name}.tar.bz2"
    fetch(f"{SHERPA_RELEASES}/{name}.tar.bz2", archive)
    with tarfile.open(archive) as tar:
        tar.extractall(MODELS, filter="data")
    archive.unlink()


def fetch_whisper(local: str, repo: str) -> None:
    target = MODELS / local
    if (target / "model.bin").exists():
        print(f"have {local}")
        return
    print(f"get  {repo}")
    snapshot_download(repo, local_dir=target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turbo", action="store_true", help="also fetch Whisper large-v3-turbo")
    args = parser.parse_args()

    MODELS.mkdir(exist_ok=True)
    fetch(SILERO_URL, MODELS / "silero_vad.onnx")
    if not (MODELS / "smart-turn-v3.2-cpu.onnx").exists():
        hf_hub_download("pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx", local_dir=MODELS)
    for name in SHERPA_PACKAGES:
        fetch_sherpa(name)
    for local, repo in WHISPER_REPOS.items():
        fetch_whisper(local, repo)
    if args.turbo:
        fetch_whisper(*TURBO_REPO)
    print("done")


if __name__ == "__main__":
    main()

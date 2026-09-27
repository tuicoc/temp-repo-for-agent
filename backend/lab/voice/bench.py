"""Time and score every local recogniser on the same audio files.

    python bench.py samples          # synthesise the default Vietnamese test clips
    python bench.py run              # score every available recogniser on ./samples
    python bench.py run --dir PATH   # or on any folder of <name>.wav + <name>.txt

A clip is a 16 kHz mono WAV (other rates are resampled) with its reference
transcript in a .txt file of the same name. WER and CER are computed after
lowercasing and dropping punctuation, nothing more: numbers written as digits
by the recogniser and as words in the reference count as errors, which is
exactly the gap inverse text normalisation has to close.

Clips synthesised with TTS are clean studio speech, so their WER is a floor,
not a forecast. Real call audio will be worse.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import statistics
import unicodedata
from pathlib import Path

import numpy as np
import soundfile
import soxr

import asr

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"

DEFAULT_CLIPS = [
    ("vi-VN-HoaiMyNeural", "Chào em, chị muốn hỏi máy lọc không khí Xiaomi bốn Lite giá bao nhiêu vậy em?"),
    ("vi-VN-NamMinhNeural", "Phòng nhà anh khoảng hai mươi lăm mét vuông, nhà có con nhỏ."),
    ("vi-VN-HoaiMyNeural", "Số điện thoại của chị là không chín không tám một hai ba bốn năm sáu."),
    ("vi-VN-NamMinhNeural", "Ngân sách của anh tầm bốn triệu tám trăm nghìn thôi em ạ."),
    ("vi-VN-HoaiMyNeural", "Thôi để chị hỏi ông xã rồi chiều mai chị gọi lại cho em nhé."),
    ("vi-VN-NamMinhNeural", "Em ơi, máy Sharp với máy Coway thì máy nào chạy êm hơn?"),
    ("vi-VN-HoaiMyNeural", "Khuyến mãi tặng lõi lọc còn áp dụng tới ngày mười sáu tháng mười không em?"),
    ("vi-VN-NamMinhNeural", "Ừ được rồi, em chốt đơn cho anh, giao về quận Bình Thạnh nhé."),
]


def normalise(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


def distance(a: list, b: list) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def error_rates(reference: str, hypothesis: str) -> tuple[float, float]:
    ref_words, hyp_words = normalise(reference), normalise(hypothesis)
    ref_chars, hyp_chars = list(" ".join(ref_words)), list(" ".join(hyp_words))
    wer = distance(ref_words, hyp_words) / max(1, len(ref_words))
    cer = distance(ref_chars, hyp_chars) / max(1, len(ref_chars))
    return wer, cer


def load_wav(path: Path) -> np.ndarray:
    audio, rate = soundfile.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    return soxr.resample(audio, rate, 16_000) if rate != 16_000 else audio


async def make_samples() -> None:
    import edge_tts

    SAMPLES.mkdir(exist_ok=True)
    for index, (voice, text) in enumerate(DEFAULT_CLIPS, 1):
        stem = SAMPLES / f"clip{index:02d}"
        if stem.with_suffix(".wav").exists():
            continue
        mp3 = stem.with_suffix(".mp3")
        for attempt in range(8):
            try:
                await edge_tts.Communicate(text, voice).save(str(mp3))
                break
            except edge_tts.exceptions.NoAudioReceived:
                if attempt == 7:
                    raise
                await asyncio.sleep(2)
        audio, rate = soundfile.read(mp3, dtype="float32", always_2d=True)
        audio = soxr.resample(audio.mean(axis=1), rate, 16_000)
        soundfile.write(stem.with_suffix(".wav"), audio, 16_000, subtype="PCM_16")
        stem.with_suffix(".txt").write_text(text, encoding="utf-8")
        mp3.unlink()
        print(f"wrote {stem.name}.wav")


def run(folder: Path, only: list[str] | None, show: bool) -> None:
    clips = sorted(folder.glob("*.wav"))
    if not clips:
        raise SystemExit(f"No .wav files in {folder}; run `python bench.py samples` first")
    audio = {clip.stem: load_wav(clip) for clip in clips}
    reference = {clip.stem: clip.with_suffix(".txt").read_text(encoding="utf-8").strip() for clip in clips}
    total_audio = sum(len(a) for a in audio.values()) / 16_000

    print(f"{len(clips)} clips, {total_audio:.1f} s of audio, {asr.THREADS} threads\n")
    print(f"{'model':<18} {'load s':>7} {'mean s':>7} {'max s':>7} {'RTF':>6} {'WER':>6} {'CER':>6}")
    for entry in asr.available():
        name = entry["name"]
        if only and name not in only:
            continue
        loaded = asr.load(name)
        asr.transcribe(name, audio[clips[0].stem])  # warm-up, not timed
        times, wers, cers, outputs = [], [], [], []
        for stem, samples in audio.items():
            result = asr.transcribe(name, samples)
            wer, cer = error_rates(reference[stem], result.text)
            times.append(result.seconds)
            wers.append(wer)
            cers.append(cer)
            outputs.append((stem, result.text, wer))
        rtf = sum(times) / total_audio
        print(
            f"{name:<18} {loaded:>7.1f} {statistics.mean(times):>7.3f} {max(times):>7.3f} "
            f"{rtf:>6.3f} {statistics.mean(wers):>6.1%} {statistics.mean(cers):>6.1%}"
        )
        if show:
            for stem, text, wer in outputs:
                print(f"    {stem} {wer:>5.0%}  {text}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("samples")
    runner = sub.add_parser("run")
    runner.add_argument("--dir", type=Path, default=SAMPLES)
    runner.add_argument("--model", action="append", help="limit to these recognisers")
    runner.add_argument("--show", action="store_true", help="print every transcript")
    args = parser.parse_args()
    if args.command == "samples":
        asyncio.run(make_samples())
    else:
        run(args.dir, args.model, args.show)


if __name__ == "__main__":
    main()

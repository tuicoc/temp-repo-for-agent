"""P5 thin adapter over the existing ASR runner; replay is never new inference."""
from importlib.metadata import version
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

from .assets import Assets, read_json
from .collector import status
from .contracts import ROOT, checker, validate
from .datasets import inspect_dataset, new_output, snapshot, close_output
from .runner import _write

LOCK_KEYS = ("profile", "normalizer", "parameters", "versions", "code_hashes",
             "model_files", "scorer_sha256", "vad_parameters", "initial_prompt",
             "phone_refinement", "diarization", "warmup_samples")


def file_hash(path):
    # Stream local model weights rather than loading a GB into memory.
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verify_lock(assets, registry, split, mode):
    asr = registry["asr"]
    lock = assets.resolve(asr["dev_lock"])
    source = assets.resolve(asr["model_source"])
    runner_root = (assets.root / asr["runner"]["path"]).parent
    if (not source.get("model_id") or not source.get("revision") or source.get("download_status") != "complete"
            or (runner_root / source["local_path"]).resolve() != (assets.root / asr["model_dir"]).resolve()
            or (runner_root / source["verified_local_run"] / "config.lock.json").resolve() != (assets.root / asr["dev_lock"]["path"]).resolve()):
        raise ValueError("Model source provenance must match explicit local directory and dev lock")
    if set(lock) != set(LOCK_KEYS) or lock["profile"] != "baseline" or lock["diarization"] is not None:
        raise ValueError("P5 adapter supports the pinned M1 baseline lock only")
    if lock["code_hashes"] != {"run_eval.py": asr["runner"]["sha256"], "text_processing.py": asr["processor"]["sha256"]}:
        raise ValueError("ASR code differs from dev lock")
    if lock["scorer_sha256"] != file_hash(ROOT / "sources/btc/eval/reference_eval.py"):
        raise ValueError("ASR scorer differs from dev lock")
    if lock["versions"] != {n: version(n) for n in ("faster-whisper", "ctranslate2", "av")}:
        raise ValueError("ASR runtime differs from dev lock")
    if type(lock["warmup_samples"]) is not int or lock["warmup_samples"] < 0:
        raise ValueError("Invalid warmup lock")
    if mode == "replay":
        if asr["cohorts"][split]["replay"] is None:
            raise ValueError("No historical replay registered; use explicit local inference")
        historical = assets.resolve(asr["cohorts"][split]["replay"]["manifest"])
        if historical.get("mode") != "local_asr" or {k: historical.get(k) for k in LOCK_KEYS} != lock:
            raise ValueError("Historical hypotheses are not from the pinned dev configuration")
    if mode == "infer":
        model = (assets.root / asr["model_dir"]).resolve(strict=True)
        if not model.is_dir() or not model.is_relative_to(assets.root):
            raise ValueError("Local model directory invalid")
        files = {p.name: file_hash(p) for p in model.iterdir() if p.is_file()}
        if files != lock["model_files"] or "model.bin" not in files:
            raise ValueError("Local model inventory/hash differs from dev lock")
    return lock


def asr_suite(settings, out, *, split="eval", mode="replay"):
    if split not in ("dev", "eval") or mode not in ("replay", "infer"):
        raise ValueError("Explicit dev/eval cohort and replay/infer mode required")
    assets, registry, refs, readiness = inspect_dataset(settings)
    if not readiness["execution_gate"]["allowed"]:
        raise ValueError("Dataset execution blocked: " + ", ".join(readiness["execution_gate"]["reason_codes"]))
    lock = verify_lock(assets, registry, split, mode)
    out = new_output(out, assets, registry)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    snapshot(out, assets, refs)
    _write(out / "dataset-readiness.json", readiness)
    local = Assets(out)
    cohort = registry["asr"]["cohorts"][split]
    gt = assets.resolve(cohort["ground_truth"])
    expected = [d["id"] for d in gt["dialogues"]]
    # Materialize the existing runner's layout from verified snapshot bytes.
    dataset = out / "native-input"
    (dataset / "audio").mkdir(parents=True)
    shutil.copyfile(out / "inputs" / cohort["ground_truth"]["path"], dataset / "ground_truth.json")
    for audio in cohort["audio"]:
        shutil.copyfile(out / "inputs" / audio["asset"]["path"], dataset / "audio" / (audio["id"] + ".wav"))
    argv = [sys.executable, "-B", str(ROOT.parent / "asr/run_eval.py"), "--dataset", str(dataset),
            "--out", str(out / "native-asr"), "--model", str(assets.root / registry["asr"]["model_dir"]),
            "--profile", lock["profile"], "--warmup", str(lock["warmup_samples"]),
            "--expected-count", str(len(expected))]
    if mode == "replay":
        argv += ["--hypotheses", str(out / "inputs" / cohort["replay"]["hypotheses"]["path"]), "--reextract"]
    else:
        argv += ["--lock", str(out / "inputs" / registry["asr"]["dev_lock"]["path"])]
    invocation = {"argv": argv, "mode": mode, "split": split,
                  "runner_sha256": registry["asr"]["runner"]["sha256"],
                  "adapter_sha256": file_hash(Path(__file__)), "dev_lock": registry["asr"]["dev_lock"],
                  "new_inference": mode == "infer", "returncode": None}
    with (out / "stdout.log").open("x") as stdout, (out / "stderr.log").open("x") as stderr:
        try:
            completed = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=1800 if mode == "infer" else 120)
            invocation["returncode"] = completed.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            invocation["error"] = str(exc)
    _write(out / "asr-invocation.json", invocation)
    issues = []

    def issue(code, message, path="asr-invocation.json"):
        item = {"code": code, "message": message, "classification": "missing_evidence",
                "artifact": local.ref(path), "json_pointer": ""}
        validate("Issue", item)
        issues.append(item)

    if invocation["returncode"] not in (0, 2):
        issue("ASR_RUNNER_ERROR", "Native runner failed or timed out; partial evidence retained")
    observed, unknown, native = [], [], None
    if (out / "native-asr/report.json").is_file():
        native = read_json(out / "native-asr/report.json")
        hypotheses = read_json(out / "native-asr/hypotheses.json")
        observed = sorted(hypotheses)
        unknown = native["coverage"]["unknown_ids"]
        if not native["coverage"]["complete"]:
            issue("ASR_NATIVE_INCOMPLETE", "Native input/hypothesis validation incomplete", "native-asr/coverage.json")
        if mode == "replay" and (read_json(out / "native-asr/timing.json") or native["timing"]["asr_seconds_per_audio_minute"] is not None):
            issue("REPLAY_TIMING_INVALID", "Replay cannot report newly measured ASR timing", "native-asr/timing.json")
    else:
        issue("ASR_REPORT_MISSING", "No native report; entire expected cohort retained")
    missing = sorted(set(expected) - set(observed))
    if missing or unknown or set(observed) - set(expected):
        issue("ASR_COVERAGE", "Missing/unknown hypotheses; never shrink registered cohort")
    # Recheck producer files and source pins after execution, before closing evidence.
    try:
        for ref in refs:
            assets.resolve(ref, json_content=False)
        verify_lock(assets, registry, split, mode)
        checker.verify_sources()
    except (OSError, ValueError, KeyError) as exc:
        issue("ASR_INPUT_CHANGED", str(exc))
    state = status(issues)
    coverage = {"schema_version": "1.0.0", "artifact_id": "p5/asr/coverage", "run_id": out.name,
                "scope": "team_asr/" + split, "expected_ids": expected, "observed_ids": observed,
                "missing_ids": missing, "duplicate_ids": [], "unknown_ids": sorted(set(unknown) | (set(observed) - set(expected))),
                "status": state}
    validate("Coverage", coverage)
    _write(out / "coverage.json", coverage)
    validation = {"schema_version": "1.0.0", "artifact_id": "p5/asr/validation", "run_id": out.name,
                  "status": state, "issues": issues, "coverage_refs": [local.ref("coverage.json")]}
    validate("ValidationReport", validation)
    _write(out / "validation.json", validation)
    report = {"report_kind": "p5-asr-suite-v1", "dataset_id": registry["dataset_id"], "version": registry["version"],
              "split": split, "mode": mode,
              "new_inference": bool(mode == "infer" and native and native["timing"]["samples"]), "status": state,
              "provisional": registry["provisional"], "review_policy": registry["review_policy"],
              "human_review_complete": native["human_review_complete"] if native else False,
              "benchmark_ready": readiness["benchmark_ready"], "quality_accepted": False, "btc_audio_evaluated": False,
              "coverage_ref": local.ref("coverage.json"), "validation_ref": local.ref("validation.json"),
              "native_report_ref": local.ref("native-asr/report.json") if native else None,
              "raw_metrics": native["raw_metrics"] if native else None,
              "normalized_metrics": native["normalized_metrics"] if native else None,
              "supplemental_entity_accuracy": native["supplemental_entity_accuracy"] if native else None,
              "timing": native["timing"] if native else None,
              "timing_notice": "REPLAY_NO_NEW_TIMING" if mode == "replay" else "Native timing excludes pinned warmup; not TTFT",
              "notice": "Pipeline status only. Native BTC metrics retained without replacement formulas; P6 aggregation pending."}
    _write(out / "asr-suite-report.json", report)
    close_output(out)
    return report

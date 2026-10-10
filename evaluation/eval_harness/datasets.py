"""P5 pinned provisional dataset inventory; no generation, review or model calls."""
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import wave

from .assets import Assets, read_json
from .collector import status
from .contracts import ROOT, checker, validate
from .extractor import digest
from .runner import _output_path, _write

REVIEW_WAIVER = "USER_SKIP_REVIEW_TEMPORARY_DATASET_2026_10_04"


def load_registry(settings):
    settings = Path(settings).resolve()
    config = read_json(settings)
    if set(config) != {"asset_root", "registry"}:
        raise ValueError("P5 settings require asset_root and pinned registry AssetRef")
    assets = Assets(settings.parent / config["asset_root"])
    registry = assets.resolve(config["registry"])
    if set(registry) != {"schema_version", "dataset_id", "version", "provisional", "review_policy", "scenario_sets", "asr"}:
        raise ValueError("Unexpected P5 registry fields")
    if registry["schema_version"] != "p5-inputs-v1" or not isinstance(registry["provisional"], bool):
        raise ValueError("P5 staging registry version/provisional flag invalid")
    if not registry["dataset_id"] or not registry["version"]:
        raise ValueError("Dataset id/version required")
    review = registry["review_policy"]
    if set(review) != {"required", "reason"} or type(review["required"]) is not bool:
        raise ValueError("Explicit review policy required")
    if not review["required"] and (review["reason"] != REVIEW_WAIVER or not registry["provisional"]):
        raise ValueError("Do not silently waive human review")
    asr = registry["asr"]
    if set(asr) != {"runner", "processor", "model_source", "model_dir", "dev_lock", "cohorts"} or set(asr["cohorts"]) != {"dev", "eval"}:
        raise ValueError("P5 ASR requires explicit runner/processor/model/dev lock and dev/eval cohorts")
    refs = [config["registry"]]
    for ref in [config["registry"]] + [asr[k] for k in ("runner", "processor", "model_source", "dev_lock")]:
        validate("AssetRef", ref)
        if ref["pointer"]:
            raise ValueError("P5 registry and ASR file pins require whole-file pointers")
    for key, file in (("runner", "run_eval.py"), ("processor", "text_processing.py")):
        path = assets.resolve(asr[key], json_content=False)
        if path.read_bytes() != (ROOT.parent / "asr" / file).read_bytes():
            raise ValueError("ASR adapter only runs the existing canonical code")
        refs.append(asr[key])
    for key in ("model_source", "dev_lock"):
        assets.resolve(asr[key])
        refs.append(asr[key])
    model = (assets.root / asr["model_dir"]).resolve()
    if Path(asr["model_dir"]).is_absolute() or not model.is_relative_to(assets.root):
        raise ValueError("Model directory must stay inside asset_root")
    checker.verify_sources()
    return assets, registry, refs, config["registry"]


def inspect_dataset(settings):
    assets, registry, refs, registry_ref = load_registry(settings)
    issues, scenario_inventory, audio_inventory = [], [], []
    customers, ids, payloads = defaultdict(set), defaultdict(set), defaultdict(set)

    def issue(code, message, classification="missing_evidence", origin=None):
        item = {"code": code, "message": message, "classification": classification,
                "artifact": origin or registry_ref, "json_pointer": ""}
        validate("Issue", item)
        issues.append(item)

    def take(ref, json_content=True):
        value = assets.resolve(ref, json_content=json_content)
        refs.append(ref)
        return value

    qualifying = []
    for group in registry["scenario_sets"]:
        if set(group) != {"id", "split", "asset_root", "manifest"} or group["split"] not in ("development", "frozen", "growth", "public"):
            raise ValueError("Scenario set requires id/split/asset_root/pinned manifest")
        manifest = take(group["manifest"])
        validate("Manifest", manifest)
        group_root = (assets.root / group["asset_root"]).resolve(strict=True)
        if not group_root.is_relative_to(assets.root):
            raise ValueError("Scenario root must stay inside declared asset_root")
        source = Assets(group_root)
        def linked(ref):
            source.resolve(ref, json_content=False)
            return {**ref, "path": str(group_root.relative_to(assets.root) / ref["path"])}
        for ref in manifest["sources"] + manifest["grading_contracts"] + [manifest["configuration"][k] for k in ("prompt", "tools", "kb")]:
            take(linked(ref), json_content=False)
        for ref in manifest["scenarios"]:
            scenario = take(linked(ref))
            validate("Scenario", scenario)
            sid = scenario["scenario_id"]
            fingerprint = digest({k: v for k, v in scenario.items() if k not in ("scenario_id", "notes")})
            if sid in ids[group["split"]] or fingerprint in payloads[group["split"]]:
                issue("SCENARIO_DUPLICATE", sid, "schema_error")
            ids[group["split"]].add(sid)
            payloads[group["split"]].add(fingerprint)
            customers[group["split"]].add(scenario["customer_phone"])
            calls = len(scenario["calls"])
            row = {"scenario_id": sid, "split": group["split"], "fixture": manifest["fixture"],
                   "calls": calls, "hard_case": scenario["hard_case"], "customer_phone": scenario["customer_phone"],
                   "channels": sorted({c.get("channel", "unspecified") for c in scenario["calls"].values()})}
            scenario_inventory.append(row)
            if group["split"] == "frozen" and not manifest["fixture"] and not scenario.get("derived_from"):
                qualifying.append(row)
                if calls not in (2, 3):
                    issue("FROZEN_CALL_COUNT", sid)
    all_audio_ids, all_audio_hashes = set(), set()
    for split, cohort in registry["asr"]["cohorts"].items():
        if set(cohort) != {"ground_truth", "audio", "replay"} or (cohort["replay"] is not None and set(cohort["replay"]) != {"manifest", "hypotheses"}):
            raise ValueError("Cohort requires GT/audio; replay is null or pinned manifest/hypotheses")
        file_refs = [cohort["ground_truth"]] + [a["asset"] for a in cohort["audio"]]
        if cohort["replay"] is not None:
            file_refs += list(cohort["replay"].values())
        for ref in file_refs:
            validate("AssetRef", ref)
            if ref["pointer"]:
                raise ValueError("ASR dataset/replay pins require whole-file pointers")
        gt = take(cohort["ground_truth"])
        if not isinstance(gt, dict) or not isinstance(gt.get("dialogues"), list) or not gt["dialogues"]:
            raise ValueError("ASR GT needs nonempty dialogues")
        expected = [d["id"] for d in gt["dialogues"]]
        if len(set(expected)) != len(expected):
            issue("ASR_GT_DUPLICATE", split, "schema_error")
        for dialogue in gt["dialogues"]:
            key = dialogue["id"]
            if not isinstance(key, str) or not key or key in (".", "..") or Path(key).name != key:
                raise ValueError("Unsafe ASR dialogue ID")
            if not isinstance(dialogue.get("full_text"), str) or not dialogue["full_text"].strip():
                raise ValueError("ASR full_text required")
            phone = dialogue.get("entities", {}).get("phone")
            if phone:
                customers["development" if split == "dev" else "frozen"].add(str(phone))
        declared = [a["id"] for a in cohort["audio"]]
        if Counter(expected) != Counter(declared):
            issue("ASR_DECLARED_COVERAGE", split)
        seconds, valid, reviewed = 0.0, 0, sum(d.get("review_status") == "human_verified" for d in gt["dialogues"])
        for audio in cohort["audio"]:
            if set(audio) != {"id", "asset"}:
                raise ValueError("Audio requires id and AssetRef")
            if audio["id"] in all_audio_ids or audio["asset"]["sha256"] in all_audio_hashes:
                issue("ASR_SPLIT_OR_AUDIO_DUPLICATE", audio["id"], "schema_error")
            all_audio_ids.add(audio["id"])
            all_audio_hashes.add(audio["asset"]["sha256"])
            try:
                path = take(audio["asset"], False)
                with wave.open(str(path), "rb") as wav:
                    frames = wav.getnframes()
                    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000) or not frames:
                        raise ValueError("Nonempty PCM16 mono 16kHz required")
                    if len(wav.readframes(frames)) != frames * 2:
                        raise ValueError("Truncated WAV")
                    seconds += frames / 16000
                valid += 1
            except (ValueError, OSError, EOFError, wave.Error) as exc:
                issue("ASR_AUDIO_MISSING_OR_INVALID", str(exc), origin=audio["asset"])
        if cohort["replay"] is not None:
            historical = take(cohort["replay"]["manifest"])
            take(cohort["replay"]["hypotheses"])
            if historical.get("ground_truth_sha256") != cohort["ground_truth"]["sha256"]:
                issue("REPLAY_GT_MISMATCH", split, "schema_error")
            previous = {a["id"]: a["sha256"] for a in historical.get("audio", [])}
            if len(previous) != len(historical.get("audio", [])) or previous != {a["id"]: a["asset"]["sha256"] for a in cohort["audio"]}:
                issue("REPLAY_AUDIO_MISMATCH", split, "schema_error")
        audio_inventory.append({"split": split, "declared": len(expected), "valid_wav": valid,
                                "audio_seconds": seconds, "human_verified": reviewed,
                                "review_status": gt.get("review_status", "unverified")})
        if registry["review_policy"]["required"] and (reviewed != len(expected) or gt.get("review_status") != "human_verified"):
            issue("HUMAN_REVIEW_PENDING", split)
    names = sorted(customers)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if customers[a] & customers[b]:
                issue("CUSTOMER_SPLIT_LEAK", a + "/" + b, "schema_error")
    ordinary = sum(not r["hard_case"] for r in qualifying)
    hard = sum(bool(r["hard_case"]) for r in qualifying)
    evaluation_audio = next(r for r in audio_inventory if r["split"] == "eval")
    quotas = {"frozen_ordinary": {"actual": ordinary, "required": 20},
              "frozen_hard": {"actual": hard, "required": 5},
              "team_eval_audio": {"actual": evaluation_audio["valid_wav"], "required": 20}}
    for key, quota in quotas.items():
        if quota["actual"] < quota["required"]:
            issue("DATASET_QUOTA", key + ": " + str(quota))
    if registry["provisional"]:
        issue("PROVISIONAL_DATASET", "User requested existing temporary data; replacement expected")
    c1 = {"transcripts": None, "audio_files": None, "audio_seconds": None,
          "multisession_customers": None, "multichannel_customers": None}
    # C.1 product-corpus quotas cannot be inferred from an evaluation registry.
    issue("PRODUCT_CORPUS_INVENTORY_NOT_SUPPLIED", "120 transcripts/40 audio/1h/30 multisession/10 multichannel need separate inventory")
    execution_issues = [i for i in issues if i["code"] not in ("DATASET_QUOTA", "PROVISIONAL_DATASET", "PRODUCT_CORPUS_INVENTORY_NOT_SUPPLIED")]
    report = {"dataset_id": registry["dataset_id"], "version": registry["version"],
              "provisional": registry["provisional"], "review_policy": registry["review_policy"],
              "source_asset_root": str(assets.root), "status": status(issues), "issues": issues,
              "execution_gate": {"allowed": not execution_issues, "reason_codes": sorted({i["code"] for i in execution_issues})},
              "scenario_inventory": scenario_inventory, "asr_inventory": audio_inventory,
              "quotas": quotas, "product_corpus_C1": c1,
              "benchmark_ready": not issues, "btc_audio_evaluated": False,
              "notice": "P5 provisional inventory, not a Frozen/production benchmark certification"}
    unique_refs = {digest(r): r for r in refs}
    return assets, registry, list(unique_refs.values()), report


def new_output(out, assets, registry):
    # The declared root may be evaluation/ (which also owns runs/).
    # Protect concrete inputs, not that whole shared root.
    out = _output_path(out, Assets(ROOT))
    protected = [assets.root / registry["asr"]["model_dir"]]
    protected += [(assets.root / group["manifest"]["path"]).parent for group in registry["scenario_sets"]]
    protected += [(assets.root / registry["asr"][key]["path"]).parent for key in ("dev_lock", "model_source", "runner", "processor")]
    protected += [(assets.root / ref["path"]).parent for c in registry["asr"]["cohorts"].values()
                  if c["replay"] is not None for ref in c["replay"].values()]
    protected += [(assets.root / c["ground_truth"]["path"]).parent for c in registry["asr"]["cohorts"].values()]
    if any(out.is_relative_to(p.resolve()) for p in protected):
        raise ValueError("Do not write inside dataset/model inputs")
    return out


def snapshot(out, assets, refs):
    out = Path(out).resolve()
    for ref in refs:
        path = assets.resolve({**ref, "pointer": ""}, json_content=False)
        payload = path.read_bytes()
        target = out / "inputs" / ref["path"]
        if not target.resolve().is_relative_to(out / "inputs"):
            raise ValueError("Snapshot path escaped output")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != payload:
                raise ValueError("Conflicting pinned snapshot bytes")
        else:
            with target.open("xb") as stream:
                stream.write(payload)


def close_output(out):
    _write(out / "artifacts.lock.json", {"files": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                   for p in sorted(out.rglob("*")) if p.is_file()}})


def dataset_readiness(settings, out):
    assets, registry, refs, report = inspect_dataset(settings)
    out = new_output(out, assets, registry)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    snapshot(out, assets, refs)
    _write(out / "dataset-readiness.json", report)
    for ref in refs:
        assets.resolve(ref, json_content=False)
    close_output(out)
    return report

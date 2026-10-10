"""Pinned fixture replay only. No heuristic pretending to be a general extractor."""
import hashlib
import json
from pathlib import Path

from .contracts import ROOT


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def extractor_input(document):
    # Deliberately excludes scenario, expected labels, memory, tools' oracle results.
    return {key: document[key] for key in ("agent_text", "tool_texts", "consultant_texts")}


class FixtureExtractor:
    def __init__(self, assets, descriptor_ref, manifest):
        if descriptor_ref not in manifest["sources"]:
            raise ValueError("Extractor descriptor must be pinned before Agent execution")
        descriptor = assets.resolve(descriptor_ref)
        required = {"kind", "version", "records", "schema", "implementation_sha256"}
        if set(descriptor) != required or descriptor["kind"] != "fixture_replay":
            raise ValueError("Only explicit fixture_replay is implemented; no model fallback")
        if not manifest["fixture"] or manifest["purpose"] == "official_eval":
            raise ValueError("Fixture extraction must never be used for a real/official benchmark")
        if descriptor["version"] != manifest["configuration"]["extractor_version"]:
            raise ValueError("Extractor version differs from pinned manifest")
        if descriptor["implementation_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError("Extractor implementation changed; repin in a new run")
        for key in ("records", "schema"):
            if descriptor[key] not in manifest["sources"]:
                raise ValueError(f"Pin extractor {key} in manifest.sources")
        assets.resolve(descriptor["schema"])
        if descriptor["schema"]["sha256"] != hashlib.sha256((ROOT / "contracts.schema.json").read_bytes()).hexdigest():
            raise ValueError("Pinned extraction schema differs from local contract registry")
        records = assets.resolve(descriptor["records"])
        if not isinstance(records, list) or any(set(r) != {"input_sha256", "items"} for r in records):
            raise ValueError("Fixture records require exact input_sha256/items pairs")
        self.records = {r["input_sha256"]: r["items"] for r in records}
        if len(self.records) != len(records):
            raise ValueError("Duplicate extraction inputs; never select the best annotation")
        self.version, self.descriptor_ref = descriptor["version"], descriptor_ref
        self.descriptor = descriptor

    def replay(self, document):
        key = digest(extractor_input(document))
        if key not in self.records:
            raise ValueError("No pinned fixture annotation for actual input; extraction missing")
        return self.records[key]

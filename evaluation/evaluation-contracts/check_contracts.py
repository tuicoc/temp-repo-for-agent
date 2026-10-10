#!/usr/bin/env python3
"""Offline contract/fixture checks; never executes an Agent, tool, or scorer."""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urldefrag

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def pointer(data, path):
    for key in path.removeprefix("/").split("/") if path else []:
        key = key.replace("~1", "/").replace("~0", "~")
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def walk(data):
    yield data
    if isinstance(data, dict):
        for value in data.values():
            yield from walk(value)
    elif isinstance(data, list):
        for value in data:
            yield from walk(value)


def edit(data, path, value=None, remove=False):
    parent, _, key = path.rpartition("/")
    target = pointer(data, parent)
    key = int(key) if isinstance(target, list) else key
    if remove:
        del target[key]
    else:
        target[key] = value


SCHEMAS = [ROOT / "contracts.schema.json", ROOT / "grading-contract.schema.json"]
SCHEMAS += [ROOT / "sources/btc/schemas" / name for name in
            ("trace_log.schema.json", "call_brief.schema.json", "handoff_brief.schema.json")]
# No network retrieval callback. Unregistered resources fail closed.
registry = Registry()
for path in SCHEMAS:
    document = json.loads(path.read_text())
    Draft202012Validator.check_schema(document)
    registry = registry.with_resource(path.as_uri(), Resource.from_contents(document, default_specification=DRAFT202012))
for path in SCHEMAS:
    for node in walk(json.loads(path.read_text())):
        if isinstance(node, dict) and "$ref" in node:
            registry.resolver(path.as_uri()).lookup(node["$ref"])


def errors(schema, data):
    file, fragment = urldefrag(schema)
    uri = (ROOT / file).resolve().as_uri() + ("#" + fragment if fragment else "")
    return list(Draft202012Validator({"$ref": uri}, registry=registry,
                                    format_checker=FormatChecker()).iter_errors(data))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def asset_errors(data):
    issues = set()
    for node in walk(data):
        if not isinstance(node, dict) or not {"path", "sha256", "pointer"} <= node.keys():
            continue
        path = (ROOT / node["path"]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            issues.add("S03_REFERENCE")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != node["sha256"]:
            issues.add("S04_HASH")
        try:
            if node["pointer"]:
                pointer(json.loads(path.read_text()), node["pointer"])
        except (KeyError, IndexError, ValueError, TypeError):
            issues.add("S03_REFERENCE")
    return issues


def semantics(bundle):
    """Selected cross-artifact checks demonstrable using fixtures, not a runner."""
    out = asset_errors(bundle)
    manifest, traces = bundle["manifest"], bundle["traces"]
    expected = {(manifest["run_id"], p["config"], p["scenario_id"], p["call"], turn)
                for p in manifest["planned_calls"] for turn in range(1, p["expected_turns"] + 1)}
    observed = [(t["run_id"], t["config"], t["scenario_id"], t["call"], t["turn"]) for t in traces]
    if len(observed) != len(set(observed)):
        out.add("S01_DUPLICATE")
    if set(observed) != expected:
        out.add("S02_COVERAGE")
    if manifest["state_namespaces"]["full"] == manifest["state_namespaces"]["baseline_no_memory"]:
        out.add("S06_STATE")
    plans = {c: {(p["scenario_id"], p["call"], p["expected_turns"]) for p in manifest["planned_calls"] if p["config"] == c}
             for c in ("full", "baseline_no_memory")}
    if plans["full"] != plans["baseline_no_memory"]:
        out.add("S06_STATE")
    inputs = {}
    for trace in traces:
        key = (trace["scenario_id"], trace["call"], trace["turn"])
        text = trace["customer_text"]
        if key in inputs and inputs[key] != text:
            out.add("S14_INPUT")
        inputs[key] = text
    grading = bundle["grading"]
    try:
        scenario = pointer(read(grading["scenario"]["path"]), grading["scenario"]["pointer"])
        if grading["scenario_id"] != scenario["scenario_id"]:
            out.add("S12_GRADING")
        if {x["call"] for x in grading["calls"]} != set(scenario["calls"]):
            out.add("S12_GRADING")
        for call in grading["calls"]:
            original = scenario["calls"][call["call"]].get("success_if")
            reference = call["official_success_if"]
            expected_pointer = grading["scenario"]["pointer"] + "/calls/" + call["call"] + "/success_if"
            if original is not None and (reference is None or reference["path"] != grading["scenario"]["path"] or reference["pointer"] != expected_pointer or reference["sha256"] != grading["scenario"]["sha256"]):
                out.add("S12_GRADING")
            if original is None and reference is not None:
                out.add("S12_GRADING")
    except (KeyError, IndexError, ValueError, TypeError, OSError):
        out.add("S12_GRADING")
    for suite, key in (("asr", "asr_ids"), ("rag", "rag_ids")):
        if set(manifest[key]) != set(bundle.get(suite, {})):
            out.add("S13_SUITE_COVERAGE")
    for node in walk(bundle):
        if not isinstance(node, dict):
            continue
        if {"verdict", "completeness", "reason_codes"} <= node.keys():
            allowed = {("PASS", "COMPLETE"), ("FAIL", "COMPLETE"), ("FAIL", "INCOMPLETE"),
                       ("UNDETERMINED", "INCOMPLETE"), ("NOT_APPLICABLE", "NOT_APPLICABLE")}
            if (node["verdict"], node["completeness"]) not in allowed:
                out.add("S05_STATUS")
        if {"started_at", "finished_at"} <= node.keys():
            from datetime import datetime
            if datetime.fromisoformat(node["finished_at"]) < datetime.fromisoformat(node["started_at"]):
                out.add("S07_TIME")
        if {"expected_ids", "observed_ids", "missing_ids", "unknown_ids", "duplicate_ids"} <= node.keys():
            expected_ids, observed_ids = set(node["expected_ids"]), node["observed_ids"]
            duplicates = {k for k, count in Counter(observed_ids).items() if count > 1}
            if (set(node["missing_ids"]) != expected_ids - set(observed_ids)
                    or set(node["unknown_ids"]) != set(observed_ids) - expected_ids
                    or set(node["duplicate_ids"]) != duplicates
                    or len(expected_ids) != len(node["expected_ids"])):
                out.add("S02_COVERAGE")
            if (node["missing_ids"] or node["unknown_ids"] or duplicates) and node["status"]["completeness"] == "COMPLETE":
                out.add("S05_STATUS")
        if {"metric_id", "formula_id", "value", "denominator", "status"} <= node.keys():
            if node["status"] != "MEASURED" and node["value"] is not None:
                out.add("S08_FORMULA")
            if node["status"] == "MEASURED" and node["denominator"] == 0:
                out.add("S08_FORMULA")
            # Current fixture protocol; legacy tool-accuracy.v1 is report history only.
            if node["formula_id"] == "tool-accuracy.v1":
                out.add("S08_FORMULA")
            if node["formula_id"] in ("ratio.v1", "percent.v1", "tool-accuracy.v2", "cost-call.v1") and node["status"] == "MEASURED":
                den, num = node["denominator"], node["numerator"]
                factor = 100 if node["formula_id"] in ("percent.v1", "tool-accuracy.v2") else 1
                if not den or num is None or node["value"] is None or abs(node["value"] - factor*num/den) > 1e-6:
                    out.add("S08_FORMULA")
                if node["formula_id"] == "tool-accuracy.v2" and node["unit"] != "percent":
                    out.add("S08_FORMULA")
                if node["formula_id"] == "cost-call.v1" and (node["unit"] != "currency_per_call" or node["currency"] is None):
                    out.add("S08_FORMULA")
        if {"criterion_id", "applicable", "attempts", "status", "verdict"} <= node.keys():
            if node["applicable"] and node["status"]["verdict"] in ("PASS", "FAIL"):
                if node["verdict"] is None or node["verdict"]["criterion_id"] != node["criterion_id"] or node["verdict"]["verdict"] != node["status"]["verdict"]:
                    out.add("S09_JUDGE")
            if not node["applicable"] and (node["verdict"] is not None or node["attempts"] != 0):
                out.add("S09_JUDGE")
        if {"source_split", "permission", "purpose"} <= node.keys():
            if node["source_split"] in ("frozen", "hidden") and node["permission"] == "allow" and node["purpose"] == "learning":
                out.add("S11_SOURCE")
    decision = bundle["release"]
    if decision["decision"] == "active":
        if len({decision[k] for k in ("candidate_hash", "approved_hash", "evaluated_hash")}) != 1:
            out.add("S10_RELEASE")
        applicable = {x["id"] for x in manifest["suites"] if x["applicable"]}
        results = {x["suite"]: x for x in decision["suite_results"] if x["applicable"]}
        if not applicable <= results.keys() or decision["dispute_ids"]:
            out.add("S10_RELEASE")
        if any(x["status"]["verdict"] != "PASS" or x["status"]["completeness"] != "COMPLETE" or x["report"] is None for x in results.values()):
            out.add("S10_RELEASE")
    return out


def verify_sources():
    """Read-only BTC inventory/hash gate, also reused before starting workers."""
    lock = read("sources.lock.json")
    actual_files = {str(p.relative_to(ROOT)) for p in (ROOT/"sources/btc").rglob("*") if p.is_file() and p.name != ".DS_Store"}
    require(actual_files == set(lock["files"]), "Source inventory drift")
    for path, digest in lock["files"].items():
        require(hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, f"BTC altered: {path}")
    return lock


def main():
    """Validate pinned BTC sources and the templates used by live evaluation."""
    lock = verify_sources()
    for path in (ROOT / "sources/btc/test_set/public_sample").glob("*.json"):
        require(not errors("contracts.schema.json#/$defs/Scenario", json.loads(path.read_text())), str(path))
    for path in (ROOT / "sources/btc/eval/runs").glob("*.jsonl"):
        for line in path.read_text().splitlines():
            require(not errors("sources/btc/schemas/trace_log.schema.json", json.loads(line)), str(path))
    require(not errors("contracts.schema.json#/$defs/OfficialReport", read("sources/btc/eval/runs/report_example.json")), "Report BTC mismatch")
    require(not errors("grading-contract.schema.json", read("fixtures/grading.json")), "Grading template invalid")
    print(f"PASS: {len(SCHEMAS)} schemas, {len(lock['files'])} pinned BTC source hashes, live grading template.")
    print("NOT RUN: Agent, extractor, scorer, acceptance behaviors A01–A18.")


if __name__ == "__main__":
    main()

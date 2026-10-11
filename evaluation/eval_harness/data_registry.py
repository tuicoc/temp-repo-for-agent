"""One offline inventory for team text scenarios under evaluation/datasets."""
from collections import Counter
from pathlib import Path

from .assets import read_json
from .contracts import validate
from .extractor import digest


def inspect(root, only=None):
    root = Path(root).resolve(strict=True)
    registry = read_json(root / "registry.json")
    if set(registry) != {"schema_version", "sets"} or registry["schema_version"] != "team-datasets-v1" or not isinstance(registry["sets"], list):
        raise ValueError("Invalid team dataset registry")
    rows, issues, ids, fingerprints = [], [], [], []
    groups = [group for group in registry["sets"] if only is None or group["id"] == only]
    if only is not None and len(groups) != 1:
        raise ValueError("Dataset ID must select exactly one registered set")
    for group in groups:
        if not {"id", "split", "path", "reviewed_by", "status"}.issubset(group) or set(group) - {"id", "split", "path", "reviewed_by", "status", "tool_labels", "gt_review"} or group["split"] not in {"development", "public", "frozen", "growth"} or group["status"] not in {"diagnostic", "approved"}:
            raise ValueError("Invalid dataset set declaration")
        path = (root / group["path"]).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_dir() or path == root:
            raise ValueError("Dataset path escapes evaluation/datasets")
        files = sorted(path.glob("*.json"))
        if not files:
            issues.append({"code": "EMPTY_SET", "set": group["id"]})
        if group["status"] == "approved" and not group["reviewed_by"]:
            issues.append({"code": "REVIEW_MISSING", "set": group["id"]})
        labels = None
        reviews = None
        if group["status"] == "approved":
            label_path = (root / group.get("tool_labels", "")).resolve()
            if not label_path.is_relative_to(root) or not label_path.is_file():
                issues.append({"code": "TOOL_LABELS_MISSING", "set": group["id"]})
            else:
                labels = read_json(label_path)
                if not isinstance(labels, dict):
                    raise ValueError("Tool labels must map scenario/call IDs")
            review_path = (root / group.get("gt_review", "")).resolve()
            if not review_path.is_relative_to(root) or not review_path.is_file():
                issues.append({"code": "GT_REVIEW_MISSING", "set": group["id"]})
            else:
                reviews = read_json(review_path)
                if not isinstance(reviews, dict):
                    raise ValueError("GT review must map scenario/call IDs")
        for file in files:
            scenario = read_json(file)
            validate("Scenario", scenario)
            sid = scenario["scenario_id"]
            ids.append(sid)
            fingerprints.append(digest({k: v for k, v in scenario.items() if k not in {"scenario_id", "notes"}}))
            if scenario.get("seed_history") or any(call.get("seed_history") for call in scenario["calls"].values()):
                issues.append({"code": "UNSUPPORTED_SEED_HISTORY", "scenario": sid})
            if reviews is not None:
                expected_review = reviews.get(sid)
                if not isinstance(expected_review, dict) or set(expected_review) != set(scenario["calls"]):
                    issues.append({"code": "GT_REVIEW_COVERAGE", "scenario": sid})
                else:
                    for call_id, review in expected_review.items():
                        if (not isinstance(review, dict) or set(review) != {"status", "reviewed_by", "source", "decision"}
                                or review.get("status") != "approved" or review.get("reviewed_by") != group["reviewed_by"]
                                or not isinstance(review.get("source"), str) or not review["source"].strip()
                                or not isinstance(review.get("decision"), str) or not review["decision"].strip()):
                            issues.append({"code": "GT_REVIEW_INCOMPLETE", "scenario": sid, "call": call_id})
            if labels is not None:
                expected = labels.get(sid)
                if not isinstance(expected, dict) or set(expected) != set(scenario["calls"]):
                    issues.append({"code": "TOOL_LABEL_COVERAGE", "scenario": sid})
                else:
                    for call_id, spec in scenario["calls"].items():
                        row = expected[call_id]
                        if not isinstance(row, list) or any(set(item) != {"name", "args_match", "required"} for item in row):
                            issues.append({"code": "TOOL_LABEL_SHAPE", "scenario": sid, "call": call_id})
                            continue
                        required = spec["success_if"].get("tool_called") if spec.get("success_if") else None
                        if bool(row) != bool(required) or (required and (len(row) != 1 or row[0] != {"name": required, "args_match": spec["success_if"].get("args_match", {}), "required": True})):
                            issues.append({"code": "TOOL_LABEL_MISMATCH", "scenario": sid, "call": call_id})
            rows.append({"scenario_id": sid, "set": group["id"], "split": group["split"],
                         "status": group["status"], "calls": len(scenario["calls"]), "sha256": digest(scenario)})
        if labels is not None and set(labels) != {row["scenario_id"] for row in rows if row["set"] == group["id"]}:
            issues.append({"code": "TOOL_LABEL_SET_COVERAGE", "set": group["id"]})
        if reviews is not None and set(reviews) != {row["scenario_id"] for row in rows if row["set"] == group["id"]}:
            issues.append({"code": "GT_REVIEW_SET_COVERAGE", "set": group["id"]})
    for key, values in (("SCENARIO_ID_DUPLICATE", ids), ("SCENARIO_CONTENT_DUPLICATE", fingerprints)):
        for value, count in Counter(values).items():
            if count > 1:
                issues.append({"code": key, "value": value})
    return {"schema_version": "team-dataset-readiness-v1", "scenarios": rows,
            "issues": issues, "execution_gate": {"allowed": not issues and bool(rows) and all(row["status"] == "approved" for row in rows)},
            "notice": "Offline shape/coverage gate; reviewer assertions and business GT must be independently verified against BTC sources."}

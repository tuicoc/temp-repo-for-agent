"""Optional, closed P6 billing/review evidence; never repair historical runs."""
from collections import Counter
from math import isclose

from .assets import Assets, parse_json, read_json
from .collector import context_key, locked_run
from .contracts import validate
from .extractor import digest


def reconcile_usage(assets, ledger, raw_assets, config, run_id, policy):
    """Each hook request and adapter binding gets exactly one reconciled receipt.

    Provider/adapter billing is a trusted input, not proof of provider authenticity.
    Missing or unfinalized usage remains incomplete, including timeout charges.
    """
    required = {"schema_version", "run_id", "configs"}
    if set(ledger) != required or ledger["schema_version"] != "p6-usage-ledger-v1" or ledger["run_id"] != run_id:
        raise ValueError("Usage ledger shape/run mismatch")
    if set(ledger["configs"]) != {"full", "baseline_no_memory"}:
        raise ValueError("Usage ledger must cover both configurations")
    group = ledger["configs"][config]
    if set(group) != {"raw_records_ref", "receipts"}:
        raise ValueError("Usage group requires raw_records_ref/receipts")
    raw_ref = raw_assets.ref(config + "/raw-records.json")
    if group["raw_records_ref"] != raw_ref:
        raise ValueError("Usage ledger does not bind exact raw records")
    raw = raw_assets.resolve(raw_ref)
    expected = [i for i, r in enumerate(raw) if r.get("kind") == "hook_request" or
                r.get("kind") == "adapter_message" and r.get("phase") == "binding"]
    indices = [r["raw_index"] for r in group["receipts"]]
    if any(type(i) is not int for i in indices) or Counter(indices) != Counter(expected):
        raise ValueError("Usage receipt coverage missing/duplicate/unknown")
    totals = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    receipt_ids = set()
    incomplete = None
    for entry in group["receipts"]:
        if set(entry) != {"raw_index", "receipt_ref"}:
            raise ValueError("Usage entry shape invalid")
        receipt = assets.resolve(entry["receipt_ref"])
        required = {"receipt_id", "request_sha256", "cost_scope", "reconciled", "pricing_sha256",
                    "currency", "cost", "input_tokens", "output_tokens", "cost_units"}
        if not isinstance(receipt, dict) or set(receipt) != required:
            raise ValueError("Billing receipt shape invalid")
        if not isinstance(receipt["receipt_id"], str) or not receipt["receipt_id"].strip() or receipt["receipt_id"] in receipt_ids:
            raise ValueError("Duplicate/empty billing receipt ID")
        receipt_ids.add(receipt["receipt_id"])
        if receipt["request_sha256"] != digest(raw[entry["raw_index"]]) or receipt["cost_scope"] != "hook_runtime":
            raise ValueError("Billing receipt wrong hook/scope")
        if type(receipt["reconciled"]) is not bool:
            raise ValueError("Reconciliation flag must be boolean")
        if not receipt["reconciled"]:
            incomplete = "USAGE_RECONCILIATION_PENDING"
        if receipt["pricing_sha256"] != digest(policy["prices"]) or receipt["currency"] != policy["currency"]:
            raise ValueError("Billing receipt price/currency mismatch")
        if any(type(receipt[k]) is not int or receipt[k] < 0 for k in ("input_tokens", "output_tokens")):
            raise ValueError("Receipt tokens must be nonnegative integers")
        if not isinstance(receipt["cost_units"], dict) or set(receipt["cost_units"]) != {"asr", "tts", "tool"}:
            raise ValueError("Explicit ASR/TTS/tool usage required")
        if any(type(receipt["cost_units"][k]) is not int for k in ("tts", "tool")):
            raise ValueError("TTS character/tool invocation counts must be integers")
        units = {"llm_input": receipt["input_tokens"], "llm_output": receipt["output_tokens"], **receipt["cost_units"]}
        if any(type(u) not in (int, float) or u < 0 for u in units.values()):
            raise ValueError("Invalid component usage")
        if type(receipt["cost"]) not in (int, float) or receipt["cost"] < 0:
            raise ValueError("Invalid receipt cost")
        if policy["currency"] is None or any(p is None for p in policy["prices"].values()):
            incomplete = "PRICE_OR_COST_SCOPE_MISSING"
            continue
        charge = 0.0
        for key, rate in policy["prices"].items():
            if rate == "not_used":
                if units[key] != 0:
                    raise ValueError("Billing not_used contradicts usage")
            else:
                charge += rate * units[key]
        if not isclose(charge, receipt["cost"], rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("Billing receipt total does not match pinned prices")
        for key in totals:
            totals[key] += receipt[key]
    # No receipt is not evidence of zero usage.
    if not expected:
        incomplete = "NO_RUNTIME_USAGE_RECEIPTS"
    return (None if incomplete else totals), incomplete


def import_casebook(assets, originals, score_assets, manifest):
    review = read_json(assets.path("casebook-review.json"))
    if set(review) != {"schema_version", "run_id", "reviewed_by", "source_score_ref", "records"} or review["schema_version"] != "p6-casebook-review-v1":
        raise ValueError("Casebook review shape invalid")
    if review["run_id"] != manifest["run_id"] or review["source_score_ref"] != score_assets.ref("score-report.json"):
        raise ValueError("Casebook review does not bind exact source score")
    if not isinstance(review["reviewed_by"], str) or not review["reviewed_by"].strip():
        raise ValueError("Casebook reviewer required")
    by_id = {e["error_id"]: e for e in originals}
    seen, reviewed = set(), []
    for record in review["records"]:
        validate("ErrorRecord", record)
        error_id = record["error_id"]
        if error_id in seen or error_id not in by_id:
            raise ValueError("Duplicate/unknown reviewed error")
        seen.add(error_id)
        original = by_id[error_id]
        immutable = ("run_id", "context", "category", "expected", "observed", "source_split", "learning_permission")
        if any(record[k] != original[k] for k in immutable):
            raise ValueError("Reviewed error changes original evidence/learning permission")
        if any(not isinstance(record[k], str) or not record[k].strip() for k in ("root_cause", "remediation")):
            raise ValueError("Nonempty root cause/remediation required")
        if not record["evidence_refs"] or not record["retest_ref"] or record["retest_ref"]["pointer"]:
            raise ValueError("Case analysis evidence and whole retest report required")
        for ref in record["evidence_refs"]:
            assets.resolve(ref, json_content=False)
        retest = assets.resolve(record["retest_ref"])
        validate("SupplementalReport", retest)
        if retest["run_id"] == manifest["run_id"]:
            raise ValueError("Retest must be a distinct actual run, not R0 regrade")
        retest_path = assets.path(record["retest_ref"]["path"])
        retest_assets, _ = locked_run(retest_path.parent)
        retest_manifest = read_json(retest_assets.path("manifest.json"))
        validate("Manifest", retest_manifest)
        if retest["run_id"] == manifest["run_id"] or retest_manifest["run_id"] != retest["run_id"]:
            raise ValueError("Retest must be a distinct actual run, not R0 regrade")
        ctx = record["context"]
        trace_name = "full" if ctx["config"] == "full" else "baseline"
        trace = [parse_json(line) for line in retest_assets.path("scorer-input/" + trace_name + ".jsonl").read_text().splitlines()]
        raw_run = read_json(retest_assets.path("evidence/raw/runner-report.json"))
        if raw_run["run_id"] != retest["run_id"] or any(r["run_id"] != retest["run_id"] for r in trace):
            raise ValueError("Retest report reuses old raw/trace run identity")
        if not any(r["scenario_id"] == ctx["scenario_id"] and r["call"] == ctx["call"] and r["config"] == ctx["config"] for r in trace):
            raise ValueError("Retest lacks reviewed call execution")
        if retest_manifest["fixture"] and not manifest["fixture"]:
            raise ValueError("Fixture retest cannot qualify a real error")
        for check in retest["checks"]:
            for ref in check["evidence_refs"]:
                retest_assets.resolve(ref, json_content=False)
        reviewed.append(record)
    return reviewed

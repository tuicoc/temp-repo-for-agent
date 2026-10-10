"""Create a diagnostic BTC-compatible revision of output (1); never edit its source."""
import copy
import hashlib
import json
from pathlib import Path

from eval_harness.contracts import validate

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "output (1)" / "scenarios"
TARGET = ROOT / "datasets" / "output1-btc-diagnostic-v1"

# Human-authored diagnostic assertions; none is an approved official GT label.
ASSERTIONS = {
    "SCN-GEN-0001": {
        "call_1": {"tool_called": "pricing.get_quote", "args_match": {"sku": "SKU-AP-X"}},
        "call_2": {"tool_called": "order.status", "args_match": {"order_id": "OD188213"}},
    },
    "SCN-GEN-0002": {
        "call_1": {"tool_called": "pricing.get_quote", "args_match": {"sku": "SKU-MB-PUMP1"}},
        "call_2": {"tool_called": "order.status", "args_match": {"order_id": "OD301177"}},
    },
    "SCN-GEN-0003": {
        "call_1": {"tool_called": "inventory.check", "args_match": {"sku": "SKU-AP-Y"},
                   "must_not_call_tools": ["order.create"]},
        "call_2": {"must_say_any": ["mã đơn", "thông tin đơn"], "must_not_call_tools": ["order.create"]},
        "call_3": {"must_say_any": ["mã đơn", "thông tin đơn"], "must_not_call_tools": ["order.create"]},
    },
    "SCN-GEN-0004": {
        "call_1": {"must_say_any": ["xác nhận", "cho em biết tên"], "must_not_call_tools": ["order.create", "order.status"]},
        "call_2": {"must_say_any": ["xác nhận", "cho em biết tên"], "must_not_call_tools": ["order.create", "order.status"]},
        "call_3": {"must_say_any": ["xác nhận", "cho em biết tên"], "must_not_call_tools": ["order.create", "order.status"]},
    },
    "SCN-GEN-0005": {
        "call_1": {"must_say_any": ["xác nhận", "cho em biết tên"], "must_not_call_tools": ["order.create", "order.status"]},
        "call_2": {"must_say_any": ["xác nhận", "cho em biết tên"], "must_not_call_tools": ["order.create", "order.status"]},
    },
}

OUTCOMES = {"cap_nhat_don": "khac", "thong_tin": "khac", "chot": "khac"}
PRIVATE_ORDER_FIELDS = ("order_id", "order_status", "tracking", "order_date")


def convert(source):
    scenario = copy.deepcopy(source)
    sid = scenario["scenario_id"]
    if set(scenario["calls"]) != set(ASSERTIONS[sid]):
        raise ValueError(f"Unexpected calls in {sid}")
    changes = []
    for call, spec in scenario["calls"].items():
        before = copy.deepcopy(spec)
        spec["success_if"] = copy.deepcopy(ASSERTIONS[sid][call])
        outcome = spec.get("expected_outcome")
        spec["expected_outcome"] = OUTCOMES.get(outcome, outcome)
        if spec.get("days_later", 0) is None:
            spec.pop("days_later")
        # A shared phone is not an identity; no private CRM/order GT may be assumed.
        if sid in ("SCN-GEN-0004", "SCN-GEN-0005"):
            spec.pop("must_carry_over", None)
            for field in PRIVATE_ORDER_FIELDS:
                spec.get("ground_truth_facts", {}).pop(field, None)
        elif sid == "SCN-GEN-0003":
            spec.pop("must_carry_over", None)
            if call != "call_1":
                for field in PRIVATE_ORDER_FIELDS:
                    spec.get("ground_truth_facts", {}).pop(field, None)
        elif sid == "SCN-GEN-0001" and call == "call_2":
            spec["must_carry_over"] = ["order_id"]
            spec["must_not_ask"] = ["order_id"]
            # The old SKU was sold at 4.29m; 4.49m is a different current quote.
            spec["ground_truth_facts"].pop("final_price_vnd", None)
        elif sid == "SCN-GEN-0002" and call == "call_2":
            spec["must_carry_over"] = ["tracking"]
            spec["must_not_ask"] = ["order_id"]
        if sid == "SCN-GEN-0005":
            for key, value in list(spec.get("ground_truth_facts", {}).items()):
                if value is None and key in ("list_price_vnd", "final_price_vnd", "stock_qty"):
                    del spec["ground_truth_facts"][key]
        for field in spec.get("must_carry_over", []):
            if field not in spec.get("ground_truth_facts", {}):
                raise ValueError(f"Carry-over has no GT: {sid}/{call}/{field}")
        changed = {key: {"before": before.get(key), "after": spec.get(key)}
                   for key in ("success_if", "expected_outcome", "days_later", "must_carry_over", "must_not_ask")
                   if before.get(key) != spec.get(key)}
        old_gt, new_gt = before.get("ground_truth_facts", {}), spec.get("ground_truth_facts", {})
        for key in sorted(set(old_gt) | set(new_gt)):
            if old_gt.get(key) != new_gt.get(key):
                changed["ground_truth_facts/" + key] = {"before": old_gt.get(key), "after": new_gt.get(key)}
        changes.append({"call": call, "field_changes": changed,
                        "gt_status": "diagnostic_author_interpreted_pending_qa"})
    validate("Scenario", scenario)
    return scenario, changes


def main():
    if TARGET.exists():
        raise SystemExit(f"Refusing to overwrite existing revision: {TARGET}")
    files = sorted(SOURCE.glob("*.json"))
    if {p.stem for p in files} != set(ASSERTIONS):
        raise SystemExit("Source scenario set changed; review normalization first")
    prepared, report = {}, []
    for path in files:
        raw = path.read_bytes()
        scenario, changes = convert(json.loads(raw))
        prepared[path.name] = json.dumps(scenario, ensure_ascii=False, indent=2) + "\n"
        report.append({"source": str(path.relative_to(ROOT)), "source_sha256": hashlib.sha256(raw).hexdigest(),
                       "derived": "scenarios/" + path.name, "calls": changes})
    (TARGET / "scenarios").mkdir(parents=True)
    for name, payload in prepared.items():
        (TARGET / "scenarios" / name).write_text(payload, encoding="utf-8")
    (TARGET / "conversion-report.json").write_text(json.dumps({
        "schema_version": "output1-btc-diagnostic-v1", "official_gt_approved": False,
        "scope": "5 scenarios; JSON only; no ASR; no model run", "files": report,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(files)} scenario files / {sum(len(r['calls']) for r in report)} calls: {TARGET}")


if __name__ == "__main__":
    main()

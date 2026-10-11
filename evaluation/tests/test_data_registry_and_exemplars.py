import json
import tempfile
import unittest
from unittest.mock import patch
import sys
from pathlib import Path

from eval_harness.data_registry import inspect
from eval_harness.exemplars import check
from normalize_output1 import ROOT
from product import prepare


class DataRegistryAndExemplarTest(unittest.TestCase):
    def test_registered_diagnostic_data_is_visible_but_not_approved(self):
        report = inspect(ROOT / "datasets")
        self.assertEqual(len(report["scenarios"]), 5)
        self.assertFalse(report["execution_gate"]["allowed"])

    def test_two_independent_inserted_examples_are_few_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank = [dict(exemplar_id=f"E{i}", version=1, situation="too_expensive",
                         source_call_id=f"C{i}", source_customer_id=f"P{i}", source_split="development",
                         order_verified=True, qa_passed=True, approved_by="qa@example.test",
                         status="active", dialogue=[{"role": "agent", "text": "Mình dự kiến ngân sách bao nhiêu ạ?"}])
                    for i in (1, 2)]
            usage = [{"turn_id": "T1", "situation": "too_expensive", "selected": [["E1", 1], ["E2", 1]],
                      "inserted": [["E1", 1], ["E2", 1]]}]
            (root / "bank.json").write_text(json.dumps(bank))
            (root / "usage.json").write_text(json.dumps(usage))
            report = check(root / "bank.json", root / "usage.json")
            self.assertEqual(report["turns"][0]["status"], "few_shot")
            bank[1]["source_customer_id"] = "P1"
            (root / "bank.json").write_text(json.dumps(bank))
            self.assertIn("SOURCES_NOT_INDEPENDENT", [i["code"] for i in check(root / "bank.json", root / "usage.json")["issues"]])

    def test_registered_sixth_case_can_prepare_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "new/scenarios"
            directory.mkdir(parents=True)
            sample = json.loads((ROOT / "datasets/output1-btc-diagnostic-v2/scenarios/SCN-GEN-0001.json").read_text())
            sample["scenario_id"] = "TEAM-NEW-0006"
            (directory / "TEAM-NEW-0006.json").write_text(json.dumps(sample))
            labels = {sample["scenario_id"]: {call: ([{"name": spec["success_if"]["tool_called"],
                "args_match": spec["success_if"].get("args_match", {}), "required": True}]
                if spec["success_if"].get("tool_called") else []) for call, spec in sample["calls"].items()}}
            (root / "labels.json").write_text(json.dumps(labels))
            reviews = {sample["scenario_id"]: {call: {"status": "approved", "reviewed_by": "human-reviewer",
                "source": "BTC policy and mock state for the call date", "decision": "Verified expected outcome and success conditions"}
                for call in sample["calls"]}}
            (root / "review.json").write_text(json.dumps(reviews))
            (root / "registry.json").write_text(json.dumps({"schema_version": "team-datasets-v1", "sets": [
                {"id": "new", "split": "development", "path": "new/scenarios", "tool_labels": "labels.json",
                 "gt_review": "review.json", "reviewed_by": "human-reviewer", "status": "approved"}]}))
            self.assertTrue(inspect(root, only="new")["execution_gate"]["allowed"])
            (root / "review.json").write_text("{}")
            self.assertFalse(inspect(root, only="new")["execution_gate"]["allowed"])
            (root / "review.json").write_text(json.dumps(reviews))
            with patch("product.DATASETS", root), patch("product.PYTHON", Path(sys.executable)), patch("product.product_settings", return_value={
                "provider": "test", "model": "test-model", "parameters": {"temperature": 0},
                "extractor": {"provider": "test", "model": "test-model"},
            }):
                report = prepare(root / "prepared", dataset_id="new")
            self.assertTrue(report["execution_gate"]["allowed"])


if __name__ == "__main__":
    unittest.main()

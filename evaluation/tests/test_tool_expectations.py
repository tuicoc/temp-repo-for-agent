import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from eval_harness.assets import read_json
from eval_harness.contracts import validate
from product import prepare
from tool_expectations import labels_for
from normalize_output1 import ROOT


class ToolExpectationsTest(unittest.TestCase):
    def test_all_five_scenarios_have_pinned_labels(self):
        paths = sorted((ROOT / "datasets/output1-btc-diagnostic-v2/scenarios").glob("SCN-GEN-*.json"))
        self.assertEqual(len(paths), 5)
        calls = [(read_json(path)["scenario_id"], call, data["success_if"])
                 for path in paths for call, data in read_json(path)["calls"].items()]
        self.assertEqual(len(calls), 12)
        self.assertEqual(sum(len(labels_for(*entry)) for entry in calls), 5)
        for scenario_id, call, success_if in calls:
            self.assertEqual(bool(labels_for(scenario_id, call, success_if)), bool(success_if.get("tool_called")))

    def test_prepare_wires_both_configs_without_running_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "inputs"
            with patch("product.PYTHON", Path(sys.executable)), patch("product.product_settings", return_value={
                "provider": "test", "model": "test-model", "parameters": {"temperature": 0},
                "extractor": {"provider": "test", "model": "test-model"},
            }):
                result = prepare(out)
            self.assertTrue(result["execution_gate"]["allowed"])
            for config in ("full", "baseline_no_memory"):
                labels = sorted((out / "expected-tools" / config).rglob("*.json"))
                self.assertEqual(len(labels), 12)
                for path in labels:
                    validate("ExpectedToolCalls", read_json(path))
                    self.assertEqual(read_json(path)["context"]["config"], config)


if __name__ == "__main__":
    unittest.main()

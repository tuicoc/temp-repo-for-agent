import json
import tempfile
import unittest
from pathlib import Path

from eval_harness.history import render_history


class HistoryTest(unittest.TestCase):
    def test_completed_and_failed_runs(self):
        with tempfile.TemporaryDirectory() as root:
            runs = Path(root)
            failed = runs / "20261010-100000"
            failed.mkdir()
            (failed / "execution-report.json").write_text(json.dumps({
                "stages": [{"stage": "run", "completed_calls": 0, "execution_complete": False,
                            "errors": [{"code": "EXECUTION_ERROR", "phase": "open_scenario"}]}],
                "pipeline_error": None,
            }))
            complete = runs / "20261010-110000"
            (complete / "scored").mkdir(parents=True)
            (complete / "execution-report.json").write_text(json.dumps({
                "stages": [{"stage": "run", "completed_calls": 24},
                           {"stage": "score", "status": {"verdict": "FAIL", "completeness": "INCOMPLETE",
                                                         "reason_codes": ["USAGE_MISSING"]}}],
                "pipeline_error": None,
            }))
            (complete / "scored/official-report.json").write_text(json.dumps({
                "baseline": {"task_success_rate": {"value": 20}},
                "system": {"task_success_rate": {"value": 40}},
            }))
            table = render_history(runs)
            self.assertIn("20261010-100000 | 0 | — → —", table)
            self.assertIn("ERROR | EXECUTION_ERROR (open_scenario)", table)
            self.assertIn("20261010-110000 | 24 | 20% → 40%", table)
            self.assertIn("FAIL/INCOMPLETE | USAGE_MISSING", table)


if __name__ == "__main__":
    unittest.main()

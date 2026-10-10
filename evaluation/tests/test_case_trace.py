import json
from pathlib import Path
import tempfile
import unittest

from eval_harness.case_trace import build, write


class CaseTraceTests(unittest.TestCase):
    def test_complete_and_partial_views(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / "inputs/scenarios").mkdir(parents=True)
            (run / "evidence").mkdir()
            (run / "scored").mkdir()
            scenario = {"scenario_id": "CASE-1", "calls": {"call_1": {
                "customer_turns": ["Xin chào"], "success_if": {"must_say_any": ["chào"]}}}}
            (run / "inputs/scenarios/CASE-1.json").write_text(json.dumps(scenario))
            (run / "inputs/manifest.json").write_text(json.dumps({"run_id": "RUN-1", "scenarios": [{}]}))
            report = {"stages": [{"stage": "score", "status": {"completeness": "COMPLETE"}}],
                      "pipeline_error": None}
            partial = build(run, report)
            self.assertEqual(partial["status"], "INCOMPLETE")
            self.assertEqual(partial["cases"][0]["configurations"]["full"]["calls"][0]["turns"][0]["agent_text"], "MISSING")

            row = {"scenario_id": "CASE-1", "call": "call_1", "turn": 1,
                   "agent_text": "Chào chị", "tool_calls": [{"result": {"_internal_note": "secret"}}]}
            for name in ("full", "baseline"):
                (run / f"evidence/{name}.jsonl").write_text(json.dumps(row) + "\n")
            (run / "scored/official-report.json").write_text(json.dumps({"system": {}, "baseline": {}}))
            result = build(run, report)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["cases"][0]["configurations"]["full"]["calls"][0]["turns"][0]["tool_calls"][0]["result"]["_internal_note"], "[REDACTED]")
            for stage in ("run", "collect", "score"):
                interrupted = {"stages": [{"stage": stage}], "pipeline_error": stage + " failed"}
                self.assertEqual(build(run, interrupted)["status"], "INCOMPLETE")
            path = write(run, report)
            self.assertEqual(path.name, "case-trace.json")
            self.assertEqual(json.loads(path.read_text())["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()

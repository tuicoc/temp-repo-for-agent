import json
from pathlib import Path
import tempfile
import unittest

from eval_harness.gaps import candidates, check, publish


class KnowledgeGapTest(unittest.TestCase):
    def test_handoff_is_candidate_not_automatic_faq(self):
        row = {"run_id": "RUN", "scenario_id": "SCN", "call": "call_1", "turn": 2,
               "customer_text": "Máy này dùng cho phòng lớn được không?",
               "agent_text": "Em xin chuyển người phụ trách ạ.",
               "tool_calls": [{"name": "handoff.transfer", "result": {"ticket_id": "T-1"}}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "full/transcripts").mkdir(parents=True)
            (root / "full/transcripts/turn.json").write_text(json.dumps({"context": {"scenario_id": "SCN", "call": "call_1", "turn": 2},
                "consultant_texts": ["Có, nếu dưới 30m2."]}))
            report = candidates({"full": [row]}, root, source_split="development")
            self.assertEqual(len(report["candidates"]), 1)
            gap = report["candidates"][0]
            self.assertEqual(gap["status"], "REVIEW_REQUIRED")
            source = root / "candidates.json"
            source.write_text(json.dumps(report))
            review = root / "review.json"
            approved = {"gap_id": gap["gap_id"], "reviewer": "consultant-1", "decision": "approve_faq",
                        "general_question": "Máy dùng cho phòng 30m2 được không?",
                        "general_answer": "Có thể dùng theo diện tích hãng công bố.",
                        "evidence": "Consultant answered; checked manufacturer specification",
                        "policy_checked": True, "consultant_answer_verified": True,
                        "must_say_any": ["diện tích hãng công bố"]}
            review.write_text(json.dumps(approved))
            with self.assertRaises(ValueError):
                publish(source, self._unapproved(root, approved), root / "no-review")
            source.write_text(json.dumps(candidates({"full": [row]}, root, source_split="frozen")))
            with self.assertRaises(ValueError):
                publish(source, review, root / "frozen")
            source.write_text(json.dumps(report))
            result = publish(source, review, root / "approved")
            self.assertEqual(result["status"], "CANDIDATE_READY")
            case = json.loads((root / "approved/growth-case.json").read_text())
            self.assertEqual(case["split"], "growth")
            self.assertTrue(case["golden_set_unchanged"])
            response = root / "responses.json"
            response.write_text(json.dumps({gap["gap_id"]: "Vui lòng xem diện tích hãng công bố."}))
            self.assertEqual(check(root, response)["counts"]["PASS"], 1)
            response.write_text(json.dumps({gap["gap_id"]: "Em không biết."}))
            self.assertEqual(check(root, response)["counts"]["FAIL"], 1)
            response.write_text("{}")
            self.assertEqual(check(root, response)["counts"]["MISSING"], 1)

    def test_explicit_unknown_is_captured_without_handoff(self):
        row = {"run_id": "RUN", "scenario_id": "SCN", "call": "call_1", "turn": 1,
               "customer_text": "Khi nào giao?", "agent_text": "Em chưa có thông tin chính xác ạ.",
               "tool_calls": []}
        with tempfile.TemporaryDirectory() as directory:
            report = candidates({"full": [row]}, Path(directory))
        self.assertEqual(len(report["candidates"]), 1)
        self.assertFalse(report["candidates"][0]["signals"]["handoff_success"])

    @staticmethod
    def _unapproved(root, review):
        path = root / "unapproved.json"
        path.write_text(json.dumps({**review, "policy_checked": False}))
        return path


if __name__ == "__main__":
    unittest.main()

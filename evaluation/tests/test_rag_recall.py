import unittest
import json
import tempfile
from pathlib import Path

from eval_harness.rag_recall import validate_retrieval
from eval_harness.reporting import btc_module


class RagRecallTest(unittest.TestCase):
    def test_coverage_and_ids(self):
        questions = [{"qid": f"Q{i:02}", "type": "multi_hop" if i == 1 else "single",
                      "relevant_chunk_ids": ["A", "B"] if i == 1 else ["A"]}
                     for i in range(1, 61)]
        results = {q["qid"]: ["A", "B"] for q in questions}
        self.assertTrue(validate_retrieval(questions, results))
        with self.assertRaises(ValueError):
            validate_retrieval(questions, {"Q01": ["A"]})
        results["Q01"] = ["A", "A"]
        with self.assertRaises(ValueError):
            validate_retrieval(questions, results)

    def test_btc_scorer_uses_retrieved_ids_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa.json").write_text(json.dumps({"questions": [
                {"qid": "Q01", "type": "single", "relevant_chunk_ids": ["A"]}]}))
            (root / "retrieval.json").write_text(json.dumps({
                "Q01": {"retrieved_chunk_ids": ["A"]}}))
            scored = btc_module().rag_eval(str(root / "qa.json"), str(root / "retrieval.json"))
            self.assertEqual(scored["recall@3"], 100)


if __name__ == "__main__":
    unittest.main()

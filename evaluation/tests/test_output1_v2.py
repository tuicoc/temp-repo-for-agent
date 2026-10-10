import unittest

from eval_harness.assets import read_json
from normalize_output1 import ROOT, convert


class Output1V2Test(unittest.TestCase):
    def test_reviewed_labels_and_pinned_source(self):
        source = ROOT / "output (1)/scenarios"
        target = ROOT / "datasets/output1-btc-diagnostic-v2/scenarios"
        for path in sorted(source.glob("*.json")):
            self.assertEqual(convert(read_json(path))[0], read_json(target / path.name))
        three = read_json(target / "SCN-GEN-0003.json")["calls"]
        self.assertIn("chưa có đơn", three["call_2"]["success_if"]["must_say_any"])
        self.assertIn("chưa ghi nhận đơn", three["call_3"]["success_if"]["must_say_any"])
        four = read_json(target / "SCN-GEN-0004.json")["calls"]
        five = read_json(target / "SCN-GEN-0005.json")["calls"]
        for call in (*four.values(), *five.values()):
            self.assertIn("cho em xin tên", call["success_if"]["must_say_any"])
            self.assertIn("order.status", call["success_if"]["must_not_call_tools"])
        two = read_json(target / "SCN-GEN-0002.json")["calls"]["call_2"]
        self.assertEqual(two["must_carry_over"], ["tracking"])
        self.assertFalse(read_json(target.parent / "conversion-report.json")["official_gt_approved"])


if __name__ == "__main__":
    unittest.main()

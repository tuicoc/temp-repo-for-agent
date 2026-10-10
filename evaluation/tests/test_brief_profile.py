import unittest

from eval_harness.scoring import brief_matches_profile
from eval_harness.collector import expects_call_brief


class BriefProfileTest(unittest.TestCase):
    scenario = {"customer_phone": "0985003703"}
    spec = {"ground_truth_facts": {"customer_id": "C031"}}

    def test_masked_call_brief_is_the_same_profile(self):
        self.assertTrue(brief_matches_profile(
            {"customer_phone": "******3703", "customer_id": "C031"}, "call_brief", self.scenario, self.spec))

    def test_wrong_last_four_or_customer_id_is_rejected(self):
        self.assertFalse(brief_matches_profile(
            {"customer_phone": "******9999", "customer_id": "C031"}, "call_brief", self.scenario, self.spec))
        self.assertFalse(brief_matches_profile(
            {"customer_phone": "******3703", "customer_id": "C999"}, "call_brief", self.scenario, self.spec))

    def test_handoff_still_requires_the_full_phone(self):
        self.assertFalse(brief_matches_profile(
            {"customer_phone": "******3703", "customer_id": "C031"}, "handoff_brief", self.scenario, self.spec))
        self.assertTrue(brief_matches_profile(
            {"customer_phone": "0985003703", "customer_id": None}, "handoff_brief", self.scenario, self.spec))

    def test_no_brief_is_expected_for_an_unidentified_shared_phone(self):
        context = {"config": "full", "call": "call_2"}
        self.assertFalse(expects_call_brief(context, {"customer_id": "unidentified"}))
        self.assertTrue(expects_call_brief(context, {"customer_id": "C031"}))
        self.assertFalse(expects_call_brief({"config": "baseline_no_memory", "call": "call_2"},
                                            {"customer_id": "C031"}))


if __name__ == "__main__":
    unittest.main()

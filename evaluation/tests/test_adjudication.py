import unittest

from eval_harness.adjudication import interpret_claim, review_tool_errors


class AdjudicationTest(unittest.TestCase):
    def test_product_alias_requires_unique_catalog_evidence(self):
        expected = "Máy lọc không khí AirPure Y"
        row = {"tool_calls": [{"name": "catalog.search", "result": {"items": [
            {"sku": "SKU-Y", "name": expected}]}}]}
        self.assertEqual(interpret_claim("product_name", "AirPure Y", expected, [row])[0], "EQUIVALENT")
        row["tool_calls"][0]["result"]["items"].append({"sku": "SKU-OTHER", "name": "Bộ lọc AirPure Y"})
        self.assertEqual(interpret_claim("product_name", "AirPure Y", expected, [row])[0], "NEEDS_REVIEW")

    def test_shipping_needs_tool_confirmation(self):
        row = {"tool_calls": [{"name": "order.status", "result": {"orders": [{"status": "shipping"}]}}]}
        self.assertEqual(interpret_claim("order_status", "đang giao hàng", "shipping", [row])[0], "EQUIVALENT")
        self.assertEqual(interpret_claim("order_status", "đã giao hàng", "shipping", [row])[0], "NEEDS_REVIEW")
        self.assertEqual(interpret_claim("order_status", "đang giao hàng", "shipping", [])[0], "NEEDS_REVIEW")

    def test_tool_error_keeps_original_error_and_recovery(self):
        context = {"scenario_id": "SCN-1", "call": "call_1"}
        events = [
            {"outcome": "business_error", "context": context, "event_id": "err",
             "request": {"name": "pricing.get_quote", "args": {"sku": "AP-X"}}, "result": {"error": "unknown_sku"}},
            {"outcome": "success", "context": context, "event_id": "ok",
             "request": {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X"}}, "result": {}},
        ]
        row = review_tool_errors({"baseline_no_memory": events})["rows"][0]
        self.assertEqual((row["sku_arg"], row["error"], row["recovered_by"]), ("AP-X", "unknown_sku", "ok"))


if __name__ == "__main__":
    unittest.main()

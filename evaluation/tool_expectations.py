"""Diagnostic tool-call labels for the five output (1) scenarios.

Only explicit, still-valid success_if tool requirements become required calls.
All other read-only calls are allowed; business errors are reviewed separately.
"""

REQUIRED = {
    "SCN-GEN-0001": {"call_1": ("pricing.get_quote", {"sku": "SKU-AP-X"}),
                     "call_2": ("order.status", {"order_id": "OD188213"})},
    "SCN-GEN-0002": {"call_1": ("pricing.get_quote", {"sku": "SKU-MB-PUMP1"}),
                     "call_2": ("order.status", {"order_id": "OD301177"})},
    "SCN-GEN-0003": {"call_1": ("inventory.check", {"sku": "SKU-AP-Y"})},
    "SCN-GEN-0004": {},
    "SCN-GEN-0005": {},
}


def labels_for(scenario_id, call, success_if):
    if scenario_id not in REQUIRED or call not in ("call_1", "call_2", "call_3"):
        raise ValueError("Unknown tool label context")
    required = REQUIRED[scenario_id].get(call)
    if required is not None and (success_if.get("tool_called"), success_if.get("args_match")) != required:
        raise ValueError(f"Tool label disagrees with reviewed scenario: {scenario_id}/{call}")
    if required is None and success_if.get("tool_called"):
        raise ValueError(f"Unlabelled required tool: {scenario_id}/{call}")
    return [{"name": required[0], "args_match": required[1], "required": True}] if required else []

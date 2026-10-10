"""P0 pure helpers, not runtime collection or supplemental report generation."""
from datetime import datetime
from math import isfinite

from .contracts import checker, validate

READ_ONLY_TOOLS = frozenset({
    "crm.get_customer", "catalog.search", "inventory.check",
    "pricing.get_quote", "order.status",
})


def match_tool_calls(expectations, events):
    """Match one labelled context; inputs must be complete, not partial logs.

    Chronological events consume the earliest unmatched compatible label.
    Required matches are TP; optional/read-only allowances are reported separately.
    Args are exact expected-key subsets (including nested values), never null wildcards.
    This does not infer tool success from results or evaluate unresolved conditions.
    """
    validate("ExpectedToolCalls", expectations)
    if expectations["context"]["run_id"] != expectations["run_id"]:
        raise ValueError("Labels have inconsistent run_id/context")
    for label in expectations["calls"]:
        if any(value is None for value in checker.walk(label["args_match"])):
            raise ValueError("Unresolved null expected args; labels must be settled before scoring")
    seen = set()
    for event in events:
        validate("ToolEvent", event)
        if event["context"] != expectations["context"] or event["run_id"] != expectations["run_id"]:
            raise ValueError("Tool event does not belong to the labelled context")
        if event["event_id"] in seen:
            raise ValueError("Duplicate tool event_id")
        seen.add(event["event_id"])
        if datetime.fromisoformat(event["finished_at"]) < datetime.fromisoformat(event["started_at"]):
            raise ValueError("Tool event finished before it started")
    remaining = list(enumerate(expectations["calls"]))
    matches, allowed, false_positives = [], [], []
    execution_failures, execution_incomplete = [], []
    for event in sorted(events, key=lambda item: datetime.fromisoformat(item["started_at"])):
        request = event["request"]
        match = next(((index, label) for index, label in remaining
                      if label["name"] == request["name"]
                      and all(key in request["args"] and request["args"][key] == value
                              for key, value in label["args_match"].items())), None)
        if match is not None:
            remaining.remove(match)
            record = {"expected_index": match[0], "event_id": event["event_id"]}
            (matches if match[1]["required"] else allowed).append(record)
        elif expectations["allow_extra_read_only"] and request["name"] in READ_ONLY_TOOLS:
            allowed.append({"expected_index": None, "event_id": event["event_id"]})
        else:
            false_positives.append(event["event_id"])
        # Outcomes are collector evidence, not inferred from HTTP status or args.
        if event["outcome"] == "business_error":
            execution_failures.append(event["event_id"])
        elif event["outcome"] != "success":
            execution_incomplete.append(event["event_id"])
    false_negatives = [index for index, label in remaining if label["required"]]
    tp, fp, fn = len(matches), len(false_positives), len(false_negatives)
    denominator = tp + fp + fn
    return {
        "formula_id": "tool-accuracy.v2", "tp": tp, "fp": fp, "fn": fn,
        "value": 100 * tp / denominator if denominator else None,
        "status": "MEASURED" if denominator else "UNDEFINED",
        "precision": 100 * tp / (tp + fp) if tp + fp else None,
        "recall": 100 * tp / (tp + fn) if tp + fn else None,
        "matches": matches, "allowed": allowed,
        "false_positives": false_positives, "false_negatives": false_negatives,
        "execution_failures": execution_failures,
        "execution_incomplete": execution_incomplete,
    }


def cost_per_completed_call(total_runtime_cost, completed_calls):
    """Arithmetic only; caller supplies all runtime costs in one pinned currency.

    Includes failed-call cost in total; excludes judge/simulator. Completion must
    already include the after-call barrier. Missing prices/usage remain incomplete.
    """
    if type(completed_calls) is not int or completed_calls < 0:
        raise ValueError("completed_calls must be a nonnegative integer")
    if total_runtime_cost is not None and (
            type(total_runtime_cost) not in (int, float)
            or not isfinite(total_runtime_cost) or total_runtime_cost < 0):
        raise ValueError("total_runtime_cost must be finite, nonnegative or None")
    if total_runtime_cost is None:
        return {"value": None, "status": "INCOMPLETE", "reason": "MISSING_RUNTIME_COST"}
    if completed_calls == 0:
        return {"value": None, "status": "UNDEFINED", "reason": "NO_COMPLETED_CALLS"}
    return {"value": total_runtime_cost / completed_calls, "status": "MEASURED", "reason": None}

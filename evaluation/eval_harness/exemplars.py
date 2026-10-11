"""Offline checks for a situation-based exemplar bank and actual prompt use."""
import re

from .assets import read_json

PRIVATE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .()-]*\d){8,10}(?!\d)|\b\d{12}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def check(bank_file, usage_file):
    bank, usage = read_json(bank_file), read_json(usage_file)
    if not isinstance(bank, list) or not isinstance(usage, list):
        raise ValueError("Bank and usage must be JSON arrays")
    issues, entries = [], {}
    for item in bank:
        required = {"exemplar_id", "version", "situation", "source_call_id", "source_customer_id",
                    "source_split", "order_verified", "qa_passed", "approved_by", "status", "dialogue"}
        if set(item) != required or item["status"] not in {"candidate", "active", "revoked"} or item["source_split"] not in {"development", "public", "frozen", "hidden"}:
            raise ValueError("Invalid exemplar record")
        key = (item["exemplar_id"], item["version"])
        if key in entries or not all(item[k] for k in ("exemplar_id", "version", "situation", "source_call_id", "source_customer_id")):
            raise ValueError("Duplicate or incomplete exemplar identity")
        entries[key] = item
        dialogue = item["dialogue"]
        if not isinstance(dialogue, list) or not 1 <= len(dialogue) <= 4 or any(set(turn) != {"role", "text"} or turn["role"] not in {"customer", "agent"} or not isinstance(turn["text"], str) for turn in dialogue):
            issues.append({"code": "DIALOGUE_INVALID", "exemplar_id": key[0]})
            continue
        if sum(len(turn["text"]) for turn in dialogue) > 600 or PRIVATE.search(" ".join(turn["text"] for turn in dialogue)):
            issues.append({"code": "DIALOGUE_UNSAFE", "exemplar_id": key[0]})
        if item["status"] == "active" and (item["source_split"] in {"frozen", "hidden"} or not item["order_verified"] or not item["qa_passed"] or not item["approved_by"]):
            issues.append({"code": "ACTIVE_SOURCE_UNAPPROVED", "exemplar_id": key[0]})
    rows = []
    for turn in usage:
        if set(turn) != {"turn_id", "situation", "inserted", "selected"} or not isinstance(turn["inserted"], list) or not isinstance(turn["selected"], list):
            raise ValueError("Invalid exemplar usage record")
        inserted = [tuple(value) for value in turn["inserted"]]
        selected = [tuple(value) for value in turn["selected"]]
        if len(inserted) > 2 or len(inserted) != len(set(inserted)) or not set(inserted) <= set(selected):
            issues.append({"code": "USAGE_INVALID", "turn_id": turn["turn_id"]})
        sources = []
        for key in inserted:
            item = entries.get(key)
            if item is None or item["status"] != "active" or item["situation"] != turn["situation"]:
                issues.append({"code": "INSERTED_INELIGIBLE", "turn_id": turn["turn_id"]})
            else:
                sources.append((item["source_call_id"], item["source_customer_id"]))
        if len(sources) != len({call for call, _ in sources}) or len(sources) != len({customer for _, customer in sources}):
            issues.append({"code": "SOURCES_NOT_INDEPENDENT", "turn_id": turn["turn_id"]})
        rows.append({"turn_id": turn["turn_id"], "status": "few_shot" if len(inserted) == 2 else "one_shot" if inserted else "unavailable"})
    return {"report_kind": "exemplar-diagnostic-v1", "status": "INCOMPLETE" if issues else "COMPLETE",
            "issues": issues, "turns": rows,
            "notice": "Usage assertions need product prompt/context evidence before claiming real activation."}

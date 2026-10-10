"""Reuse the existing offline checker without duplicating its registry."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evaluation-contracts"
spec = importlib.util.spec_from_file_location("evaluation_contract_checker", ROOT / "check_contracts.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def validate(definition, data):
    errors = checker.errors(f"contracts.schema.json#/$defs/{definition}", data)
    if errors:
        raise ValueError(f"{definition}: " + "; ".join(error.message for error in errors))

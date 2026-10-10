"""Strict JSON and root-scoped AssetRefs for new datasets, not just fixtures."""
import hashlib
import json
from math import isfinite
from pathlib import Path
import re

from .contracts import checker, validate


def read_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8"))


def parse_json(text):
    """Same strict reader for JSON and individual JSONL lines."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Non-finite JSON: {value}")

    data = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    if any(isinstance(value, float) and not isfinite(value) for value in checker.walk(data)):
        raise ValueError("Non-finite JSON number")
    return data


def parse_json_block(text):
    """Accept one JSON document, optionally wrapped in one exact Markdown fence."""
    if not isinstance(text,str):raise ValueError("JSON response must be text")
    stripped=text.strip()
    match=re.fullmatch(r"```(?:json)?\r?\n([\s\S]*?)\r?\n```",stripped)
    return parse_json(match.group(1) if match else stripped)


class Assets:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("asset_root must be a directory")

    def path(self, name):
        if Path(name).is_absolute():
            raise ValueError("Asset paths must be relative to asset_root")
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("Asset escapes root or is not a file")
        return path

    def ref(self, name, pointer=""):
        path = self.path(name)
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pointer": pointer}

    def resolve(self, ref, *, json_content=True):
        validate("AssetRef", ref)
        path = self.path(ref["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
            raise ValueError(f"Asset hash mismatch: {ref['path']}")
        if not json_content and not ref["pointer"]:
            return path
        if ref["pointer"] and not ref["pointer"].startswith("/"):
            raise ValueError("Invalid JSON Pointer")
        data = read_json(path)
        for token in ref["pointer"][1:].split("/") if ref["pointer"] else []:
            if re.search(r"~(?:[^01]|$)", token):
                raise ValueError("Invalid JSON Pointer escape")
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(data, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", token):
                    raise ValueError("Invalid JSON Pointer array index")
                data = data[int(token)]
            else:
                data = data[token]
        return data

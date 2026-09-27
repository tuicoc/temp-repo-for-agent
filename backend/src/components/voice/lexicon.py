"""The two-layer fix for words the recogniser gets wrong. ``docs/design.md`` section 4.11.

1. Hints before recognition: the brand names in the organisers' catalogue,
   given to recognisers that accept them (Whisper's ``hotwords``).
2. Corrections after recognition: ``voice.lexicon`` in ``config/models.yaml``
   maps what the recogniser wrote to what was said. Matching ignores case
   and respects word edges, so "xiao mi" is fixed and "xiao minh" is not.

Corrections should come from errors actually observed in the lab or in the
WER bench, not from guesses.
"""

from __future__ import annotations

import json
import re

from ...config.config_manager import btc_data_dir, get_models_config


class Lexicon:
    def __init__(self) -> None:
        config = get_models_config().voice.lexicon
        self.hotwords = sorted(set(_brands()) | set(config.get("hotwords") or []))
        corrections: dict[str, str] = config.get("corrections") or {}
        # Longest first, so "xiao mi air" wins over "xiao mi".
        self._rules = [
            (re.compile(rf"(?<!\w){re.escape(wrong)}(?!\w)", re.IGNORECASE), right)
            for wrong, right in sorted(corrections.items(), key=lambda kv: -len(kv[0]))
        ]

    def correct(self, text: str) -> tuple[str, list[list[str]]]:
        applied: list[list[str]] = []
        for pattern, right in self._rules:
            text, count = pattern.subn(right, text)
            if count:
                applied.append([pattern.pattern, right])
        return text, applied


def _brands() -> list[str]:
    path = btc_data_dir() / "catalog" / "products.json"
    if not path.exists():
        return []
    products = json.loads(path.read_text(encoding="utf-8")).get("products", [])
    return sorted({p["brand"] for p in products if p.get("brand")})

"""The two-layer fix for words the recogniser gets wrong.

1. Hints before recognition: brand and product names from the catalogue,
   given to recognisers that accept them (Whisper's ``hotwords``).
2. Corrections after recognition: ``lexicon.json`` maps what the recogniser
   wrote to what was said. Matching ignores case and respects word edges, so
   "xiao mi" is fixed and "xiao minh" is not touched.

The corrections file starts nearly empty on purpose. Entries should come from
errors actually observed in the lab or in the WER bench, not from guesses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The organisers' catalogue, committed with the rest of their data.
CATALOG = HERE.parents[1] / "data" / "btc" / "catalog" / "products.json"
LEXICON = HERE / "lexicon.json"


class Lexicon:
    def __init__(self) -> None:
        self.hotwords = self._catalogue_terms()
        self._rules: list[tuple[re.Pattern[str], str]] = []
        self.reload()

    def reload(self) -> None:
        data = json.loads(LEXICON.read_text(encoding="utf-8")) if LEXICON.exists() else {}
        corrections: dict[str, str] = data.get("corrections", {})
        # Longest first, so "xiao mi air" wins over "xiao mi".
        self._rules = [
            (re.compile(rf"(?<!\w){re.escape(wrong)}(?!\w)", re.IGNORECASE), right)
            for wrong, right in sorted(corrections.items(), key=lambda kv: -len(kv[0]))
        ]
        self.hotwords = self._catalogue_terms() + list(data.get("hotwords", []))

    def correct(self, text: str) -> tuple[str, list[list[str]]]:
        applied: list[list[str]] = []
        for pattern, right in self._rules:
            text, count = pattern.subn(right, text)
            if count:
                applied.append([pattern.pattern, right])
        return text, applied

    @staticmethod
    def _catalogue_terms() -> list[str]:
        if not CATALOG.exists():
            return []
        items = json.loads(CATALOG.read_text(encoding="utf-8")).get("products", [])
        brands = sorted({item["brand"] for item in items if item.get("brand")})
        return brands

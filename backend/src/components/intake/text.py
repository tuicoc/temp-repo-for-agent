"""Chat cleanup and Unicode normalisation. ``docs/design.md`` section 4.1.

Teencode and abbreviations ("k" for không, "sp" for sản phẩm, "đc" for được)
into plain Vietnamese, word by word and only where the word stands alone,
so "249k" stays money for ITN. Then NFC, before any string comparison
anywhere: the same letter typed on two keyboards is two byte sequences
until it is normalised.

Mock: text typed without diacritics is left as it is. Restoring diacritics
needs a model or a dictionary of the catalogue's words; the advisor reads
"sp nay co ship cod k" well enough meanwhile.
"""

from __future__ import annotations

import re
import unicodedata

#: Whole words only. Ambiguous ones ("a" for anh or ạ, "e" for em) are left alone.
TEENCODE = {
    "k": "không", "ko": "không", "kh": "không", "hok": "không", "hông": "không", "khum": "không",
    "dc": "được", "đc": "được", "dk": "được", "đk": "được",
    "sp": "sản phẩm", "sdt": "số điện thoại", "sđt": "số điện thoại",
    "j": "gì", "vs": "với", "mk": "mình", "mik": "mình", "bn": "bao nhiêu", "bnh": "bao nhiêu",
    "trc": "trước", "ntn": "như thế nào", "r": "rồi", "ms": "mới", "cx": "cũng", "nc": "nói chuyện",
    "ib": "nhắn tin", "tks": "cảm ơn", "thks": "cảm ơn", "okie": "ok", "oke": "ok",
}

_WORD = re.compile(r"(?<![\w.,])([A-Za-zÀ-ỹđĐ]+)(?![\w])")


def nfc(text: str) -> str:
    """Vietnamese diacritics in NFC, so that equal words compare equal."""
    return unicodedata.normalize("NFC", text)


def clean(text: str) -> tuple[str, bool]:
    """Chat text into plain Vietnamese; and whether anything was teencode."""
    changed = False

    def swap(match: re.Match[str]) -> str:
        nonlocal changed
        word = match.group(1)
        plain = TEENCODE.get(word.lower())
        if plain is None:
            return word
        changed = True
        return plain

    cleaned = _WORD.sub(swap, nfc(text))
    return re.sub(r"\s+", " ", cleaned).strip(), changed


def plain(text: str) -> str:
    """Lower case without diacritics, for matching what customers type."""
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d").replace("Đ", "d"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))

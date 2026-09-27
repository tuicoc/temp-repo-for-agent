"""Inverse text normalisation, and reading money back out of a reply.

``docs/design.md`` sections 4.1 and 4.5. Two directions, one module, so that
what the customer said and what the guardrail reads are counted the same way.

:func:`normalise`, spoken to written, for a turn on its way in:

- "bốn triệu tám" is 4.800.000, not 4.000.008; "hai trăm bốn chín k" is
  249.000; "một củ hai" is 1.200.000; "hai triệu rưỡi" is 2.500.000;
- a run of nine or more bare digits is a digit string: "không chín tám bốn
  ..." is a phone number, 0984...;
- "ngày mai", "thứ tư tuần sau" get the date they mean appended, computed
  from the virtual clock, never the system clock, because the evaluator runs
  scenarios days apart; "bảy giờ tối" becomes 19:00.

:func:`money_spans`, written to value, for a reply on its way out: every
amount in 5.200.000đ, 5,2 triệu, 5 triệu 2, 4tr890, 249k form, with its value
in VND, so the guard can check each against the tools.

Mock: the rules cover the forms in the organisers' scenarios and ASR ground
truth; the test suite the design asks for (Entity Accuracy on money and
phone numbers) is still to be written against ``asr/ground_truth.json``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import NamedTuple

from ..clock import day_label


class Span(NamedTuple):
    start: int
    end: int
    text: str
    value: int


# ── spoken numbers ────────────────────────────────────────────────────────

DIGITS = {
    "không": 0, "linh": 0, "lẻ": 0,
    "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5, "nhăm": 5,
    "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9,
}
SCALES = {"nghìn": 1_000, "ngàn": 1_000, "k": 1_000, "triệu": 1_000_000, "củ": 1_000_000, "tỷ": 1_000_000_000, "tỉ": 1_000_000_000}
NUMBER_WORDS = set(DIGITS) | set(SCALES) | {"mười", "mươi", "trăm", "rưỡi"}

#: Words that are digits only inside a number: "tư" and "năm" are also "fourth"
#: and "year", "một" is also "a". A run must hold something unambiguous.
WEAK = {"tư", "năm", "một", "ba", "lẻ", "linh", "không"}


def _below_thousand(words: list[str]) -> int | None:
    """A number under 1000 from its words, or None if they do not form one."""
    if not words:
        return 0
    value = 0
    rest = list(words)
    if "trăm" in rest:
        at = rest.index("trăm")
        head = rest[:at]
        if len(head) != 1 or head[0] not in DIGITS:
            return None
        value = DIGITS[head[0]] * 100
        rest = rest[at + 1:]
        if rest == ["rưỡi"]:
            return value + 50
        if len(rest) == 1 and rest[0] in DIGITS and rest[0] not in ("linh", "lẻ"):
            # "hai trăm tư" is 240 in speech.
            return value + DIGITS[rest[0]] * 10
        if len(rest) == 2 and rest[0] in ("linh", "lẻ") and rest[1] in DIGITS:
            return value + DIGITS[rest[1]]
    if not rest:
        return value
    if rest[0] == "mười":
        units = rest[1:]
        if not units:
            return value + 10
        if len(units) == 1 and units[0] in DIGITS:
            return value + 10 + DIGITS[units[0]]
        return None
    if len(rest) >= 2 and rest[1] == "mươi" and rest[0] in DIGITS:
        tens = DIGITS[rest[0]] * 10
        units = rest[2:]
        if not units:
            return value + tens
        if len(units) == 1 and units[0] in DIGITS:
            return value + tens + DIGITS[units[0]]
        return None
    if len(rest) == 2 and all(w in DIGITS for w in rest):
        # "hai lăm" is 25, "bốn chín" 49.
        return value + DIGITS[rest[0]] * 10 + DIGITS[rest[1]]
    if len(rest) == 1 and rest[0] in DIGITS:
        return value + DIGITS[rest[0]]
    return None


def parse_number(words: list[str]) -> int | None:
    """A spoken number with scales: "bốn triệu tám" -> 4_800_000."""
    total = 0
    group: list[str] = []
    last_scale: int | None = None
    for word in words:
        if word in SCALES:
            scale = SCALES[word]
            chunk = _below_thousand(group)
            if chunk is None:
                return None
            total += (chunk or (1 if not group else 0)) * scale
            group = []
            last_scale = scale
        elif word == "rưỡi" and last_scale and not group:
            total += last_scale // 2
        else:
            group.append(word)
    if group:
        if last_scale and len(group) == 1 and group[0] in DIGITS:
            # A lone digit after a scale is that digit of the next place down:
            # "bốn triệu tám" is 4.8 million, "một củ hai" 1.2 million.
            total += DIGITS[group[0]] * last_scale // 10
        elif last_scale and "trăm" in group:
            chunk = _below_thousand(group)
            if chunk is None:
                return None
            total += chunk * (last_scale // 1000 if last_scale >= 1000 else 1)
        else:
            chunk = _below_thousand(group)
            if chunk is None:
                return None
            total += chunk
    return total


def _written(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _bare(token: str) -> str:
    return token.lower().strip(".,!?;:")


def _runs(tokens: list[str]) -> list[tuple[int, int]]:
    """Index ranges of maximal runs of number words."""
    runs, start = [], None
    for i, token in enumerate(tokens + [""]):
        if token and _bare(token) in NUMBER_WORDS:
            start = i if start is None else start
            if token[-1] in ".,!?;:":
                # Punctuation closes the run after this word.
                runs.append((start, i + 1))
                start = None
        elif start is not None:
            runs.append((start, i))
            start = None
    return runs


def _spoken_numbers(text: str) -> str:
    tokens = text.split(" ")
    out: list[str] = []
    cursor = 0
    for start, end in _runs(tokens):
        words = [_bare(t) for t in tokens[start:end]]
        bare = all(w in DIGITS for w in words)
        # "không năm triệu" is a negation before a number, not a zero.
        while len(words) > 1 and words[0] == "không" and not bare:
            start += 1
            words = words[1:]
        has_digit = any(w in DIGITS or w == "mười" for w in words)
        if not has_digit or (all(w in WEAK for w in words) and len(words) < 3):
            continue
        out.extend(tokens[cursor:start])
        trailing = tokens[end - 1][len(tokens[end - 1].rstrip(".,!?;:")):]
        if bare and len(words) >= 3:
            out.append("".join(str(DIGITS[w]) for w in words) + trailing)
        else:
            value = parse_number(words)
            if value is None:
                out.extend(tokens[start:end])
            else:
                money = any(w in SCALES for w in words)
                out.append((format_vnd(value) if money else str(value)) + trailing)
        cursor = end
    out.extend(tokens[cursor:])
    return " ".join(out)


# ── dates and times ───────────────────────────────────────────────────────

WEEKDAYS = {"thứ hai": 0, "thứ ba": 1, "thứ tư": 2, "thứ năm": 3, "thứ sáu": 4, "thứ bảy": 5, "chủ nhật": 6}
RELATIVE_DAYS = {"hôm nay": 0, "ngày mai": 1, "mai": 1, "ngày kia": 2, "ngày mốt": 2, "tuần sau": 7}
DATE_PHRASE = re.compile(
    r"\b(thứ hai|thứ ba|thứ tư|thứ năm|thứ sáu|thứ bảy|chủ nhật)( tuần sau| tuần tới| tuần này)?|\b(hôm nay|ngày mai|ngày kia|ngày mốt)\b",
    re.IGNORECASE,
)
HOUR = re.compile(r"\b(\d{1,2})\s*(?:giờ|h)(?:\s*(\d{1,2}))?\s*(sáng|trưa|chiều|tối)?", re.IGNORECASE)


def _dates(text: str, now: datetime) -> str:
    today = now.date()

    def replace(match: re.Match[str]) -> str:
        phrase = match.group(0)
        lower = phrase.lower()
        if match.group(3):
            day = today + timedelta(days=RELATIVE_DAYS[lower])
        else:
            weekday = WEEKDAYS[match.group(1).lower()]
            ahead = (weekday - today.weekday()) % 7 or 7
            if match.group(2) and match.group(2).strip() in ("tuần sau", "tuần tới"):
                start_next = today + timedelta(days=7 - today.weekday())
                day = start_next + timedelta(days=weekday)
            else:
                day = today + timedelta(days=ahead)
        return f"{phrase} ({day_label(day)})"

    return DATE_PHRASE.sub(replace, text)


def _hours(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        part = (match.group(3) or "").lower()
        if part in ("chiều", "tối") and hour < 12:
            hour += 12
        if part == "trưa" and hour < 11:
            hour += 12
        if hour > 23 or minute > 59:
            return match.group(0)
        return f"{hour:02d}:{minute:02d}"

    return HOUR.sub(replace, text)


def normalise(text: str, now: datetime) -> str:
    """Money, phone numbers, dates and times in *text*, spoken form to written."""
    # Dates first: "thứ hai" is a weekday before it is the number two.
    written = _dates(text, now)
    written = _spoken_numbers(written)
    return _hours(written)


# ── written money, read back ──────────────────────────────────────────────

_MILLION = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(triệu|tr|củ)(?![a-zà-ỹ])(?:\s*(\d{1,3})(?![\d.,]\d))?", re.IGNORECASE)
_BILLION = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(tỷ|tỉ)(?![a-zà-ỹ])", re.IGNORECASE)
_THOUSAND = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(k|nghìn|ngàn)(?![a-zà-ỹ])", re.IGNORECASE)
_GROUPED = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+)(?:\s*(đồng|đ|vnđ|vnd|d)(?![a-zà-ỹ]))?", re.IGNORECASE)
_PLAIN = re.compile(r"(?<![\w.,])(\d{4,9})\s*(đồng|đ|vnđ|vnd)(?![a-zà-ỹ])", re.IGNORECASE)


def _decimal(raw: str) -> float:
    return float(raw.replace(",", "."))


def money_spans(text: str) -> list[Span]:
    """Every amount of money written in *text*, in VND, without overlaps."""
    found: list[Span] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s.start or start >= s.end for s in found)

    for match in _BILLION.finditer(text):
        found.append(Span(match.start(), match.end(), match.group(0), int(round(_decimal(match.group(1)) * 1_000_000_000))))
    for match in _MILLION.finditer(text):
        if not free(match.start(), match.end()):
            continue
        value = _decimal(match.group(1)) * 1_000_000
        tail = match.group(3)
        if tail and "." not in match.group(1) and "," not in match.group(1):
            value += int(tail) * 10 ** (6 - len(tail))
        found.append(Span(match.start(), match.end(), match.group(0), int(round(value))))
    for match in _THOUSAND.finditer(text):
        if free(match.start(), match.end()):
            found.append(Span(match.start(), match.end(), match.group(0), int(round(_decimal(match.group(1)) * 1_000))))
    for match in _GROUPED.finditer(text):
        if free(match.start(), match.end()):
            digits = re.sub(r"[.,]", "", match.group(1))
            value = int(digits)
            # 1.000 on its own is a thousand; a grouped number under 1.000 dong
            # is not money anyone quotes.
            if value >= 1_000:
                found.append(Span(match.start(), match.end(), match.group(0), value))
    for match in _PLAIN.finditer(text):
        if free(match.start(), match.end()):
            found.append(Span(match.start(), match.end(), match.group(0), int(match.group(1))))
    return sorted(found)


def format_vnd(value: int) -> str:
    """``5.200.000đ``, as the advisor writes a price."""
    return f"{_written(int(value))}đ"

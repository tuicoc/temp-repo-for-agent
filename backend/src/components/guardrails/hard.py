"""The hard check on a reply: code only, under 50 ms. ``docs/design.md`` section 4.5.

It turns the price hallucination threshold (at most 5%) from a hope into a
guarantee, and it can be shown live.

| Check | How |
|---|---|
| money | every amount must come from a valid source: this turn's tool results, the policy passages just read, the customer's own words, or a quantity times a unit price. A price from the brief only as history ("hôm trước bên em báo") |
| internal | no purchase price, margin, supplier or price floor |
| personal data | no raw phone, ID or account number; no token that is not this call's |
| tier | below VERIFIED, no price the brief holds, no order code |
| human | no claim to be a person |
| shape | not empty, at most three sentences unless summing up an order, Vietnamese |

Money is read with :func:`~src.components.intake.itn.money_spans`, the code
intake uses, so what the customer said and what the guard reads are counted
the same way. Every reason is returned, not just the first, so one
regeneration can fix them all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from ..intake.itn import format_vnd, money_spans
from ..intake.pii import PATTERNS, TOKEN
from . import Verdict

MAX_SENTENCES = 3

HISTORY = re.compile(r"(hôm trước|lần trước|trước đây|hôm qua|đã báo|bên em báo|báo chị|báo anh)", re.IGNORECASE)
INTERNAL = re.compile(r"(giá nhập|giá vốn|biên lợi nhuận|lợi nhuận|nhà cung cấp|giá sàn|price_floor|_internal|chiết khấu nội bộ)", re.IGNORECASE)
HUMAN = re.compile(
    r"(em là người thật|em là nhân viên thật|em không phải (là )?(máy|bot|robot|ai|trợ lý (ảo|tự động))|"
    r"em là con người|không phải trợ lý ảo đâu)",
    re.IGNORECASE,
)
ORDER_CODE = re.compile(r"\bOD\d{5,}\b")
ORDER_SUMMARY = re.compile(r"(tổng (cộng|đơn|tiền)|xác nhận đơn|lên đơn|mã đơn)", re.IGNORECASE)
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class GuardInput:
    """What the hard check may read (section 3.2)."""

    text: str
    tool_results: tuple[dict[str, Any], ...]
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    #: The customer's own words in this call, tokenised.
    customer_said: tuple[str, ...] = ()
    #: Amounts in the policy passages read this turn.
    policy_texts: tuple[str, ...] = ()
    #: Prices the brief holds: history, never a current price.
    brief_prices: tuple[int, ...] = ()
    #: This call's vault tokens, the only ones the text may carry.
    tokens: frozenset[str] = field(default_factory=frozenset)


def numbers_in(value: Any) -> set[int]:
    """Every integer amount in a tool result, at any depth, including inside text."""
    found: set[int] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, int):
        found.add(value)
    elif isinstance(value, float) and value.is_integer():
        found.add(int(value))
    elif isinstance(value, str):
        found.update(span.value for span in money_spans(value))
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= numbers_in(item)
    return found


def allowed_amounts(view: GuardInput) -> set[int]:
    amounts: set[int] = set()
    for result in view.tool_results:
        amounts |= numbers_in(result.get("result"))
    for text in (*view.customer_said, *view.policy_texts):
        amounts.update(span.value for span in money_spans(text))
    # A quantity times a unit price, and the difference of two amounts
    # (a discount, a price change), for small quantities.
    base = {a for a in amounts if a >= 1_000}
    amounts |= {a * q for a in base for q in range(2, 6)}
    amounts |= {abs(a - b) for a in base for b in base if a != b}
    return amounts


def check(view: GuardInput) -> Verdict:
    """Every check in the table; all reasons, not the first."""
    text = view.text.strip()
    reasons: list[str] = []
    if not text:
        return Verdict(False, ("Câu trả lời rỗng.",))

    allowed = allowed_amounts(view)
    history = set(view.brief_prices)
    for sentence in SENTENCE.split(text):
        for span in money_spans(sentence):
            if span.value in allowed:
                continue
            if span.value in history and HISTORY.search(sentence):
                if view.tier != "VERIFIED":
                    reasons.append(f"Chưa xác minh danh tính nên không được nhắc giá đã báo {format_vnd(span.value)}.")
                continue
            reasons.append(
                f"Số tiền {span.text} không có trong kết quả tool của lượt này, lời khách hay chính sách; "
                "gọi tool để lấy số đúng hoặc bỏ con số."
            )

    if INTERNAL.search(text):
        reasons.append("Nhắc tới thông tin nội bộ (giá nhập, biên lợi nhuận, nhà cung cấp, giá sàn).")
    for kind, pattern in PATTERNS:
        if pattern.search(text):
            reasons.append(f"Có dữ liệu cá nhân thô ({kind.lower()}) trong câu trả lời.")
            break
    strangers = [m.group(0) for m in TOKEN.finditer(text) if m.group(0) not in view.tokens]
    if strangers:
        reasons.append(f"Có mã dữ liệu cá nhân không thuộc cuộc gọi này: {', '.join(strangers)}.")
    if view.tier != "VERIFIED" and ORDER_CODE.search(text):
        reasons.append("Chưa xác minh danh tính nên không được đọc mã đơn.")
    if HUMAN.search(text):
        reasons.append("Không được nhận là người thật.")

    sentences = [s for s in SENTENCE.split(text) if len(s.strip()) > 12]
    if len(sentences) > MAX_SENTENCES and not ORDER_SUMMARY.search(text):
        reasons.append(f"Quá dài: {len(sentences)} câu, tối đa {MAX_SENTENCES}.")
    if len(text) > 40 and not VIETNAMESE.search(text):
        reasons.append("Câu trả lời không phải tiếng Việt.")

    return Verdict(not reasons, tuple(dict.fromkeys(reasons)))


def warnings_for(texts: Iterable[str], view: GuardInput) -> list[str]:
    """The same checks on a consultant's text, as warnings rather than a block."""
    return [reason for text in texts for reason in check(GuardInput(**{**view.__dict__, "text": text})).reasons]

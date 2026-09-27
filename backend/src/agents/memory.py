"""MemoryAgent: what to remember about this customer. ``docs/design.md`` section 5.4.

Runs in ``after_call`` under the ``memory_writer`` role, the only path into
the ledger. Five steps; the gate and the commit decision are code
(``src/components/memory``), the judgements are here:

1. ``load``: the call's tokenised transcript, the tool log, current facts;
2. ``extract``: candidates in the organisers' flat slot names;
3. ``gate``: noise, the open-note cap, format and range, who wins;
4. ``commit``: add, update or skip per slot, code by the win rule;
5. ``summarize``: one episode line, "Cuộc 1 (15/10, hotline): tư vấn
   SKU-AP-Y 5.200.000đ kèm GIFT-FILTER, khách chờ hỏi chồng".

**Mock.** Section 5.4 specifies one structured-output model call for
``extract`` and ``summarize``. Until it is built, both are rules: business
facts from the tool log (what was quoted, ordered, booked, handed over),
needs and blockers from the customer's words by pattern. Deterministic,
which keeps the baseline comparison honest meanwhile; open notes are not
extracted at all.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from ..components.clock import day_label
from ..components.intake.itn import format_vnd, money_spans
from ..components.memory.gate import Candidate
from .base import BaseAgent

ROOM = re.compile(r"(\d{1,3})\s*(m2|m²|mét vuông|met vuong|mét)", re.IGNORECASE)
CHILDREN_YES = re.compile(r"(có (bé|con|em bé|trẻ)|bé nhỏ|con nhỏ|trẻ nhỏ|em bé|nhà có bé)", re.IGNORECASE)
CHILDREN_NO = re.compile(r"(không có (bé|con|trẻ)|chưa có (bé|con))", re.IGNORECASE)
BUDGET_CUE = re.compile(r"(ngân sách|tầm|khoảng|dưới|tối đa|không quá|budget|trong vòng)", re.IGNORECASE)
ASK_FAMILY = re.compile(r"hỏi (ý kiến )?(ông xã|chồng|vợ|bà xã|người nhà|gia đình|bố mẹ|bố|mẹ|anh nhà|nhà chị)", re.IGNORECASE)
THINK = re.compile(r"(suy nghĩ thêm|cân nhắc thêm|để (chị|anh|em|mình) (xem|nghĩ))", re.IGNORECASE)
COMPARE = re.compile(r"(so sánh|bên khác|chỗ khác|shop khác)", re.IGNORECASE)
TOO_DEAR = re.compile(r"(đắt quá|mắc quá|hơi đắt|giá cao)", re.IGNORECASE)
SIZE = re.compile(r"\bsize\s*([0-9]{2}|[smlx]{1,3})\b", re.IGNORECASE)
COLOUR = re.compile(r"\bmàu\s+(trắng|đen|xanh|đỏ|hồng|xám|be|nâu|vàng|kem)\b", re.IGNORECASE)
TRANSFER = re.compile(r"(chuyển khoản|ck qua|banking)", re.IGNORECASE)
COD = re.compile(r"(\bcod\b|nhận hàng (rồi )?trả tiền|thanh toán khi nhận)", re.IGNORECASE)
UNHAPPY = re.compile(r"(bực|chán|mất thời gian|lâu quá|hỏi rồi mà|nói rồi mà)", re.IGNORECASE)
CALL_BACK = re.compile(r"(gọi lại|liên hệ lại|báo lại)", re.IGNORECASE)

FAMILY = {"ông xã": "chồng", "anh nhà": "chồng", "nhà chị": "chồng", "bà xã": "vợ"}


class MemoryAgent(BaseAgent):
    """Decides what the call established about the customer."""

    def __init__(self) -> None:
        super().__init__("memory")

    async def extract(self, transcript: Sequence[dict[str, Any]], tool_log: Sequence[dict[str, Any]], *, on: str) -> list[Candidate]:
        """Candidates from the tool log and the customer's words, in turn order."""
        found: list[Candidate] = []

        for call in tool_log:
            envelope = call.get("result") or {}
            if not envelope.get("ok"):
                continue
            data = envelope.get("data") or {}
            turn = int(call.get("turn") or 0)
            name = call.get("name")
            if name == "pricing.get_quote" and data.get("sku"):
                found += [
                    Candidate("product_advised", data["sku"], "tool", turn),
                    Candidate("price_quoted_vnd", int(data["final_price_vnd"]), "tool", turn),
                    Candidate("quoted_on", on, "tool", turn),
                ]
                # The promotion the customer was told about, not the free COD
                # or shipping every order gets.
                promos = [p["promo_code"] for p in data.get("applied_promos") or []
                          if p.get("type") not in ("freeship", "freecod")]
                if promos:
                    found.append(Candidate("promo_code", promos[0], "tool", turn))
            elif name == "order.create" and data.get("order_id"):
                found += [Candidate("order_id", data["order_id"], "tool", turn), Candidate("outcome", "chot_don", "tool", turn)]
            elif name == "schedule.callback" and data.get("callback_at"):
                found += [Candidate("callback_at", data["callback_at"], "tool", turn), Candidate("outcome", "hen_goi_lai", "tool", turn)]
            elif name == "handoff.transfer" and data.get("ticket_id"):
                found.append(Candidate("outcome", "chuyen_may", "tool", turn))

        for line in transcript:
            if line.get("speaker") != "customer":
                continue
            text = str(line.get("text") or "")
            turn = int(line.get("turn") or 0)
            if match := ROOM.search(text):
                found.append(Candidate("room_area_m2", int(match.group(1)), "customer", turn))
            if CHILDREN_NO.search(text):
                found.append(Candidate("has_children", False, "customer", turn))
            elif CHILDREN_YES.search(text):
                found.append(Candidate("has_children", True, "customer", turn))
            if BUDGET_CUE.search(text):
                amounts = money_spans(text)
                if amounts:
                    found.append(Candidate("budget_vnd", amounts[-1].value, "customer", turn))
            if match := ASK_FAMILY.search(text):
                who = FAMILY.get(match.group(2).lower(), match.group(2).lower())
                found += [Candidate("blocker", f"cần hỏi ý kiến {who}", "customer", turn),
                          Candidate("decision_maker", who, "customer", turn)]
            elif THINK.search(text):
                found.append(Candidate("blocker", "cần suy nghĩ thêm", "customer", turn))
            if COMPARE.search(text):
                found.append(Candidate("objection_type", "so_sanh_gia", "customer", turn))
                amounts = money_spans(text)
                if amounts:
                    found.append(Candidate("competitor_price_vnd", amounts[0].value, "customer", turn))
            elif TOO_DEAR.search(text):
                found.append(Candidate("objection_type", "gia_cao", "customer", turn))
            if match := SIZE.search(text):
                found.append(Candidate("size", match.group(1).upper(), "customer", turn))
            if match := COLOUR.search(text):
                found.append(Candidate("color", match.group(1).lower(), "customer", turn))
            if TRANSFER.search(text):
                found.append(Candidate("payment", "bank", "customer", turn))
            elif COD.search(text):
                found.append(Candidate("payment", "COD", "customer", turn))
            if UNHAPPY.search(text):
                found.append(Candidate("sentiment", "kho_chiu", "customer", turn))

        outcomes = [c for c in found if c.slot == "outcome"]
        if not outcomes and any(CALL_BACK.search(str(l.get("text") or "")) for l in transcript if l.get("speaker") == "customer"):
            found.append(Candidate("outcome", "hen_goi_lai", "customer", max((int(l.get("turn") or 0) for l in transcript), default=0)))
        return found

    async def summarize(self, candidates: Sequence[Candidate], *, call_number: int, day: str, channel: str) -> dict[str, Any]:
        """The episode: one line, and the outcome."""
        last = {c.slot: c.value for c in candidates if c.slot}
        parts = []
        if "product_advised" in last:
            price = f" {format_vnd(last['price_quoted_vnd'])}" if "price_quoted_vnd" in last else ""
            promo = f" kèm {last['promo_code']}" if "promo_code" in last else ""
            parts.append(f"tư vấn {last['product_advised']}{price}{promo}")
        if "order_id" in last:
            parts.append(f"chốt đơn {last['order_id']}")
        if "callback_at" in last:
            parts.append(f"hẹn gọi lại {last['callback_at']}")
        if "blocker" in last:
            parts.append(f"khách {last['blocker']}")
        if last.get("outcome") == "chuyen_may":
            parts.append("đã chuyển tư vấn viên")
        summary = f"Cuộc {call_number} ({day_label(day)[:5]}, {channel}): " + (", ".join(parts) or "chưa có gì đáng ghi")
        return {
            "summary": summary,
            "outcome": last.get("outcome") or "khac",
            "objection_type": last.get("objection_type"),
            "sentiment": last.get("sentiment") or "binh_thuong",
            "commitments": [f"gọi lại {last['callback_at']}"] if "callback_at" in last else [],
        }

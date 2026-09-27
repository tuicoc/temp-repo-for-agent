"""The Handoff Brief, as a person reads it. ``docs/design.md`` section 4.10.

Who the customer is, what was advised and at what price, the blocker, what
was promised, what is disputed, why the call was handed over, the question
nobody answered, the order, and what to do first. Written to be understood
in ten seconds without asking the customer anything again.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..intake.itn import format_vnd

REASONS = {
    "cau_hoi_y_te": "câu hỏi y tế",
    "ngoai_pham_vi_tai_lieu": "ngoài phạm vi tài liệu",
    "khach_yeu_cau_gap_nguoi": "khách muốn gặp người",
    "khieu_nai_nghiem_trong": "khiếu nại nghiêm trọng",
    "loi_he_thong": "lỗi hệ thống",
    "khach_mat_kien_nhan": "khách mất kiên nhẫn",
    "khac": "khác",
}


def render_handoff(brief: Mapping[str, Any]) -> str:
    """The brief as a short paragraph for the consultant who takes the call."""
    who = brief.get("customer_name") or "Khách chưa rõ tên"
    phone = str(brief.get("customer_phone") or "")
    parts = [f"{who}{', số đuôi ' + phone[-4:] if phone else ''}."]
    parts.append(f"Lý do chuyển: {REASONS.get(str(brief.get('escalation_reason')), brief.get('escalation_reason'))}"
                 + (f" ({brief['escalation_reason_detail']})" if brief.get("escalation_reason_detail") else "") + ".")
    if brief.get("product_advised"):
        price = f", đã báo {format_vnd(brief['price_quoted_vnd'])}" if brief.get("price_quoted_vnd") else ""
        parts.append(f"Đã tư vấn {brief['product_advised']}{price}.")
    if brief.get("conversation_summary"):
        parts.append(str(brief["conversation_summary"]))
    questions = brief.get("open_questions") or []
    if questions:
        parts.append("Chưa trả lời được: " + "; ".join(str(q) for q in questions) + ".")
    if brief.get("next_action"):
        parts.append(f"Việc cần làm: {brief['next_action']}")
    return " ".join(parts)

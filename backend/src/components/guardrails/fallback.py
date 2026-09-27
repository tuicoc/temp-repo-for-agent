"""What the system says when it cannot trust a draft. ``docs/design.md`` section 4.9.

Admit first, never guess a number. The safe line is said when a draft is
still blocked after two regenerations; a second one in the same call sends
the next turn to HANDOFF (route, rule 1). The other lines are the table's,
for the harness to say without a model.
"""

from __future__ import annotations

SAFE_LINE = "Dạ để em kiểm tra kỹ rồi phản hồi anh/chị ngay ạ."

LINES = {
    "tool_down": "Dạ hệ thống bên em đang tra cứu hơi chậm, em xin phép nhắn lại anh/chị trong ít phút ạ.",
    "asr_unclear": "Dạ em nghe chưa rõ, anh/chị nói lại giúp em được không ạ?",
    "model_error": "Dạ em xin lỗi, em chưa trả lời được ngay. Anh/chị cho em một chút để kiểm tra lại ạ.",
    "bridging": "Dạ em kết nối anh/chị với đồng nghiệp phụ trách ngay ạ, anh/chị chờ em một chút.",
}

#: Per lane; a lane not listed gets SAFE_LINE.
BY_LANE = {
    "CLARIFY": LINES["asr_unclear"],
    "HANDOFF": LINES["bridging"],
}


def safe_line(lane: str) -> str:
    """What to say for *lane* when no draft could be trusted."""
    return BY_LANE.get(lane, SAFE_LINE)


def is_bridging(text: str) -> bool:
    """Whether a line is the handoff line in some form."""
    lowered = " ".join(text.lower().split())
    return "kết nối" in lowered and any(w in lowered for w in ("đồng nghiệp", "nhân viên", "tư vấn viên", "người phụ trách"))

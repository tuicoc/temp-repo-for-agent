"""Deterministic routing agent: the Advisor contract without an unnecessary LLM."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .base import BaseAgent


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lane: Literal["IDENTITY_RESOLUTION", "POST_SALE", "SCHEDULING", "OUT_OF_SCOPE", "CONTINUITY", "SALES"]
    intent: Literal["identity", "order_service", "callback", "out_of_scope", "continuity", "sales"]


class OrchestratorAgent(BaseAgent):
    """Reads only identity tier, current customer text and operational flags."""

    SYSTEM_PROMPT = (
        "Vai trò: điều phối lượt tư vấn. Nguồn: tier, lời khách đã che PII và flags; "
        "không đọc GT, lịch sử riêng chưa xác minh hoặc điểm đánh giá. "
        "Ưu tiên xác minh danh tính và lỗi hệ thống trước ý định bán hàng. "
        "Đầu ra RouteDecision; thiếu căn cứ thì chọn lane an toàn. "
        "Agent này dùng luật tất định, không gọi model hay business tool."
    )
    RESPONSE_FORMAT = RouteDecision
    CONTRACT_VERSION = "orchestrator-v1"

    def __init__(self):
        self.name = "orchestrator"

    def process(self, state):
        if set(state) - {"tier", "customer_text", "flags", "has_previous_session"}:
            raise ValueError("Orchestrator received forbidden state")
        tier, text, flags = state["tier"], state["customer_text"].casefold(), state.get("flags") or {}
        if flags.get("tool_health") == "failed" or flags.get("handoff_requested"):
            lane, intent = "OUT_OF_SCOPE", "out_of_scope"
        elif flags.get("asr_low_conf") or tier == "ambiguous":
            lane, intent = "IDENTITY_RESOLUTION", "identity"
        elif any(word in text for word in ("đơn hàng", "mã đơn", "đổi trả", "bảo hành", "giao tới đâu", "vận chuyển")):
            lane, intent = ("POST_SALE", "order_service") if tier == "verified" else ("IDENTITY_RESOLUTION", "identity")
        elif any(word in text for word in ("gọi lại", "tư vấn sau", "hẹn gọi", "callback")):
            lane, intent = "SCHEDULING", "callback"
        elif any(word in text for word in ("dự báo thời tiết", "chứng khoán", "bóng đá", "viết code", "bài tập toán")):
            lane, intent = "OUT_OF_SCOPE", "out_of_scope"
        elif tier == "verified" and state.get("has_previous_session"):
            lane, intent = "CONTINUITY", "continuity"
        else:
            lane, intent = "SALES", "sales"
        return self.RESPONSE_FORMAT(lane=lane, intent=intent).model_dump()

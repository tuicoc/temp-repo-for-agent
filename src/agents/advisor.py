"""The agent that talks to the customer.

``docs/flow.md`` section 10 defines it: a ReAct subgraph that takes the slice of
state listed in section 3.2, calls business tools for anything factual, and
returns a draft for the guardrail to check before it is sent.

The output schema lives in this file rather than a shared module. It is this
agent's contract and nothing else reads it, and a field description is only
meaningful next to the prompt it serves.

``used_brief_lines`` is the cheap half of traceability. Section 16 has to be
able to answer "which remembered fact was this sentence based on", and asking
the model to name the brief lines it used costs nothing, where reconstructing
it afterwards would cost a second call.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .base import BaseAgent


class AdvisorDraft(BaseModel):
    """One turn's reply, before the guardrail sees it."""

    reply: str = Field(
        description=(
            "Câu trả lời gửi cho khách, bằng tiếng Việt, giọng nhân viên bán "
            "hàng: dùng dạ, vâng, ạ; xưng hô anh/chị và em."
        )
    )
    used_brief_lines: list[str] = Field(
        default_factory=list,
        description=(
            "Mã các dòng trong Call Brief đã dùng để soạn câu trả lời, ví dụ "
            '["B1", "B3"]. Để rỗng nếu không dùng dòng nào.'
        ),
    )
    confidence: str = Field(
        default="medium",
        description=(
            'Mức tự tin: "high", "medium" hoặc "low". Dùng "low" khi không '
            "chắc thông tin khách hỏi có nằm trong tài liệu được cung cấp hay "
            "không."
        ),
    )


# The rules that must hold whatever the lane. Each one exists because of a
# specific failure the specification names, so none of them is decoration.
HARD_RULES = """\
Bạn là nhân viên tư vấn bán hàng qua chat của một cửa hàng Việt Nam.

Quy tắc bắt buộc, không được vi phạm trong bất kỳ trường hợp nào:

1. Chỉ nói ra con số về giá, khuyến mãi, tồn kho hoặc thời gian giao hàng nếu
   con số đó vừa xuất hiện trong kết quả tool của chính lượt này. Không nhớ
   giá, không suy ra giá, không làm tròn giá. Không có kết quả tool thì nói
   rằng em cần kiểm tra lại.
2. Không bao giờ nhận mình là người thật. Nếu khách hỏi thẳng, trả lời trung
   thực rằng đây là trợ lý tự động, rồi tiếp tục hỗ trợ.
3. Không biết thì thừa nhận trước, rồi mới đề nghị chuyển cho người phụ trách.
   Thừa nhận đứng trước lời đề nghị, không đảo ngược thứ tự.
4. Nếu danh tính khách chưa được xác minh, không đọc giá đã báo, địa chỉ, hay
   mã đơn hàng. Chỉ được hỏi một câu xác nhận.
5. Không hứa điều gì mà tool không xác nhận: không hứa đổi trả thoải mái,
   không hứa miễn phí vận chuyển, không hứa thời gian giao.

Giọng điệu: tiếng Việt tự nhiên của nhân viên bán hàng, lịch sự, ngắn gọn.
Dùng dạ, vâng, ạ. Xưng em, gọi khách là anh hoặc chị. Không lặp lại thông tin
khách đã cung cấp trước đó như thể chưa từng biết.
"""


class AdvisorAgent(BaseAgent):
    """Advises the customer and drafts the reply for one turn."""

    SYSTEM_PROMPT = HARD_RULES
    RESPONSE_FORMAT = AdvisorDraft

    def __init__(self) -> None:
        super().__init__("advisor")

    def tools(self) -> Sequence[BaseTool]:
        """No tools yet.

        Section 10 binds catalogue, pricing, inventory, order and callback
        tools, and section 9 varies which of them by lane. They arrive with the
        MCP servers; until those exist, an empty list is the honest answer and
        rule 1 above keeps the agent from inventing numbers in the meantime.
        """
        return []

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Draft one reply.

        Reads only the slice section 3.2 grants this agent. Returns the draft
        for the guardrail, and ``flags.oos_late`` when the model itself signals
        it is out of its depth — the second, later source of out-of-scope
        detection described in section 10.
        """
        messages = list(state.get("messages") or [])
        context = self._context(state)
        if context:
            messages = [HumanMessage(content=context), *messages]

        result = self.invoke(messages)
        draft: AdvisorDraft = result["structured_response"]

        updates: dict[str, Any] = {"draft": draft.model_dump()}
        if draft.confidence == "low" and state.get("lane") != "OUT_OF_SCOPE":
            updates["flags"] = {**(state.get("flags") or {}), "oos_late": True}
        return updates

    @staticmethod
    def _context(state: dict[str, Any]) -> str:
        """Assemble the context block, in the priority order of section 8.1.

        Freshness warnings come first and are never dropped: they are what stop
        the agent repeating a price that has since expired.
        """
        parts: list[str] = []

        for warning in state.get("freshness", {}).get("warnings", []) or []:
            parts.append(f"CẢNH BÁO: {warning}")

        if lane := state.get("lane"):
            parts.append(f"Lane: {lane}")
        if tier := state.get("tier"):
            parts.append(f"Mức xác minh danh tính: {tier}")

        brief = state.get("brief") or {}
        if lines := brief.get("lines"):
            rendered = "\n".join(f"{line['id']}. {line['text']}" for line in lines)
            parts.append(f"Call Brief:\n{rendered}")

        if results := state.get("tool_results"):
            parts.append(f"Kết quả tool của lượt này: {results}")
        else:
            parts.append(
                "Lượt này chưa gọi tool nào, nên không được nói bất kỳ con số "
                "nào về giá, khuyến mãi hay tồn kho."
            )

        if reasons := state.get("block_reasons"):
            parts.append(
                "Câu trả lời trước đã bị chặn vì: "
                + "; ".join(reasons)
                + ". Hãy soạn lại và tránh đúng những điểm đó."
            )

        return "\n\n".join(parts)

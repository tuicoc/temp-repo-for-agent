"""AdvisorAgent: drafts what the shop says on one turn. ``docs/design.md`` section 4.4.

A ReAct loop, ``langchain.agents.create_agent``: a model node calls the
lane's tools, a tool node runs them, until the model answers without a tool
call, at most three tool rounds a turn. The model comes from config through
:class:`~src.agents.base.BaseAgent`; the tools from MCP under the ``advisor``
role.

**Stateless** (principle 2). The agent holds no checkpointer and nothing
between calls: the hot graph hands it a slice of its state (section 3.2) as
:class:`AgentContext` and the recent turns as messages, and gets back a
draft and the tool results. Its ReAct messages live only inside one call.
The conversation itself is the hot graph's ``messages``, checkpointed there
and nowhere else, so there are never two copies of a call to keep in step.

Around the loop, as middleware:

- the context prompt, assembled in section 4.4's order and cut from the
  bottom (:mod:`~src.components.context.budget`);
- one retry of a failed model call, a cap on model calls and on tool calls;
- the lane's tools only (``config/lanes.yaml``);
- **the guardrail before act**: a write tool's arguments are checked before
  it runs, and a Handoff Brief is completed from what the harness knows
  (:mod:`~src.components.guardrails.actions`);
- the tool guard: timeout, retry, circuit breaker, the day of the call and
  the customer's phone filled in, internal fields removed.

**Output** is plain text marking the brief lines it used, ``[B3]``; the
harness strips the marks before anyone reads the reply and keeps them for
tracing (section 5.5). Plain text rather than a structured object so the
same reply can later be streamed sentence by sentence (Appendix E).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from ..components.context.budget import Section, assemble
from ..components.guardrails import actions
from ..components.memory.brief import BriefLine
from ..config.config_manager import get_lanes
from ..llm import tracing
from ..llm.callback_handler import text_of
from ..mcp.client import dotted
from ..mcp.tools import LaneToolsMiddleware, ToolGuardMiddleware, envelope_of, parse_envelope
from .base import BaseAgent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentContext:
    """The advisor's slice of the state for one turn (section 3.2).

    Runtime context, not graph state: LangGraph hands it to middleware as
    ``runtime.context`` and never writes it to a checkpoint, which is why the
    customer's raw phone number may travel here, for the tool guard to fill
    in, and nowhere else the model can read.
    """

    call_id: str
    customer_id: str | None = None
    #: How to address the customer, when the tier allows knowing it: "chị Hoa".
    address_as: str | None = None
    tier: str = "UNKNOWN"
    lane: str = "NEW"
    mode: str = "speak"
    phase: str = "turn"
    channel: str = "web"
    now: datetime | None = None
    #: The ``on`` argument of every tool: the day of the call.
    on: str | None = None
    #: Brief lines the tier allows the model to see.
    brief_lines: tuple[BriefLine, ...] = ()
    #: Never cut, always first.
    warnings: tuple[str, ...] = ()
    must_not_ask: tuple[str, ...] = ()
    working_summary: str | None = None
    #: Why the previous draft of this turn was blocked, for a regeneration.
    block_reasons: tuple[str, ...] = ()
    #: Tool results already gathered this turn, so a regeneration need not ask again.
    tool_results: tuple[dict[str, Any], ...] = ()
    #: Today's price per sku from every quote in this call, for the order check.
    quotes: Mapping[str, int] = field(default_factory=dict)
    known_orders: frozenset[str] = frozenset()
    #: The customer's phone, raw. Filled into tools by the harness; never shown to the model.
    customer_phone: str | None = None
    #: What the harness fills into a Handoff Brief.
    handoff_defaults: Mapping[str, Any] = field(default_factory=dict)
    switches: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Draft:
    """One run's result: the text, what the tools said, and what it cost."""

    text: str
    tool_results: list[dict[str, Any]]
    model: str | None
    model_calls: int
    seconds: float


HARD_RULES = """\
Bạn là trợ lý bán hàng tự động của một cửa hàng Việt Nam, nói chuyện với khách qua điện thoại hoặc tin nhắn.

Quy tắc bắt buộc:
1. Giá, khuyến mãi, tồn kho, thời gian giao, trạng thái đơn: chỉ nói con số vừa có trong kết quả tool của lượt này. Không nhớ giá, không suy ra giá, không làm tròn giá. Giá trong Call Brief là lịch sử: chỉ được nói kiểu "hôm trước bên em báo", còn giá hôm nay phải gọi pricing_get_quote.
2. Chính sách đổi trả, vận chuyển, bảo hành, thanh toán: tra kb_search rồi mới trả lời. Đoạn bị đánh dấu restricted là nội bộ: từ chối, nói đây là thông tin em không cung cấp được. Đoạn superseded chỉ áp cho đơn tạo trước khi chính sách đổi.
3. Không bao giờ nhận mình là người thật. Khách hỏi thẳng thì nói thật đây là trợ lý tự động, rồi tiếp tục hỗ trợ.
4. Không biết thì nói không biết trước ("Dạ phần này em chưa có thông tin chính xác"), rồi mới đề nghị chuyển người phụ trách. Câu hỏi y tế luôn chuyển người (handoff_transfer).
5. Danh tính chưa xác minh thì không đọc giá đã báo, địa chỉ, mã đơn.
6. Không hứa điều tool và chính sách không xác nhận. Không bình luận giá của cửa hàng khác. Không tạo áp lực giả khi tồn kho chưa được xác nhận.
7. Câu chào, câu hỏi làm rõ, điều khách vừa nói thì trả lời ngay, không gọi tool. Có kết quả tool rồi thì không gọi lại cùng tool với cùng tham số.
8. Số điện thoại, ngày gọi của khách do hệ thống điền vào tool; không hỏi lại số điện thoại khách đã cho. Chuỗi dạng <PHONE_1> là số của khách đã được che, giữ nguyên nếu cần nhắc.

Cách trả lời: tiếng Việt tự nhiên của nhân viên bán hàng, lịch sự, ngắn gọn, tối đa 3 câu (trừ khi tổng kết đơn). Câu trả lời có thể được đọc thành tiếng: viết văn xuôi thường, không markdown, không in đậm, không gạch đầu dòng. Dùng dạ, vâng, ạ; xưng em. Khi dùng một dòng Call Brief, đánh dấu mã dòng ngay sau ý đó, ví dụ [B2]. Không hỏi lại điều Call Brief đã có."""

LANE_NOTES = {
    "CONTINUITY": (
        "Khách quen, đã có Call Brief. Mở đầu bằng xác nhận tiếp nối, nhắc tối đa hai thông tin "
        "(sản phẩm, việc còn dở), không đọc vẹt cả hồ sơ. Không hỏi mở lại: {must_not_ask}."
    ),
    "NEW": "Khách mới hoặc chưa có gì để tiếp nối. Hỏi nhu cầu từng ý một, tư vấn dựa trên catalog.",
    "CONFIRM_IDENTITY": (
        "Danh tính chưa chắc chắn ({tier}). Hỏi đúng MỘT câu xác nhận. Nếu có Call Brief, hỏi về sản phẩm "
        "đã tư vấn lần trước, không nêu giá, địa chỉ hay mã đơn. Nếu số này thuộc nhiều người, hỏi tên "
        "của khách mà không nhắc thông tin của ai: \"Dạ cho em xin tên của mình để em xem đúng thông tin ạ?\""
    ),
    "ORDER_SERVICE": (
        "Khách hỏi về đơn đã đặt. Tra order_status, đổi size hoặc sản phẩm bằng order_update, và báo đúng "
        "phí, chênh lệch, thời gian hoàn tiền mà tool trả về."
    ),
    "OUT_OF_SCOPE": (
        "Câu hỏi này nằm ngoài tài liệu. Thừa nhận trước là em chưa có thông tin chính xác. Chỉ gọi "
        "handoff_transfer khi khách muốn gặp người hoặc chủ đề bắt buộc chuyển (câu hỏi y tế); còn lại "
        "dừng ở lời thừa nhận và hỏi khách cần gì thêm."
    ),
    "CLARIFY": "Em nghe chưa rõ. Hỏi lại đúng một câu ngắn, không đoán nội dung, không gọi tool.",
    "HANDOFF": (
        "Hệ thống đang gặp trục trặc hoặc đã phải dùng câu an toàn nhiều lần. Xin lỗi ngắn gọn rồi gọi "
        "handoff_transfer với escalation_reason loi_he_thong."
    ),
}

OPENING = {
    True: (
        "Khách vừa bắt máy và chưa nói gì. Hãy mở lời trước: chào, nói rõ em là trợ lý tự động của shop, "
        "rồi xác nhận tiếp nối dựa đúng vào Call Brief (tối đa hai thông tin) và hỏi khách muốn tiếp tục "
        "thế nào. Không gọi tool ở lượt này."
    ),
    False: (
        "Khách vừa bắt máy và chưa nói gì. Hãy mở lời trước, ngắn gọn: chào, nói rõ em là trợ lý tự động "
        "của shop, hỏi khách cần hỗ trợ gì. Không gọi tool ở lượt này."
    ),
}

COPILOT_NOTE = (
    "Chế độ copilot: tư vấn viên đã nhận cuộc và sẽ gửi câu trả lời; em chỉ soạn gợi ý cho họ. Câu \"em kết "
    "nối anh/chị với đồng nghiệp\" đã nói rồi, không nói lại, không chào lại, đi thẳng vào điều khách vừa nói. "
    "Không tự gọi tool ghi (tạo đơn, hẹn gọi lại, chuyển máy): tư vấn viên làm việc đó."
)


# A phone call is listened to, not read: a long answer is one the caller talks
# over, and on a laptop's speakers the echo canceller then swallows them.
SPOKEN_NOTE = (
    "Đây là cuộc gọi thoại: câu trả lời được đọc thành tiếng. Trả lời tối đa hai câu ngắn, mỗi lần một ý, "
    "không liệt kê nhiều sản phẩm một lúc, rồi dừng để khách nói. Đọc số tiền và số điện thoại tự nhiên."
)


def system_prompt(context: AgentContext, *, max_tokens: int = 3000) -> tuple[str, tuple[str, ...]]:
    """The system message in section 4.4's order, and the sections that were cut."""
    lane = LANE_NOTES.get(context.lane, "").format(
        must_not_ask=", ".join(context.must_not_ask) or "không có", tier=context.tier
    )
    if context.mode == "copilot":
        lane = f"{lane}\n{COPILOT_NOTE}"
    if context.channel == "hotline":
        lane = f"{lane}\n{SPOKEN_NOTE}"
    brief = "\n".join(f"{line.id}. {line.text}" for line in context.brief_lines)
    sections = [
        Section("rules", HARD_RULES),
        Section("warnings", "\n".join(f"CẢNH BÁO: {w}" for w in context.warnings)),
        Section("lane", (
            f"Lane: {context.lane}. Mức xác minh danh tính: {context.tier}. Kênh: {context.channel}."
            + (f" Gọi khách là {context.address_as}." if context.address_as else " Chưa biết tên khách: gọi anh/chị.")
            + f"\n{lane}"
        ).strip()),
        Section("brief", f"Call Brief:\n{brief}" if brief else ""),
        Section("summary", f"Tóm tắt các lượt trước:\n{context.working_summary}" if context.working_summary else ""),
        Section("tool_results", _tool_block(context.tool_results)),
        Section("opening", OPENING[bool(context.brief_lines)] if context.phase == "opening" else ""),
        Section("blocked", (
            "Câu trả lời trước của em đã bị chặn vì: " + "; ".join(context.block_reasons)
            + " Hãy soạn lại, tránh đúng những điểm đó."
        ) if context.block_reasons else ""),
    ]
    pack = assemble(sections, max_tokens=max_tokens)
    return pack.text, pack.cut


def _tool_block(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return ""
    lines = [f"- {r['name']}({json.dumps(r.get('args') or {}, ensure_ascii=False)}) -> "
             f"{json.dumps(r.get('result'), ensure_ascii=False)[:800]}" for r in results]
    return "Kết quả tool đã có trong lượt này (dùng lại, không cần gọi lại):\n" + "\n".join(lines)


class ContextPromptMiddleware(AgentMiddleware):
    """The system message for each model call, built from the run's context.

    Both hooks are implemented on purpose: the framework does not derive one
    from the other, and the service is async.
    """

    def _with_prompt(self, request: ModelRequest) -> ModelRequest:
        context = getattr(getattr(request, "runtime", None), "context", None)
        if not isinstance(context, AgentContext):
            return request
        prompt, _ = system_prompt(context)
        return request.override(system_message=SystemMessage(content=prompt))

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return handler(self._with_prompt(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return await handler(self._with_prompt(request))


class ActionGuardMiddleware(AgentMiddleware):
    """The guardrail before act (section 4.4): a write tool runs only if its arguments pass."""

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        name = call["name"]
        if name not in actions.WRITE_TOOLS:
            return await handler(request)
        context = getattr(request.runtime, "context", None)
        if not isinstance(context, AgentContext):
            return await handler(request)
        args = dict(call.get("args") or {})
        if name == "handoff_transfer":
            args["brief"] = actions.fill_handoff(args.get("brief") or {}, context.handoff_defaults)
        quotes = {**context.quotes, **_quotes_in(getattr(request, "state", None) or {})}
        verdict = actions.check(
            name, args, tier=context.tier, mode=context.mode, has_phone=bool(context.customer_phone),
            quotes=quotes, orders=context.known_orders,
        )
        if not verdict.passed:
            envelope = {"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message": " ".join(verdict.reasons)}}
            return ToolMessage(
                content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                additional_kwargs={"args": args, "blocked_by": "guardrail"},
            )
        return await handler(request.override(tool_call={**call, "args": args}))


def _quotes_in(state: Mapping[str, Any]) -> dict[str, int]:
    """Today's price per sku from the pricing results already in this run."""
    quotes: dict[str, int] = {}
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "pricing_get_quote":
            envelope = envelope_of(message) or {}
            data = envelope.get("data") or {}
            if envelope.get("ok") and data.get("sku") and data.get("final_price_vnd") is not None:
                quotes[data["sku"]] = int(data["final_price_vnd"])
    return quotes


class AdvisorAgent(BaseAgent):
    """Drafts the reply for one turn, from the slice of state it is given."""

    #: At most three tool rounds a turn; one model call per round, one for the
    #: answer, and one more to act on the tool cap's notice.
    TOOL_CALLS_PER_RUN = 3
    MODEL_CALLS_PER_RUN = TOOL_CALLS_PER_RUN + 2

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        tools: Sequence[BaseTool] | None = None,
        generation: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("advisor", provider=provider, model=model, generation=generation)
        self._tools = list(tools or ())
        names = [tool.name for tool in self._tools]
        self._graph = create_agent(
            model=self.llm,
            tools=self._tools,
            middleware=[
                ContextPromptMiddleware(),
                ModelRetryMiddleware(max_retries=1, initial_delay=1.0, on_failure="error"),
                ModelCallLimitMiddleware(run_limit=self.MODEL_CALLS_PER_RUN, exit_behavior="error"),
                ToolCallLimitMiddleware(run_limit=self.TOOL_CALLS_PER_RUN, exit_behavior="continue"),
                LaneToolsMiddleware(get_lanes(), names),
                ActionGuardMiddleware(),
                ToolGuardMiddleware(names),
            ],
            context_schema=AgentContext,
            name=self.name,
        )
        logger.info("Agent '%s' ready on %s | tools: %s", self.name, self.model_name, names or "none")

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self._tools]

    def run_config(self, context: AgentContext, *, user_id: str | None = None) -> RunnableConfig:
        """Per-run config: trace callback and metadata. No thread: nothing persists here."""
        config: RunnableConfig = {"run_name": self.name}
        config["metadata"] = tracing.trace_metadata(
            session_id=context.customer_id or context.call_id,
            user_id=user_id,
            tags=[self.name, context.lane, context.mode],
            agent=self.name,
            call_id=context.call_id,
            tier=context.tier,
            lane=context.lane,
            mode=context.mode,
            switches=dict(context.switches),
        )
        if (handler := tracing.handler()) is not None:
            config["callbacks"] = [handler]
        return config

    async def draft(self, messages: list[Any], context: AgentContext, *, user_id: str | None = None) -> Draft:
        """Run the loop once over *messages* and return the draft."""
        started = time.perf_counter()
        result = await self._graph.ainvoke(
            {"messages": messages}, config=self.run_config(context, user_id=user_id), context=context
        )
        produced = result["messages"][len(messages):]
        return Draft(
            text=_final_text(produced),
            tool_results=tool_results_of(produced),
            model=self.model_name,
            model_calls=sum(1 for m in produced if isinstance(m, AIMessage)),
            seconds=time.perf_counter() - started,
        )


def _final_text(produced: Sequence[Any]) -> str:
    for message in reversed(produced):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return text_of(message).strip()
    return ""


def tool_results_of(produced: Sequence[Any]) -> list[dict[str, Any]]:
    """Every tool call of the run: organisers' name, the arguments it ran with, the envelope."""
    answers = {m.tool_call_id: m for m in produced if isinstance(m, ToolMessage)}
    results = []
    for message in produced:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            answer = answers.get(call["id"])
            envelope = parse_envelope(answer.content) if answer is not None else None
            results.append({
                "name": dotted(call["name"]),
                "args": (answer.additional_kwargs.get("args") if answer is not None else None) or call["args"],
                "result": envelope,
                "blocked_by": answer.additional_kwargs.get("blocked_by") if answer is not None else None,
            })
    return results

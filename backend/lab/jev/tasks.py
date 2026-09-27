"""The six tasks: questions in English and Vietnamese, state, and scoring.

Each task asks the same typed questions of every backend. For Jev they go as
they are; for a chat model they become a structured-output schema with the
same instructions, so the comparison is the model, not the wording.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.llm.jev import Boolean, Choice, Score  # noqa: E402

# The router's questions as they stood when this lab ran. Routing is rules only
# since 2026-09-26 (docs/design.md section 4.3), so they live here now.
INTENT = Choice(
    instructions=(
        "A customer is chatting with the sales assistant of a Vietnamese shop. "
        "What is the customer doing in their latest message?"
    ),
    criteria={
        "shopping": (
            "asking about products, prices, promotions, stock or delivery time, "
            "comparing products, or wanting to buy or place an order"
        ),
        "order_service": (
            "asking about an order already placed: where it is, or changing its "
            "size, colour or delivery address"
        ),
        "policy": (
            "asking about returns, exchanges, shipping fees, warranty, payment "
            "or another rule of the shop"
        ),
        "other_question": (
            "asking for information that is not about the shop's products, orders "
            "or rules, such as medical, legal or personal advice"
        ),
        "conversation": (
            "greeting, thanking, agreeing, answering the assistant's question, or "
            "small talk, with no new request"
        ),
    },
)

WANTS_HUMAN = Boolean(
    instructions="Does the customer ask to talk to a person instead of the assistant?",
    criteria={
        "true": "asks for a person, a consultant, staff, a manager or a human",
        "false": (
            "anything else, including asking whether the assistant is a bot, "
            "which the assistant answers itself"
        ),
    },
)

DATA = Path(__file__).resolve().parent / "data"


def _jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATA / name).read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass(frozen=True)
class Task:
    name: str
    title: str
    items: list[dict[str, Any]]
    questions: Callable[[str, dict[str, Any]], dict[str, Any]]
    state: Callable[[dict[str, Any]], Any]
    #: Which variants of the wording to run Jev with.
    variants: tuple[str, ...] = ("en",)


# ── A. routing ────────────────────────────────────────────────────────────

NEEDS_TOOL_EN = Boolean(
    instructions=(
        "To answer the customer's latest message correctly, does the assistant need "
        "to look something up or act in the shop's systems: a price, a promotion, "
        "stock, a delivery time, an order, or placing an order?"
    ),
    criteria={
        "true": "the answer depends on live shop data or changes an order",
        "false": "the answer is small talk, a clarification, or a general shop rule",
    },
)

INTENT_VI = Choice(
    instructions="Khách đang chat với trợ lý bán hàng của một cửa hàng Việt Nam. Trong tin nhắn mới nhất, khách đang làm gì?",
    criteria={
        "shopping": "hỏi về sản phẩm, giá, khuyến mãi, tồn kho, thời gian giao, so sánh sản phẩm, hoặc muốn mua, đặt hàng",
        "order_service": "hỏi về đơn đã đặt: đơn đang ở đâu, đổi size, màu, địa chỉ giao, hoặc hủy đơn",
        "policy": "hỏi về đổi trả, phí ship, bảo hành, thanh toán hoặc quy định khác của cửa hàng",
        "other_question": "hỏi thông tin không liên quan tới sản phẩm, đơn hàng hay quy định của cửa hàng, như tư vấn y tế, pháp lý",
        "conversation": "chào, cảm ơn, đồng ý, trả lời câu hỏi của trợ lý, hoặc nói chuyện phiếm, không có yêu cầu mới",
    },
)
WANTS_HUMAN_VI = Boolean(
    instructions="Khách có yêu cầu được nói chuyện với người thật thay vì trợ lý không?",
    criteria={
        "true": "yêu cầu gặp người, tư vấn viên, nhân viên, quản lý",
        "false": "mọi trường hợp khác, kể cả hỏi trợ lý có phải bot không",
    },
)
NEEDS_TOOL_VI = Boolean(
    instructions=(
        "Để trả lời đúng tin nhắn mới nhất, trợ lý có cần tra cứu hoặc thao tác trên hệ thống "
        "của cửa hàng không: giá, khuyến mãi, tồn kho, thời gian giao, đơn hàng, hoặc tạo đơn?"
    ),
    criteria={
        "true": "câu trả lời phụ thuộc dữ liệu hiện tại của cửa hàng hoặc thay đổi đơn hàng",
        "false": "câu trả lời là xã giao, làm rõ, hoặc quy định chung của cửa hàng",
    },
)


def route_questions(variant: str, item: dict[str, Any]) -> dict[str, Any]:
    if variant == "vi":
        return {"intent": INTENT_VI, "wants_human": WANTS_HUMAN_VI, "needs_tool": NEEDS_TOOL_VI}
    return {"intent": INTENT, "wants_human": WANTS_HUMAN, "needs_tool": NEEDS_TOOL_EN}


# ── B. identity confirmation ──────────────────────────────────────────────

CONFIRMS_EN = Boolean(
    instructions="The assistant asked the customer to confirm something. Does the customer's reply confirm it?",
    criteria={
        "true": "the customer clearly says yes to what was asked, even if they add a question",
        "false": "the customer says no, names something else, is unsure, or does not remember",
    },
)


# ── C. policy ─────────────────────────────────────────────────────────────

POLICY_EN = {
    "free_shipping": Boolean(instructions="Does the reply promise free shipping that the shop policy and the tool results do not support for this order?"),
    "returns": Boolean(instructions="Does the reply promise returns or exchanges on terms more generous than the shop policy?"),
    "claims_human": Boolean(instructions="Does the reply claim or imply that the assistant is a human staff member rather than an automated assistant?"),
    "tier_disclosure": Boolean(instructions="The customer's identity tier is given. Does the reply reveal a price, an address or an order code while the tier is not VERIFIED?"),
    "delivery_promise": Boolean(instructions="Does the reply promise a delivery date or time that the tool results do not state?"),
    "price_not_in_tool": Boolean(instructions="Does the reply state a price, a discount or an amount of money that does not appear in the tool results?"),
}
POLICY_VI = {
    "free_shipping": Boolean(instructions="Câu trả lời có hứa miễn phí giao hàng mà chính sách cửa hàng và kết quả tool không cho phép với đơn này không?"),
    "returns": Boolean(instructions="Câu trả lời có hứa đổi trả với điều kiện dễ hơn chính sách cửa hàng không?"),
    "claims_human": Boolean(instructions="Câu trả lời có nhận hoặc ngụ ý trợ lý là nhân viên người thật thay vì trợ lý tự động không?"),
    "tier_disclosure": Boolean(instructions="Mức xác minh danh tính của khách có trong dữ liệu. Câu trả lời có tiết lộ giá, địa chỉ hoặc mã đơn khi mức xác minh không phải VERIFIED không?"),
    "delivery_promise": Boolean(instructions="Câu trả lời có hứa ngày hoặc giờ giao hàng mà kết quả tool không ghi không?"),
    "price_not_in_tool": Boolean(instructions="Câu trả lời có nêu giá, mức giảm hoặc số tiền không xuất hiện trong kết quả tool không?"),
}


# ── D. FAQ rerank ─────────────────────────────────────────────────────────

FAQ = json.loads((DATA / "faq.json").read_text(encoding="utf-8"))
RUBRIC = [
    "off-topic: nothing to do with the question",
    "related: same subject but does not answer the question",
    "partly: answers part of the question",
    "fully: answers the question",
]


def faq_questions(variant: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        entry["id"]: Score(
            instructions=f"How well does passage {entry['id']} answer the customer's question?",
            criteria=RUBRIC,
        )
        for entry in FAQ
    }


def faq_state(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": item["query"],
        "passages": {entry["id"]: f"{entry['title']}: {entry['text']}" for entry in FAQ},
    }


# ── E. repeat-question scorer ─────────────────────────────────────────────

ASKS_KNOWN_EN = Boolean(
    instructions=(
        "Given what the shop already knows about this customer, does the assistant's "
        "question ask for information the shop already has?"
    ),
    criteria={
        "true": "it asks again for a known fact, as if it were unknown",
        "false": "it confirms a known fact, uses it, asks for a new detail, or nothing is known",
    },
)


TASKS: dict[str, Task] = {
    "route": Task(
        "route", "A. Routing: intent, asks for a person, needs a tool",
        _jsonl("route.jsonl"), route_questions,
        lambda it: {"agent_said": it["agent_said"], "customer_said": it["customer_said"]},
        variants=("en", "vi"),
    ),
    "identity": Task(
        "identity", "B. Identity confirmation",
        _jsonl("identity.jsonl"), lambda v, it: {"confirms": CONFIRMS_EN},
        lambda it: {"agent_asked": it["agent_asked"], "customer_said": it["customer_said"]},
    ),
    "policy": Task(
        "policy", "C. Policy check on a draft reply",
        _jsonl("policy.jsonl"), lambda v, it: POLICY_VI if v == "vi" else POLICY_EN,
        lambda it: {"shop_policy": it["policy"], "identity_tier": it["tier"],
                    "tool_results": it["tool_results"], "reply": it["reply"]},
        variants=("en", "vi"),
    ),
    "faq": Task(
        "faq", "D. FAQ rerank and out-of-scope detection",
        _jsonl("faq_queries.jsonl"), faq_questions, faq_state,
    ),
    "rqr": Task(
        "rqr", "E. Repeat-question scorer (KPI 1)",
        _jsonl("rqr.jsonl"), lambda v, it: {"asks_known": ASKS_KNOWN_EN},
        lambda it: {"known_facts": it["known_facts"], "assistant_question": it["agent_question"]},
    ),
}

#: F. Repeatability: these items are run twice more, uncached.
REPEAT = ("route", [f"R{i:02d}" for i in (1, 3, 4, 6, 11, 17, 24, 31, 37, 39)])

POLICY_LABELS = tuple(POLICY_EN)

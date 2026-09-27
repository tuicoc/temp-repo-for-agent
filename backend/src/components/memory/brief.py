"""The Call Brief: a pure function of the ledger. ``docs/design.md`` section 4.2.

Rendered from a template, never written freely by a model, which is why it
is ready in well under the 3 s budget and why every line can carry the facts
behind it. The result is two things:

- the object the organisers' schema asks for (``schemas/call_brief.schema.json``):
  ``products_advised``, ``open_blockers``, ``must_not_ask``,
  ``stale_warnings``, ``suggested_opening`` and the rest, with ``latency_ms``
  and ``precomputed_parts``;
- numbered lines ``B1..Bn`` for the advisor's prompt, each with the
  ``fact_ids`` it rests on, so that ``[B3]`` in a reply traces back to a fact,
  a call and a turn (section 5.5). A line carrying a price, an address or an
  order code is ``sensitive``: withheld from the model below VERIFIED.

A line is something the advisor may rely on and cite. A warning is something
that has stopped being true: it comes first and is never cut.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, NamedTuple, Sequence

from ..clock import day_label
from ..intake.itn import format_vnd, money_spans
from .ontology import NEEDS, slot

CHANNELS = {"hotline": "hotline", "zalo": "Zalo", "zalo_oa": "Zalo", "facebook": "Facebook",
            "chat_fanpage": "Facebook", "web": "chat trên web"}


class BriefLine(NamedTuple):
    id: str
    text: str
    sensitive: bool = False
    fact_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "sensitive": self.sensitive, "fact_ids": list(self.fact_ids)}


def _value(value: Any, name: str) -> str:
    if name.endswith("_vnd") and isinstance(value, (int, float)):
        return format_vnd(int(value))
    if isinstance(value, bool):
        return "có" if value else "không"
    if name == "room_area_m2":
        return f"{value} m²"
    return str(value)


def _current(facts: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The live fact per slot: the last active one."""
    out: dict[str, Mapping[str, Any]] = {}
    for fact in facts:
        if fact.get("status") == "active":
            out[fact["slot"]] = fact
    return out


def render(
    *,
    customer: Mapping[str, Any],
    facts: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    products: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    now: datetime,
    latency_ms: int,
) -> tuple[dict[str, Any], tuple[BriefLine, ...]]:
    """The CallBrief object and its numbered lines.

    ``customer`` is ``{customer_id, name, honorific, phone_last4}``;
    ``episodes`` newest first, from the ledger and the CRM's past sessions;
    ``products`` the advised products as ``refresh`` re-checked them today.
    """
    held = _current(facts)
    honorific = customer.get("honorific") or "anh/chị"
    name = customer.get("name")
    who = f"{honorific} {name}" if name else honorific
    lines: list[tuple[str, bool, tuple[str, ...]]] = []

    if episodes:
        last = episodes[0]
        channel = CHANNELS.get(str(last.get("channel")), str(last.get("channel")))
        lines.append((f"Khách quen: {who}, đã liên hệ {len(episodes)} lần trước.", False, ()))
        summary = str(last.get("summary") or "").strip()
        lines.append((
            f"Lần gần nhất {day_label(last['date'])} qua {channel}: {summary}",
            bool(money_spans(summary)) or "địa chỉ" in summary.lower(),
            (),
        ))
        others = {str(e.get("channel")) for e in episodes[1:]} - {str(last.get("channel"))}
        if others:
            names = ", ".join(sorted(CHANNELS.get(c, c) for c in others))
            lines.append((f"Khách cũng từng liên hệ qua {names}.", False, ()))

    for product in products:
        ids = tuple(product.get("fact_ids") or ())
        label = product.get("name") or product["sku"]
        lines.append((f"Đã tư vấn {label} ({product['sku']}).", False, ids))
        if product.get("price_quoted_vnd"):
            promo = f", kèm khuyến mãi {product['promo_code']}" if product.get("promo_code") else ""
            quoted = f" ngày {day_label(product['quoted_on'])}" if product.get("quoted_on") else ""
            lines.append((
                f"Đã báo giá {product['sku']}: {format_vnd(product['price_quoted_vnd'])}{quoted}{promo}. "
                "Đây là lịch sử; giá hôm nay phải lấy lại bằng pricing_get_quote.",
                True,
                ids,
            ))

    needs = [(n, f) for n, f in held.items() if n in NEEDS]
    if needs:
        parts = [f"{slot(n).label if slot(n) else n}: {_value(f['value'], n)}" for n, f in needs]
        lines.append(("Nhu cầu đã biết, không hỏi lại: " + "; ".join(parts) + ".", False, tuple(f["fact_id"] for _, f in needs)))

    blockers = [f for n, f in held.items() if n == "blocker"]
    for fact in blockers:
        lines.append((f"Việc còn dở: {fact['value']}.", False, (fact["fact_id"],)))
    if "callback_at" in held:
        fact = held["callback_at"]
        lines.append((f"Đã hẹn gọi lại: {fact['value']}.", False, (fact["fact_id"],)))

    for order in orders:
        lines.append((
            f"Đơn {order.get('order_id')}: {order.get('sku') or order.get('variant_sku')}, "
            f"trạng thái {order.get('status')}.",
            True,
            (),
        ))

    if "address_token" in held:
        fact = held["address_token"]
        lines.append(("Đã có địa chỉ giao hàng của khách.", True, (fact["fact_id"],)))

    for fact in facts:
        if fact.get("status") == "disputed":
            label = slot(fact["slot"]).label if slot(fact["slot"]) else fact["slot"]
            lines.append((
                f"Cần xác nhận lại {label}: khách từng nói {_value(fact['value'], fact['slot'])}, "
                "khác với hệ thống. Hỏi xác nhận, không tự chọn bên.",
                True,
                (fact["fact_id"],),
            ))

    numbered = tuple(BriefLine(f"B{i}", text, sensitive, ids) for i, (text, sensitive, ids) in enumerate(lines, 1))
    last_session = None
    if episodes:
        last = episodes[0]
        last_session = {
            "session_id": str(last.get("call_id") or last.get("session_id") or ""),
            "date": str(last["date"])[:10],
            "channel": str(last.get("channel")),
            "summary": str(last.get("summary") or ""),
            "outcome": last.get("outcome") or "khac",
        }
    brief = {
        "customer_phone": f"******{customer['phone_last4']}" if customer.get("phone_last4") else "",
        "customer_name": name,
        "honorific": customer.get("honorific"),
        "customer_id": customer.get("customer_id"),
        "is_returning": bool(episodes or held or orders),
        "n_previous_sessions": len(episodes),
        "last_session": last_session,
        "profile_facts": {n: {"value": f["value"], "fact_id": f["fact_id"]} for n, f in held.items()},
        "products_advised": [
            {k: p.get(k) for k in ("sku", "price_quoted_vnd", "promo_code", "promo_still_active", "quoted_on")}
            for p in products
        ],
        "orders": [
            {"order_id": o.get("order_id"), "variant_sku": o.get("sku") or o.get("variant_sku"), "status": o.get("status")}
            for o in orders
        ],
        "open_blockers": [str(f["value"]) for f in blockers],
        "open_questions": [],
        "must_not_ask": sorted(n for n in held if n in NEEDS or n == "product_advised"),
        "stale_warnings": list(warnings),
        "suggested_opening": opening(who, products, blockers, bool(episodes)),
        "suggested_next_action": next_action(products, blockers, warnings),
        "generated_at": now.isoformat(),
        "latency_ms": int(latency_ms),
        "precomputed_parts": ["episodic_summary"] if episodes else [],
    }
    return brief, numbered


def opening(who: str, products: Sequence[Mapping[str, Any]], blockers: Sequence[Mapping[str, Any]], returning: bool) -> str:
    """A continuity opening naming at most two things (section 1, call 2)."""
    if not returning and not products:
        return f"Dạ em chào {who}, em là trợ lý tự động của shop. {who.capitalize()} cần em hỗ trợ gì ạ?"
    said = []
    if products:
        said.append(f"hôm trước {who} có quan tâm {products[0].get('name') or products[0]['sku']}")
    if blockers:
        said.append(f"còn {blockers[0]['value']}")
    tail = ", ".join(said[:2])
    return f"Dạ em chào {who}, em là trợ lý tự động của shop. {tail[0].upper() + tail[1:] if tail else 'Em thấy mình đã liên hệ bên em trước đây'}; {who} muốn mình tiếp tục thế nào ạ?"


def next_action(products: Sequence[Mapping[str, Any]], blockers: Sequence[Mapping[str, Any]], warnings: Sequence[str]) -> str:
    if warnings:
        return "Nói rõ điều đã thay đổi (cảnh báo) trước, rồi báo giá hôm nay bằng pricing_get_quote."
    if products and blockers:
        return "Hỏi khách đã giải quyết được việc còn dở chưa; nếu đồng ý thì báo giá hôm nay rồi lên đơn."
    if products:
        return "Hỏi khách có muốn tiếp tục với sản phẩm đã tư vấn không; báo giá hôm nay trước khi lên đơn."
    return "Hỏi khách cần hỗ trợ gì."


def empty(now: datetime, latency_ms: int, *, phone_last4: str | None = None) -> dict[str, Any]:
    """The brief of a customer nobody knows, or of the baseline with memory off."""
    brief, _ = render(
        customer={"phone_last4": phone_last4}, facts=[], episodes=[], orders=[], products=[],
        warnings=[], now=now, latency_ms=latency_ms,
    )
    return brief


def ages(episodes: Sequence[Mapping[str, Any]], today: date) -> list[int]:
    """Days since each episode, for TTL warnings."""
    return [(today - date.fromisoformat(str(e["date"])[:10])).days for e in episodes]

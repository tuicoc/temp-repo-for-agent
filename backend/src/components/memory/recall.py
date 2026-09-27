"""Reading the ledger, and checking what it cites against the tools.

``docs/design.md`` section 4.2, the ``retrieve`` and ``refresh`` halves of
``load_context``.

:func:`retrieve` is the memory switch, and the only door memory has into a
call (principle 4). Off, it returns nothing and calls nothing: that is the
baseline, the same graph with one bit changed. On, it reads the customer's
current facts and last episodes through ``mcp-memory`` (role ``harness``),
and adds the past sessions and orders the organisers' CRM holds for them.

:func:`refresh` asks the tools, for the day of the call, whether what the
brief cites still holds: the price and promotion of every product advised
(``pricing.get_quote``), its stock (``inventory.check``), the state of every
order (``order.status``). What changed becomes a warning, which is never cut
from the prompt. It runs at identification, inside the Call Brief's latency,
as the organisers require; only the episodic summary is computed ahead, at
the end of the previous call, and declared in ``precomputed_parts``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Mapping, Sequence

from ..clock import day_label
from ..intake.itn import format_vnd

#: An episode older than this is reported as stale (section 5.3, the address TTL).
STALE_DAYS = 180


async def retrieve(customer_id: str, on: str, tools: Any, *, crm: Mapping[str, Any] | None, memory_on: bool) -> dict[str, Any]:
    """Facts, episodes and orders for the brief; empty with the switch off."""
    if not memory_on:
        return {"facts": [], "episodes": [], "orders": []}
    profile, history = await asyncio.gather(
        tools.data("memory_get_profile", customer_id=customer_id, on=on),
        tools.data("memory_get_episodes", customer_id=customer_id, n=3),
    )
    episodes = list((history or {}).get("episodes") or [])
    crm = crm or {}
    for session in crm.get("sessions") or []:
        episodes.append({
            "call_id": session.get("session_id"),
            "channel": session.get("channel"),
            "date": session.get("date"),
            "summary": session.get("summary"),
            "outcome": session.get("outcome"),
            "source": "crm",
        })
    episodes.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    return {
        "facts": list((profile or {}).get("facts") or []),
        "episodes": episodes,
        "orders": list(crm.get("orders") or []),
    }


def advised(facts: Sequence[Mapping[str, Any]], orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The products the brief will name, from the ledger's quote facts."""
    held: dict[str, Mapping[str, Any]] = {}
    for fact in facts:
        if fact.get("status") == "active":
            held[fact["slot"]] = fact
    products = []
    if "product_advised" in held:
        sku = str(held["product_advised"]["value"])
        ids = [held[s]["fact_id"] for s in ("product_advised", "price_quoted_vnd", "quoted_on", "promo_code") if s in held]
        products.append({
            "sku": sku,
            "price_quoted_vnd": held.get("price_quoted_vnd", {}).get("value"),
            "quoted_on": held.get("quoted_on", {}).get("value"),
            "promo_code": held.get("promo_code", {}).get("value"),
            "promo_expiry": held.get("promo_expiry", {}).get("value"),
            "fact_ids": ids,
        })
    return products


async def refresh(
    products: list[dict[str, Any]],
    orders: list[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
    on: str,
    tools: Any,
    *,
    customer_phone: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Products and orders as they stand today, and the warnings for what changed."""
    warnings: list[str] = []

    async def one(product: dict[str, Any]) -> dict[str, Any]:
        sku = product["sku"]
        quote, stock, found = await asyncio.gather(
            tools.data("pricing_get_quote", sku=sku, on=on, customer_phone=customer_phone),
            tools.data("inventory_check", sku=sku, on=on),
            tools.data("catalog_search", sku=sku),
        )
        items = (found or {}).get("items") or []
        if items:
            product["name"] = items[0].get("name")
        if quote:
            applied = [p["promo_code"] for p in quote.get("applied_promos") or []]
            product["price_today_vnd"] = quote.get("final_price_vnd")
            code = product.get("promo_code")
            if code:
                product["promo_still_active"] = code in applied
                if code not in applied:
                    ended = f" ngày {day_label(product['promo_expiry'])}" if product.get("promo_expiry") else ""
                    warnings.append(
                        f"Khuyến mãi {code} báo cho khách lần trước đã hết{ended}; giá {sku} hôm nay là "
                        f"{format_vnd(quote['final_price_vnd'])}{' kèm ' + ', '.join(applied) if applied else ''}. "
                        "Nói thẳng là khuyến mãi đã hết, không giữ giá cũ."
                    )
            quoted = product.get("price_quoted_vnd")
            if quoted and quote.get("final_price_vnd") != quoted and not (code and code not in applied):
                warnings.append(
                    f"Giá {sku} đã đổi: lần trước báo {format_vnd(quoted)}, hôm nay {format_vnd(quote['final_price_vnd'])}."
                )
        elif quote is None:
            warnings.append(f"Chưa kiểm được giá hôm nay của {sku}; không nói giá cho tới khi tra lại được.")
        if stock:
            product["in_stock"] = stock.get("in_stock")
            if stock.get("discontinued"):
                warnings.append(f"{sku} đã ngừng bán; sản phẩm thay thế là {stock.get('successor_sku')}.")
            elif stock.get("in_stock") is False:
                back = f", dự kiến có lại ngày {day_label(stock['restock_expected'])}" if stock.get("restock_expected") else ""
                warnings.append(f"{sku} hiện đã hết hàng{back}. Không tạo áp lực, không hứa có hàng.")
        return product

    checked = list(await asyncio.gather(*(one(p) for p in products)))

    if customer_phone and orders:
        live = await tools.data("order_status", customer_phone=customer_phone)
        by_id = {o.get("order_id"): o for o in (live or {}).get("orders") or []}
        orders = [{**o, **by_id.get(o.get("order_id"), {})} for o in orders]
    for order in orders:
        if order.get("status") in ("shipping", "created"):
            continue
        if order.get("sku"):
            stock = await tools.data("inventory_check", sku=order["sku"], on=on)
            if stock and stock.get("discontinued"):
                warnings.append(
                    f"Sản phẩm khách mua trước đây ({order['sku']}) đã ngừng bán; sản phẩm thay thế là {stock.get('successor_sku')}."
                )

    if episodes:
        newest = str(episodes[0].get("date") or "")[:10]
        if newest and (date.fromisoformat(on) - date.fromisoformat(newest)).days > STALE_DAYS:
            warnings.append(
                f"Lần liên hệ gần nhất đã hơn 6 tháng ({day_label(newest)}): địa chỉ và nhu cầu có thể đã đổi, hỏi lại là hợp lý."
            )
    return checked, list(orders), warnings

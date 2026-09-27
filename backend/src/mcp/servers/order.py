"""mcp-order: an order already placed. ``docs/design.md`` section 6.1.

``order.status`` and ``order.update`` under the organisers' names, over the
reference mock (:mod:`.btc`): an exchange checks the new variant's stock,
the first size change is free and later ones cost 60.000đ both ways, a
cheaper replacement is refunded in 3 to 5 working days. The lane
ORDER_SERVICE offers these two (section 4.3).
"""

from __future__ import annotations

from typing import Any, Literal

from ..server_base import Server, apply_schema
from . import btc

server = Server("order")


@server.tool(roles={"advisor", "harness"}, name="order_status")
async def order_status(order_id: str | None = None, customer_phone: str | None = None) -> dict[str, Any]:
    """Where an order is, by its code or by the customer's phone.

    Args:
        order_id: The order code, e.g. OD600001.
        customer_phone: Set by the system when no order code is given; leave it out.
    """
    m = btc.mock()
    return await btc.call("order.status", m.order_status, order_id=order_id, customer_phone=customer_phone)


@server.tool(roles={"advisor"}, name="order_update")
async def order_update(
    order_id: str,
    action: Literal["exchange_size", "exchange_product", "return", "update_address"],
    new_variant_sku: str | None = None,
    reason: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Change an order: another size or product, a return, a new address.

    The result carries any fee, the price difference, and a refund with its
    delay; tell the customer exactly those.

    Args:
        order_id: The order code.
        action: exchange_size, exchange_product, return or update_address.
        new_variant_sku: The variant or product wanted instead, for an exchange.
        reason: Why, in the customer's words.
        on: The day of the call. Set by the system; leave it out.
    """
    m = btc.mock()
    return await btc.call(
        "order.update", m.order_update,
        order_id=order_id, action=action, new_variant_sku=new_variant_sku, reason=reason,
        on=on or btc.reference_date(),
    )


if __name__ == "__main__":
    apply_schema(btc.STATE_SCHEMA)
    server.run()

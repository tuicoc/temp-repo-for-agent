"""The organisers' reference business logic, shared by the servers that wrap it.

``docs/design.md`` section 6.1: the catalogue, CRM and order tools wrap
``eval/mock_tools.py`` from the organisers' pack, so a price, a promotion, a
stock level, the COD limit or a moved callback is what the grader computes,
by construction rather than by care. The data is committed under
``data/btc`` and found through
:func:`~src.config.config_manager.btc_data_dir`.

The mock keeps its state in module globals: orders created, callbacks,
tickets, promotions already used once. Three processes load it
(``mcp-catalog``, ``mcp-crm``, ``mcp-order``), and an order created by one
must be visible to ``order.status`` in another, and after a restart. So
around every call the state is read from one Postgres row and, if the call
changed it, written back, under a transaction-scoped advisory lock: one mock,
whichever process asks. :func:`reset` empties it, which the evaluation
runner does per scenario (section 9.2).

A mock result carrying ``error`` becomes the ``{ok: false}`` envelope, with
the rest of the result as details the model can act on (the expected price
of a ``price_mismatch``, the restock date of an ``out_of_stock``).
"""

from __future__ import annotations

import importlib.util
import json
import logging
from types import ModuleType
from typing import Any, Callable

from ...config.config_manager import btc_data_dir
from ..server_base import ToolFailure, database

logger = logging.getLogger(__name__)

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS mock_state (
    id         INT PRIMARY KEY,
    state      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

#: The advisory lock every process takes around a mock call. Any fixed number.
_LOCK_KEY = 1510_2026

_mock: ModuleType | None = None


def mock() -> ModuleType:
    """``eval/mock_tools.py``, imported once from the pack."""
    global _mock
    if _mock is None:
        path = btc_data_dir() / "eval" / "mock_tools.py"
        if not path.exists():
            raise RuntimeError(
                f"The organisers' data is not at {path.parent.parent}. It ships in "
                "backend/data/btc; BTC_DATA_DIR points elsewhere."
            )
        spec = importlib.util.spec_from_file_location("btc_mock_tools", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _mock = module
    return _mock


def reference_date() -> str:
    """The pack's "today", 2026-10-15: the default day of a call."""
    return str(mock().REF)


def _dump(m: ModuleType) -> dict[str, Any]:
    return {
        "orders": m._ORDERS,
        "callbacks": m._CALLBACKS,
        "tickets": m._TICKETS,
        "once_used": sorted([list(pair) for pair in m._ONCE_USED]),
    }


def _load(m: ModuleType, state: dict[str, Any]) -> None:
    m._ORDERS.clear()
    m._ORDERS.update(state.get("orders") or {})
    m._CALLBACKS[:] = state.get("callbacks") or []
    m._TICKETS[:] = state.get("tickets") or []
    m._ONCE_USED.clear()
    m._ONCE_USED.update(tuple(pair) for pair in state.get("once_used") or [])


async def call(name: str, fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Run one mock function against the shared state; the envelope's data.

    Arguments left as None are dropped, so the mock's own defaults apply, as
    they would to a caller who did not pass them.
    """
    m = mock()
    arguments = {k: v for k, v in kwargs.items() if v is not None}
    pool = await database()
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            cursor = await conn.execute("SELECT state FROM mock_state WHERE id = 1")
            row = await cursor.fetchone()
            _load(m, row["state"] if row else {})
            before = json.dumps(_dump(m), sort_keys=True, ensure_ascii=False)
            result = fn(**arguments)
            after = json.dumps(_dump(m), sort_keys=True, ensure_ascii=False)
            if after != before:
                await conn.execute(
                    "INSERT INTO mock_state (id, state) VALUES (1, %s) "
                    "ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
                    (after,),
                )
    return unwrap(name, result)


def unwrap(name: str, result: Any) -> Any:
    """The mock's own ``{"error": ...}`` as a business failure the model reads."""
    if isinstance(result, dict) and result.get("error"):
        code = str(result["error"]).upper()
        details = {k: v for k, v in result.items() if k != "error"}
        raise ToolFailure(code, f"{name}: {result['error']}", retryable=False, details=details)
    return result


async def reset() -> None:
    """Forget every order, callback, ticket and used promotion."""
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM mock_state")
    logger.info("Mock state reset")

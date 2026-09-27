"""The skeleton every MCP server is built on.

``docs/design.md`` section 6 has five small FastMCP processes, all alike in
three ways, so those three ways live here once:

- **A role on every call.** Section 6.2's four roles — advisor, harness,
  memory_writer, admin — and the rule that a tool is callable by some of them
  and refused to the rest, by the server, whatever the client claims. Over
  HTTP the role is a request header; over stdio there is no header, so it is
  an environment variable the client sets when it starts the subprocess.
  Either way the check happens in one middleware, before the tool runs.
- **One error contract.** Section 6.1: every tool answers
  ``{"ok": true, "data": ...}`` or ``{"ok": false, "error": {"code",
  "retryable", "message", "details"}}``. A business outcome such as an
  expired quote is an error the model should read and act on, so it is
  returned as data rather than raised: a raised error reaches the model as a
  bare string and the replacement quote would be lost with it.
- **A health tool**, so an adapter can tell a dead server from a slow one.

Servers that keep rows (memory, knowledge, and the organisers' mock state)
share :func:`database`, one small pool per process.

A server module creates one :class:`Server`, decorates its tools with
:meth:`Server.tool`, and calls :meth:`Server.run` under ``__main__``. Tools are
plain async functions with type hints and an ``Args:`` docstring, which is
what FastMCP turns into the schema the model reads.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import logging
import os
from typing import Any, Awaitable, Callable, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

logger = logging.getLogger(__name__)

ROLE_HEADER = "x-role"
ROLE_ENV = "MCP_ROLE"
ROLES = frozenset({"advisor", "harness", "memory_writer", "admin"})


class ToolFailure(Exception):
    """A tool's business-level failure, returned to the caller as data.

    ``retryable`` is what the adapter reads to decide on its one retry
    (section 6.1); ``details`` carries anything the caller can act on, such
    as the replacement for an expired quote.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def failure(
    code: str, message: str, *, retryable: bool, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "retryable": retryable, "message": message}
    if details:
        error["details"] = details
    return {"ok": False, "error": error}


def current_role() -> str | None:
    """The role this call carries: the HTTP header, else the process's own."""
    # Empty when there is no HTTP request, which is every stdio call.
    header = get_http_headers().get(ROLE_HEADER)
    return header or os.environ.get(ROLE_ENV)


class RoleMiddleware(Middleware):
    """Refuses a tool call whose role is not in that tool's list."""

    def __init__(self, allowed: dict[str, frozenset[str]]) -> None:
        self._allowed = allowed

    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: Callable[..., Awaitable[Any]]
    ) -> Any:
        name = context.message.name
        roles = self._allowed.get(name)
        role = current_role()
        if roles is None or role not in roles:
            # Raised, not returned: a caller that reaches a tool it is not
            # allowed to see has a wiring bug, not a business outcome.
            raise ToolError(f"FORBIDDEN: role {role!r} may not call {name!r}")
        return await call_next(context)


class Server:
    """One MCP server: a FastMCP app, a role table, and the run command."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.mcp = FastMCP(name)
        self._allowed: dict[str, frozenset[str]] = {}
        self.mcp.add_middleware(RoleMiddleware(self._allowed))

        @self.tool(roles=ROLES, name="health")
        async def health() -> dict[str, Any]:
            """Liveness check: which server answered, and under which role."""
            return {"server": name, "role": current_role()}

    def tool(
        self, *, roles: Iterable[str], name: str | None = None
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Register an async function as a tool callable by *roles*.

        The function's signature and docstring become the tool's schema, so
        parameters are documented under ``Args:`` and nowhere else. Its return
        value is wrapped in the ``ok`` envelope; a :class:`ToolFailure` becomes
        the ``error`` envelope; anything else raised becomes a retryable
        ``INTERNAL`` error, logged here with the traceback.
        """
        unknown = set(roles) - ROLES
        if unknown:
            raise ValueError(f"Unknown roles {sorted(unknown)}; known: {sorted(ROLES)}")

        def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            tool_name = name or fn.__name__

            @functools.wraps(fn)
            async def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
                try:
                    return ok(await fn(*args, **kwargs))
                except ToolFailure as fail:
                    return failure(
                        fail.code, fail.message, retryable=fail.retryable, details=fail.details
                    )
                except Exception as error:  # noqa: BLE001 - the contract promises an envelope
                    logger.exception("Tool %s.%s failed", self.name, tool_name)
                    return failure(
                        "INTERNAL", f"{type(error).__name__}: {error}", retryable=True
                    )

            self._allowed[tool_name] = frozenset(roles)
            self.mcp.tool(name=tool_name)(wrapped)
            return fn

        return decorator

    def run(self, argv: Sequence[str] | None = None) -> None:
        """Serve. stdio by default, one subprocess per role (section 2);
        ``--transport http`` when several sessions share one server.

        Over stdio, stdout is the protocol channel: nothing in a server may
        print to it. Logging goes to stderr, which is where it goes by default.
        """
        parser = argparse.ArgumentParser(description=f"MCP server: {self.name}")
        parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8800)
        args = parser.parse_args(argv)

        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        if args.transport == "stdio":
            self.mcp.run(transport="stdio", show_banner=False)
        else:
            self.mcp.run(transport="http", host=args.host, port=args.port, show_banner=False)


# ── the database, for servers that keep rows ──────────────────────────────

_pool: AsyncConnectionPool | None = None
_pool_lock = asyncio.Lock()


async def database() -> AsyncConnectionPool:
    """This process's own small pool. Every process that shares the database
    draws from the same connection cap, so it stays at two."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            # Imported here: a server without rows never needs the settings.
            from ..api.settings import get_settings

            url, _ = get_settings().require_database_url()
            pool = AsyncConnectionPool(
                url,
                min_size=1,
                max_size=2,
                open=False,
                timeout=10,
                kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 10},
            )
            await pool.open()
            await pool.wait(timeout=12)
            _pool = pool
    return _pool


#: The advisory lock every server takes while it creates its tables.
SCHEMA_LOCK = 1510_0001


def apply_schema(sql: str) -> None:
    """Create or migrate a server's tables before it serves.

    Synchronous and at startup, not lazily on first use: the API may read a
    server's table before that server has had a reason to create it.
    """
    from ..api.settings import get_settings

    url, _ = get_settings().require_database_url()
    with psycopg.connect(url, autocommit=True) as conn:
        # Servers start together, one per role, and CREATE TABLE IF NOT
        # EXISTS is not atomic: without the lock two of them race on the same
        # type name and the loser dies. One at a time, then.
        conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
        try:
            conn.execute(sql)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))

"""One MCP client per role, and the tools it may see.

``docs/design.md`` section 6.2: four roles — advisor, harness, memory_writer,
admin — each with its own client, and the server checks the role on every
call. The role travels as an environment variable when the server is a
subprocess over stdio, and as a request header when the server is reached
over HTTP (several sessions sharing one server).

**Names.** The organisers name tools with a dot (``inventory.check``), and
the grader matches those names in the trace. A dot is refused by
OpenAI-compatible providers, so on the wire the dot is an underscore:
each server registers ``inventory_check``, and :func:`dotted` turns it back.
The client group prefixes every tool with its server's name
(``catalog_inventory_check``); :func:`tools_for` strips that prefix again, so
the model, ``config/lanes.yaml`` and the trace all see one spelling each.
Every organiser name has exactly one dot and no underscore before it, which
is what makes the round trip exact.

The ``langchain.mcp`` namespace is in beta and warns once per process on
import. The warning is silenced here and only here, with ``langchain`` pinned
in ``requirements.txt`` so the API cannot change underneath us; the day the
pin moves, this is the file to re-read.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import warnings
from contextlib import AsyncExitStack
from typing import Any

from langchain_core._api import LangChainBetaWarning

warnings.filterwarnings("ignore", category=LangChainBetaWarning)

from fastmcp import Client  # noqa: E402 - after the filter, on purpose
from fastmcp.client.group import ClientGroup  # noqa: E402
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport  # noqa: E402
from langchain.mcp import MCPAdapter  # noqa: E402
from langchain_core.tools import BaseTool  # noqa: E402

from ..config.config_manager import ROOT  # noqa: E402
from .server_base import ROLE_ENV, ROLE_HEADER, ROLES  # noqa: E402

logger = logging.getLogger(__name__)

#: Server name -> the module run as ``python -m <module>`` over stdio.
SERVERS: dict[str, str] = {
    "memory": "src.mcp.servers.memory",
    "catalog": "src.mcp.servers.catalog",
    "crm": "src.mcp.servers.crm",
    "order": "src.mcp.servers.order",
    "knowledge": "src.mcp.servers.knowledge",
}

#: Server name -> (environment variable naming its URL, default port) over HTTP.
HTTP_URLS: dict[str, tuple[str, int]] = {
    "memory": ("MCP_MEMORY_URL", 8801),
    "catalog": ("MCP_CATALOG_URL", 8802),
    "crm": ("MCP_CRM_URL", 8803),
    "order": ("MCP_ORDER_URL", 8804),
    "knowledge": ("MCP_KNOWLEDGE_URL", 8805),
}


def dotted(name: str) -> str:
    """The organisers' name of a wire name: ``inventory_check`` -> ``inventory.check``."""
    return name.replace("_", ".", 1)


def wire(name: str) -> str:
    """The wire name of an organisers' name: ``inventory.check`` -> ``inventory_check``."""
    return name.replace(".", "_", 1)


def transport_mode() -> str:
    """``stdio`` unless MCP_TRANSPORT says ``http``."""
    return os.environ.get("MCP_TRANSPORT", "stdio").lower()


def client_group(role: str, *, mode: str | None = None) -> ClientGroup:
    """A client for every server, all carrying *role*."""
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; known: {sorted(ROLES)}")
    mode = mode or transport_mode()

    clients: dict[str, Client] = {}
    for name, module in SERVERS.items():
        if mode == "stdio":
            transport = StdioTransport(
                command=sys.executable,
                args=["-m", module],
                # The child needs the whole environment (.env is loaded by
                # the settings, but keys may also come from the shell) plus
                # the one variable that names its role.
                env={**os.environ, ROLE_ENV: role},
                cwd=str(ROOT),
                # One subprocess for the life of this client, not one per
                # call. Each tool call opens a session over it.
                keep_alive=True,
            )
        elif mode == "http":
            variable, port = HTTP_URLS[name]
            url = os.environ.get(variable, f"http://127.0.0.1:{port}/mcp")
            transport = StreamableHttpTransport(url, headers={ROLE_HEADER: role})
        else:
            raise ValueError(f"MCP_TRANSPORT must be stdio or http, not {mode!r}")
        clients[name] = Client(transport)
    return ClientGroup(clients)


# Adapters are opened once per role and kept open for the life of the process:
# the tools they list call back through them, and over stdio the open adapter
# is what keeps the subprocess alive between calls.
_stack = AsyncExitStack()
_adapters: dict[str, MCPAdapter] = {}
_tool_names: dict[str, list[str]] = {}
_lock = asyncio.Lock()


def status() -> dict[str, dict[str, Any]]:
    """Which roles are connected and what they can call, for the health report."""
    return {
        role: {"status": "connected", "transport": transport_mode(), "tools": names}
        for role, names in _tool_names.items()
    }


async def tools_for(role: str) -> list[BaseTool]:
    """The LangChain tools *role* may call, connecting on first use."""
    async with _lock:
        adapter = _adapters.get(role)
        if adapter is None:
            adapter = await _stack.enter_async_context(MCPAdapter(client_group(role)))
            _adapters[role] = adapter
            logger.info("MCP client for role %r connected over %s", role, transport_mode())
    tools = [_unprefixed(tool) for tool in await adapter.list_tools()]
    # The health tool is the adapter's business, not the model's.
    tools = [tool for tool in tools if tool.name != "health"]
    _tool_names[role] = [t.name for t in tools]
    logger.info("MCP tools for role %r: %s", role, _tool_names[role])
    return tools


def _unprefixed(tool: BaseTool) -> BaseTool:
    """The tool under its server's own name, without the group's prefix.

    Safe to rename: the adapted tool routes its calls by the name it was
    listed under, captured when it was built, not by ``tool.name``.
    """
    for server in SERVERS:
        prefix = f"{server}_"
        if tool.name.startswith(prefix):
            tool.name = tool.name[len(prefix):]
            break
    return tool


async def close_all() -> None:
    """Disconnect every role's client. Called once, at shutdown."""
    async with _lock:
        _adapters.clear()
        _tool_names.clear()
        await _stack.aclose()

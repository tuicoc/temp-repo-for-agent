"""Binding MCP tools to an agent: by lane, with a guard around every call.

Two middleware, both straight from ``docs/design.md``, and both deliberately
*not* a tool class of our own — the framework's ``@tool`` and the MCP adapter
already produce the tools; what is ours is the policy around them.

- :class:`LaneToolsMiddleware`, section 4.3. The lane ``route`` chose decides
  which tools the model is offered on each call. The table is
  ``config/lanes.yaml``, a declaration rather than code, because the brief
  asks the team to present "when a tool is called and when it is not".
- :class:`ToolGuardMiddleware`, sections 4.4, 4.9 and 6.1. A timeout on every
  call (2 s, 3 s for knowledge), one retry when the server says the failure
  is retryable, a circuit breaker that skips a tool for a minute after it
  fails twice in a row. Around the call, the harness's two duties of section
  4.4: it fills in ``on`` (the day of the call) and ``customer_phone`` so
  the model never needs to see the number, and it removes every field whose
  name starts with ``_internal`` from the result before the model reads it.
  Business outcomes such as a price mismatch are ``ok: false`` too, but they
  are answers, not failures: they never count against the breaker.

Both are shared by every request that runs through one compiled agent, so
the only mutable state is the breaker's, and it is meant to be shared: a
server that is down is down for everyone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Iterable, Mapping

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

#: Error codes that mean the tool could not be reached or ran no business
#: logic. Only these count against the circuit breaker.
INFRASTRUCTURE_CODES = frozenset({"TIMEOUT", "TOOL_ERROR", "INTERNAL", "CIRCUIT_OPEN"})


def _tool_name(tool: Any) -> str | None:
    """The name of a bound tool, whether it is a BaseTool or a provider dict."""
    name = getattr(tool, "name", None)
    if name:
        return str(name)
    if isinstance(tool, dict):
        return tool.get("name") or (tool.get("function") or {}).get("name")
    return None


class LaneToolsMiddleware(AgentMiddleware):
    """Offers the model only the tools the run's lane allows."""

    def __init__(self, lanes: Mapping[str, frozenset[str]], mcp_tool_names: Iterable[str]) -> None:
        super().__init__()
        self._lanes = {lane: frozenset(names) for lane, names in lanes.items()}
        self._mcp = frozenset(mcp_tool_names)

    def _filtered(self, request: Any) -> Any:
        context = getattr(getattr(request, "runtime", None), "context", None)
        lane = getattr(context, "lane", None)
        allowed = self._lanes.get(lane)
        if allowed is None:
            # A lane the table does not know gets nothing rather than
            # everything: the safe reading of a missing row.
            if lane is not None:
                logger.warning("Lane %r is not in config/lanes.yaml; binding no tools", lane)
            allowed = frozenset()
        # Anything that is not an MCP tool — a structured-output tool, for
        # one — is left alone.
        tools = [
            tool
            for tool in request.tools
            if (name := _tool_name(tool)) not in self._mcp or name in allowed
        ]
        return request.override(tools=tools)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._filtered(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._filtered(request))


class ToolGuardMiddleware(AgentMiddleware):
    """Timeout, one retry, a circuit breaker, and the virtual clock."""

    #: Section 6.1: seconds per call, by tool; everything else gets DEFAULT_TIMEOUT.
    TIMEOUTS = {"kb_search": 3.0, "kb_upsert": 3.0}
    DEFAULT_TIMEOUT = 2.0

    def __init__(
        self,
        tool_names: Iterable[str],
        *,
        timeout: float | None = None,
        retries: int = 1,
        breaker_failures: int = 2,
        breaker_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        self._guarded = frozenset(tool_names)
        self._timeout = timeout
        self._retries = retries
        self._breaker_failures = breaker_failures
        self._breaker_seconds = breaker_seconds
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    # ── hooks ─────────────────────────────────────────────────────────────

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        name = call["name"]
        if name not in self._guarded:
            return await handler(request)
        if self._is_open(name):
            return self._envelope_message(
                call, "CIRCUIT_OPEN", f"{name} is paused after repeated failures", retryable=False
            )
        request = self._with_context(request)

        limit = self._timeout or self.TIMEOUTS.get(name, self.DEFAULT_TIMEOUT)
        attempt = 0
        while True:
            attempt += 1
            try:
                result = strip_internal(await asyncio.wait_for(handler(request), timeout=limit))
            except asyncio.TimeoutError:
                result = self._envelope_message(
                    call, "TIMEOUT", f"{name} did not answer within {limit:g}s", retryable=True
                )
            except Exception as error:  # noqa: BLE001 - reported to the model as data
                logger.exception("Tool %s raised", name)
                result = self._envelope_message(
                    call, "TOOL_ERROR", f"{type(error).__name__}: {error}", retryable=True
                )
            if self._settle(name, result, attempt):
                return with_args(result, request.tool_call.get("args") or {})

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        """The sync path, for scripts: same policy without the timeout."""
        call = request.tool_call
        name = call["name"]
        if name not in self._guarded:
            return handler(request)
        if self._is_open(name):
            return self._envelope_message(
                call, "CIRCUIT_OPEN", f"{name} is paused after repeated failures", retryable=False
            )
        request = self._with_context(request)

        attempt = 0
        while True:
            attempt += 1
            try:
                result = strip_internal(handler(request))
            except Exception as error:  # noqa: BLE001
                logger.exception("Tool %s raised", name)
                result = self._envelope_message(
                    call, "TOOL_ERROR", f"{type(error).__name__}: {error}", retryable=True
                )
            if self._settle(name, result, attempt):
                return result

    # ── policy ────────────────────────────────────────────────────────────

    def _settle(self, name: str, result: Any, attempt: int) -> bool:
        """Decide whether *result* is final. Updates the breaker."""
        envelope = envelope_of(result)
        if envelope is None or envelope.get("ok", True):
            self._failures[name] = 0
            return True
        error = envelope.get("error") or {}
        if error.get("retryable") and attempt <= self._retries:
            logger.info("Tool %s failed with %s; retrying once", name, error.get("code"))
            return False
        if error.get("code") in INFRASTRUCTURE_CODES:
            self._record_failure(name, error)
        return True

    def _is_open(self, name: str) -> bool:
        return self._open_until.get(name, 0.0) > time.monotonic()

    def _record_failure(self, name: str, error: Mapping[str, Any]) -> None:
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count >= self._breaker_failures:
            self._open_until[name] = time.monotonic() + self._breaker_seconds
            self._failures[name] = 0
            # docs/design.md section 4.9: repeated failure is what moves
            # route towards HANDOFF; the advisor step counts failures from
            # the tool results into the state's flags.
            logger.warning(
                "Circuit open for tool %s for %.0fs after %s: %s",
                name, self._breaker_seconds, error.get("code"), error.get("message"),
            )

    def _with_context(self, request: Any) -> Any:
        """Fill in what the run knows and the model should not have to.

        The day of the call goes into any tool that takes ``on``, the
        customer's phone into any that takes ``customer_phone`` (except the
        lookup, whose phone is the question), and the customer id into any
        that takes ``customer_id``. Each overrides whatever the model wrote.
        """
        context = getattr(getattr(request, "runtime", None), "context", None)
        tool = getattr(request, "tool", None)
        accepted = getattr(tool, "args", None)
        if context is None or not isinstance(accepted, dict):
            return request
        name = request.tool_call["name"]
        extra: dict[str, Any] = {}
        on = getattr(context, "on", None)
        if on and "on" in accepted:
            extra["on"] = on
        phone = getattr(context, "customer_phone", None)
        if phone and "customer_phone" in accepted and name != "crm_get_customer":
            extra["customer_phone"] = phone
        customer = getattr(context, "customer_id", None)
        if customer and "customer_id" in accepted:
            extra["customer_id"] = customer
        if not extra:
            return request
        call = request.tool_call
        return request.override(tool_call={**call, "args": {**call.get("args", {}), **extra}})

    @staticmethod
    def _envelope_message(
        call: Mapping[str, Any], code: str, message: str, *, retryable: bool
    ) -> ToolMessage:
        envelope = {"ok": False, "error": {"code": code, "retryable": retryable, "message": message}}
        return ToolMessage(
            content=json.dumps(envelope, ensure_ascii=False),
            tool_call_id=call["id"],
            name=call["name"],
        )


def with_args(result: Any, args: Mapping[str, Any]) -> Any:
    """The tool message, carrying the arguments the tool actually ran with.

    The model wrote some of them; the harness filled in the day and the
    phone. The trace records what ran (section 9.3), so it is kept here.
    """
    if not isinstance(result, ToolMessage):
        return result
    return result.model_copy(update={"additional_kwargs": {**result.additional_kwargs, "args": dict(args)}})


def without_internal(value: Any) -> Any:
    """*value* with every key starting with ``_internal`` removed, at any depth."""
    if isinstance(value, dict):
        return {k: without_internal(v) for k, v in value.items() if not str(k).startswith("_internal")}
    if isinstance(value, list):
        return [without_internal(v) for v in value]
    return value


def strip_internal(result: Any) -> Any:
    """A tool message whose envelope no longer carries internal fields.

    ``pricing.get_quote`` returns the price floor below which staff may not
    go; it is for the harness, never for the model (section 4.4).
    """
    envelope = envelope_of(result)
    if envelope is None:
        return result
    cleaned = without_internal(envelope)
    if cleaned == envelope:
        return result
    return result.model_copy(update={"content": json.dumps(cleaned, ensure_ascii=False)})


def envelope_of(result: Any) -> dict[str, Any] | None:
    """The ``{ok, ...}`` envelope inside a tool message, or None if there is none."""
    if not isinstance(result, ToolMessage):
        return None
    return parse_envelope(result.content)


def parse_envelope(content: Any) -> dict[str, Any] | None:
    """The envelope in a tool's raw content: a JSON string, or text blocks."""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) and "ok" in parsed else None


class ToolBox:
    """A role's tools, called by the harness directly rather than by a model.

    ``load_context`` looks the caller up, reads the ledger and re-checks
    prices through this (sections 4.2 and 6.2, role ``harness``); the
    ``after_call`` task writes the ledger through it (role
    ``memory_writer``). Every call answers with the ``{ok, data | error}``
    envelope, whatever went wrong, so a caller never needs a try block.
    """

    def __init__(self, tools: Iterable[Any], *, timeout: float = 3.0) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._timeout = timeout

    def has(self, name: str) -> bool:
        return name in self._tools

    async def call(self, name: str, /, **args: Any) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": {"code": "NO_TOOL", "retryable": False, "message": f"{name} is not available"}}
        try:
            raw = await asyncio.wait_for(tool.ainvoke({k: v for k, v in args.items() if v is not None}), timeout=self._timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "TIMEOUT", "retryable": True, "message": f"{name} took over {self._timeout:g}s"}}
        except Exception as error:  # noqa: BLE001 - reported as data, like the servers do
            logger.warning("Harness call %s failed: %s", name, error)
            return {"ok": False, "error": {"code": "TOOL_ERROR", "retryable": True, "message": f"{type(error).__name__}: {error}"}}
        envelope = parse_envelope(raw)
        if envelope is None:
            return {"ok": False, "error": {"code": "BAD_ENVELOPE", "retryable": False, "message": str(raw)[:200]}}
        return without_internal(envelope)

    async def data(self, name: str, /, **args: Any) -> Any:
        """The data of a successful call, or None."""
        envelope = await self.call(name, **args)
        return envelope.get("data") if envelope.get("ok") else None

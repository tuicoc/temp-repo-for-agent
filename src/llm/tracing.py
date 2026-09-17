"""Langfuse tracing.

``docs/flow.md`` section 2 puts Langfuse Cloud on the Hobby plan by default and
keeps a self-hosted profile for later: the self-hosted build wants six
containers and about 8 GB of RAM, too much for a demo laptop. Section 16 makes
the consequence explicit — the project's own Postgres tables are the source of
truth and Langfuse is a screen to look through, because Hobby keeps data for
30 days and allows two users.

Tracing is optional. With no keys set, :func:`handler` returns None and
everything runs exactly as before, so a teammate who has not signed up is never
blocked.

Two details that are easy to get wrong, both called out by the Langfuse
instrumentation guidance:

- **Import order.** The SDK reads its credentials when the client is first
  built, so it must not be imported before ``.env`` is loaded. Every import
  here is inside a function, and importing this module pulls in
  ``config_manager`` first, which is what loads ``.env``.
- **Flushing.** Traces are batched on a background thread, so a short script
  exits before they are sent. :func:`flush` must be called at the end of a run.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any

# Imported for the side effect: this is what loads .env, and it has to happen
# before the Langfuse client reads its credentials.
from ..config import config_manager  # noqa: F401

logger = logging.getLogger(__name__)

# Patterns redacted before anything leaves the machine. docs/flow.md section 16
# requires that traces carry only tokenised text; this is the backstop for when
# something slips through, not the tokeniser itself.
_PII_PATTERNS = (
    # Vietnamese mobile numbers, written locally or with the country code.
    re.compile(r"(?<!\d)(?:\+?84|0)\d{9}(?!\d)"),
    # Citizen identity numbers.
    re.compile(r"(?<!\d)\d{12}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
)


def mask(data: Any) -> Any:
    """Redact anything that looks like personal data, at any depth."""
    if isinstance(data, str):
        for pattern in _PII_PATTERNS:
            data = pattern.sub("[REDACTED]", data)
        return data
    if isinstance(data, dict):
        return {key: mask(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return type(data)(mask(item) for item in data)
    return data


def is_configured() -> bool:
    """Whether both Langfuse keys are present."""
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY")) and bool(
        os.environ.get("LANGFUSE_SECRET_KEY")
    )


@lru_cache(maxsize=1)
def client() -> Any | None:
    """The Langfuse client, built once, with masking enabled."""
    if not is_configured():
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning(
            "Langfuse keys are set but the package is missing. "
            "Run: pip install -r requirements.txt"
        )
        return None
    # Keys and base URL come from the environment, which .env has populated.
    return Langfuse(mask=mask)


@lru_cache(maxsize=1)
def handler() -> Any | None:
    """The LangChain callback handler, or None when tracing is off.

    Cached, because one handler serves the whole process and each one opens a
    background exporter.
    """
    if client() is None:
        logger.debug("Langfuse not configured; tracing disabled")
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def trace_metadata(
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the ``metadata`` dict LangChain passes through to Langfuse.

    The ``langfuse_`` prefixed keys are lifted onto the trace itself; anything
    else stays as metadata you can filter on.
    """
    metadata: dict[str, Any] = dict(extra)
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if user_id:
        metadata["langfuse_user_id"] = user_id
    if tags:
        metadata["langfuse_tags"] = tags
    return metadata


def auth_check() -> tuple[bool, str]:
    """Verify the credentials actually work.

    Worth calling at startup: the handler fails silently by design, so a wrong
    key otherwise shows up as traces that never arrive rather than as an error.
    """
    if not is_configured():
        return False, "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set"
    try:
        active = client()
        if active is None:
            return False, "langfuse package not installed"
        if active.auth_check():
            host = os.environ.get("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
            return True, f"authenticated against {host}"
        return False, "credentials rejected by the server"
    except Exception as error:  # noqa: BLE001 - reported to the caller
        return False, f"{type(error).__name__}: {error}"


def flush() -> None:
    """Send anything still buffered. Call this before a script exits."""
    active = client()
    if active is None:
        return
    try:
        active.flush()
    except Exception as error:  # noqa: BLE001 - never fail a run over telemetry
        logger.warning("Could not flush Langfuse: %s", error)

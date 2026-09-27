"""The web service.

The API only. The single-page app is deployed separately, so every browser
call is cross-origin and CORS has to be configured rather than avoided: the
allowed origins come from CORS_ORIGINS on the server, and they must be exact.
A wildcard will not do, because these requests carry an Authorization header
and browsers refuse "*" when credentials are involved.

Startup applies the database schema and seeds the single account, and is
allowed to fail loudly. An instance that answers requests without a database
would only fail later, further from the cause.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..components import voice as voice_component
from ..llm import tracing
from ..mcp import client as mcp_client
from . import admin, auth, calls, db, harness, voice
from .db import close_pool, diagnose_connection, init_checkpointer, init_db
from .settings import get_settings

VERSION = "0.0.0"
STARTED_AT = datetime.now(timezone.utc)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# Set when startup could not reach the database. The app still serves, so the
# problem can be asked about rather than guessed at from a container that will
# not stay up.
STARTUP_ERROR: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global STARTUP_ERROR
    try:
        await init_db()
        await init_checkpointer()
        logger.info("Database ready")
    except Exception as error:  # noqa: BLE001 - reported through /health
        STARTUP_ERROR = str(error)
        logger.error("Database unavailable at startup: %s", error)
        logger.error(
            "The app is serving anyway so that /health can be read. "
            "Every request needing the database will fail until this is fixed."
        )
    else:
        # Start the MCP servers and build the hot graph now, so the first
        # customer does not wait for them. A failure here is logged and
        # retried on the first request, where it is reported properly. Calls
        # that ended without being remembered are remembered now (section 2).
        try:
            await harness.ready()
            harness.spawn(harness.remember_unfinished())
        except Exception as error:  # noqa: BLE001
            logger.error("Warm-up failed, will retry on first request: %s", error)
    # Voice is made ready now, not in the first call, on every machine the
    # packages are on. In the background: the API is up at once.
    if not voice_component.status()["missing_packages"]:
        harness.spawn(_prepare_voice())
    yield
    # Traces are batched on a background thread; a worker that is recycled
    # without this loses its last batch.
    tracing.flush()
    await mcp_client.close_all()
    await close_pool()


async def _prepare_voice() -> None:
    """Download the weights this machine lacks (all of them on a new server,
    once, into VOICE_MODELS_DIR), then load the chosen models."""
    from ..components.voice import fetch

    started = time.perf_counter()
    try:
        await asyncio.to_thread(fetch.fetch_all)
        loaded = await voice.warm()
    except Exception:  # noqa: BLE001 - a call tries again, and says why it cannot
        logger.exception("Voice preparation failed")
        return
    logger.info("Voice ready in %.1f s: %s, %s", time.perf_counter() - started, loaded["asr"], loaded["tts"])


app = FastAPI(title="Agent Core", lifespan=lifespan)

settings = get_settings()


class StampArrival:
    """The moment a request reached the API: where TTFT starts
    (``eval/huong-dan-do-latency.md``, rule 1), before any routing or parsing.
    Plain ASGI, so it never buffers the SSE stream it sits in front of."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["arrived"] = time.perf_counter()
        await self.app(scope, receive, send)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
logger.info("Allowing browser calls from: %s", ", ".join(settings.allowed_origins))

app.add_middleware(StampArrival)

app.include_router(auth.router)
app.include_router(calls.router)
app.include_router(voice.router)
app.include_router(admin.router)


@app.get("/health")
async def health() -> dict[str, Any]:
    """What Azure polls, and what a person reads when something is wrong.

    Cheap when healthy. When the database could not be reached at startup it
    also reports where the connection string came from, the host, and the
    address that host resolves to — the three facts that separate a DNS problem
    from a routing problem from a credentials problem.
    """
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "status": "ok" if STARTUP_ERROR is None else "degraded",
        "version": VERSION,
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": int((now - STARTED_AT).total_seconds()),
    }
    if STARTUP_ERROR is not None:
        report.update(await diagnose_connection())
        report["startup_error"] = STARTUP_ERROR.splitlines()[0]
        return report

    # Each part that can fail on its own, reported on its own. None of these
    # calls a model; the report has to stay cheap enough to poll.
    report["components"] = {
        "database": await db.ping(),
        "checkpointer": {"status": "ok" if db.checkpointer_ready() else "not initialised"},
        "mcp": mcp_client.status() or {"status": "not connected"},
        "agent": harness.status(),
        "voice": voice_component.status(),
        "tracing": {"status": "on" if tracing.is_configured() else "off"},
    }
    report["sessions"] = await calls.session_counts()
    return report

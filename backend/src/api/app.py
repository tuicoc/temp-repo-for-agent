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

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, chat
from .db import close_pool, diagnose_connection, init_db
from .settings import get_settings

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
        init_db()
        logger.info("Database ready")
    except Exception as error:  # noqa: BLE001 - reported through /health
        STARTUP_ERROR = str(error)
        logger.error("Database unavailable at startup: %s", error)
        logger.error(
            "The app is serving anyway so that /health can be read. "
            "Every request needing the database will fail until this is fixed."
        )
    yield
    close_pool()


app = FastAPI(title="Agent Core", lifespan=lifespan)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
logger.info("Allowing browser calls from: %s", ", ".join(settings.allowed_origins))

app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health")
def health() -> dict[str, Any]:
    """What Azure polls, and what a person reads when something is wrong.

    Cheap when healthy. When the database could not be reached at startup it
    also reports where the connection string came from, the host, and the
    address that host resolves to — the three facts that separate a DNS problem
    from a routing problem from a credentials problem.
    """
    if STARTUP_ERROR is None:
        return {"status": "ok"}
    report = diagnose_connection()
    report["status"] = "degraded"
    report["startup_error"] = STARTUP_ERROR.splitlines()[0]
    return report

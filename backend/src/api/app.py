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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import auth, chat
from .db import close_pool, init_db
from .settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database ready")
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
def health() -> dict[str, str]:
    """What Azure polls. Cheap on purpose: no database, no model."""
    return {"status": "ok"}

"""Settings for the web service.

Read from the environment, the same way the rest of the project does. On Azure
these come from the app's environment variables rather than a file, which is
why nothing here falls back to a value that would work by accident: a missing
``JWT_SECRET`` in production must stop the app, not quietly sign tokens with a
default that anyone could guess.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Importing this loads .env once, before anything reads the environment.
from ..config.config_manager import ROOT  # noqa: F401


class WebSettings(BaseSettings):
    """Everything the HTTP layer needs."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Signing key for access tokens. No default: an app that signs with a
    # guessable secret is worse than one that refuses to start.
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12

    # The one account that exists. Registration is deliberately absent; see
    # src/api/auth.py.
    seed_user_email: str | None = None
    seed_user_password: str | None = None

    database_url: str | None = None

    # Where the frontend is served from. The two deployments are separate, so
    # every browser call is cross-origin and the list has to be right or the
    # browser silently refuses every request.
    #
    # Set CORS_ORIGINS on the server to a comma-separated list of exact
    # origins. A wildcard is not an option: credentials are sent with these
    # requests, and browsers reject "*" when they are.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_azure(self) -> bool:
        """Whether this process is running on Azure App Service."""
        return bool(os.environ.get("WEBSITE_SITE_NAME"))

    def require(self, field: str) -> str:
        value = getattr(self, field)
        if not value:
            raise RuntimeError(
                f"{field.upper()} is not set. On Azure add it under "
                f"Settings -> Environment variables; locally add it to .env."
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> WebSettings:
    return WebSettings()

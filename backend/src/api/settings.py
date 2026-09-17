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


# RFC 7518 section 3.2: an HS256 key must be at least as long as the hash it
# produces.
MIN_SECRET_BYTES = 32

# Where a Postgres connection string might be, in the order we trust it.
#
# DATABASE_URL is ours. The rest are what Azure injects, and it does not use
# our name: Service Connector writes AZURE_POSTGRESQL_CONNECTIONSTRING or the
# separate parts below it, while the older Connection strings blade prefixes
# whatever you called it with POSTGRESQLCONNSTR_. Reading all of them means
# connecting the database in the portal is enough, with nothing to copy across
# by hand and nothing to keep in step afterwards.
CONNECTION_STRING_VARS = (
    "DATABASE_URL",
    "AZURE_POSTGRESQL_CONNECTIONSTRING",
    "POSTGRESQL_CONNECTIONSTRING",
)

# The parts Service Connector writes when it does not write a whole string.
CONNECTION_PART_VARS = {
    "host": "AZURE_POSTGRESQL_HOST",
    "port": "AZURE_POSTGRESQL_PORT",
    "dbname": "AZURE_POSTGRESQL_DATABASE",
    "user": "AZURE_POSTGRESQL_USER",
    "password": "AZURE_POSTGRESQL_PASSWORD",
}


def _normalise(raw: str) -> str:
    """Make a connection string psycopg will accept.

    psycopg takes a postgresql:// URI or libpq keyword form as they are. What
    it will not take is a JDBC URL, which Azure offers alongside the others and
    which is easy to copy by mistake, so that prefix is stripped rather than
    left to fail with a confusing message.
    """
    value = raw.strip()
    if value.startswith("jdbc:"):
        value = value[len("jdbc:"):]
    return value


def resolve_database_url() -> tuple[str | None, str | None]:
    """Find the connection string. Returns (value, which variable it came from)."""
    for name in CONNECTION_STRING_VARS:
        if value := os.environ.get(name):
            return _normalise(value), name

    # Azure App Service exposes the older Connection strings blade with a
    # per-type prefix, and the suffix is whatever the entry was named.
    for name, value in os.environ.items():
        if name.startswith("POSTGRESQLCONNSTR_") and value:
            return _normalise(value), name

    parts = {
        key: os.environ[var]
        for key, var in CONNECTION_PART_VARS.items()
        if os.environ.get(var)
    }
    if {"host", "dbname", "user"} <= parts.keys():
        parts.setdefault("port", "5432")
        parts.setdefault("sslmode", "require")
        rendered = " ".join(f"{key}={value}" for key, value in parts.items())
        return rendered, "AZURE_POSTGRESQL_* parts"

    return None, None


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

    # Left unset here on purpose: resolve_database_url looks in several places,
    # because Azure does not use this name.
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

    def require_database_url(self) -> tuple[str, str]:
        """The connection string and the variable it came from, or an error
        naming every place that was searched."""
        value, source = resolve_database_url()
        if value:
            return value, source
        searched = ", ".join(
            (*CONNECTION_STRING_VARS, "POSTGRESQLCONNSTR_*", *CONNECTION_PART_VARS.values())
        )
        raise RuntimeError(
            "No PostgreSQL connection string found. Looked at: "
            + searched
            + ". On Azure, connecting the database under Settings -> Service "
            "Connector sets one of these for you; locally, put DATABASE_URL in "
            "backend/.env."
        )

    def require(self, field: str) -> str:
        if field == "database_url":
            return self.require_database_url()[0]

        value = getattr(self, field)
        if not value:
            raise RuntimeError(
                f"{field.upper()} is not set. On Azure add it under "
                f"Settings -> Environment variables; locally add it to .env."
            )
        if field == "jwt_secret" and len(value.encode()) < MIN_SECRET_BYTES:
            # PyJWT only warns about this. A short key is the whole security of
            # every session, so it is refused rather than logged.
            raise RuntimeError(
                f"JWT_SECRET is only {len(value.encode())} bytes. HS256 needs at "
                f"least {MIN_SECRET_BYTES}, or the signature is guessable. "
                f'Generate one: python -c "import secrets; '
                f'print(secrets.token_urlsafe(48))"'
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> WebSettings:
    return WebSettings()


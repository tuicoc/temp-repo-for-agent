"""The PII vault's rows. ``docs/design.md`` sections 4.1 and 5.3.

A call's tokens and the values behind them, encrypted with AES-GCM under a
key derived from the service secret. Loaded into a
:class:`~src.components.intake.pii.Vault` before a turn, the new entries
saved after it. The checkpoint, the transcript and the model only ever see
``<PHONE_1>``.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..components.intake.pii import Vault
from .db import connection
from .settings import get_settings


def _key() -> bytes:
    return hashlib.sha256(b"pii-vault:" + get_settings().require("jwt_secret").encode()).digest()


def identity_secret() -> str:
    """The secret keys are hashed with (section 4.2). Derived from the service
    secret until one of its own is configured."""
    return hashlib.sha256(b"identity:" + get_settings().require("jwt_secret").encode()).hexdigest()


def _seal(value: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, value.encode(), None)


def _open(blob: bytes) -> str:
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], None).decode()


async def load(call_id: int) -> Vault:
    async with connection() as conn:
        cursor = await conn.execute("SELECT token, kind, value_enc FROM pii_vault WHERE call_id = %s", (call_id,))
        rows = await cursor.fetchall()
    return Vault(entries={r["token"]: (r["kind"], _open(bytes(r["value_enc"]))) for r in rows})


async def save(call_id: int, vault: Vault, *, customer_id: str | None = None) -> None:
    """Write the entries added since the vault was loaded."""
    if not vault.added:
        return
    async with connection() as conn:
        for token in vault.added:
            kind, value = vault.entries[token]
            await conn.execute(
                "INSERT INTO pii_vault (call_id, token, kind, value_enc, customer_id) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (call_id, token) DO NOTHING",
                (call_id, token, kind, _seal(value), customer_id),
            )
    vault.added.clear()

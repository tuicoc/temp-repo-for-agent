"""Personal data: tokenised before a model or a trace sees it, restored after.

``docs/design.md`` sections 4.1 and 4.5. A phone number becomes
``<PHONE_1>``, an ID card number ``<CCCD_1>``, a bank account ``<BANK_1>``,
and the value goes into the call's :class:`Vault`. The model, Jev, Langfuse
and the checkpoint only ever see the token. :func:`detokenize` runs after
every guard has passed, and restores only this call's own tokens: a phone
number the customer gave may be read back to them; an ID card or account
number never is, only its last four digits (policies QT-04, PB-08).

The vault here is in memory, one per call. The API loads the call's rows
from the ``pii_vault`` table before a turn and saves what was added after
it, encrypted; the evaluation runner keeps it in memory. Deleting a
customer is deleting their vault rows.

Mock: addresses are not tokenised yet. An address is free text with no
reliable pattern; the design's ``<ADDR_1>`` waits for a better detector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Order matters: a 12-digit ID card before a 9-14 digit account, a phone before both.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PHONE", re.compile(r"(?<![\d<])(?:\+84|84)?0?(?:3|5|7|8|9)\d{8}(?!\d)")),
    ("CCCD", re.compile(r"(?<![\d<])0\d{11}(?!\d)")),
    ("BANK", re.compile(r"(?<![\d<])\d{9,14}(?!\d)")),
)
TOKEN = re.compile(r"<(PHONE|CCCD|BANK|ADDR)_(\d+)>")


def normalise_phone(raw: str) -> str | None:
    """Ten digits starting with 0, or None when *raw* is not a Vietnamese mobile."""
    digits = re.sub(r"[\s\-.()]", "", raw)
    if digits.startswith("+84"):
        digits = "0" + digits[3:]
    elif digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    elif len(digits) == 9:
        digits = "0" + digits
    return digits if re.fullmatch(r"0\d{9}", digits) else None


@dataclass
class Vault:
    """One call's tokens and the values behind them."""

    entries: dict[str, tuple[str, str]] = field(default_factory=dict)  # token -> (kind, value)
    #: Tokens added since the vault was loaded, for the caller to persist.
    added: list[str] = field(default_factory=list)

    def put(self, kind: str, value: str) -> str:
        for token, (known_kind, known) in self.entries.items():
            if known_kind == kind and known == value:
                return token
        index = 1 + sum(1 for k, _ in self.entries.values() if k == kind)
        token = f"<{kind}_{index}>"
        self.entries[token] = (kind, value)
        self.added.append(token)
        return token

    def get(self, token: str) -> str | None:
        entry = self.entries.get(token)
        return entry[1] if entry else None

    def values(self, kind: str) -> list[str]:
        return [value for k, value in self.entries.values() if k == kind]


def tokenise(text: str, vault: Vault) -> str:
    """*text* with personal data replaced by this call's tokens."""
    for kind, pattern in PATTERNS:
        def swap(match: re.Match[str], kind: str = kind) -> str:
            value = match.group(0)
            if kind == "PHONE":
                value = normalise_phone(value) or value
            return vault.put(kind, value)

        text = pattern.sub(swap, text)
    return text


def detokenize(text: str, vault: Vault, *, reveal_phone: bool = True) -> str:
    """Restore this call's tokens: phone numbers in full for the customer
    themselves, everything else (and phones, for staff screens) as the last
    four digits."""

    def swap(match: re.Match[str]) -> str:
        value = vault.get(match.group(0))
        if value is None:
            return match.group(0)
        if match.group(1) == "PHONE" and reveal_phone:
            return value
        return "****" + value[-4:]

    return TOKEN.sub(swap, text)


def unknown_tokens(text: str, vault: Vault) -> list[str]:
    """Tokens in *text* that are not this call's: a leak from somewhere else."""
    return [m.group(0) for m in TOKEN.finditer(text) if vault.get(m.group(0)) is None]


def mask(text: str) -> str:
    """For logs: long digit strings keep their last four digits only."""
    return re.sub(r"(?<!\d)\d{9,14}(?!\d)", lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)

"""Keys, tiers, and the one confirming question. ``docs/design.md`` section 4.2.

Keys come from the connection (the number a call came from, the Zalo or
Facebook identity of a chat) and from what the customer says (a phone
number). A key is hashed with a secret before any lookup, because ten digits
reverse from a plain hash in seconds; the last four digits are kept for
display. A customer id is not a phone number: a number is a household's key,
and one may point to two people.

| Tier | When | What follows |
|---|---|---|
| VERIFIED | a connection key matches exactly one customer, or a match was confirmed in the call | full brief |
| PROBABLE | a key the customer stated mid-call matches one customer | CONFIRM_IDENTITY: one question, no price, address or order code |
| AMBIGUOUS | a key matches two customers or more | no brief for anyone; CONFIRM_IDENTITY |
| UNKNOWN | no match | a new customer, lane NEW |

:func:`decide` is the table. The lookups themselves (``crm.get_customer`` and
``identity.find``) run in the pipeline, through the harness's tools.

:func:`confirms` and :func:`pick_by_name` are the judgements: does the answer
confirm what the question named, which of two people is this. Mock: word
lists and name matching; the Jev lab of 2026-09-23 scored Jev 100% on the
first, so it is the candidate once it is wired.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Literal, NamedTuple, Sequence

from ..intake.pii import normalise_phone
from ..intake.text import plain

Tier = Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
KeyType = Literal["phone", "zalo_id", "fb_id"]

PHONE_IN_TEXT = re.compile(r"(?<![\d<])(?:\+?84|0)\d{9}(?!\d)")

AFFIRMATION = re.compile(r"\b(đúng|phải|chuẩn|chính xác|vâng|ok|okay|ừ|ừm|dạ đúng|đúng rồi|chính nó|rồi)\b")
NEGATION = re.compile(r"\b(không|sai|nhầm|chưa|đâu có)\b")
#: A denial that contains an affirming word: "không phải", "không đúng".
DENIAL = re.compile(r"\b(không phải|không đúng|sai rồi|nhầm rồi|nhầm số|không có|chưa từng|chưa hề)\b")


class Key(NamedTuple):
    """One key. ``value`` is the raw value: it lives only in runtime context
    and the vault, never in the checkpointed state."""

    kind: KeyType
    value: str
    digest: str
    last4: str | None
    #: From the connection (caller id, channel identity) rather than the words.
    from_connection: bool


class Match(NamedTuple):
    customer_id: str
    name: str | None = None
    honorific: str | None = None
    phone: str | None = None
    #: "crm" for the organisers' seed, "ledger" for a customer met on a call.
    source: str = "crm"


def digest(kind: str, value: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:32]


def make_key(kind: KeyType, value: str, secret: str, *, from_connection: bool) -> Key:
    last4 = value[-4:] if kind == "phone" else None
    return Key(kind, value, digest(kind, value, secret), last4, from_connection)


def phones_in(text: str | None) -> list[str]:
    """Phone numbers the customer stated, normalised, in order, once each."""
    found: list[str] = []
    for match in PHONE_IN_TEXT.finditer(text or ""):
        phone = normalise_phone(match.group(0))
        if phone and phone not in found:
            found.append(phone)
    return found


def decide(matches: Sequence[Match], *, from_connection: bool) -> Tier:
    """The tier table, from the customers a key matched."""
    distinct = {m.customer_id for m in matches}
    if not distinct:
        return "UNKNOWN"
    if len(distinct) > 1:
        return "AMBIGUOUS"
    return "VERIFIED" if from_connection else "PROBABLE"


def confirms(answer: str) -> bool | None:
    """True when *answer* confirms, False when it denies, None when it says neither."""
    text = answer.lower()
    if DENIAL.search(text):
        return False
    yes = bool(AFFIRMATION.search(text))
    no = bool(NEGATION.search(text))
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


def pick_by_name(text: str, candidates: Sequence[Match]) -> Match | None:
    """The one candidate whose name the customer said, if exactly one."""
    words = set(re.findall(r"\w+", plain(text)))
    hits = [c for c in candidates if c.name and plain(c.name) in words]
    return hits[0] if len(hits) == 1 else None


def matches_from_crm(result: dict[str, Any]) -> list[Match]:
    """``crm.get_customer``'s answer as matches: none, one, or the candidates of a shared number."""
    if not result or not result.get("found"):
        return []
    if result.get("ambiguous"):
        return [
            Match(c["customer_id"], c.get("name"), c.get("honorific"), None, "crm")
            for c in result.get("candidates") or []
        ]
    return [Match(result["customer_id"], result.get("name"), result.get("honorific"), result.get("phone"), "crm")]

"""mcp-knowledge: what the shop's documents say. ``docs/design.md`` section 7.

Three sources in one store, each chunk under its own code:

- the organisers' policy corpus, ``policy/*.md``, one chunk per ``## [XX-nn]``
  section, read from the pack at startup;
- FAQ entries a consultant saved after a handoff (the Gap Loop, section 10.2);
- approved playbook entries (Reflection, section 10.3).

The last two are rows in ``kb_chunks``, written by ``kb.upsert`` under the
``admin`` role once a person has approved them.

Every chunk carries its document, a validity window taken from
``changelog.md``, and a ``restricted`` flag. A restricted chunk (the internal
purchasing note) is indexed and returned, so the harness knows the question
touched a forbidden topic and Recall@k is counted correctly, but its text is
withheld from every role except ``admin``: the advisor gets the code and an
instruction to refuse. A chunk no longer in force on the day of the call is
returned marked ``superseded``, because an order placed before the change is
still served by the old text (CL-01).

**Mock retrieval.** Section 7 specifies a Vietnamese embedding combined with
keyword search. Until the embedding is chosen this is keyword search alone:
BM25 over syllables and syllable pairs, diacritics removed.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from ...config.config_manager import btc_data_dir
from ..server_base import Server, ToolFailure, apply_schema, current_role, database

server = Server("knowledge")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('faq', 'playbook')),
    title       TEXT NOT NULL,
    text        TEXT NOT NULL,
    situation   TEXT,
    valid_from  DATE,
    valid_to    DATE,
    provenance  JSONB NOT NULL DEFAULT '{}',
    revoked     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

#: Documents whose text never reaches a customer (section 7, "bẫy tài liệu nội bộ").
RESTRICTED_DOCS = {"ghi-chu-nhap-hang-NOI-BO.md"}

#: Validity windows from changelog.md CL-01: the returns policy changed on 2026-10-01.
VALIDITY = {
    "chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md": (None, "2026-09-30"),
    "chinh-sach-doi-tra.md": ("2026-10-01", None),
}

HEADING = re.compile(r"^## \[([A-Z]+(?:-[A-Z]+)?-\d+)\]\s*(.*)$", re.MULTILINE)


@dataclass
class Chunk:
    chunk_id: str
    doc: str
    title: str
    text: str
    source: str = "policy"
    restricted: bool = False
    valid_from: str | None = None
    valid_to: str | None = None
    situation: str | None = None
    terms: Counter = field(default_factory=Counter)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _terms(text: str) -> Counter:
    words = re.findall(r"[a-z0-9]+", _plain(text))
    pairs = [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return Counter(words + pairs)


def _policy_chunks() -> list[Chunk]:
    folder = btc_data_dir() / "policy"
    chunks: list[Chunk] = []
    for path in sorted(folder.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        matches = list(HEADING.finditer(body))
        valid_from, valid_to = VALIDITY.get(path.name, (None, None))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            text = body[match.end():end].strip()
            chunks.append(Chunk(
                chunk_id=match.group(1),
                doc=path.name,
                title=match.group(2).strip(),
                text=text,
                restricted=path.name in RESTRICTED_DOCS,
                valid_from=valid_from,
                valid_to=valid_to,
                terms=_terms(f"{match.group(2)} {text}"),
            ))
    return chunks


_corpus: list[Chunk] | None = None


def corpus() -> list[Chunk]:
    global _corpus
    if _corpus is None:
        _corpus = _policy_chunks()
    return _corpus


async def _stored_chunks() -> list[Chunk]:
    pool = await database()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT chunk_id, source, title, text, situation, valid_from, valid_to "
            "FROM kb_chunks WHERE NOT revoked"
        )
        rows = await cursor.fetchall()
    return [
        Chunk(
            chunk_id=row["chunk_id"],
            doc=row["source"],
            title=row["title"],
            text=row["text"],
            source=row["source"],
            situation=row["situation"],
            valid_from=row["valid_from"].isoformat() if row["valid_from"] else None,
            valid_to=row["valid_to"].isoformat() if row["valid_to"] else None,
            terms=_terms(f"{row['title']} {row['text']}"),
        )
        for row in rows
    ]


def bm25(query: str, chunks: list[Chunk], *, k1: float = 1.4, b: float = 0.75) -> list[tuple[float, Chunk]]:
    """Okapi BM25 over the chunks' terms, best first."""
    wanted = _terms(query)
    if not wanted or not chunks:
        return []
    average = sum(sum(c.terms.values()) for c in chunks) / len(chunks)
    frequency = Counter(term for c in chunks for term in c.terms)
    n = len(chunks)
    scored = []
    for chunk in chunks:
        length = sum(chunk.terms.values())
        score = 0.0
        for term in wanted:
            tf = chunk.terms.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: -pair[0])
    return scored


def _in_force(chunk: Chunk, on: str | None) -> bool:
    if on is None:
        return True
    if chunk.valid_from and on < chunk.valid_from:
        return False
    if chunk.valid_to and on > chunk.valid_to:
        return False
    return True


@server.tool(roles={"advisor", "harness", "admin"}, name="kb_search")
async def kb_search(query: str, k: int = 3, on: str | None = None) -> dict[str, Any]:
    """Search the shop's policies, FAQ and playbook for what applies.

    Use for returns, exchanges, delivery, payment, warranty, promotion rules
    and product specifications. Each hit has a chunk_id to cite. A hit marked
    superseded is an old rule, only for orders placed before it changed. A
    hit marked restricted is internal: never reveal anything about it, say it
    is not information you can share.

    Args:
        query: The customer's question in their own words.
        k: How many passages to return, at most 8.
        on: The day of the call. Set by the system; leave it out.
    """
    chunks = corpus() + await _stored_chunks()
    ranked = bm25(query, chunks)[: max(1, min(k, 8))]
    reveal = current_role() == "admin"
    hits = []
    for score, chunk in ranked:
        hit: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "doc": chunk.doc,
            "source": chunk.source,
            "title": chunk.title,
            "score": round(score, 3),
            "superseded": not _in_force(chunk, on),
            "restricted": chunk.restricted,
        }
        hit["text"] = None if chunk.restricted and not reveal else chunk.text
        hits.append(hit)
    return {"hits": hits, "abstain": not hits}


@server.tool(roles={"admin"}, name="kb_upsert")
async def kb_upsert(
    source: Literal["faq", "playbook"],
    title: str,
    text: str,
    situation: str | None = None,
    chunk_id: str | None = None,
    provenance: dict[str, Any] | None = None,
    revoke: bool = False,
) -> dict[str, Any]:
    """Add, replace or revoke one FAQ or playbook entry, after a person approved it.

    Args:
        source: faq or playbook.
        title: The question, or the situation it handles.
        text: The answer, or the entry.
        situation: For a playbook entry, its situation from config/situations.yaml.
        chunk_id: Omit to add; give it to replace or revoke.
        provenance: call_id and turn of the answer, or the lesson ids behind an entry.
        revoke: True to switch the entry off.
    """
    if not text.strip():
        raise ToolFailure("BAD_REQUEST", "An entry needs text")
    chunk_id = chunk_id or f"{source.upper()}-{uuid.uuid4().hex[:8]}"
    pool = await database()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO kb_chunks (chunk_id, source, title, text, situation, provenance, revoked) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (chunk_id) DO UPDATE SET title = EXCLUDED.title, text = EXCLUDED.text, "
            "situation = EXCLUDED.situation, provenance = EXCLUDED.provenance, revoked = EXCLUDED.revoked",
            (chunk_id, source, title, text, situation, json.dumps(provenance or {}, ensure_ascii=False), revoke),
        )
    return {"chunk_id": chunk_id, "revoked": revoke}


if __name__ == "__main__":
    apply_schema(SCHEMA)
    server.run()

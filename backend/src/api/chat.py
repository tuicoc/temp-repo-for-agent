"""The chat endpoints.

One conversation is a list of messages and the advisor answers the newest one.
Replies stream back over Server-Sent Events.

Why SSE and not WebSockets, given that real-time voice may come later: the
brief's own list of ways to lose marks opens with spending weeks on real-time
voice, ``docs/flow.md`` Appendix A puts it among the things with no feature
flag, and section 2 specifies SSE for the turn endpoint. Voice would need a
bidirectional audio channel of its own — WebRTC, or a socket to a realtime
audio API — so it would not reuse this endpoint even if this endpoint were a
socket. Choosing WebSockets now would buy nothing and cost a setting on Azure
and a held connection on a single-core instance.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from ..agents.advisor import AdvisorAgent
from ..config.config_manager import get_models_config
from ..llm.callback_handler import text_of
from .auth import CurrentUser
from .db import connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# How much of a conversation is replayed to the model. The ledger and the Call
# Brief of docs/flow.md section 6 are what will carry older context; until they
# exist, a fixed window keeps a long conversation from growing the prompt
# without limit.
HISTORY_LIMIT = 20

# Shown while the model works. Section 8.4 only allows a filler on a turn that
# calls a tool, because a chat where every reply opens with "let me check"
# reads as fake. The advisor has no tools yet, so this is a neutral holding
# line rather than a claim to be looking something up.
FILLER = "Dạ anh/chị đợi em một chút ạ."


class ModelOption(BaseModel):
    id: str
    provider: str
    label: str


class Conversation(BaseModel):
    id: int
    title: str
    created_at: str


class Message(BaseModel):
    id: int
    role: str
    content: str
    model: str | None = None
    created_at: str


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    provider: str | None = None
    model: str | None = None


@lru_cache(maxsize=8)
def _agent(provider: str | None, model: str | None) -> AdvisorAgent:
    """One agent per model, built once.

    Compiling the graph costs real time, and the rate limiter it carries is
    shared per provider, so rebuilding per request would throw away the
    throttling state along with the work.
    """
    return AdvisorAgent(provider=provider, model=model)


@router.get("/models", response_model=list[ModelOption])
def list_models() -> list[ModelOption]:
    """Every model the chat page may switch to.

    Read from config/models.yaml, so the picker cannot offer something the
    server is not configured to reach.
    """
    config = get_models_config()
    return [
        ModelOption(id=model, provider=name, label=f"{block.label} · {model}")
        for name, block in config.providers.items()
        for model in block.models
    ]


@router.get("/conversations", response_model=list[Conversation])
def list_conversations(user: CurrentUser) -> list[Conversation]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations "
            "WHERE user_id = %s ORDER BY created_at DESC",
            (user.id,),
        ).fetchall()
    return [
        Conversation(id=r["id"], title=r["title"], created_at=r["created_at"].isoformat())
        for r in rows
    ]


@router.post("/conversations", response_model=Conversation, status_code=201)
def create_conversation(user: CurrentUser) -> Conversation:
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO conversations (user_id) VALUES (%s) "
            "RETURNING id, title, created_at",
            (user.id,),
        ).fetchone()
    return Conversation(
        id=row["id"], title=row["title"], created_at=row["created_at"].isoformat()
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: CurrentUser) -> None:
    with connection() as conn:
        deleted = conn.execute(
            "DELETE FROM conversations WHERE id = %s AND user_id = %s RETURNING id",
            (conversation_id, user.id),
        ).fetchone()
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


@router.get("/conversations/{conversation_id}/messages", response_model=list[Message])
def list_messages(conversation_id: int, user: CurrentUser) -> list[Message]:
    _own(conversation_id, user.id)
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, model, created_at FROM messages "
            "WHERE conversation_id = %s ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
    return [
        Message(
            id=r["id"],
            role=r["role"],
            content=r["content"],
            model=r["model"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: int, body: SendMessage, user: CurrentUser
) -> StreamingResponse:
    """Store the customer's turn and stream the advisor's reply."""
    _own(conversation_id, user.id)

    with connection() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
            (conversation_id, body.content),
        )
        # The first thing said names the conversation, so the sidebar is
        # readable without opening anything.
        conn.execute(
            "UPDATE conversations SET title = %s "
            "WHERE id = %s AND title = 'New conversation'",
            (body.content[:60], conversation_id),
        )

    history = _history(conversation_id)
    agent = _agent(body.provider, body.model)

    return StreamingResponse(
        _stream(agent, history, conversation_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Azure App Service sits behind a proxy that will otherwise buffer
            # the whole response and defeat the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


def _stream(
    agent: AdvisorAgent, history: list[Any], conversation_id: int
) -> Iterator[str]:
    """Yield SSE frames for one turn.

    Not a token stream, and that is the specification's choice rather than a
    shortcut. Section 8.4 of docs/flow.md points out that ``guard_hard`` has to
    see a complete sentence before it can check the numbers in it, so raw model
    output cannot go to the customer as it arrives. The filler line and the two
    latency figures in that section exist for exactly this reason.

    Streaming the draft here would also mean streaming JSON: the advisor is
    constrained to AdvisorDraft, so its tokens are the serialised object and
    not prose. Measured, not assumed.

    The wire format is therefore: a filler frame straight away so the page has
    something to show, then the finished reply, then done. When the guardrail
    arrives it slots in before the reply frame and nothing on the page changes.
    """
    started = time.perf_counter()
    yield _event("filler", {"text": FILLER})
    ttft = time.perf_counter() - started

    try:
        result = agent.invoke(history)
        draft = result["structured_response"]
    except Exception as error:  # noqa: BLE001 - the browser needs to hear about it
        logger.exception("Advisor failed on conversation %s", conversation_id)
        yield _event("error", {"message": f"{type(error).__name__}: {error}"})
        return

    reply = draft.reply.strip()
    ttft_content = time.perf_counter() - started

    if reply:
        with connection() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, model) "
                "VALUES (%s, 'assistant', %s, %s)",
                (conversation_id, reply, agent.model_name),
            )

    yield _event(
        "message",
        {
            "content": reply,
            "model": agent.model_name,
            "confidence": draft.confidence,
            "used_brief_lines": draft.used_brief_lines,
        },
    )
    # Both numbers, because reporting only the first would flatter the system:
    # one is when the page stopped looking frozen, the other is when the
    # customer could actually read an answer.
    yield _event(
        "done", {"ttft": round(ttft, 3), "ttft_content": round(ttft_content, 3)}
    )


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _history(conversation_id: int) -> list[Any]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = %s "
            "ORDER BY created_at DESC LIMIT %s",
            (conversation_id, HISTORY_LIMIT),
        ).fetchall()
    return [
        HumanMessage(content=r["content"])
        if r["role"] == "user"
        else AIMessage(content=r["content"])
        for r in reversed(rows)
    ]


def _own(conversation_id: int, user_id: int) -> None:
    """Refuse a conversation that is not this user's, as if it did not exist."""
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

"""The agent the lab talks to.

``backend``: the real product. The lab signs in with the seeded customer
account, places a web call, and sends each transcript to the same turn
endpoint the chat page uses. Voice is only a shell around that turn, which is
the architecture being tested. The backend must be running.

``echo``: repeats what it heard. For testing the voice path without spending
model quota.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ENV = Path(__file__).resolve().parents[2] / ".env"


@dataclass
class Reply:
    text: str
    seconds: float  # request to reply
    meta: dict[str, Any] = field(default_factory=dict)


class AgentError(RuntimeError):
    pass


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


BACKEND = "http://127.0.0.1:8000"


async def _sign_in(client: httpx.AsyncClient, account: str) -> None:
    """Sign *client* in with the seeded account whose env prefix is *account*."""
    env = _env()
    email, password = env.get(f"{account}_EMAIL"), env.get(f"{account}_PASSWORD")
    if not email or not password:
        raise AgentError(f"{account}_EMAIL and {account}_PASSWORD are not set in backend/.env")
    try:
        login = await client.post("/api/auth/login", json={"email": email, "password": password})
    except httpx.ConnectError as error:
        raise AgentError("The backend is not running on 127.0.0.1:8000") from error
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"


class Admin:
    """The backend's advisor switch, ``/api/admin/advisor``, which is staff only.

    The switch is the backend's own: it rebuilds the advisor for that process,
    so it also changes what the chat page talks to, and a restart of the
    backend returns to ``config/models.yaml``.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=BACKEND, timeout=httpx.Timeout(120, connect=5))
        self._signed_in = False

    async def _request(self, method: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._signed_in:
            await _sign_in(self._client, "SEED_USER")
            self._signed_in = True
        try:
            response = await self._client.request(method, "/api/admin/advisor", json=body)
        except httpx.ConnectError as error:
            self._signed_in = False
            raise AgentError("The backend is not running on 127.0.0.1:8000") from error
        if response.status_code == 401:
            self._signed_in = False
        if response.status_code != 200:
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise AgentError(f"{response.status_code}: {detail}")
        return response.json()

    async def current(self) -> dict[str, Any]:
        return await self._request("GET")

    async def switch(self, provider: str | None, model: str | None) -> dict[str, Any]:
        body = {"provider": provider, "model": model} if provider and model else {}
        return await self._request("POST", body)


admin = Admin()


class BackendAgent:
    name = "backend"

    def __init__(self, base_url: str = BACKEND) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(240, connect=5))
        self._call_id: int | None = None

    async def start(self) -> None:
        await _sign_in(self._client, "SEED_CUSTOMER")
        call = await self._client.post("/api/calls", json={"channel": "web"})
        call.raise_for_status()
        self._call_id = call.json()["id"]

    async def opening(self) -> Reply:
        return await self._turn(None)

    async def turn(self, text: str) -> Reply:
        return await self._turn(text)

    async def _turn(self, text: str | None) -> Reply:
        body: dict[str, Any] = {"turn_id": uuid.uuid4().hex}
        if text is not None:
            body["content"] = text
        started = time.perf_counter()
        event = None
        async with self._client.stream("POST", f"/api/calls/{self._call_id}/turn", json=body) as response:
            if response.status_code != 200:
                await response.aread()
                raise AgentError(f"{response.status_code}: {response.text[:200]}")
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event:
                    data = json.loads(line[5:])
                    if event == "message":
                        return Reply(data["content"], time.perf_counter() - started, data.get("meta") or {})
                    if event == "error":
                        raise AgentError(data.get("message", "The agent failed"))
                    if event == "waiting":
                        raise AgentError("The call is in copilot mode; a consultant answers")
        raise AgentError("The stream ended without a reply")

    async def end(self) -> None:
        if self._call_id is not None:
            try:
                await self._client.post(f"/api/calls/{self._call_id}/end")
            except httpx.HTTPError:
                pass
        await self._client.aclose()


class EchoAgent:
    name = "echo"

    async def start(self) -> None:
        return None

    async def opening(self) -> Reply:
        return Reply("Dạ em chào anh chị, em là trợ lý ảo. Anh chị cần em hỗ trợ gì ạ?", 0.0)

    async def turn(self, text: str) -> Reply:
        return Reply(f"Dạ, em nghe anh chị nói là: {text}. Anh chị nói tiếp đi ạ.", 0.0)

    async def end(self) -> None:
        return None


def agent(name: str) -> BackendAgent | EchoAgent:
    if name == "backend":
        return BackendAgent()
    if name == "echo":
        return EchoAgent()
    raise ValueError(f"Unknown agent {name!r}")

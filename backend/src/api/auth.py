"""Login, and the dependency that guards everything else.

Deliberately smaller than the reference project's auth. There is no
registration endpoint and no refresh-token rotation, because there is one
seeded account: the login page exists to keep a public URL from being a free
LLM bill, not to manage identities. Access tokens are bearer tokens with a
long expiry, held by the browser.

That is a real trade-off and worth naming. A bearer token in browser storage
is readable by any script on the page, which an HttpOnly refresh cookie is
not. It is acceptable while one known person logs in to a demo; it stops being
acceptable the moment real customers have accounts, and at that point the
reference project's refresh-cookie flow is the thing to port.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .db import connection, verify_password
from .settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    # A plain string, not EmailStr: that would pull in email-validator to
    # check the address of the one account we seeded ourselves. The browser
    # validates the shape.
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str


class User(BaseModel):
    id: int
    email: str
    # customer, consultant, qa or admin. Decides which screens exist, and
    # whose conversations may be read.
    role: str = "consultant"

    @property
    def is_staff(self) -> bool:
        return self.role != "customer"


def create_access_token(user: User) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_minutes
    )
    payload = {"sub": str(user.id), "email": user.email, "exp": expires}
    return jwt.encode(
        payload, settings.require("jwt_secret"), algorithm=settings.jwt_algorithm
    )


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User:
    """Resolve the caller, or refuse the request.

    Every failure answers 401 with the same wording. Saying which part was
    wrong tells an attacker which half to keep trying.
    """
    unauthorised = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorised

    user = await user_from_token(credentials.credentials)
    if user is None:
        raise unauthorised
    return user


async def user_from_token(token: str) -> User | None:
    """The user a bearer token names, or None. Shared with the voice
    WebSocket, where a browser cannot send an Authorization header."""
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.require("jwt_secret"),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id, email, role FROM users WHERE id = %s", (int(user_id),)
        )
        row = await cursor.fetchone()
    return User(**row) if row is not None else None


async def staff_user(user: Annotated[User, Depends(current_user)]) -> User:
    """The caller, provided they are staff. A customer gets 403."""
    if not user.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff only")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
StaffUser = Annotated[User, Depends(staff_user)]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    async with connection() as conn:
        cursor = await conn.execute(
            "SELECT id, email, role, password_hash FROM users WHERE email = %s",
            (body.email.strip().lower(),),
        )
        row = await cursor.fetchone()

    # The password is verified even when the account does not exist, so that a
    # wrong address and a wrong password take the same time to answer. bcrypt
    # is slow by design, so it runs in a thread rather than on the event loop
    # that every other request is waiting on.
    stored = row["password_hash"] if row else "$2b$12$" + "x" * 53
    verified = await asyncio.to_thread(verify_password, body.password, stored)
    if not verified or row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    user = User(id=row["id"], email=row["email"], role=row["role"])
    return LoginResponse(access_token=create_access_token(user), email=user.email)


@router.get("/me", response_model=User)
async def me(user: CurrentUser) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: CurrentUser) -> None:
    """Accepted so the client has something to call.

    Nothing is revoked server-side: with no token blacklist a bearer token
    stays valid until it expires, and the client dropping it is what ends the
    session. The reference project keeps a blacklist; that is the piece to
    bring over if a token ever needs killing before its expiry.
    """
    return None

"""Google OAuth 2.0 helper — httpx 기반, authlib 불필요."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from piloci.db.models import User

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "openid email profile"


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    resp.raise_for_status()
    return resp.json()


async def get_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    resp.raise_for_status()
    return resp.json()


async def upsert_google_user(db: AsyncSession, userinfo: dict[str, Any]) -> User:
    """구글 유저 정보로 DB upsert 후 User 반환."""
    from sqlalchemy import or_, select

    from piloci.db.models import User

    email: str = userinfo.get("email", "")
    sub: str = userinfo.get("sub", "")
    name: str = userinfo.get("name") or userinfo.get("email", "")

    result = await db.execute(
        select(User).where(
            or_(
                (User.oauth_provider == "google") & (User.oauth_sub == sub),
                User.email == email,
            )
        )
    )
    user: User | None = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            email_verified=True,
            name=name,
            oauth_provider="google",
            oauth_sub=sub,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        # 기존 로컬 계정이면 google 연결
        if user.oauth_sub is None:
            user.oauth_provider = "google"
            user.oauth_sub = sub
            user.email_verified = True
        if not user.name:
            user.name = name
        user.last_login_at = now

    await db.commit()
    await db.refresh(user)
    return user


def generate_state() -> str:
    return secrets.token_urlsafe(32)

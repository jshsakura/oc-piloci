"""OAuth 2.0 helpers for configured third-party providers."""

from __future__ import annotations

import base64
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, cast
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from piloci.config import Settings
    from piloci.db.models import User

from piloci.auth.crypto import encrypt_token

logger = logging.getLogger(__name__)

NormalizedUserInfo = dict[str, str]
UserExtractor = Callable[[dict[str, Any]], NormalizedUserInfo]


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    auth_url: str
    token_url: str
    userinfo_url: str
    scopes: str
    extra_auth_params: dict[str, str] = field(default_factory=dict)
    userinfo_headers: dict[str, str] = field(default_factory=dict)
    extract_user: UserExtractor = field(default=lambda payload: _normalize_userinfo(payload))


def _normalize_userinfo(payload: dict[str, Any]) -> NormalizedUserInfo:
    email = payload.get("email")
    sub = payload.get("sub")
    name = payload.get("name")
    return {
        "email": str(email or ""),
        "sub": str(sub or ""),
        "name": str(name or email or ""),
    }


def _extract_google_user(payload: dict[str, Any]) -> NormalizedUserInfo:
    return _normalize_userinfo(payload)


def _extract_github_user(payload: dict[str, Any]) -> NormalizedUserInfo:
    email = payload.get("email")
    name = payload.get("name") or payload.get("login") or email
    return {
        "email": str(email or ""),
        "sub": str(payload.get("id") or ""),
        "name": str(name or ""),
    }


def _extract_kakao_user(payload: dict[str, Any]) -> NormalizedUserInfo:
    kakao_account = payload.get("kakao_account")
    kakao_profile = kakao_account.get("profile") if isinstance(kakao_account, dict) else {}
    email = kakao_account.get("email") if isinstance(kakao_account, dict) else None
    name = kakao_profile.get("nickname") if isinstance(kakao_profile, dict) else email
    return {
        "email": str(email or ""),
        "sub": str(payload.get("id") or ""),
        "name": str(name or email or ""),
    }


def _extract_naver_user(payload: dict[str, Any]) -> NormalizedUserInfo:
    response = payload.get("response")
    response_data = response if isinstance(response, dict) else {}
    email = response_data.get("email")
    name = response_data.get("nickname") or email
    return {
        "email": str(email or ""),
        "sub": str(response_data.get("id") or ""),
        "name": str(name or ""),
    }


PROVIDERS: dict[str, ProviderConfig] = {
    "google": ProviderConfig(
        name="google",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
        scopes="openid email profile",
        extra_auth_params={"access_type": "online", "prompt": "select_account"},
        extract_user=_extract_google_user,
    ),
    "github": ProviderConfig(
        name="github",
        auth_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scopes="user:email",
        userinfo_headers={"Accept": "application/vnd.github+json"},
        extract_user=_extract_github_user,
    ),
    "kakao": ProviderConfig(
        name="kakao",
        auth_url="https://kauth.kakao.com/oauth/authorize",
        token_url="https://kauth.kakao.com/oauth/token",
        userinfo_url="https://kapi.kakao.com/v2/user/me",
        scopes="profile_nickname account_email",
        extract_user=_extract_kakao_user,
    ),
    "naver": ProviderConfig(
        name="naver",
        auth_url="https://nid.naver.com/oauth2.0/authorize",
        token_url="https://nid.naver.com/oauth2.0/token",
        userinfo_url="https://openapi.naver.com/v1/nid/me",
        scopes="",
        extract_user=_extract_naver_user,
    ),
}


def _get_provider(provider: str) -> ProviderConfig:
    provider_config = PROVIDERS.get(provider)
    if provider_config is None:
        raise ValueError(f"Unknown OAuth provider: {provider}")
    return provider_config


def build_auth_url(provider: str, client_id: str, redirect_uri: str, state: str) -> str:
    provider_config = _get_provider(provider)
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if provider_config.scopes:
        params["scope"] = provider_config.scopes
    params.update(provider_config.extra_auth_params)
    return f"{provider_config.auth_url}?{urlencode(params)}"


async def exchange_code(
    provider: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    provider_config = _get_provider(provider)
    headers = {"Accept": "application/json"} if provider == "github" else None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            provider_config.token_url,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers=headers,
        )
    resp.raise_for_status()
    return cast(dict[str, Any], resp.json())


async def get_userinfo(provider: str, access_token: str) -> NormalizedUserInfo:
    provider_config = _get_provider(provider)
    headers = {
        "Authorization": f"Bearer {access_token}",
        **provider_config.userinfo_headers,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(provider_config.userinfo_url, headers=headers)
    resp.raise_for_status()
    payload = cast(dict[str, Any], resp.json())
    return provider_config.extract_user(payload)


async def upsert_oauth_user(
    db: AsyncSession,
    provider: str,
    userinfo: NormalizedUserInfo,
    settings: Settings | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> User:
    from sqlalchemy import func, or_, select

    from piloci.config import get_settings
    from piloci.db.models import User

    _get_provider(provider)
    effective_settings = settings or get_settings()

    email = userinfo.get("email", "")
    sub = userinfo.get("sub", "")
    name = userinfo.get("name") or email
    encrypted_access_token = (
        encrypt_token(access_token, effective_settings) if access_token else None
    )
    encrypted_refresh_token = (
        encrypt_token(refresh_token, effective_settings) if refresh_token else None
    )

    result = await db.execute(
        select(User).where(
            or_(
                (User.oauth_provider == provider) & (User.oauth_sub == sub),
                User.email == email,
            )
        )
    )
    user: User | None = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if user is None:
        user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
        is_first_user = user_count == 0

        user = User(
            id=str(uuid.uuid4()),
            email=email,
            email_verified=True,
            name=name,
            oauth_provider=provider,
            oauth_sub=sub,
            oauth_access_token=encrypted_access_token,
            oauth_refresh_token=encrypted_refresh_token,
            created_at=now,
            last_login_at=now,
            approval_status="approved" if is_first_user else "pending",
            is_admin=is_first_user,
        )
        db.add(user)
    else:
        if user.oauth_sub is None:
            user.oauth_provider = provider
            user.oauth_sub = sub
            user.email_verified = True
        if not user.name:
            user.name = name
        user.oauth_access_token = encrypted_access_token
        user.oauth_refresh_token = encrypted_refresh_token
        user.last_login_at = now

    await db.commit()
    await db.refresh(user)
    return user


async def revoke_provider_token(
    provider: str, access_token: str, client_id: str, client_secret: str
) -> bool:
    _get_provider(provider)

    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "naver":
                response = await client.post(
                    "https://nid.naver.com/oauth2.0/token",
                    data={
                        "grant_type": "delete",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "access_token": access_token,
                        "service_provider": "NAVER",
                    },
                )
            elif provider == "google":
                response = await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": access_token},
                )
            elif provider == "github":
                response = await client.request(
                    "DELETE",
                    f"https://api.github.com/applications/{client_id}/grant",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Basic {basic_auth}",
                    },
                    json={"access_token": access_token},
                )
            elif provider == "kakao":
                response = await client.post(
                    "https://kapi.kakao.com/v1/user/unlink",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            else:
                return False
    except httpx.HTTPError:
        logger.warning("OAuth token revoke request failed for provider=%s", provider, exc_info=True)
        return False

    if response.status_code in {200, 204}:
        return True

    logger.warning(
        "OAuth token revoke failed for provider=%s status=%s body=%s",
        provider,
        response.status_code,
        response.text,
    )
    return False


def get_provider_credentials(settings: Settings, provider: str) -> tuple[str, str] | None:
    _get_provider(provider)
    client_id = getattr(settings, f"{provider}_client_id", None)
    client_secret = getattr(settings, f"{provider}_client_secret", None)
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def generate_state() -> str:
    return secrets.token_urlsafe(32)

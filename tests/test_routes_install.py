"""Tests for /install/{code} and the install_code injection into token creation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from starlette.requests import Request


def _make_request(
    *,
    method: str = "GET",
    path: str = "/",
    path_params: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    user: dict[str, object] | None = None,
) -> Request:
    state: dict[str, object] = {}
    scope: dict[str, object] = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "state": state,
        "path_params": path_params or {},
        "app": SimpleNamespace(state=SimpleNamespace()),
        "scheme": "https",
        "server": ("testserver", 443),
    }
    if user is not None:
        state["user"] = user
    payload = orjson.dumps(body or {})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


@pytest.fixture
def fake_pairing_store(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace get_install_pairing_store with a fake whose state is observable."""
    store = MagicMock()
    store.create = AsyncMock(return_value="CODE-XYZ")
    store.consume = AsyncMock()
    monkeypatch.setattr(
        "piloci.auth.install_pairing.get_install_pairing_store",
        lambda _settings: store,
    )
    return store


@pytest.mark.asyncio
async def test_install_route_returns_bash_with_token(fake_pairing_store: MagicMock) -> None:
    fake_pairing_store.consume.return_value = {
        "token": "jwt.fake.token",
        "base_url": "https://piloci.example.com",
    }

    from piloci.api.routes import route_install

    response = await route_install(_make_request(path_params={"code": "CODE-XYZ"}))

    assert response.status_code == 200
    assert response.media_type == "text/x-shellscript"
    body = response.body.decode()
    assert body.startswith("#!/usr/bin/env bash")
    assert "jwt.fake.token" in body
    assert "https://piloci.example.com" in body
    fake_pairing_store.consume.assert_awaited_once_with("CODE-XYZ")


@pytest.mark.asyncio
async def test_install_route_returns_410_when_code_already_consumed(
    fake_pairing_store: MagicMock,
) -> None:
    fake_pairing_store.consume.return_value = None

    from piloci.api.routes import route_install

    response = await route_install(_make_request(path_params={"code": "STALE"}))

    assert response.status_code == 410
    body = response.body.decode()
    assert body.startswith("#!/usr/bin/env bash")
    # No token leaks in the failure body.
    assert "jwt." not in body


@pytest.mark.asyncio
async def test_install_route_rejects_blank_or_oversized_code(
    fake_pairing_store: MagicMock,
) -> None:
    from piloci.api.routes import route_install

    blank = await route_install(_make_request(path_params={"code": "   "}))
    assert blank.status_code == 400
    fake_pairing_store.consume.assert_not_awaited()

    oversized = await route_install(_make_request(path_params={"code": "x" * 65}))
    assert oversized.status_code == 400


@pytest.mark.asyncio
async def test_install_route_rejects_whitespace_in_code(
    fake_pairing_store: MagicMock,
) -> None:
    from piloci.api.routes import route_install

    bad = await route_install(_make_request(path_params={"code": "abc def"}))
    assert bad.status_code == 400
    fake_pairing_store.consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_hook_stop_script_route_requires_auth() -> None:
    from piloci.api.routes import route_hook_stop_script

    unauth = await route_hook_stop_script(_make_request(path="/api/hook/stop-script"))
    assert unauth.status_code == 401


@pytest.mark.asyncio
async def test_hook_stop_script_route_returns_generic_template() -> None:
    from piloci.api.routes import route_hook_stop_script

    response = await route_hook_stop_script(
        _make_request(
            path="/api/hook/stop-script",
            user={"user_id": "u1", "email": "u@example.com"},
        )
    )
    assert response.status_code == 200
    assert response.media_type == "text/x-shellscript"
    body = response.body.decode()
    assert body.startswith("#!/usr/bin/env bash")
    # The template must not embed any token. "Bearer {token}" is the runtime
    # header format so the literal string is fine; what must NOT appear is a
    # concrete credential.
    assert "jwt." not in body
    # It must read the token from config.json instead.
    assert "config.json" in body

from __future__ import annotations

from typing import cast

import pytest
from mcp.server.lowlevel import Server
from starlette.testclient import TestClient

from piloci.mcp.streamable_http import create_streamable_http_app


class _DummyServer:
    async def run(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("run() must not be called when auth fails")

    def create_initialization_options(self):
        return {}


def test_streamable_http_missing_authorization_returns_401() -> None:
    app = create_streamable_http_app(cast(Server, cast(object, _DummyServer())))
    with TestClient(app) as client:
        response = client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401
    assert response.headers.get("www-authenticate", "").startswith("Bearer")


def test_streamable_http_non_bearer_authorization_returns_401() -> None:
    app = create_streamable_http_app(cast(Server, cast(object, _DummyServer())))
    with TestClient(app) as client:
        response = client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Authorization": "Basic xyz"},
        )
    assert response.status_code == 401


def test_streamable_http_invalid_bearer_token_returns_401() -> None:
    app = create_streamable_http_app(cast(Server, cast(object, _DummyServer())))
    with TestClient(app) as client:
        response = client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert response.status_code == 401


@pytest.mark.skip(
    reason=(
        "Mock receive() returns lifespan.startup forever; the app legitimately "
        "responds with startup.complete and waits for a shutdown that never "
        "arrives, hanging the test. Fix by yielding shutdown after startup, "
        "or rewrite the assertion against the real ASGI lifespan contract."
    )
)
@pytest.mark.asyncio
async def test_streamable_http_ignores_non_http_scope() -> None:
    """Non-HTTP scope returns immediately without raising."""
    app = create_streamable_http_app(cast(Server, cast(object, _DummyServer())))

    async def receive():  # pragma: no cover
        return {"type": "lifespan.startup"}

    sent: list = []

    async def send(message):
        sent.append(message)

    await app({"type": "lifespan", "headers": []}, receive, send)
    assert sent == []

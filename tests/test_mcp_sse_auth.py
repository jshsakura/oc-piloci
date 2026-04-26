from __future__ import annotations

from typing import cast

from mcp.server.lowlevel import Server
from starlette.testclient import TestClient

from piloci.mcp.sse import create_sse_app


class _DummyServer:
    async def run(
        self, *args, **kwargs
    ):  # pragma: no cover - should not be reached in auth failures
        raise AssertionError("run() should not be called for unauthorized SSE requests")

    def create_initialization_options(self):
        return {}


def test_mcp_sse_requires_bearer_header() -> None:
    app = create_sse_app(cast(Server, cast(object, _DummyServer())))

    with TestClient(app) as client:
        response = client.get("/sse")

    assert response.status_code == 401
    assert response.text == "Unauthorized"


def test_mcp_sse_rejects_invalid_bearer_token() -> None:
    app = create_sse_app(cast(Server, cast(object, _DummyServer())))

    with TestClient(app) as client:
        response = client.get("/sse", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
    assert response.text == "Unauthorized"

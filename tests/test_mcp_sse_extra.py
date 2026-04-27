from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from piloci.mcp.sse import create_sse_app


def test_healthz_endpoint():
    mock_server = MagicMock()
    app = create_sse_app(mock_server, debug=True, prefix="/mcp")
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

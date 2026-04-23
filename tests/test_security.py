from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from piloci.api.security import SecurityHeadersMiddleware

_REQUIRED_HEADERS = [
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Strict-Transport-Security",
    "Content-Security-Policy",
]


def _homepage(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _make_app() -> Starlette:
    app = Starlette(routes=[Route("/", _homepage), Route("/healthz", _homepage)])
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_make_app())


def test_all_security_headers_present(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    for header in _REQUIRED_HEADERS:
        assert header in response.headers, f"Missing header: {header}"


def test_x_content_type_options_value(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_x_frame_options_value(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"


def test_referrer_policy_value(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_permissions_policy_value(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"


def test_hsts_value(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_csp_value(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["Content-Security-Policy"] == "default-src 'self'; script-src 'self'"


def test_healthz_also_has_security_headers(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    for header in _REQUIRED_HEADERS:
        assert header in response.headers, f"Missing header on /healthz: {header}"

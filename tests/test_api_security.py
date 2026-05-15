from __future__ import annotations

import orjson
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from piloci.api.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    delete_csrf_cookie,
    set_csrf_cookie,
)


async def _post_endpoint(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _build_app() -> Starlette:
    return Starlette(
        routes=[Route("/unsafe", _post_endpoint, methods=["POST"])],
        middleware=[Middleware(CSRFMiddleware)],
    )


def test_csrf_rejects_cookie_authenticated_post_without_header() -> None:
    with TestClient(_build_app()) as client:
        response = client.post("/unsafe", cookies={"piloci_session": "session-id"})

    assert response.status_code == 403
    assert orjson.loads(response.content) == {"error": "CSRF validation failed"}


def test_csrf_allows_matching_double_submit_token() -> None:
    token = "csrf-token"

    with TestClient(_build_app()) as client:
        response = client.post(
            "/unsafe",
            cookies={"piloci_session": "session-id", CSRF_COOKIE_NAME: token},
            headers={CSRF_HEADER_NAME: token},
        )

    assert response.status_code == 200
    assert response.text == "ok"


def test_csrf_skips_bearer_authenticated_post() -> None:
    with TestClient(_build_app()) as client:
        response = client.post(
            "/unsafe",
            cookies={"piloci_session": "session-id"},
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 200


def test_csrf_cookie_helpers_set_and_delete_browser_readable_cookie() -> None:
    response = Response()

    set_csrf_cookie(response, "token", secure=True, max_age=60)

    cookie = response.headers["set-cookie"]
    assert f"{CSRF_COOKIE_NAME}=token" in cookie
    assert "HttpOnly" not in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie

    delete_response = Response()
    delete_csrf_cookie(delete_response)
    assert f"{CSRF_COOKIE_NAME}=" in delete_response.headers["set-cookie"]

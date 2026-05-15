from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: https:",
        "connect-src 'self' https: wss:",
    ]
)


_API_ONLY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": _CSP,
}

_STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_COOKIE_NAME = "piloci_csrf"
CSRF_HEADER_NAME = "x-csrf-token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str, *, secure: bool, max_age: int) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=False,
        samesite="lax",
        secure=secure,
        max_age=max_age,
        path="/",
    )


def delete_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        path = request.url.path
        is_api = path.startswith("/api/") or path in ("/healthz", "/readyz", "/profilez")
        for header, value in _STATIC_HEADERS.items():
            response.headers[header] = value
        if is_api:
            for header, value in _API_ONLY_HEADERS.items():
                response.headers[header] = value
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF check for cookie-authenticated unsafe requests."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._requires_check(request):
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
            header_token = request.headers.get(CSRF_HEADER_NAME)
            if (
                not cookie_token
                or not header_token
                or not secrets.compare_digest(cookie_token, header_token)
            ):
                return JSONResponse({"error": "CSRF validation failed"}, status_code=403)
        return await call_next(request)

    @staticmethod
    def _requires_check(request: Request) -> bool:
        if request.method.upper() in _SAFE_METHODS:
            return False
        if not request.cookies.get("piloci_session"):
            return False
        auth_header = request.headers.get("Authorization", "")
        return not auth_header.startswith("Bearer ")

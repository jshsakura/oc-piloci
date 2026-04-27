from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
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

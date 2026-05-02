from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Rate limit constants
RATE_LOGIN = "10/minute"
RATE_SIGNUP = "3/minute"
RATE_PASSWORD_RESET = "3/hour"
RATE_MCP_SSE = "60/minute"
RATE_MCP_TOOL = "100/minute"
RATE_DATA_IO = "6/hour"

limiter = Limiter(key_func=get_remote_address)


def setup_ratelimit(app) -> None:
    """Register slowapi state and exception handler on the given app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

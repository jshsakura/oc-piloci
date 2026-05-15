from __future__ import annotations

import os

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
RATE_DEVICE = "20/minute"
RATE_MUTATION = "60/minute"
RATE_CHAT = "30/minute"
RATE_INGEST = "30/minute"
RATE_ADMIN = "30/minute"

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("REDIS_URL") or os.environ.get("PILOCI_REDIS_URL") or "memory://",
    in_memory_fallback_enabled=True,
)


def setup_ratelimit(app) -> None:
    """Register slowapi state and exception handler on the given app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

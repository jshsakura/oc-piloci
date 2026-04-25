from __future__ import annotations

import logging
import resource
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import orjson
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_WINDOW_SIZE = 200


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            data.update(extra)
        return orjson.dumps(data).decode()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 2)
    rank = max(0, min(len(values) - 1, int(round((len(values) - 1) * percentile))))
    return round(values[rank], 2)


class RuntimeProfiler:
    def __init__(self, window_size: int = _WINDOW_SIZE) -> None:
        self._window_size = window_size
        self._samples: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def observe(self, name: str, duration_ms: float) -> None:
        rounded = round(duration_ms, 2)
        with self._lock:
            bucket = self._samples.get(name)
            if bucket is None:
                bucket = deque(maxlen=self._window_size)
                self._samples[name] = bucket
            bucket.append(rounded)

    @contextmanager
    def track(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, (time.perf_counter() - start) * 1000)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            metrics = {
                name: self._summarize(list(samples))
                for name, samples in sorted(self._samples.items())
            }
            last_updated = datetime.now(timezone.utc).isoformat() if self._samples else None
        return {
            "rss_mb": _rss_mb(),
            "window_size": self._window_size,
            "updated_at": last_updated,
            "metrics": metrics,
        }

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()

    @staticmethod
    def _summarize(samples: list[float]) -> dict[str, float | int]:
        ordered = sorted(samples)
        return {
            "count": len(ordered),
            "last_ms": ordered[-1],
            "avg_ms": round(sum(ordered) / len(ordered), 2),
            "p50_ms": _percentile(ordered, 0.50),
            "p95_ms": _percentile(ordered, 0.95),
            "max_ms": round(max(ordered), 2),
        }


_SKIP_PROFILE_PATHS = frozenset({"/healthz", "/readyz", "/profilez"})


class RuntimeProfilingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path not in _SKIP_PROFILE_PATHS:
            duration_ms = (time.perf_counter() - start) * 1000
            get_runtime_profiler().observe(f"http {request.method} {request.url.path}", duration_ms)
        return response


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss_kb = usage.ru_maxrss
    return round(rss_kb / 1024, 2)


_profiler = RuntimeProfiler()


def get_runtime_profiler() -> RuntimeProfiler:
    return _profiler


def reset_runtime_profiler() -> None:
    _profiler.reset()


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Quiet noisy libs
    for lib in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)

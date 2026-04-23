"""Tests for structured logging utilities."""
from __future__ import annotations

import json
import logging

import pytest

from piloci.utils.logging import JSONFormatter, configure_logging


def _make_record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_json_formatter_basic():
    fmt = JSONFormatter()
    record = _make_record("hello world")
    output = fmt.format(record)
    data = json.loads(output)
    assert data["msg"] == "hello world"
    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    assert "ts" in data


def test_json_formatter_warning_level():
    fmt = JSONFormatter()
    record = _make_record("warn msg", level=logging.WARNING)
    data = json.loads(fmt.format(record))
    assert data["level"] == "WARNING"


def test_json_formatter_with_exc_info():
    fmt = JSONFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = _make_record("error happened")
    record.exc_info = exc_info
    output = fmt.format(record)
    data = json.loads(output)
    assert "exc" in data
    assert "ValueError" in data["exc"]


def test_configure_logging_text_mode():
    configure_logging(level="DEBUG", fmt="text")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    handler = root.handlers[0]
    assert not isinstance(handler.formatter, JSONFormatter)


def test_configure_logging_json_mode():
    configure_logging(level="WARNING", fmt="json")
    root = logging.getLogger()
    assert root.level == logging.WARNING
    handler = root.handlers[0]
    assert isinstance(handler.formatter, JSONFormatter)


def test_configure_logging_quiesces_noisy_libs():
    configure_logging(level="INFO", fmt="text")
    for lib in ("uvicorn.access", "httpx", "httpcore"):
        assert logging.getLogger(lib).level == logging.WARNING

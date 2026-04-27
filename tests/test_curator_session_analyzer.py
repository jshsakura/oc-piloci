"""Tests for curator/session_analyzer.py."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from piloci.curator.session_analyzer import (
    _truncate_transcript,
    _validate_instinct,
    extract_instincts,
)

# ---------------------------------------------------------------------------
# _truncate_transcript
# ---------------------------------------------------------------------------


def test_truncate_short_input_unchanged():
    text = "short transcript"
    assert _truncate_transcript(text) == text


def test_truncate_long_input_gets_prefix():
    text = "x" * 10000
    result = _truncate_transcript(text)
    assert result.startswith("...[truncated]...\n")
    assert len(result) < len(text)
    assert len(result) == len("...[truncated]...\n") + 6000


def test_truncate_exact_limit_unchanged():
    text = "a" * 6000
    assert _truncate_transcript(text) == text


def test_truncate_one_over_gets_truncated():
    text = "a" * 6001
    result = _truncate_transcript(text)
    assert result.startswith("...[truncated]...")


# ---------------------------------------------------------------------------
# _validate_instinct
# ---------------------------------------------------------------------------


def test_validate_valid_instinct():
    item = {
        "trigger": "user prefers black formatter",
        "action": "use black",
        "domain": "code-style",
        "evidence": "multiple corrections",
    }
    result = _validate_instinct(item)
    assert result is not None
    assert result["trigger"] == "user prefers black formatter"
    assert result["action"] == "use black"
    assert result["domain"] == "code-style"
    assert result["evidence"] == "multiple corrections"


def test_validate_missing_trigger():
    result = _validate_instinct({"action": "do something"})
    assert result is None


def test_validate_missing_action():
    result = _validate_instinct({"trigger": "something"})
    assert result is None


def test_validate_empty_trigger():
    result = _validate_instinct({"trigger": "  ", "action": "do"})
    assert result is None


def test_validate_empty_action():
    result = _validate_instinct({"trigger": "hi", "action": "  "})
    assert result is None


def test_validate_non_dict_returns_none():
    assert _validate_instinct("not a dict") is None
    assert _validate_instinct(42) is None
    assert _validate_instinct(None) is None


def test_validate_truncates_long_strings():
    item = {
        "trigger": "t" * 500,
        "action": "a" * 500,
        "evidence": "e" * 300,
    }
    result = _validate_instinct(item)
    assert result is not None
    assert len(result["trigger"]) <= 300
    assert len(result["action"]) <= 300
    assert len(result["evidence"]) <= 200


def test_validate_default_domain_is_other():
    item = {"trigger": "test", "action": "act"}
    result = _validate_instinct(item)
    assert result is not None
    assert result["domain"] == "other"


def test_validate_non_string_domain_becomes_other():
    item = {"trigger": "t", "action": "a", "domain": 42}
    result = _validate_instinct(item)
    assert result is not None
    assert result["domain"] == "other"


def test_validate_non_string_evidence_becomes_empty():
    item = {"trigger": "t", "action": "a", "evidence": 123}
    result = _validate_instinct(item)
    assert result is not None
    assert result["evidence"] == ""


def test_validate_missing_evidence_defaults_empty():
    item = {"trigger": "t", "action": "a"}
    result = _validate_instinct(item)
    assert result is not None
    assert result["evidence"] == ""


# ---------------------------------------------------------------------------
# extract_instincts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_instincts_empty_transcript():
    result = await extract_instincts("")
    assert result == []


@pytest.mark.asyncio
async def test_extract_instincts_whitespace_transcript():
    result = await extract_instincts("   \n\t  ")
    assert result == []


@pytest.mark.asyncio
async def test_extract_instincts_success(monkeypatch):
    fake_response = {
        "instincts": [
            {
                "trigger": "prefers black",
                "action": "run black",
                "domain": "code-style",
                "evidence": "seen 3 times",
            },
            {
                "trigger": "likes tests",
                "action": "write pytest",
                "domain": "testing",
                "evidence": "always tests",
            },
        ]
    }
    mock_chat = AsyncMock(return_value=fake_response)
    monkeypatch.setattr("piloci.curator.session_analyzer.chat_json", mock_chat)

    result = await extract_instincts("session transcript here")

    assert len(result) == 2
    assert result[0]["trigger"] == "prefers black"
    assert result[1]["domain"] == "testing"
    mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_extract_instincts_gemma_failure_returns_empty(monkeypatch):
    mock_chat = AsyncMock(side_effect=Exception("gemma down"))
    monkeypatch.setattr("piloci.curator.session_analyzer.chat_json", mock_chat)

    result = await extract_instincts("some transcript")
    assert result == []


@pytest.mark.asyncio
async def test_extract_instincts_invalid_response_shape(monkeypatch):
    mock_chat = AsyncMock(return_value={"not_instincts": []})
    monkeypatch.setattr("piloci.curator.session_analyzer.chat_json", mock_chat)

    result = await extract_instincts("transcript")
    assert result == []


@pytest.mark.asyncio
async def test_extract_instincts_filters_invalid_items(monkeypatch):
    fake_response = {
        "instincts": [
            {"trigger": "valid", "action": "act", "domain": "git"},
            "not a dict",
            {"trigger": "", "action": "empty trigger"},
            {"trigger": "valid2", "action": "act2"},
        ]
    }
    mock_chat = AsyncMock(return_value=fake_response)
    monkeypatch.setattr("piloci.curator.session_analyzer.chat_json", mock_chat)

    result = await extract_instincts("transcript")
    assert len(result) == 2
    assert result[0]["trigger"] == "valid"
    assert result[1]["trigger"] == "valid2"


@pytest.mark.asyncio
async def test_extract_instincts_passes_custom_endpoint(monkeypatch):
    mock_chat = AsyncMock(return_value={"instincts": []})
    monkeypatch.setattr("piloci.curator.session_analyzer.chat_json", mock_chat)

    await extract_instincts("text", endpoint="http://custom:1234", model="mymodel")

    call_kwargs = mock_chat.call_args
    assert call_kwargs.kwargs["endpoint"] == "http://custom:1234"
    assert call_kwargs.kwargs["model"] == "mymodel"

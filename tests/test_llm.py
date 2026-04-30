from __future__ import annotations

from unittest.mock import patch

import pytest

from piloci import llm

# ---------------------------------------------------------------------------
# Factory: get_chat_provider
# ---------------------------------------------------------------------------


def _settings(**overrides):
    base = {
        "chat_provider": "gemma_local",
        "gemma_endpoint": "http://localhost:9090/v1/chat/completions",
        "gemma_model": "gemma",
        "anthropic_api_key": None,
        "anthropic_model": "claude-haiku-4-5",
        "openai_compat_endpoint": None,
        "openai_compat_api_key": None,
        "openai_compat_model": "gpt-4o-mini",
    }
    base.update(overrides)

    class _S:
        pass

    s = _S()
    for k, v in base.items():
        setattr(s, k, v)
    return s


def test_get_chat_provider_returns_gemma_local_by_default():
    p = llm.get_chat_provider(_settings())
    assert isinstance(p, llm.LocalGemmaProvider)


def test_get_chat_provider_handles_uppercase_value():
    s = _settings(chat_provider="GEMMA_LOCAL")
    p = llm.get_chat_provider(s)
    assert isinstance(p, llm.LocalGemmaProvider)


def test_get_chat_provider_returns_anthropic_when_configured():
    s = _settings(chat_provider="anthropic", anthropic_api_key="sk-fake")
    p = llm.get_chat_provider(s)
    assert isinstance(p, llm.AnthropicProvider)


def test_get_chat_provider_raises_when_anthropic_key_missing():
    s = _settings(chat_provider="anthropic", anthropic_api_key=None)
    with pytest.raises(ValueError, match="anthropic_api_key"):
        llm.get_chat_provider(s)


def test_get_chat_provider_returns_openai_compat_when_configured():
    s = _settings(
        chat_provider="openai_compat",
        openai_compat_endpoint="https://api.groq.com/openai/v1",
        openai_compat_api_key="gsk-fake",
    )
    p = llm.get_chat_provider(s)
    assert isinstance(p, llm.OpenAICompatProvider)


def test_get_chat_provider_raises_when_openai_compat_endpoint_missing():
    s = _settings(chat_provider="openai_compat", openai_compat_endpoint=None)
    with pytest.raises(ValueError, match="openai_compat_endpoint"):
        llm.get_chat_provider(s)


def test_get_chat_provider_rejects_unknown_provider():
    s = _settings(chat_provider="cohere")
    with pytest.raises(ValueError, match="unknown chat_provider"):
        llm.get_chat_provider(s)


# ---------------------------------------------------------------------------
# OpenAICompatProvider — endpoint normalization
# ---------------------------------------------------------------------------


def test_openai_compat_appends_chat_completions_when_missing():
    p = llm.OpenAICompatProvider(
        endpoint="https://api.groq.com/openai/v1",
        model="llama-3",
    )
    assert p._endpoint.endswith("/chat/completions")


def test_openai_compat_keeps_path_when_already_complete():
    p = llm.OpenAICompatProvider(
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        model="llama-3",
    )
    assert p._endpoint.endswith("/chat/completions")
    assert "chat/completions/chat/completions" not in p._endpoint


def test_openai_compat_attaches_bearer_when_api_key_provided():
    p = llm.OpenAICompatProvider(endpoint="http://x", model="m", api_key="k1")
    assert p._headers.get("Authorization") == "Bearer k1"


def test_openai_compat_omits_auth_header_without_key():
    p = llm.OpenAICompatProvider(endpoint="http://x", model="m")
    assert "Authorization" not in p._headers


# ---------------------------------------------------------------------------
# AnthropicProvider — message shape
# ---------------------------------------------------------------------------


def test_anthropic_constructor_rejects_empty_key():
    with pytest.raises(ValueError, match="api_key"):
        llm.AnthropicProvider(api_key="", model="claude-haiku-4-5")


# ---------------------------------------------------------------------------
# LocalGemmaProvider — delegates to existing chat_stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_gemma_provider_delegates_to_chat_stream():
    captured: dict = {}

    async def fake_stream(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        for tok in ["a", "b"]:
            yield tok

    with patch("piloci.llm._local_gemma_stream", side_effect=fake_stream):
        p = llm.LocalGemmaProvider(endpoint="http://e/v1/chat/completions", model="g")
        out = [c async for c in p.stream([{"role": "user", "content": "hi"}], max_tokens=42)]

    assert out == ["a", "b"]
    assert captured["messages"][0]["content"] == "hi"
    assert captured["kwargs"]["endpoint"] == "http://e/v1/chat/completions"
    assert captured["kwargs"]["model"] == "g"
    assert captured["kwargs"]["max_tokens"] == 42

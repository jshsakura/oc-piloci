from __future__ import annotations

from unittest.mock import patch

import httpx
import orjson
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


# ---------------------------------------------------------------------------
# Streaming helpers — mock httpx transport for SSE responses
# ---------------------------------------------------------------------------


def _sse_response(lines: list[str], status: int = 200) -> httpx.Response:
    """Build an SSE-style httpx.Response from raw text lines."""
    body = "\n".join(lines).encode("utf-8")
    return httpx.Response(
        status,
        content=body,
        headers={"content-type": "text/event-stream"},
    )


def _patch_async_client(monkeypatch, handler):
    """Replace ``httpx.AsyncClient`` so streaming flows go through ``handler``.

    ``handler`` is an ``httpx.MockTransport`` compatible callable receiving the
    outgoing ``httpx.Request`` and returning an ``httpx.Response``.
    """
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------------------
# OpenAICompatProvider — construction guards
# ---------------------------------------------------------------------------


def test_openai_compat_rejects_empty_endpoint():
    with pytest.raises(ValueError, match="endpoint"):
        llm.OpenAICompatProvider(endpoint="", model="m")


# ---------------------------------------------------------------------------
# OpenAICompatProvider.stream — SSE parsing happy path + edge cases
# ---------------------------------------------------------------------------


async def test_openai_compat_stream_yields_content_deltas(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = orjson.loads(request.content)
        chunks = [
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {"content": "!"}}]},
        ]
        lines = [f"data: {orjson.dumps(c).decode()}" for c in chunks]
        lines.append("data: [DONE]")
        return _sse_response(lines)

    _patch_async_client(monkeypatch, handler)
    p = llm.OpenAICompatProvider(
        endpoint="https://api.example.com/v1",
        model="m1",
        api_key="key-xyz",
    )

    out = [tok async for tok in p.stream([{"role": "user", "content": "hi"}], max_tokens=64)]

    assert out == ["Hel", "lo", "!"]
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["authorization"] == "Bearer key-xyz"
    assert captured["payload"]["model"] == "m1"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["max_tokens"] == 64
    assert captured["payload"]["messages"][0]["content"] == "hi"


async def test_openai_compat_stream_skips_non_data_and_blank_lines(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            "",  # blank
            ": comment line (ignored)",
            "event: ping",  # non-data prefix
            "data: ",  # empty body after strip
            "data: [DONE]",
            'data: {"choices": [{"delta": {"content": "X"}}]}',
        ]
        return _sse_response(lines)

    _patch_async_client(monkeypatch, handler)
    p = llm.OpenAICompatProvider(endpoint="https://x/v1/chat/completions", model="m")
    out = [tok async for tok in p.stream([{"role": "user", "content": "q"}])]
    assert out == ["X"]


async def test_openai_compat_stream_skips_malformed_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            "data: {not valid json}",
            'data: {"choices": [{"delta": {"content": "ok"}}]}',
        ]
        return _sse_response(lines)

    _patch_async_client(monkeypatch, handler)
    p = llm.OpenAICompatProvider(endpoint="https://x/v1/chat/completions", model="m")
    out = [tok async for tok in p.stream([{"role": "user", "content": "q"}])]
    assert out == ["ok"]


async def test_openai_compat_stream_skips_empty_choices_and_missing_content(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            'data: {"choices": []}',  # empty choices
            'data: {"choices": [{"delta": {}}]}',  # no content key
            'data: {"choices": [{"delta": null}]}',  # null delta
            'data: {"choices": [{"delta": {"content": ""}}]}',  # empty string
            'data: {"choices": [{"delta": {"content": "real"}}]}',
        ]
        return _sse_response(lines)

    _patch_async_client(monkeypatch, handler)
    p = llm.OpenAICompatProvider(endpoint="https://x/v1/chat/completions", model="m")
    out = [tok async for tok in p.stream([{"role": "user", "content": "q"}])]
    assert out == ["real"]


async def test_openai_compat_stream_raises_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    _patch_async_client(monkeypatch, handler)
    p = llm.OpenAICompatProvider(endpoint="https://x/v1/chat/completions", model="m")

    with pytest.raises(httpx.HTTPStatusError):
        [tok async for tok in p.stream([{"role": "user", "content": "q"}])]


async def test_openai_compat_stream_raises_on_server_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _patch_async_client(monkeypatch, handler)
    p = llm.OpenAICompatProvider(endpoint="https://x/v1/chat/completions", model="m")

    with pytest.raises(httpx.HTTPStatusError):
        [tok async for tok in p.stream([{"role": "user", "content": "q"}])]


# ---------------------------------------------------------------------------
# AnthropicProvider.stream — system message handling + SSE event parsing
# ---------------------------------------------------------------------------


async def test_anthropic_stream_yields_text_deltas(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = orjson.loads(request.content)
        lines = [
            'data: {"type": "message_start"}',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " there"}}',
            'data: {"type": "message_stop"}',
        ]
        return _sse_response(lines)

    _patch_async_client(monkeypatch, handler)
    p = llm.AnthropicProvider(api_key="sk-test", model="claude-haiku-4-5")
    msgs = [
        {"role": "system", "content": "be brief"},
        {"role": "system", "content": "also be kind"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "prev reply"},
        {"role": "tool", "content": "should be filtered"},
    ]
    out = [tok async for tok in p.stream(msgs, max_tokens=128, temperature=0.5)]

    assert out == ["Hi", " there"]
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    # system messages merged, joined by blank line
    assert captured["payload"]["system"] == "be brief\n\nalso be kind"
    # only user/assistant pass through; system/tool are filtered out
    roles = [m["role"] for m in captured["payload"]["messages"]]
    assert roles == ["user", "assistant"]
    assert captured["payload"]["max_tokens"] == 128
    assert captured["payload"]["temperature"] == 0.5
    assert captured["payload"]["stream"] is True


async def test_anthropic_stream_omits_system_when_no_system_messages(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = orjson.loads(request.content)
        return _sse_response(['data: {"type": "message_stop"}'])

    _patch_async_client(monkeypatch, handler)
    p = llm.AnthropicProvider(api_key="sk-test", model="claude-haiku-4-5")
    out = [tok async for tok in p.stream([{"role": "user", "content": "hi"}])]

    assert out == []
    assert "system" not in captured["payload"]


async def test_anthropic_stream_skips_non_text_delta_events(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            "event: ping",  # non-data
            "",  # blank
            'data: {"type": "content_block_start"}',  # wrong type
            'data: {"type": "content_block_delta", "delta": {"type": "input_json_delta"}}',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": ""}}',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "real"}}',
            "data: ",  # empty body
            "data: {not json}",  # malformed
            'data: {"type": "content_block_delta"}',  # missing delta
        ]
        return _sse_response(lines)

    _patch_async_client(monkeypatch, handler)
    p = llm.AnthropicProvider(api_key="sk-test", model="claude-haiku-4-5")
    out = [tok async for tok in p.stream([{"role": "user", "content": "q"}])]
    assert out == ["real"]


async def test_anthropic_stream_raises_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    _patch_async_client(monkeypatch, handler)
    p = llm.AnthropicProvider(api_key="sk-test", model="claude-haiku-4-5")

    with pytest.raises(httpx.HTTPStatusError):
        [tok async for tok in p.stream([{"role": "user", "content": "q"}])]


async def test_anthropic_stream_uses_custom_version(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["version"] = request.headers.get("anthropic-version")
        return _sse_response(['data: {"type": "message_stop"}'])

    _patch_async_client(monkeypatch, handler)
    p = llm.AnthropicProvider(
        api_key="sk-test",
        model="claude-haiku-4-5",
        version="2099-01-01",
    )
    [tok async for tok in p.stream([{"role": "user", "content": "q"}])]
    assert captured["version"] == "2099-01-01"

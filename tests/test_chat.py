from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest
from starlette.requests import Request

from piloci import chat


def _make_request(body: dict[str, Any], user: dict[str, Any] | None, store: Any) -> Request:
    payload = orjson.dumps(body)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "state": {"user": user},
        "app": MagicMock(state=MagicMock(store=store)),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


class _StubProvider:
    """Async-generator provider for tests."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.last_messages: list[dict[str, str]] | None = None

    async def stream(self, messages, *, max_tokens=768, temperature=0.2):
        self.last_messages = messages
        for tok in self._tokens:
            yield tok


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_build_messages_includes_each_memory_with_ref_label():
    memories = [
        {"memory_id": "abc", "content": "First fact"},
        {"memory_id": "def", "content": "Second fact", "tags": ["x"]},
    ]
    msgs = chat.build_messages("what?", memories)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user_text = msgs[1]["content"]
    assert "[m1]" in user_text and "[m2]" in user_text
    assert "First fact" in user_text and "Second fact" in user_text
    # Tags are NOT in the prompt to save context — only in citations
    assert "tags=" not in user_text


def test_build_messages_handles_empty_memories():
    msgs = chat.build_messages("hello", [])
    assert "(none)" in msgs[1]["content"]


def test_build_messages_truncates_long_memory_content():
    huge = "a" * (chat.DEFAULT_MAX_MEMORY_CHARS + 500)
    msgs = chat.build_messages("q", [{"memory_id": "id", "content": huge}])
    user_text = msgs[1]["content"]
    assert "…" in user_text
    assert "a" * (chat.DEFAULT_MAX_MEMORY_CHARS + 100) not in user_text


def test_build_messages_drops_memories_past_total_budget():
    # 5 memories of 400 chars each = 2000 chars.
    # With total_context_limit=600 we expect only ~1 to fit.
    memories = [{"memory_id": f"m{i}", "content": "x" * 400} for i in range(5)]
    msgs = chat.build_messages("q", memories, per_memory_limit=400, total_context_limit=600)
    user_text = msgs[1]["content"]
    # First memory should appear; later ones should be dropped
    assert "[m1]" in user_text
    assert "[m4]" not in user_text and "[m5]" not in user_text


def test_format_citations_assigns_sequential_refs():
    citations = chat.format_citations(
        [
            {"memory_id": "a", "content": "x", "score": 0.9, "tags": ["t"]},
            {"memory_id": "b", "content": "y", "score": 0.7},
        ]
    )
    assert [c["ref"] for c in citations] == ["m1", "m2"]
    assert citations[0]["memory_id"] == "a"
    assert citations[0]["score"] == 0.9
    assert citations[1]["tags"] == []


# ---------------------------------------------------------------------------
# retrieve()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_clamps_top_k_within_bounds():
    store = MagicMock()
    store.search = AsyncMock(return_value=[])
    embed_fn = AsyncMock(return_value=[0.1, 0.2])

    await chat.retrieve(
        query="q",
        user_id="u",
        project_id="p",
        store=store,
        embed_fn=embed_fn,
        top_k=99999,
    )

    embed_fn.assert_awaited_once_with("q")
    store.search.assert_awaited_once()
    kwargs = store.search.call_args.kwargs
    assert kwargs["top_k"] == chat.MAX_TOP_K


@pytest.mark.asyncio
async def test_retrieve_clamps_top_k_minimum_one():
    store = MagicMock()
    store.search = AsyncMock(return_value=[])
    embed_fn = AsyncMock(return_value=[0.0])

    await chat.retrieve(
        query="q", user_id="u", project_id="p", store=store, embed_fn=embed_fn, top_k=0
    )
    assert store.search.call_args.kwargs["top_k"] == 1


# ---------------------------------------------------------------------------
# stream_answer wires provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_answer_yields_chunks_from_provider():
    provider = _StubProvider(["Hello", " ", "world"])
    chunks = [
        c
        async for c in chat.stream_answer(
            query="q",
            memories=[{"memory_id": "a", "content": "x"}],
            provider=provider,
        )
    ]
    assert chunks == ["Hello", " ", "world"]
    # Provider received the assembled messages (system + user)
    assert provider.last_messages is not None
    assert provider.last_messages[0]["role"] == "system"


# ---------------------------------------------------------------------------
# Route guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_chat_returns_401_when_unauthenticated():
    from piloci.api.routes import route_chat

    req = _make_request({"query": "hi"}, user=None, store=MagicMock())
    resp = await route_chat(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_route_chat_requires_project_scope():
    from piloci.api.routes import route_chat

    req = _make_request({"query": "hi"}, user={"user_id": "u1"}, store=MagicMock())
    resp = await route_chat(req)
    assert resp.status_code == 400
    body = orjson.loads(resp.body)
    assert "project" in body["error"].lower()


@pytest.mark.asyncio
async def test_route_chat_rejects_blank_query():
    from piloci.api.routes import route_chat

    req = _make_request(
        {"query": "   "},
        user={"user_id": "u1", "project_id": "p1"},
        store=MagicMock(),
    )
    resp = await route_chat(req)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_route_chat_resolves_project_slug_for_session_users():
    from piloci.api.routes import route_chat

    store = MagicMock()
    store.search = AsyncMock(return_value=[{"memory_id": "x", "content": "y", "score": 0.5}])
    req = _make_request(
        {"query": "hi", "project_slug": "demo", "stream": False},
        user={"user_id": "u1"},  # no project_id in session — slug resolves it
        store=store,
    )

    async def fake_get_proj(user_id, slug):
        assert user_id == "u1" and slug == "demo"
        return {"id": "proj-resolved", "slug": "demo", "name": "Demo"}

    async def fake_embed(**kwargs):
        return [0.0]

    provider = _StubProvider(["ok"])
    with (
        patch("piloci.api.routes._get_user_project_by_slug", new=fake_get_proj),
        patch("piloci.storage.embed.embed_one", new=fake_embed),
        patch("piloci.llm.get_chat_provider", return_value=provider),
    ):
        resp = await route_chat(req)

    assert resp.status_code == 200
    # Search was called with the resolved project_id
    assert store.search.call_args.kwargs["project_id"] == "proj-resolved"


@pytest.mark.asyncio
async def test_route_chat_returns_404_for_unknown_project_slug():
    from piloci.api.routes import route_chat

    req = _make_request(
        {"query": "hi", "project_slug": "ghost"},
        user={"user_id": "u1"},
        store=MagicMock(),
    )

    async def fake_get_proj(user_id, slug):
        return None

    with patch("piloci.api.routes._get_user_project_by_slug", new=fake_get_proj):
        resp = await route_chat(req)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_route_chat_returns_503_when_provider_misconfigured():
    from piloci.api.routes import route_chat

    req = _make_request(
        {"query": "hi"},
        user={"user_id": "u1", "project_id": "p1"},
        store=MagicMock(),
    )
    with patch(
        "piloci.api.routes.get_settings",
        return_value=MagicMock(chat_provider="anthropic", anthropic_api_key=None),
    ):
        # The route imports get_chat_provider lazily; intercept it before it raises
        with patch(
            "piloci.llm.get_chat_provider",
            side_effect=ValueError("anthropic_api_key required for chat_provider=anthropic"),
        ):
            resp = await route_chat(req)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_route_chat_non_stream_returns_answer_and_citations():
    from piloci.api.routes import route_chat

    store = MagicMock()
    store.search = AsyncMock(
        return_value=[{"memory_id": "abc", "content": "the answer is 42", "score": 0.9}]
    )
    req = _make_request(
        {"query": "what is the answer?", "stream": False},
        user={"user_id": "u1", "project_id": "p1"},
        store=store,
    )

    async def fake_embed_one(**kwargs):
        return [0.1, 0.2, 0.3]

    provider = _StubProvider(["42", " is", " it"])
    with (
        patch("piloci.storage.embed.embed_one", new=fake_embed_one),
        patch("piloci.llm.get_chat_provider", return_value=provider),
    ):
        resp = await route_chat(req)

    assert resp.status_code == 200
    body = orjson.loads(resp.body)
    assert body["answer"] == "42 is it"
    assert body["citations"][0]["memory_id"] == "abc"
    assert body["citations"][0]["ref"] == "m1"


@pytest.mark.asyncio
async def test_route_chat_stream_emits_citations_then_tokens_then_done():
    from piloci.api.routes import route_chat

    store = MagicMock()
    store.search = AsyncMock(
        return_value=[{"memory_id": "m-1", "content": "hello world", "score": 0.5}]
    )
    req = _make_request(
        {"query": "hi", "stream": True},
        user={"user_id": "u1", "project_id": "p1"},
        store=store,
    )

    async def fake_embed_one(**kwargs):
        return [0.0]

    provider = _StubProvider(["hi", "!"])
    with (
        patch("piloci.storage.embed.embed_one", new=fake_embed_one),
        patch("piloci.llm.get_chat_provider", return_value=provider),
    ):
        resp = await route_chat(req)
        assert resp.media_type == "text/event-stream"
        body = b""
        async for chunk in resp.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()

    text = body.decode()
    assert "event: citations" in text
    assert "event: done" in text
    assert text.count("event: token") == 2
    pos_hi = text.find('"hi"')
    pos_bang = text.find('"!"')
    assert pos_hi != -1 and pos_bang != -1 and pos_hi < pos_bang

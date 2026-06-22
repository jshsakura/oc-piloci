"""Tests for the pull-form `ask` assistant (piloci.assistant.run_task + handle_ask).

chat_text is monkeypatched so these never touch the local llama-server.
"""

import pytest

from piloci import assistant
from piloci.tools.task_tools import AskInput, handle_ask


class _FakeStore:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    async def hybrid_search(self, user_id, project_id, query_text, query_vector, top_k=5):
        self.calls.append((user_id, project_id, query_text, top_k))
        return self.hits


class _Settings:
    gemma_endpoint = "http://localhost:9090/v1/chat/completions"
    gemma_model = "gemma"


async def _embed(_text):
    return [0.0] * 8


def _patch_chat(monkeypatch, captured=None):
    async def fake_chat_text(messages, *, targets, record_target=None, **kw):
        if captured is not None:
            captured["messages"] = messages
            captured["targets"] = targets
            captured["kw"] = kw
        if record_target is not None:
            record_target.append("local")
        return "응답 결과"

    monkeypatch.setattr(assistant, "chat_text", fake_chat_text)


@pytest.mark.asyncio
async def test_run_task_uses_memory(monkeypatch):
    captured = {}
    _patch_chat(monkeypatch, captured)
    store = _FakeStore(hits=[{"content": "배포는 태그 푸시 기반"}])

    out = await assistant.run_task(
        instruction="배포 규칙?",
        use_memory=True,
        user_id="u1",
        project_id="p1",
        store=store,
        embed_fn=_embed,
        settings=_Settings(),
    )

    assert out == {
        "answer": "응답 결과",
        "used_memory": True,
        "memory_hits": 1,
        "path": "local",
    }
    # (user_id, project_id) enforced on search
    assert store.calls[0][0] == "u1"
    assert store.calls[0][1] == "p1"
    # retrieved content injected into the user prompt
    assert "배포는 태그 푸시 기반" in captured["messages"][1]["content"]
    # local-only target
    assert captured["targets"][0].label == "local"
    assert captured["targets"][0].endpoint == _Settings.gemma_endpoint


@pytest.mark.asyncio
async def test_run_task_skips_memory_when_disabled(monkeypatch):
    _patch_chat(monkeypatch)
    store = _FakeStore(hits=[{"content": "should-not-be-used"}])

    out = await assistant.run_task(
        instruction="hi",
        use_memory=False,
        user_id="u1",
        project_id="p1",
        store=store,
        embed_fn=_embed,
        settings=_Settings(),
    )

    assert out["used_memory"] is False
    assert out["memory_hits"] == 0
    assert store.calls == []  # no search performed


@pytest.mark.asyncio
async def test_run_task_no_project_skips_memory(monkeypatch):
    _patch_chat(monkeypatch)
    store = _FakeStore(hits=[{"content": "x"}])

    out = await assistant.run_task(
        instruction="hi",
        use_memory=True,
        user_id="u1",
        project_id=None,  # no project scope → cannot/should not search
        store=store,
        embed_fn=_embed,
        settings=_Settings(),
    )

    assert out["used_memory"] is False
    assert store.calls == []


@pytest.mark.asyncio
async def test_run_task_retrieval_failure_is_best_effort(monkeypatch):
    _patch_chat(monkeypatch)

    class _BoomStore:
        async def hybrid_search(self, *a, **k):
            raise RuntimeError("lancedb down")

    out = await assistant.run_task(
        instruction="hi",
        use_memory=True,
        user_id="u1",
        project_id="p1",
        store=_BoomStore(),
        embed_fn=_embed,
        settings=_Settings(),
    )

    # task still completes; memory just absent
    assert out["answer"] == "응답 결과"
    assert out["used_memory"] is False


@pytest.mark.asyncio
async def test_handle_ask_delegates(monkeypatch):
    _patch_chat(monkeypatch)
    store = _FakeStore(hits=[])

    out = await handle_ask(
        AskInput(instruction="요약해"),
        "u1",
        "p1",
        store,
        _embed,
        _Settings(),
    )

    assert out["answer"] == "응답 결과"
    assert out["path"] == "local"


def test_ask_desc_within_budget():
    from piloci.tools.task_tools import ASK_DESC

    assert len(ASK_DESC) <= 120
    for field in AskInput.model_fields.values():
        if field.description:
            assert len(field.description) <= 80

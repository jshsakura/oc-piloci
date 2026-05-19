"""Unit tests for the team-wiki worker.

The worker has two layers: pure helpers (clustering, slugify, dawn-window
gate) and orchestration that touches the DB + LLM. These tests cover the
pure layer plus a smoke-level `build_team_wiki` run with mocked store and
LLM provider so coverage exercises the full code path without a live GLM.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from piloci.curator.team_wiki_worker import (
    _DAWN_END_HOUR,
    _DAWN_START_HOUR,
    _cluster,
    _doc_top_folder,
    _in_dawn_window,
    _memory_primary_tag,
    _slugify,
    _user_prompt,
)


def test_slugify_keeps_hangul_strips_punctuation() -> None:
    assert _slugify("회의록 5월") == "회의록-5월"
    assert _slugify("API Design!!") == "api-design"
    assert _slugify("") == "article"  # fallback


def test_doc_top_folder_returns_root_for_bare_files() -> None:
    assert _doc_top_folder("notes.md") == "_root"
    assert _doc_top_folder("docs/api/auth.md") == "docs"
    assert _doc_top_folder("") == "_root"


def test_memory_primary_tag_falls_back_to_misc() -> None:
    assert _memory_primary_tag([]) == "_misc"
    assert _memory_primary_tag(["alpha", "beta"]) == "alpha"


def test_cluster_groups_docs_by_top_folder_and_memories_by_first_tag() -> None:
    docs = [
        {"id": "d1", "path": "docs/a.md", "content": "alpha"},
        {"id": "d2", "path": "docs/b.md", "content": "beta"},
        {"id": "d3", "path": "code/x.py", "content": "code"},
    ]
    memories = [
        {"id": "m1", "content": "decision", "tags": ["plan"]},
        {"id": "m2", "content": "another", "tags": ["plan", "extra"]},
    ]

    clusters = _cluster(memories, docs)
    by_label = {(c["category"], c["label"]): c for c in clusters}

    assert ("folder", "docs") in by_label
    assert len(by_label[("folder", "docs")]["sources"]) == 2
    assert ("folder", "code") in by_label
    assert ("tag", "plan") in by_label
    assert len(by_label[("tag", "plan")]["sources"]) == 2


def test_cluster_drops_documents_without_path() -> None:
    clusters = _cluster([], [{"id": "x", "path": "", "content": ""}])
    assert clusters == []


def test_user_prompt_includes_category_label_and_sources() -> None:
    cluster = {
        "category": "folder",
        "label": "docs",
        "sources": [{"kind": "doc", "path": "docs/api.md", "content": "body"}],
    }
    text = _user_prompt(cluster)
    assert "folder/docs" in text
    # New layered prompt: docs come under "1차 출처" with their path as a
    # `code-spanned` header — replaces the old single-line "[문서 ...]" form.
    assert "1차 출처" in text
    assert "docs/api.md" in text
    assert "body" in text


def test_in_dawn_window_uses_start_end_hours() -> None:
    # _in_dawn_window does `from datetime import datetime` *inside* the
    # function — the local import means we have to patch the symbol on the
    # datetime module itself rather than on the worker module.
    import datetime as dt_module

    class _StubDateTime:
        hour = 0

        @classmethod
        def now(cls) -> "_StubDateTime":
            return cls()

    with patch.object(dt_module, "datetime", _StubDateTime):
        for hour in range(_DAWN_START_HOUR, _DAWN_END_HOUR):
            _StubDateTime.hour = hour
            assert _in_dawn_window() is True
        for hour in (0, 1, 2, _DAWN_END_HOUR, 12, 23):
            _StubDateTime.hour = hour
            assert _in_dawn_window() is False


@pytest.mark.asyncio
async def test_build_team_wiki_returns_error_when_no_external_provider(
    monkeypatch,
) -> None:
    """The worker refuses to fall back to local Gemma — surfaces a Korean
    error string to the caller so the UI can guide the user to register GLM."""

    from piloci.curator import team_wiki_worker

    async def _fake_resolve(_team_id: str) -> dict:
        return {"id": "team-1", "name": "T", "owner_id": "owner-1"}

    async def _fake_memories(_team_id, _store) -> list:
        return []

    async def _fake_docs(_team_id) -> list:
        return [{"id": "d1", "path": "docs/a.md", "content": "x"}]

    async def _fake_fallbacks(_user_id: str) -> list:
        return []  # no external providers registered

    async def _fake_save_vault(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(team_wiki_worker, "_resolve_team", _fake_resolve)
    monkeypatch.setattr(team_wiki_worker, "_list_team_memories", _fake_memories)
    monkeypatch.setattr(team_wiki_worker, "_list_team_documents", _fake_docs)
    monkeypatch.setattr(team_wiki_worker, "load_user_fallbacks", _fake_fallbacks)
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", _fake_save_vault)

    result = await team_wiki_worker.build_team_wiki("team-1", AsyncMock())
    assert result["success"] is False
    assert "외부 AI" in result["error"]


@pytest.mark.asyncio
async def test_build_team_wiki_short_circuits_when_team_missing(monkeypatch) -> None:
    from piloci.curator import team_wiki_worker

    async def _none(_team_id: str) -> None:
        return None

    monkeypatch.setattr(team_wiki_worker, "_resolve_team", _none)
    result = await team_wiki_worker.build_team_wiki("ghost", AsyncMock())
    assert result == {"success": False, "error": "team ghost not found"}


@pytest.mark.asyncio
async def test_build_team_wiki_no_source_material_short_circuits(monkeypatch) -> None:
    """When the team has zero docs and zero memories the worker should skip
    the LLM round-trip entirely and return ``articles_built=0``."""

    from piloci.curator import team_wiki_worker

    async def _fake_resolve(_team_id: str) -> dict:
        return {"id": "team-empty", "name": "Empty", "owner_id": "owner-1"}

    async def _fake_memories(_team_id, _store) -> list:
        return []

    async def _fake_docs(_team_id) -> list:
        return []

    def _fake_save_vault(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(team_wiki_worker, "_resolve_team", _fake_resolve)
    monkeypatch.setattr(team_wiki_worker, "_list_team_memories", _fake_memories)
    monkeypatch.setattr(team_wiki_worker, "_list_team_documents", _fake_docs)
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", _fake_save_vault)

    result = await team_wiki_worker.build_team_wiki("team-empty", AsyncMock())
    assert result["success"] is True
    assert result["articles_built"] == 0
    assert result["reason"] == "no source material"


@pytest.mark.asyncio
async def test_build_team_wiki_full_pipeline_with_mocked_glm(monkeypatch) -> None:
    """End-to-end happy path: one cluster, GLM returns a valid article,
    upsert succeeds, vault is merged, watermark is bumped."""

    from piloci.curator import team_wiki_worker

    async def _fake_resolve(_team_id: str) -> dict:
        return {"id": "team-1", "name": "Team", "owner_id": "owner-1"}

    async def _fake_memories(_team_id, _store) -> list:
        return []

    async def _fake_docs(_team_id) -> list:
        return [{"id": "doc-1", "path": "docs/intro.md", "content": "hello"}]

    class _Target:
        label = "glm"

    async def _fake_fallbacks(_user_id: str) -> list:
        return [_Target()]

    async def _fake_chat_json(_messages, **kwargs):
        # Append the served target so build_team_wiki captures `generated_by`.
        record = kwargs.get("record_target")
        if record is not None:
            record.append("glm")
        return {
            "title": "Intro",
            "slug": "intro",
            "summary": "hello",
            "content": "# Intro",
            "category": "folder/docs",
            "linked_topics": [],
        }

    upsert_calls: list[dict] = []

    async def _fake_upsert(_team_id, payload, *, generated_by):
        upsert_calls.append(payload)
        return {
            "id": "art-1",
            "slug": "intro",
            "title": "Intro",
            "summary": "hello",
            "category": "folder/docs",
            "revision": 1,
            "generated_by": generated_by,
            "sources": payload["sources"],
        }

    def _fake_save_vault(*args, **kwargs) -> None:
        return None

    def _fake_merge(*args, **kwargs) -> dict:
        return {}

    async def _fake_mark(_team_id) -> None:
        return None

    monkeypatch.setattr(team_wiki_worker, "_resolve_team", _fake_resolve)
    monkeypatch.setattr(team_wiki_worker, "_list_team_memories", _fake_memories)
    monkeypatch.setattr(team_wiki_worker, "_list_team_documents", _fake_docs)
    monkeypatch.setattr(team_wiki_worker, "load_user_fallbacks", _fake_fallbacks)
    monkeypatch.setattr(team_wiki_worker, "chat_json", _fake_chat_json)
    monkeypatch.setattr(team_wiki_worker, "_upsert_article", _fake_upsert)
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", _fake_save_vault)
    monkeypatch.setattr(team_wiki_worker, "merge_wiki_articles", _fake_merge)
    monkeypatch.setattr(team_wiki_worker, "_mark_team_built", _fake_mark)

    summary = await team_wiki_worker.build_team_wiki("team-1", AsyncMock())
    assert summary["success"] is True
    assert summary["articles_built"] == 1
    assert summary["generated_by"] == "glm"
    assert len(upsert_calls) == 1
    assert upsert_calls[0]["sources"][0]["kind"] == "doc"

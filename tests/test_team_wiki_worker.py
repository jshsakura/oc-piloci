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
    _assemble_source_text,
    _cluster,
    _cluster_slug,
    _doc_top_folder,
    _human_category,
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


def test_cluster_slug_is_stable_and_title_independent() -> None:
    # Same cluster identity → same slug, regardless of any (LLM) title. This is
    # what stops rebuilds from minting duplicate articles under reworded titles.
    cluster = {"category": "folder", "label": "yokogawa-bpm", "sources": []}
    assert _cluster_slug(cluster) == _cluster_slug(dict(cluster)) == "folder-yokogawa-bpm"
    # Different clusters → different slugs.
    assert _cluster_slug({"category": "tag", "label": "plan"}) == "tag-plan"
    # Empty identity still yields a usable slug, never crashes.
    assert _cluster_slug({"category": "", "label": ""}) == "article"


# Content long enough to clear the _MIN_CLUSTER_CHARS substance gate so the
# clustering structure itself can be asserted.
_LONG = "이건 클러스터 게이트를 통과하기 위한 충분히 긴 본문 내용입니다. " * 12


def test_cluster_groups_docs_by_top_folder_and_memories_by_first_tag() -> None:
    docs = [
        {"id": "d1", "path": "docs/a.md", "content": "alpha " + _LONG},
        {"id": "d2", "path": "docs/b.md", "content": "beta " + _LONG},
        {"id": "d3", "path": "code/x.py", "content": "code " + _LONG},
    ]
    memories = [
        {"id": "m1", "content": "decision " + _LONG, "tags": ["plan"]},
        {"id": "m2", "content": "another " + _LONG, "tags": ["plan", "extra"]},
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


def test_cluster_skips_thin_clusters_below_min_chars() -> None:
    # A folder/tag holding only a stray line must NOT become an article — that's
    # the "empty-folder garbage" the substance gate is there to prevent.
    docs = [{"id": "d1", "path": "docs/a.md", "content": "한 줄짜리 메모"}]
    assert _cluster([], docs) == []


def test_human_category_maps_internal_buckets_to_none() -> None:
    assert _human_category({"label": "_root"}) is None
    assert _human_category({"label": "_misc"}) is None
    assert _human_category({"label": ""}) is None
    # Real folder/tag names pass through as the sidebar label.
    assert _human_category({"label": "docs"}) == "docs"
    assert _human_category({"label": "security"}) == "security"


def test_cluster_skips_binary_documents() -> None:
    """Binary uploads have empty inline content; feeding them to the LLM only
    yields empty articles, so digestion drops them entirely."""
    docs = [
        {"id": "d1", "path": "docs/a.md", "content": "real text " + _LONG},
        {"id": "b1", "path": "assets/logo.png", "content": "", "is_binary": True},
    ]
    clusters = _cluster([], docs)
    all_ids = {s["id"] for c in clusters for s in c["sources"]}
    assert "d1" in all_ids
    assert "b1" not in all_ids


def test_cluster_skips_empty_content_documents() -> None:
    clusters = _cluster([], [{"id": "e", "path": "docs/empty.md", "content": "   "}])
    assert clusters == []


def test_user_prompt_includes_category_label_and_source_text() -> None:
    cluster = {
        "category": "folder",
        "label": "docs",
        "sources": [{"kind": "doc", "path": "docs/api.md", "content": "body"}],
    }
    source_text, overflowed = _assemble_source_text(cluster, 60000)
    assert not overflowed
    assert "1차 출처" in source_text and "docs/api.md" in source_text and "body" in source_text
    text = _user_prompt(cluster, source_text)
    assert "folder/docs" in text
    assert "docs/api.md" in text
    assert "body" in text


def test_assemble_source_text_keeps_full_document_no_4000_cap() -> None:
    # Regression: the old [:4000] cut silently dropped the tail of a long
    # uploaded document. The full content must survive into the prompt.
    big = "본문내용" * 3000  # 12000 chars, no edge whitespace, well past 4000
    cluster = {
        "category": "folder",
        "label": "d",
        "sources": [{"kind": "doc", "path": "docs/big.md", "content": big}],
    }
    source_text, overflowed = _assemble_source_text(cluster, 200_000)
    assert big in source_text
    assert not overflowed


def test_assemble_source_text_flags_overflow_for_compression() -> None:
    cluster = {
        "category": "f",
        "label": "l",
        "sources": [{"kind": "doc", "path": "d.md", "content": "Y" * 5000}],
    }
    _, overflowed = _assemble_source_text(cluster, 500)
    assert overflowed


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
        return [{"id": "d1", "path": "docs/a.md", "content": "x" * 500}]

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
        return [{"id": "doc-1", "path": "docs/intro.md", "content": "hello " + "본문 " * 200}]

    class _Target:
        label = "glm"

    async def _fake_fallbacks(_user_id: str) -> list:
        return [_Target()]

    # The body is now generated as plain markdown via chat_text (must clear the
    # _MIN_ARTICLE_CHARS junk gate, ≥150 chars).
    _article_body = "# Intro\n\n## 개요\n" + "이 문서는 인트로를 설명합니다. " * 20

    async def _fake_chat_text(_messages, **kwargs):
        record = kwargs.get("record_target")
        if record is not None:
            record.append("glm")
        return _article_body

    # One fake serves every JSON call: critique (no issues → no revise),
    # judge (high scores → no retry), and metadata extraction.
    async def _fake_chat_json(_messages, **kwargs):
        return {
            "title": "Intro",
            "slug": "intro",
            "summary": "hello",
            "linked_topics": [],
            "accuracy": 5,
            "completeness": 5,
            "clarity": 5,
            "action": "accept",
        }

    async def _fake_sweep(_team_id, _keep_slugs, _min_chars) -> int:
        return 0

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
    monkeypatch.setattr(team_wiki_worker, "chat_text", _fake_chat_text)
    monkeypatch.setattr(team_wiki_worker, "_upsert_article", _fake_upsert)
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", _fake_save_vault)
    monkeypatch.setattr(team_wiki_worker, "merge_wiki_articles", _fake_merge)
    monkeypatch.setattr(team_wiki_worker, "_mark_team_built", _fake_mark)
    monkeypatch.setattr(team_wiki_worker, "_sweep_stale_llm_articles", _fake_sweep)

    summary = await team_wiki_worker.build_team_wiki("team-1", AsyncMock())
    assert summary["success"] is True
    assert summary["articles_built"] == 1
    assert summary["generated_by"] == "glm"
    assert len(upsert_calls) == 1
    assert upsert_calls[0]["sources"][0]["kind"] == "doc"
    # Stable slug derived from the cluster identity (folder/docs), not the title.
    assert upsert_calls[0]["slug"] == "folder-docs"


@pytest.mark.asyncio
async def test_build_team_wiki_change_gate_skips_when_unchanged(monkeypatch) -> None:
    """Already built + no doc changes since → no LLM regeneration. Stale
    duplicates are still swept so a skipped build leaves the wiki cleaner."""
    from datetime import datetime

    from piloci.curator import team_wiki_worker

    async def _fake_resolve(_team_id: str) -> dict:
        return {
            "id": "team-1",
            "name": "Team",
            "owner_id": "owner-1",
            "_last_built": datetime(2026, 5, 1),
        }

    async def _fake_memories(_team_id, _store) -> list:
        return []

    async def _fake_docs(_team_id) -> list:
        return [{"id": "doc-1", "path": "docs/intro.md", "content": "x " + "본문 " * 200}]

    async def _no_new_content(_team_id, _since) -> bool:
        return False

    swept: list[set] = []

    async def _fake_sweep(_team_id, keep_slugs, _min_chars) -> int:
        swept.append(keep_slugs)
        return 2

    def _boom(*_a, **_k):
        raise AssertionError("LLM must not be called on a change-gated build")

    monkeypatch.setattr(team_wiki_worker, "_resolve_team", _fake_resolve)
    monkeypatch.setattr(team_wiki_worker, "_list_team_memories", _fake_memories)
    monkeypatch.setattr(team_wiki_worker, "_list_team_documents", _fake_docs)
    monkeypatch.setattr(team_wiki_worker, "_team_has_new_content", _no_new_content)
    monkeypatch.setattr(team_wiki_worker, "_sweep_stale_llm_articles", _fake_sweep)
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", lambda *a, **k: None)
    monkeypatch.setattr(team_wiki_worker, "load_user_fallbacks", _boom)
    monkeypatch.setattr(team_wiki_worker, "chat_text", _boom)

    summary = await team_wiki_worker.build_team_wiki("team-1", AsyncMock())
    assert summary["skipped"] is True
    assert summary["articles_built"] == 0
    assert summary["cleaned_thin"] == 2
    # Sweep ran with the cluster's stable slug as the keep-set.
    assert swept == [{"folder-docs"}]

    # force=True bypasses the gate (would call the LLM, here load_user_fallbacks
    # raises) — proves the manual button still rebuilds.
    with pytest.raises(AssertionError):
        await team_wiki_worker.build_team_wiki("team-1", AsyncMock(), force=True)

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
    _first_heading,
    _human_category,
    _in_dawn_window,
    _memories_changed_since,
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


def test_memories_changed_since() -> None:
    from datetime import datetime, timezone

    since = datetime(2026, 5, 1)
    since_epoch = since.replace(tzinfo=timezone.utc).timestamp()
    # A memory updated after `since` counts as changed.
    assert _memories_changed_since([{"updated_at": since_epoch + 100}], since) is True
    # All older → unchanged.
    assert _memories_changed_since([{"updated_at": since_epoch - 100}], since) is False
    # Missing/zero timestamps are treated as old, not changed.
    assert _memories_changed_since([{}, {"updated_at": 0}], since) is False
    # since=None (never built) → always changed.
    assert _memories_changed_since([], None) is True


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


def test_first_heading_extracts_lead_title() -> None:
    body = "# Yokogawa BPM 시스템 기술 레퍼런스\n\n## 개요\n본문..."
    assert _first_heading(body) == "Yokogawa BPM 시스템 기술 레퍼런스"


def test_first_heading_skips_fenced_code_and_strips_emphasis() -> None:
    body = "```\n# not a heading\n```\n\n## **실제 제목** ##\n내용"
    assert _first_heading(body) == "실제 제목"


def test_first_heading_returns_none_without_heading() -> None:
    assert _first_heading("그냥 본문, 헤딩 없음") is None
    assert _first_heading("") is None


def test_first_heading_skips_boilerplate_section_headings() -> None:
    # The body template opens with generic section headings (개요/출처/…); none
    # is a usable title, so a body made only of them yields no heading title.
    body = "## 개요\n본문\n## 핵심 규칙·결정\n...\n## 출처\n- x"
    assert _first_heading(body) is None
    # A descriptive heading after the boilerplate is still picked up.
    body2 = "## 개요\n본문\n## Yokogawa 배포 파이프라인\n내용"
    assert _first_heading(body2) == "Yokogawa 배포 파이프라인"


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
        def now(cls, tz=None) -> "_StubDateTime":
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


@pytest.mark.asyncio
async def test_build_team_wiki_gate_rebuilds_when_only_memory_changed(monkeypatch) -> None:
    """Docs unchanged but a team memory is newer than the last build → the gate
    must NOT skip. (Regression: the gate used to look at documents only.)"""
    from datetime import datetime, timezone

    from piloci.curator import team_wiki_worker

    last_built = datetime(2026, 5, 1)
    fresh_mem_ts = last_built.replace(tzinfo=timezone.utc).timestamp() + 3600

    async def _fake_resolve(_team_id: str) -> dict:
        return {"id": "team-1", "name": "Team", "owner_id": "owner-1", "_last_built": last_built}

    async def _fake_memories(_team_id, _store) -> list:
        # Long enough to clear the _MIN_CLUSTER_CHARS substance gate so a cluster
        # actually forms (otherwise the build short-circuits before the gate).
        return [
            {
                "id": "m1",
                "content": "갱신된 메모리 내용입니다. " * 60,
                "tags": ["plan"],
                "updated_at": fresh_mem_ts,
            }
        ]

    async def _fake_docs(_team_id) -> list:
        return []

    async def _no_doc_change(_team_id, _since, **_kw) -> bool:
        return False

    def _reached(*_a, **_k):
        raise AssertionError("REACHED_BUILD")

    monkeypatch.setattr(team_wiki_worker, "_resolve_team", _fake_resolve)
    monkeypatch.setattr(team_wiki_worker, "_list_team_memories", _fake_memories)
    monkeypatch.setattr(team_wiki_worker, "_list_team_documents", _fake_docs)
    monkeypatch.setattr(team_wiki_worker, "_team_has_new_content", _no_doc_change)
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", lambda *a, **k: None)
    # If the gate wrongly skips, this never runs and no exception is raised.
    monkeypatch.setattr(team_wiki_worker, "load_user_fallbacks", _reached)

    with pytest.raises(AssertionError, match="REACHED_BUILD"):
        await team_wiki_worker.build_team_wiki("team-1", AsyncMock())


@pytest.mark.asyncio
async def test_build_team_wiki_real_db_pipeline_and_helpers(monkeypatch, tmp_path) -> None:
    """End-to-end against a real SQLite DB with the REAL upsert/sweep/mark + the
    critique→revise→judge→retry loop. Exercises the DB-touching code paths
    (insert + update/revision branches, stale-article + revision sweep, the
    memory-aware change signal) that the fully-mocked smoke test can't reach."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from piloci.curator import team_wiki_worker
    from piloci.db import session as db_session
    from piloci.db.models import Team, TeamDocument, TeamWikiArticle, TeamWikiRevision, User
    from piloci.db.session import init_db

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wiki.db'}")
    await init_db(engine=engine)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _test_session():
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    # Worker helpers do `from piloci.db.session import async_session` per call,
    # so patching the module attribute routes them to the test DB.
    monkeypatch.setattr(db_session, "async_session", _test_session)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with factory() as s:
        s.add(
            User(
                id="owner",
                email="o@e.com",
                created_at=now,
                is_active=True,
                approval_status="approved",
            )
        )
        s.add(Team(id="t1", name="T", owner_id="owner", created_at=now, auto_wiki_enabled=True))
        s.add(
            TeamDocument(
                id="d1",
                team_id="t1",
                author_id="owner",
                path="docs/guide.md",
                content="가이드 본문 내용입니다. " * 80,
                content_hash="h1",
                updated_at=now,
                created_at=now,
            )
        )
        # Stale LLM article from an earlier build — sweep must delete it (+ its
        # revision) because its slug isn't a current cluster slug.
        s.add(
            TeamWikiArticle(
                id="old1",
                team_id="t1",
                slug="folder-old",
                title="옛글",
                content="(empty)",
                revision=1,
                author_kind="llm",
                created_at=now,
                updated_at=now,
                sources_json="[]",
            )
        )
        s.add(
            TeamWikiRevision(
                id="rev-old1",
                article_id="old1",
                team_id="t1",
                revision=1,
                title="옛글",
                content="x",
                author_kind="llm",
                created_at=now,
            )
        )
        await s.commit()

    body_md = "# 가이드\n\n## 개요\n" + "이 문서는 팀 가이드입니다. " * 30

    async def _fake_chat_text(messages, **kw):
        rec = kw.get("record_target")
        if rec is not None:
            rec.append("glm")
        return body_md

    state = {"judge": 0, "build": 0}

    async def _fake_chat_json(messages, **kw):
        sysmsg = messages[0]["content"]
        if sysmsg == team_wiki_worker._CRITIQUE_SYSTEM:
            return {"issues": ["보강 필요"], "missing": [], "style": [], "severity": "medium"}
        if sysmsg == team_wiki_worker._JUDGE_SYSTEM:
            state["judge"] += 1
            if state["judge"] == 1:  # first judge low → triggers one retry
                return {"accuracy": 2, "completeness": 4, "clarity": 4, "action": "retry"}
            return {"accuracy": 5, "completeness": 5, "clarity": 5, "action": "accept"}
        # _META_SYSTEM — vary the title per build so the 2nd build hits the
        # update/revision branch instead of the hash-skip "unchanged" branch.
        state["build"] += 1
        return {"title": f"팀 가이드 v{state['build']}", "summary": "요약", "linked_topics": []}

    class _Target:
        label = "glm"

    async def _fake_fallbacks(_uid):
        return [_Target()]

    async def _no_links(*a, **k):
        return []

    monkeypatch.setattr(team_wiki_worker, "chat_text", _fake_chat_text)
    monkeypatch.setattr(team_wiki_worker, "chat_json", _fake_chat_json)
    monkeypatch.setattr(team_wiki_worker, "load_user_fallbacks", _fake_fallbacks)
    monkeypatch.setattr(team_wiki_worker, "_fetch_linked_topic_context", _no_links)
    monkeypatch.setattr(team_wiki_worker, "build_team_vault", lambda *a, **k: {})
    monkeypatch.setattr(team_wiki_worker, "save_team_vault", lambda *a, **k: None)
    monkeypatch.setattr(team_wiki_worker, "merge_wiki_articles", lambda *a, **k: {})

    store = AsyncMock()
    store.team_list.return_value = []  # no team memories

    # First build → insert path + sweep deletes the stale "folder-old" article.
    summary = await team_wiki_worker.build_team_wiki("t1", store, force=True)
    assert summary["success"] is True
    assert summary["articles_built"] == 1
    assert summary["cleaned_thin"] >= 1  # the stale article was swept

    async with factory() as s:
        from sqlalchemy import select

        slugs = (
            (await s.execute(select(TeamWikiArticle.slug).where(TeamWikiArticle.team_id == "t1")))
            .scalars()
            .all()
        )
        assert "folder-docs" in slugs
        assert "folder-old" not in slugs  # swept
        # Orphan revision of the swept article is gone too.
        rev_ids = (
            (
                await s.execute(
                    select(TeamWikiRevision.id).where(TeamWikiRevision.article_id == "old1")
                )
            )
            .scalars()
            .all()
        )
        assert rev_ids == []

    # Second build → existing slug, different title → update/revision branch.
    summary2 = await team_wiki_worker.build_team_wiki("t1", store, force=True)
    assert summary2["success"] is True
    async with factory() as s:
        from sqlalchemy import select

        rev = (
            await s.execute(
                select(TeamWikiArticle.revision).where(
                    TeamWikiArticle.slug == "folder-docs", TeamWikiArticle.team_id == "t1"
                )
            )
        ).scalar_one()
        assert rev >= 2  # revision bumped on update

    # Memory-aware change signal: store branches.
    future = now.replace(tzinfo=timezone.utc).timestamp() + 3600
    fresh_store = AsyncMock()
    fresh_store.team_list.return_value = [{"id": "m", "updated_at": future}]
    assert await team_wiki_worker._team_has_new_content("t1", now, store=fresh_store) is True
    assert await team_wiki_worker._team_has_new_content("t1", None, store=fresh_store) is True
    assert await team_wiki_worker._team_has_new_content("t1", now, store=store) is False

    # Due-for-wiki worker pre-filter (team auto-enabled but just built → not due).
    assert await team_wiki_worker._teams_due_for_wiki(store) == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_team_wiki_worker_runs_one_cycle(monkeypatch) -> None:
    """The daily daemon: in the dawn window it builds every due team, then stops
    cleanly when the stop event is set. (Covers the worker loop body.)"""
    from piloci.curator import team_wiki_worker

    built: list[str] = []

    async def _due(store=None) -> list[str]:
        return ["t1", "t2"]

    async def _build(team_id, store, *, force=False) -> dict:
        built.append(team_id)
        return {"articles_built": 1, "generated_by": "glm"}

    monkeypatch.setattr(team_wiki_worker, "_in_dawn_window", lambda: True)
    monkeypatch.setattr(team_wiki_worker, "_teams_due_for_wiki", _due)
    monkeypatch.setattr(team_wiki_worker, "build_team_wiki", _build)

    class _Stop:
        """Stays unset until both due teams are built, then trips — so one full
        cycle runs and the inner poll-sleep is skipped (no real sleeping)."""

        def is_set(self) -> bool:
            return len(built) >= 2

    await team_wiki_worker.run_team_wiki_worker(object(), AsyncMock(), _Stop())
    assert built == ["t1", "t2"]


@pytest.mark.asyncio
async def test_compress_text_map_reduce_and_failure_keep_content(monkeypatch) -> None:
    """No-loss compression: oversized source is map-reduced down; a failed map
    chunk keeps its raw text (never dropped) and the no-shrink guard stops the
    recursion instead of looping."""
    from piloci.curator import team_wiki_worker

    big = "원본 자료 내용 " * 5000  # well over the map-chunk size

    # Happy path: each chunk maps to a short note → the text shrinks.
    async def _ok(messages, **kw) -> dict:
        return {"notes": "핵심 요약"}

    monkeypatch.setattr(team_wiki_worker, "chat_json", _ok)
    out = await team_wiki_worker._compress_text(big, 200, [], [])
    assert "핵심 요약" in out
    assert len(out) < len(big)

    # Failure path: every map raises → raw chunks are preserved (no content loss),
    # and since that doesn't shrink, the guard returns without recursing forever.
    async def _boom(messages, **kw) -> dict:
        raise RuntimeError("map chunk down")

    monkeypatch.setattr(team_wiki_worker, "chat_json", _boom)
    out2 = await team_wiki_worker._compress_text(big, 200, [], [])
    assert "원본 자료 내용" in out2  # raw content survived the failure

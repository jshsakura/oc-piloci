"""Tests for the auto-maintained team entry-point map ``LOCI.md``.

``build_loci_md`` is pure (no I/O) and gets the bulk of the assertions;
``refresh_team_index`` is exercised against a real tmp SQLite + the
tmp-backed ``lancedb_store`` fixture, with ``embed_one`` stubbed so no model
loads.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from piloci.curator import team_index
from piloci.curator.team_index import LOCI_FILENAME, build_loci_md
from piloci.storage.lancedb_store import VECTOR_SIZE

# ---------------------------------------------------------------------------
# build_loci_md (pure)
# ---------------------------------------------------------------------------


def test_build_loci_md_has_nl_recall_hint_and_team_id():
    md = build_loci_md({"id": "t1", "name": "YKO"}, [], [])
    assert "# YKO" in md
    assert "여기서 시작" in md
    assert 'recall(team_id="t1"' in md  # natural-language entry point


def test_build_loci_md_uses_wikilinks_and_groups_by_folder():
    docs = [
        {"path": "docs/auth/design.md"},
        {"path": "docs/auth/tokens.md"},
        {"path": "readme.md"},
    ]
    md = build_loci_md({"id": "t1", "name": "T"}, docs, [])
    # Wikilinks strip the .md so Obsidian's graph resolves; LLM reads verbatim.
    assert "[[docs/auth/design]]" in md
    assert "[[docs/auth/tokens]]" in md
    assert "[[readme]]" in md
    # Grouped under the top-level folder header.
    assert "**docs/**" in md


def test_build_loci_md_excludes_loci_itself():
    docs = [{"path": LOCI_FILENAME}, {"path": "a.md"}]
    md = build_loci_md({"id": "t1", "name": "T"}, docs, [])
    assert "[[a]]" in md
    assert f"[[{LOCI_FILENAME[:-3]}]]" not in md  # no self-link
    assert "(1건)" in md  # only the one real doc counted


def test_build_loci_md_lists_wiki_articles():
    arts = [{"slug": "payments", "title": "결제", "summary": "결제 흐름"}]
    md = build_loci_md({"id": "t1", "name": "T"}, [], arts)
    assert "[[wiki/payments|결제]]" in md
    assert "결제 흐름" in md


def test_build_loci_md_empty_team_is_graceful():
    md = build_loci_md({"id": "t1", "name": "T"}, [], [])
    assert "아직 공유된 문서가 없습니다" in md


# ---------------------------------------------------------------------------
# refresh_team_index (DB + store)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_factory(tmp_path, monkeypatch):
    from piloci.db.models import Team, TeamDocument, User
    from piloci.db.session import init_db

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'idx.db'}")
    await init_db(engine=engine)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _session():
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    # refresh_team_index imports async_session from piloci.db.session at call time.
    monkeypatch.setattr("piloci.db.session.async_session", _session)

    now = datetime.now(timezone.utc)
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
        s.add(Team(id="t1", name="YKO", owner_id="owner", created_at=now))
        s.add(
            TeamDocument(
                id="d1",
                team_id="t1",
                author_id="owner",
                uploader_id="owner",
                updated_by_id="owner",
                path="docs/auth/design.md",
                content="auth design body",
                content_hash="h1",
                version=1,
                is_binary=False,
                size=16,
                updated_at=now,
                created_at=now,
                is_deleted=False,
            )
        )
        await s.commit()
    return factory


@pytest.fixture
def fixed_embed(monkeypatch):
    async def _embed(_text, **_kwargs):
        return [0.1] * VECTOR_SIZE

    monkeypatch.setattr("piloci.curator.team_doc_index.embed_one", _embed)


@pytest.fixture
def settings_obj(tmp_path):
    from piloci.config import Settings

    return Settings(
        lancedb_path=tmp_path / "lancedb",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )


@pytest.mark.asyncio
async def test_refresh_creates_loci_doc_and_is_searchable(
    db_factory, lancedb_store, fixed_embed, settings_obj
):
    from sqlalchemy import select

    from piloci.db.models import TeamDocument

    ok = await team_index.refresh_team_index(lancedb_store, "t1", settings=settings_obj)
    assert ok is True

    async with db_factory() as s:
        loci = (
            await s.execute(
                select(TeamDocument).where(
                    TeamDocument.team_id == "t1", TeamDocument.path == LOCI_FILENAME
                )
            )
        ).scalar_one_or_none()
    assert loci is not None
    assert "[[docs/auth/design]]" in loci.content
    assert loci.uploader_id == "owner"

    # Indexed → recall finds the map by a natural-language-ish query.
    rows = await lancedb_store.team_hybrid_search(
        "t1", query_text="시작 지도", query_vector=[0.1] * VECTOR_SIZE, top_k=5
    )
    assert any(r.get("metadata", {}).get("path") == LOCI_FILENAME for r in rows) or any(
        LOCI_FILENAME in (r.get("content") or "") for r in rows
    )


@pytest.mark.asyncio
async def test_refresh_is_idempotent_when_unchanged(
    db_factory, lancedb_store, fixed_embed, settings_obj
):
    from sqlalchemy import select

    from piloci.db.models import TeamDocument

    await team_index.refresh_team_index(lancedb_store, "t1", settings=settings_obj)
    async with db_factory() as s:
        v1 = (
            await s.execute(
                select(TeamDocument.version).where(
                    TeamDocument.team_id == "t1", TeamDocument.path == LOCI_FILENAME
                )
            )
        ).scalar_one()

    # Re-run with no document changes → content hash matches → no version bump.
    await team_index.refresh_team_index(lancedb_store, "t1", settings=settings_obj)
    async with db_factory() as s:
        v2 = (
            await s.execute(
                select(TeamDocument.version).where(
                    TeamDocument.team_id == "t1", TeamDocument.path == LOCI_FILENAME
                )
            )
        ).scalar_one()
    assert v1 == v2


@pytest.mark.asyncio
async def test_refresh_missing_team_returns_false(
    db_factory, lancedb_store, fixed_embed, settings_obj
):
    assert (
        await team_index.refresh_team_index(lancedb_store, "no-such-team", settings=settings_obj)
    ) is False

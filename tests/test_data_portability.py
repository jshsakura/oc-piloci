from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import orjson
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from piloci.api import data_portability as dp
from piloci.config import Settings
from piloci.db.models import Project, UserProfile
from piloci.db.session import init_db
from piloci.storage.lancedb_store import VECTOR_SIZE, MemoryStore


def _settings(*, database_url: str, lancedb_path) -> Settings:
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        database_url=database_url,
        lancedb_path=lancedb_path,
    )


@pytest.fixture
async def env(monkeypatch, tmp_path) -> AsyncGenerator[tuple[Settings, MemoryStore], None]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'piloci.db'}"
    settings = _settings(database_url=database_url, lancedb_path=tmp_path / "lancedb")

    monkeypatch.setattr("piloci.db.session.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.db.session._engine", None)
    monkeypatch.setattr("piloci.db.session._session_factory", None)

    eng: AsyncEngine = create_async_engine(
        database_url, echo=False, connect_args={"check_same_thread": False}
    )
    await init_db(engine=eng)

    factory = async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    @asynccontextmanager
    async def _test_async_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    monkeypatch.setattr(dp, "async_session", _test_async_session)

    store = MemoryStore(settings)
    await store.ensure_collection()

    try:
        yield settings, store
    finally:
        await store.close()
        await eng.dispose()


async def _seed_user(store: MemoryStore, *, user_id: str) -> tuple[str, str]:
    """Insert a user with 2 projects, 3 memories, 1 profile. Returns (slug_a, slug_b)."""
    now = datetime.now(timezone.utc)
    project_a = Project(
        id="proj-a",
        user_id=user_id,
        slug="alpha",
        name="Alpha",
        description="primary",
        created_at=now,
        updated_at=now,
    )
    project_b = Project(
        id="proj-b",
        user_id=user_id,
        slug="beta",
        name="Beta",
        description=None,
        created_at=now,
        updated_at=now,
    )
    profile = UserProfile(
        user_id=user_id,
        project_id="proj-a",
        profile_json=orjson.dumps({"static": ["likes pi"], "dynamic": []}).decode(),
        updated_at=now,
    )

    async with dp.async_session() as db:
        # User row not strictly required for export logic — projects FK will fail
        # without one, so insert via raw SQL to avoid pulling in auth flow.
        from sqlalchemy import text

        await db.execute(
            text(
                "INSERT INTO users (id, email, email_verified, created_at, "
                "is_active, is_admin, approval_status, quota_bytes, "
                "failed_login_count, totp_enabled) VALUES "
                "(:id, :email, 0, :now, 1, 0, 'approved', 1073741824, 0, 0)"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "now": now},
        )
        db.add_all([project_a, project_b, profile])

    vec_a = [0.1] * VECTOR_SIZE
    vec_b = [0.2] * VECTOR_SIZE
    await store.save(
        user_id=user_id,
        project_id="proj-a",
        content="memory one",
        vector=vec_a,
        tags=["alpha"],
        metadata={"source": "ui"},
    )
    await store.save(
        user_id=user_id,
        project_id="proj-a",
        content="memory two",
        vector=vec_a,
        tags=["alpha"],
    )
    await store.save(
        user_id=user_id,
        project_id="proj-b",
        content="memory three",
        vector=vec_b,
        tags=["beta"],
    )

    return "alpha", "beta"


@pytest.mark.asyncio
async def test_build_export_archive_round_trip(env):
    settings, store = env
    await _seed_user(store, user_id="user-1")

    archive = await dp.build_export_archive(
        user_id="user-1",
        store=store,
        settings=settings,
        piloci_version="0.0.0-test",
    )

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = set(zf.namelist())
        assert names == {
            dp.MANIFEST_NAME,
            dp.PROJECTS_NAME,
            dp.MEMORIES_NAME,
            dp.PROFILES_NAME,
        }

        manifest = orjson.loads(zf.read(dp.MANIFEST_NAME))
        assert manifest["archive_version"] == dp.ARCHIVE_VERSION
        assert manifest["embed_model"] == settings.embed_model
        assert manifest["vector_size"] == VECTOR_SIZE
        assert manifest["user_id"] == "user-1"
        assert manifest["counts"] == {"projects": 2, "memories": 3, "profiles": 1}
        for key in (dp.PROJECTS_NAME, dp.MEMORIES_NAME, dp.PROFILES_NAME):
            assert manifest["checksums"][key].startswith("sha256:")

        projects = orjson.loads(zf.read(dp.PROJECTS_NAME))
        assert {p["slug"] for p in projects} == {"alpha", "beta"}

        table = pq.read_table(io.BytesIO(zf.read(dp.MEMORIES_NAME)))
        assert table.num_rows == 3
        contents = set(table.column("content").to_pylist())
        assert contents == {"memory one", "memory two", "memory three"}
        for vec in table.column("vector").to_pylist():
            assert len(vec) == VECTOR_SIZE

        profiles = orjson.loads(zf.read(dp.PROFILES_NAME))
        assert len(profiles) == 1
        assert profiles[0]["project_id"] == "proj-a"


@pytest.mark.asyncio
async def test_import_archive_into_fresh_user_preserves_vectors(env):
    settings, store = env
    await _seed_user(store, user_id="user-source")
    archive = await dp.build_export_archive(
        user_id="user-source",
        store=store,
        settings=settings,
        piloci_version="0.0.0-test",
    )

    # Insert the destination user and try to import the source's archive
    now = datetime.now(timezone.utc)
    async with dp.async_session() as db:
        from sqlalchemy import text

        await db.execute(
            text(
                "INSERT INTO users (id, email, email_verified, created_at, "
                "is_active, is_admin, approval_status, quota_bytes, "
                "failed_login_count, totp_enabled) VALUES "
                "(:id, :email, 0, :now, 1, 0, 'approved', 1073741824, 0, 0)"
            ),
            {"id": "user-dest", "email": "dest@example.com", "now": now},
        )

    async def _refuse_embed(_: str) -> list[float]:
        raise AssertionError("embed_one should not be called when models match")

    summary = await dp.import_archive(
        archive,
        user_id="user-dest",
        store=store,
        settings=settings,
        embed_one_fn=_refuse_embed,
    )

    assert summary.projects_imported == 2
    assert summary.projects_renamed == 0
    assert summary.memories_imported == 3
    assert summary.profiles_imported == 1
    assert summary.re_embedded is False

    async with dp.async_session() as db:
        slugs = (
            await db.execute(
                select(Project.slug).where(Project.user_id == "user-dest").order_by(Project.slug)
            )
        ).all()
        assert [s[0] for s in slugs] == ["alpha", "beta"]

        new_alpha_id = (
            await db.execute(
                select(Project.id).where(Project.user_id == "user-dest", Project.slug == "alpha")
            )
        ).scalar_one()

    rows = await store.list(user_id="user-dest", project_id=new_alpha_id, limit=10)
    assert {r["content"] for r in rows} == {"memory one", "memory two"}


@pytest.mark.asyncio
async def test_import_archive_renames_colliding_project_slugs(env):
    settings, store = env
    await _seed_user(store, user_id="user-1")
    archive = await dp.build_export_archive(
        user_id="user-1",
        store=store,
        settings=settings,
        piloci_version="0.0.0-test",
    )

    # Re-import the same archive back into the same user — every slug should collide
    summary = await dp.import_archive(
        archive,
        user_id="user-1",
        store=store,
        settings=settings,
        embed_one_fn=lambda _t: (_ for _ in ()).throw(AssertionError("no reembed")),
    )

    assert summary.projects_imported == 2
    assert summary.projects_renamed == 2

    async with dp.async_session() as db:
        slugs = (
            await db.execute(
                select(Project.slug).where(Project.user_id == "user-1").order_by(Project.slug)
            )
        ).all()
        observed = [s[0] for s in slugs]
        assert "alpha" in observed
        assert "alpha-imported" in observed
        assert "beta" in observed
        assert "beta-imported" in observed
        assert len(observed) == len(set(observed))


@pytest.mark.asyncio
async def test_import_archive_rejects_embed_model_mismatch_without_reembed(env):
    settings, store = env
    await _seed_user(store, user_id="user-1")
    archive = await dp.build_export_archive(
        user_id="user-1",
        store=store,
        settings=settings,
        piloci_version="0.0.0-test",
    )

    # Tamper the archive's manifest so it advertises a different embed model
    tampered_buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(archive)) as src,
        zipfile.ZipFile(tampered_buf, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for name in src.namelist():
            data = src.read(name)
            if name == dp.MANIFEST_NAME:
                manifest = orjson.loads(data)
                manifest["embed_model"] = "different/embed-model"
                data = orjson.dumps(manifest)
            dst.writestr(name, data)
    tampered = tampered_buf.getvalue()

    with pytest.raises(dp.ArchiveError) as excinfo:
        await dp.import_archive(
            tampered,
            user_id="user-2",
            store=store,
            settings=settings,
            embed_one_fn=lambda _t: (_ for _ in ()).throw(AssertionError("no reembed")),
        )
    assert excinfo.value.status == 409


@pytest.mark.asyncio
async def test_import_archive_reembeds_when_allowed(env):
    settings, store = env
    await _seed_user(store, user_id="user-source")
    archive = await dp.build_export_archive(
        user_id="user-source",
        store=store,
        settings=settings,
        piloci_version="0.0.0-test",
    )

    tampered_buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(archive)) as src,
        zipfile.ZipFile(tampered_buf, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for name in src.namelist():
            data = src.read(name)
            if name == dp.MANIFEST_NAME:
                manifest = orjson.loads(data)
                manifest["embed_model"] = "different/embed-model"
                data = orjson.dumps(manifest)
            dst.writestr(name, data)
    tampered = tampered_buf.getvalue()

    now = datetime.now(timezone.utc)
    async with dp.async_session() as db:
        from sqlalchemy import text

        await db.execute(
            text(
                "INSERT INTO users (id, email, email_verified, created_at, "
                "is_active, is_admin, approval_status, quota_bytes, "
                "failed_login_count, totp_enabled) VALUES "
                "(:id, :email, 0, :now, 1, 0, 'approved', 1073741824, 0, 0)"
            ),
            {"id": "user-dest", "email": "dest@example.com", "now": now},
        )

    seen: list[str] = []

    async def _fake_embed(text: str) -> list[float]:
        seen.append(text)
        return [0.42] * VECTOR_SIZE

    summary = await dp.import_archive(
        tampered,
        user_id="user-dest",
        store=store,
        settings=settings,
        embed_one_fn=_fake_embed,
        allow_reembed=True,
    )

    assert summary.re_embedded is True
    assert summary.memories_imported == 3
    assert sorted(seen) == ["memory one", "memory three", "memory two"]


@pytest.mark.asyncio
async def test_import_archive_rejects_garbage_zip(env):
    settings, store = env
    with pytest.raises(dp.ArchiveError):
        await dp.import_archive(
            b"not a zip",
            user_id="user-1",
            store=store,
            settings=settings,
            embed_one_fn=lambda _t: (_ for _ in ()).throw(AssertionError("never")),
        )


@pytest.mark.asyncio
async def test_import_archive_rejects_unsupported_archive_version(env):
    settings, store = env

    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            dp.MANIFEST_NAME,
            orjson.dumps({"archive_version": 999, "embed_model": settings.embed_model}),
        )
    archive = sink.getvalue()

    with pytest.raises(dp.ArchiveError):
        await dp.import_archive(
            archive,
            user_id="user-1",
            store=store,
            settings=settings,
            embed_one_fn=lambda _t: (_ for _ in ()).throw(AssertionError("never")),
        )


def test_next_free_slug_picks_base_when_free():
    chosen, renamed = dp._next_free_slug("foo", set())
    assert chosen == "foo"
    assert renamed is False


def test_metadata_export_coercion_keeps_only_json_objects():
    assert dp._coerce_metadata_str({"source": "ui"}) == '{"source":"ui"}'
    assert dp._coerce_metadata_str(b'{"source":"bytes"}') == '{"source":"bytes"}'
    assert dp._coerce_metadata_str('{"source":"str"}') == '{"source":"str"}'
    assert dp._coerce_metadata_str(b"not-json") == "{}"
    assert dp._coerce_metadata_str("not-json") == "{}"
    assert dp._coerce_metadata_str('["not", "object"]') == "{}"
    assert dp._coerce_metadata_str(None) == "{}"


def test_import_normalizers_reject_unusable_values():
    assert dp._normalize_slug(None) is None
    assert dp._normalize_slug(" Bad Slug ") is None
    assert dp._normalize_slug(" Valid-Slug ") == "valid-slug"
    assert dp._normalize_tags(None) == []
    assert dp._normalize_tags("solo") == []
    assert dp._normalize_tags(["alpha", 42]) == ["alpha", "42"]
    assert dp._normalize_metadata({"ok": True}) == {"ok": True}
    assert dp._normalize_metadata(b'{"ok":true}') == {"ok": True}
    assert dp._normalize_metadata('{"ok":true}') == {"ok": True}
    assert dp._normalize_metadata(b"bad") == {}
    assert dp._normalize_metadata("bad") == {}
    assert dp._normalize_metadata("[]") == {}


@pytest.mark.asyncio
async def test_build_memories_parquet_empty_project_list_does_not_touch_store():
    class Store:
        async def _get_table(self):
            raise AssertionError("empty export should not query LanceDB")

    payload, count = await dp._build_memories_parquet("user-1", [], Store())

    table = pq.read_table(io.BytesIO(payload))
    assert count == 0
    assert table.num_rows == 0
    assert table.schema == dp._MEMORIES_SCHEMA


@pytest.mark.asyncio
async def test_build_memories_parquet_serializes_lancedb_rows():
    class Query:
        def where(self, where_clause):
            assert where_clause == "user_id = 'user-1' AND project_id IN ('proj-a')"
            return self

        async def to_list(self):
            return [
                {
                    "memory_id": "mem-1",
                    "project_id": "proj-a",
                    "content": "hello",
                    "tags": ["alpha", 7],
                    "metadata": b'{"kind":"note"}',
                    "created_at": 11,
                    "updated_at": 12,
                    "vector": [1, "2.5"],
                }
            ]

    class Table:
        def query(self):
            return Query()

    class Store:
        async def _get_table(self):
            return Table()

    payload, count = await dp._build_memories_parquet(
        "user-1", [SimpleNamespace(id="proj-a")], Store()
    )

    table = pq.read_table(io.BytesIO(payload))
    assert count == 1
    assert table.column("memory_id").to_pylist() == ["mem-1"]
    assert table.column("tags").to_pylist() == [["alpha", "7"]]
    assert table.column("metadata").to_pylist() == ['{"kind":"note"}']
    assert table.column("vector").to_pylist() == [[1.0, 2.5]]


def test_parse_archive_rejects_invalid_payload_shapes():
    with pytest.raises(dp.ArchiveError, match="missing manifest"):
        sink = io.BytesIO()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(dp.PROJECTS_NAME, b"[]")
        dp._parse_archive(sink.getvalue())

    with pytest.raises(dp.ArchiveError, match="not valid JSON"):
        sink = io.BytesIO()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(dp.MANIFEST_NAME, b"{")
        dp._parse_archive(sink.getvalue())

    with pytest.raises(dp.ArchiveError, match="manifest.json must be a JSON object"):
        sink = io.BytesIO()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(dp.MANIFEST_NAME, b"[]")
        dp._parse_archive(sink.getvalue())

    with pytest.raises(dp.ArchiveError, match="profiles.json must be a JSON list"):
        sink = io.BytesIO()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                dp.MANIFEST_NAME,
                orjson.dumps({"archive_version": dp.ARCHIVE_VERSION}),
            )
            zf.writestr(dp.PROFILES_NAME, b"{}")
        dp._parse_archive(sink.getvalue())

    with pytest.raises(dp.ArchiveError, match="projects.json must be a JSON list"):
        sink = io.BytesIO()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                dp.MANIFEST_NAME,
                orjson.dumps({"archive_version": dp.ARCHIVE_VERSION}),
            )
            zf.writestr(dp.PROJECTS_NAME, b"{}")
        dp._parse_archive(sink.getvalue())


def test_parse_archive_uses_empty_defaults_for_optional_payloads():
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            dp.MANIFEST_NAME,
            orjson.dumps({"archive_version": dp.ARCHIVE_VERSION}),
        )

    manifest, projects, memories, profiles = dp._parse_archive(sink.getvalue())

    assert manifest["archive_version"] == dp.ARCHIVE_VERSION
    assert projects == []
    assert memories.num_rows == 0
    assert profiles == []


def test_safe_id_rejects_query_breakout_characters():
    assert dp._safe_id("user-1") == "user-1"
    with pytest.raises(ValueError):
        dp._safe_id("bad'user")


@pytest.mark.asyncio
async def test_import_archive_skips_invalid_projects_memories_and_profiles(monkeypatch):
    table = pq.read_table(io.BytesIO(_seed_memories_parquet_for_import()))
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            dp.MANIFEST_NAME,
            orjson.dumps(
                {
                    "archive_version": dp.ARCHIVE_VERSION,
                    "embed_model": "different-model",
                    "vector_size": dp.VECTOR_SIZE,
                }
            ),
        )
        zf.writestr(
            dp.PROJECTS_NAME,
            orjson.dumps(
                [
                    "not-a-project",
                    {"id": 7, "slug": "alpha", "name": "Alpha"},
                    {"id": "old-a", "slug": "bad slug", "name": "Alpha"},
                    {"id": "old-b", "slug": "beta", "name": None},
                ]
            ),
        )
        mem_sink = io.BytesIO()
        pq.write_table(table, mem_sink)
        zf.writestr(dp.MEMORIES_NAME, mem_sink.getvalue())
        zf.writestr(
            dp.PROFILES_NAME,
            orjson.dumps(
                [
                    "not-a-profile",
                    {"project_id": 123, "profile_json": "{}"},
                    {"project_id": "missing", "profile_json": "{}"},
                    {"project_id": "missing", "profile_json": {}},
                ]
            ),
        )

    async def existing_slugs(user_id):
        return set()

    class Store:
        async def save_many(self, **kwargs):
            raise AssertionError("invalid archive rows should not be imported")

    monkeypatch.setattr(dp, "_existing_slugs_for_user", existing_slugs)

    async def embed_one(text):
        raise AssertionError("unmapped memory rows should not be re-embedded")

    summary = await dp.import_archive(
        sink.getvalue(),
        user_id="user-1",
        store=Store(),
        settings=SimpleNamespace(embed_model="current-model"),
        embed_one_fn=embed_one,
        allow_reembed=True,
    )

    assert summary.projects_imported == 0
    assert summary.memories_imported == 0
    assert summary.profiles_imported == 0
    assert summary.re_embedded is True


def _seed_memories_parquet_for_import() -> bytes:
    out = io.BytesIO()
    pq.write_table(
        dp.pa.Table.from_pydict(
            {
                "memory_id": ["mem-1"],
                "project_id": ["missing"],
                "content": ["ignored"],
                "tags": [[]],
                "metadata": ["{}"],
                "created_at": [1],
                "updated_at": [2],
                "vector": [[0.1] * dp.VECTOR_SIZE],
            },
            schema=dp._MEMORIES_SCHEMA,
        ),
        out,
    )
    return out.getvalue()


def test_next_free_slug_appends_imported_suffix_on_collision():
    chosen, renamed = dp._next_free_slug("foo", {"foo"})
    assert chosen == "foo-imported"
    assert renamed is True


def test_next_free_slug_increments_when_imported_already_taken():
    chosen, renamed = dp._next_free_slug("foo", {"foo", "foo-imported", "foo-imported-2"})
    assert chosen == "foo-imported-3"
    assert renamed is True

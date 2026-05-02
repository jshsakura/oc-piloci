from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import orjson
import pyarrow.parquet as pq
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from piloci.api import data_portability as dp
from piloci.api import routes
from piloci.config import Settings
from piloci.db.models import Project
from piloci.db.session import init_db
from piloci.storage.lancedb_store import VECTOR_SIZE, MemoryStore

USER_ID = "user-export"


def _make_request(
    *,
    method: str,
    path: str,
    user: dict[str, str] | None,
    store: MemoryStore | None,
    body: bytes = b"",
    query_string: bytes = b"",
) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": query_string,
        "client": ("127.0.0.1", 12345),
        "state": {"user": user},
        "app": SimpleNamespace(state=SimpleNamespace(store=store)),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _settings(*, database_url: str, lancedb_path) -> Settings:
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        database_url=database_url,
        lancedb_path=lancedb_path,
        ingest_max_body_bytes=10 * 1024 * 1024,
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
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    store = MemoryStore(settings)
    await store.ensure_collection()

    try:
        yield settings, store
    finally:
        await store.close()
        await eng.dispose()


async def _seed(store: MemoryStore, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    project = Project(
        id="proj-export",
        user_id=user_id,
        slug="alpha",
        name="Alpha",
        description=None,
        created_at=now,
        updated_at=now,
    )
    async with dp.async_session() as db:
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
        db.add(project)

    await store.save(
        user_id=user_id,
        project_id="proj-export",
        content="seeded memory",
        vector=[0.1] * VECTOR_SIZE,
        tags=["alpha"],
    )


@pytest.mark.asyncio
async def test_route_data_export_returns_401_without_user(env):
    _, store = env
    request = _make_request(method="GET", path="/api/data/export", user=None, store=store)
    response = await routes.route_data_export(request)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_data_export_returns_zip_archive(env):
    _, store = env
    await _seed(store, USER_ID)

    request = _make_request(
        method="GET", path="/api/data/export", user={"sub": USER_ID}, store=store
    )

    response = await routes.route_data_export(request)
    assert response.status_code == 200
    assert response.media_type == "application/zip"
    cd = response.headers.get("content-disposition", "")
    assert "attachment" in cd and "piloci-export-" in cd

    with zipfile.ZipFile(io.BytesIO(response.body)) as zf:
        manifest = orjson.loads(zf.read(dp.MANIFEST_NAME))
        assert manifest["user_id"] == USER_ID
        assert manifest["counts"]["projects"] == 1
        assert manifest["counts"]["memories"] == 1


@pytest.mark.asyncio
async def test_route_data_import_returns_401_without_user(env):
    _, store = env
    request = _make_request(method="POST", path="/api/data/import", user=None, store=store)
    response = await routes.route_data_import(request)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_data_import_returns_400_on_empty_body(env):
    _, store = env
    request = _make_request(
        method="POST",
        path="/api/data/import",
        user={"sub": USER_ID},
        store=store,
        body=b"",
    )
    response = await routes.route_data_import(request)
    assert response.status_code == 400
    body = orjson.loads(response.body)
    assert body["error"] == "empty body"


@pytest.mark.asyncio
async def test_route_data_import_returns_413_on_oversize_body(env, monkeypatch):
    settings, store = env
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            ingest_max_body_bytes=8,
            embed_model=settings.embed_model,
            embed_cache_dir=settings.embed_cache_dir,
            embed_lru_size=settings.embed_lru_size,
            embed_executor_workers=settings.embed_executor_workers,
            embed_max_concurrency=settings.embed_max_concurrency,
        ),
    )
    request = _make_request(
        method="POST",
        path="/api/data/import",
        user={"sub": USER_ID},
        store=store,
        body=b"x" * 64,
    )
    response = await routes.route_data_import(request)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_route_data_import_round_trip_via_export(env, monkeypatch):
    settings, store = env
    await _seed(store, USER_ID)

    # Build the archive via the same path the export route uses
    archive = await dp.build_export_archive(
        user_id=USER_ID, store=store, settings=settings, piloci_version="0.0.0-test"
    )

    # Import it back into a *different* user; embed_one must not be invoked
    # because the archive's embed_model matches settings.embed_model.
    refuse_embed = AsyncMock(side_effect=AssertionError("no reembed expected"))
    monkeypatch.setattr("piloci.storage.embed.embed_one", refuse_embed)

    # Insert destination user
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

    request = _make_request(
        method="POST",
        path="/api/data/import",
        user={"sub": "user-dest"},
        store=store,
        body=archive,
    )
    response = await routes.route_data_import(request)
    assert response.status_code == 200
    body = orjson.loads(response.body)
    assert body["imported"] is True
    assert body["projects_imported"] == 1
    assert body["memories_imported"] == 1
    assert body["re_embedded"] is False
    refuse_embed.assert_not_called()


@pytest.mark.asyncio
async def test_route_data_import_returns_409_when_embed_mismatch_without_reembed(env):
    settings, store = env
    await _seed(store, USER_ID)

    archive = await dp.build_export_archive(
        user_id=USER_ID, store=store, settings=settings, piloci_version="0.0.0-test"
    )

    # Tamper manifest so embed_model no longer matches the server
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

    request = _make_request(
        method="POST",
        path="/api/data/import",
        user={"sub": USER_ID},
        store=store,
        body=tampered_buf.getvalue(),
    )
    response = await routes.route_data_import(request)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_route_data_import_reembed_flag_triggers_reembed(env, monkeypatch):
    settings, store = env
    await _seed(store, USER_ID)

    archive = await dp.build_export_archive(
        user_id=USER_ID, store=store, settings=settings, piloci_version="0.0.0-test"
    )

    # Tamper manifest so embed_model differs from server
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

    seen: list[str] = []

    async def _fake_embed_one(**kwargs):
        seen.append(kwargs["text"])
        return [0.42] * VECTOR_SIZE

    monkeypatch.setattr("piloci.storage.embed.embed_one", _fake_embed_one)

    # Insert destination user
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
            {"id": "user-rdest", "email": "rdest@example.com", "now": now},
        )

    request = _make_request(
        method="POST",
        path="/api/data/import",
        user={"sub": "user-rdest"},
        store=store,
        body=tampered_buf.getvalue(),
        query_string=b"reembed=true",
    )
    response = await routes.route_data_import(request)
    assert response.status_code == 200
    body = orjson.loads(response.body)
    assert body["re_embedded"] is True
    assert body["memories_imported"] == 1
    assert seen == ["seeded memory"]


def test_data_routes_are_registered_and_rate_limited():
    paths_methods = {
        (r.path, tuple(sorted(r.methods or []))) for r in routes.get_routes() if hasattr(r, "path")
    }
    assert ("/api/data/export", ("GET", "HEAD")) in paths_methods
    assert ("/api/data/import", ("POST",)) in paths_methods


def test_export_archive_round_trip_via_function_layer():
    """Sanity check the export bytes are a valid zip with expected files —
    independent of the HTTP route layer."""
    from piloci.api.data_portability import (
        MANIFEST_NAME,
        MEMORIES_NAME,
        PROFILES_NAME,
        PROJECTS_NAME,
    )

    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, orjson.dumps({"archive_version": 1}))
        zf.writestr(PROJECTS_NAME, b"[]")
        zf.writestr(PROFILES_NAME, b"[]")
        # Empty parquet table that matches schema
        empty = pq.read_table(io.BytesIO(_empty_parquet_bytes()))
        sink_p = io.BytesIO()
        pq.write_table(empty, sink_p)
        zf.writestr(MEMORIES_NAME, sink_p.getvalue())

    with zipfile.ZipFile(io.BytesIO(sink.getvalue())) as zf:
        names = set(zf.namelist())
        assert {MANIFEST_NAME, PROJECTS_NAME, PROFILES_NAME, MEMORIES_NAME} <= names


def _empty_parquet_bytes() -> bytes:
    sink = io.BytesIO()
    pq.write_table(
        pq.read_table(io.BytesIO(_seed_empty_parquet())),
        sink,
    )
    return sink.getvalue()


def _seed_empty_parquet() -> bytes:
    import pyarrow as pa

    table = pa.Table.from_pydict(
        {f.name: [] for f in dp._MEMORIES_SCHEMA},
        schema=dp._MEMORIES_SCHEMA,
    )
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()

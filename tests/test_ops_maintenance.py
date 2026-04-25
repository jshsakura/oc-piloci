from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from piloci.config import Settings
from piloci.db.models import AuditLog, Project, RawSession, User
from piloci.db.session import init_db

maintenance = importlib.import_module("piloci.ops.maintenance")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings(
    *,
    database_url: str = "sqlite+aiosqlite:////tmp/piloci-maintenance.db",
    raw_session_retention_days: int = 14,
    audit_log_retention_days: int = 90,
) -> Settings:
    return Settings(
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
        database_url=database_url,
        raw_session_retention_days=raw_session_retention_days,
        audit_log_retention_days=audit_log_retention_days,
    )


@pytest.fixture
async def engine(monkeypatch, tmp_path) -> AsyncGenerator[tuple[AsyncEngine, Settings], None]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'maintenance.db'}"
    settings = _settings(database_url=database_url)
    monkeypatch.setattr("piloci.db.session.get_settings", lambda: settings)
    monkeypatch.setattr("piloci.db.session._engine", None)
    monkeypatch.setattr("piloci.db.session._session_factory", None)

    eng = create_async_engine(database_url, echo=False, connect_args={"check_same_thread": False})
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

    monkeypatch.setattr(maintenance, "async_session", _test_async_session)
    yield eng, settings
    await eng.dispose()


@pytest.fixture
async def session(engine: tuple[AsyncEngine, Settings]) -> AsyncGenerator[AsyncSession, None]:
    eng, _settings_obj = engine
    factory = async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with factory() as sess:
        yield sess


async def _seed_user_project(session: AsyncSession) -> tuple[User, Project]:
    user = User(
        id=str(uuid.uuid4()),
        email="cleanup@test.com",
        name="Cleanup",
        password_hash="$argon2id$...",
        created_at=_now(),
        is_active=True,
        is_admin=False,
        quota_bytes=1073741824,
    )
    project = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        slug="cleanup-project",
        name="Cleanup Project",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(user)
    session.add(project)
    await session.commit()
    return user, project


@pytest.mark.asyncio
async def test_cleanup_retention_deletes_old_processed_raw_sessions_and_audit_logs(
    session: AsyncSession, engine
):
    _eng, settings_obj = engine
    user, project = await _seed_user_project(session)
    old_time = _now() - timedelta(days=30)
    settings = _settings(
        database_url=settings_obj.database_url,
        raw_session_retention_days=14,
        audit_log_retention_days=14,
    )

    session.add_all(
        [
            RawSession(
                ingest_id="processed-old",
                user_id=user.id,
                project_id=project.id,
                client="claude",
                session_id="s1",
                transcript_json="[]",
                created_at=old_time,
                processed_at=old_time,
                error=None,
                memories_extracted=1,
            ),
            RawSession(
                ingest_id="pending-keep",
                user_id=user.id,
                project_id=project.id,
                client="claude",
                session_id="s2",
                transcript_json="[]",
                created_at=old_time,
                processed_at=None,
                error=None,
                memories_extracted=0,
            ),
            AuditLog(
                user_id=user.id,
                action="LOGIN",
                created_at=old_time,
            ),
            AuditLog(
                user_id=user.id,
                action="LOGIN",
                created_at=_now(),
            ),
        ]
    )
    await session.commit()

    result = await maintenance.cleanup_retention(settings)

    assert result == {"raw_sessions": 1, "audit_logs": 1}

    remaining_raw = (await session.execute(select(RawSession.ingest_id))).scalars().all()
    remaining_audit = (await session.execute(select(AuditLog.id))).scalars().all()

    assert remaining_raw == ["pending-keep"]
    assert len(remaining_audit) == 1


@pytest.mark.asyncio
async def test_cleanup_retention_respects_custom_days(session: AsyncSession, engine):
    _eng, settings_obj = engine
    user, project = await _seed_user_project(session)
    keep_time = _now() - timedelta(days=5)
    settings = _settings(
        database_url=settings_obj.database_url,
        raw_session_retention_days=14,
        audit_log_retention_days=14,
    )

    session.add_all(
        [
            RawSession(
                ingest_id="processed-recent",
                user_id=user.id,
                project_id=project.id,
                client="claude",
                session_id="s3",
                transcript_json="[]",
                created_at=keep_time,
                processed_at=keep_time,
                error=None,
                memories_extracted=1,
            ),
            AuditLog(
                user_id=user.id,
                action="LOGIN",
                created_at=keep_time,
            ),
        ]
    )
    await session.commit()

    result = await maintenance.cleanup_retention(settings)

    assert result == {"raw_sessions": 0, "audit_logs": 0}

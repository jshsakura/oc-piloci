from __future__ import annotations

import uuid
from datetime import datetime, timezone

import orjson
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from piloci.db.models import ApiToken, AuditLog, Base, PasswordResetToken, Project, User
from piloci.db.session import init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def engine():
    """In-memory SQLite engine for each test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine=eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncSession:
    """Async session bound to the in-memory engine."""
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with factory() as sess:
        yield sess


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(
    *,
    email: str = "alice@example.com",
    name: str = "Alice",
) -> User:
    return User(
        id=str(uuid.uuid4()),
        email=email,
        name=name,
        email_verified=False,
        password_hash="$argon2id$...",
        created_at=_now(),
        is_active=True,
        is_admin=False,
        quota_bytes=1073741824,
    )


# ---------------------------------------------------------------------------
# init_db — table creation
# ---------------------------------------------------------------------------

async def test_init_db_creates_tables(engine):
    """All expected tables should be present after init_db()."""
    from sqlalchemy import inspect, text

    async with engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )

    expected = {
        "users",
        "password_reset_tokens",
        "audit_logs",
        "projects",
        "api_tokens",
    }
    assert expected.issubset(set(table_names)), (
        f"Missing tables: {expected - set(table_names)}"
    )


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

async def test_create_and_query_user(session: AsyncSession):
    user = _make_user()
    session.add(user)
    await session.commit()

    fetched = await session.get(User, user.id)
    assert fetched is not None
    assert fetched.email == "alice@example.com"
    assert fetched.name == "Alice"
    assert fetched.quota_bytes == 1073741824
    assert fetched.is_active is True
    assert fetched.is_admin is False


async def test_user_email_unique_constraint(session: AsyncSession):
    """Inserting two users with the same email must raise an integrity error."""
    import sqlalchemy.exc

    user1 = _make_user(email="dup@example.com")
    user2 = _make_user(email="dup@example.com")
    session.add(user1)
    await session.commit()

    session.add(user2)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.commit()
    await session.rollback()


# ---------------------------------------------------------------------------
# PasswordResetToken
# ---------------------------------------------------------------------------

async def test_password_reset_token(session: AsyncSession):
    user = _make_user()
    session.add(user)
    await session.commit()

    token = PasswordResetToken(
        token_hash="sha256hashoftoken",
        user_id=user.id,
        expires_at=_now(),
        used=False,
        created_at=_now(),
    )
    session.add(token)
    await session.commit()

    fetched = await session.get(PasswordResetToken, "sha256hashoftoken")
    assert fetched is not None
    assert fetched.user_id == user.id
    assert fetched.used is False


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

async def test_audit_log_with_json_metadata(session: AsyncSession):
    user = _make_user()
    session.add(user)
    await session.commit()

    meta = orjson.dumps({"ip": "127.0.0.1", "action_detail": "password changed"}).decode()
    log = AuditLog(
        user_id=user.id,
        action="password_change",
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
        meta_data=meta,
        created_at=_now(),
    )
    session.add(log)
    await session.commit()

    fetched = await session.get(AuditLog, log.id)
    assert fetched is not None
    assert fetched.action == "password_change"
    parsed = orjson.loads(fetched.meta_data)
    assert parsed["ip"] == "127.0.0.1"


async def test_audit_log_nullable_user(session: AsyncSession):
    """audit_logs.user_id may be NULL (no FK violation)."""
    log = AuditLog(
        user_id=None,
        action="system_startup",
        created_at=_now(),
    )
    session.add(log)
    await session.commit()

    fetched = await session.get(AuditLog, log.id)
    assert fetched is not None
    assert fetched.user_id is None


# ---------------------------------------------------------------------------
# Project CRUD (with User FK)
# ---------------------------------------------------------------------------

async def test_create_project(session: AsyncSession):
    user = _make_user()
    session.add(user)
    await session.commit()

    project = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        slug="webapp-dev",
        name="Webapp Dev",
        description="My webapp project",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(project)
    await session.commit()

    fetched = await session.get(Project, project.id)
    assert fetched is not None
    assert fetched.slug == "webapp-dev"
    assert fetched.user_id == user.id
    assert fetched.memory_count == 0
    assert fetched.bytes_used == 0


async def test_project_slug_unique_per_user(session: AsyncSession):
    """Two projects with the same (user_id, slug) must fail."""
    import sqlalchemy.exc

    user = _make_user()
    session.add(user)
    await session.commit()

    p1 = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        slug="same-slug",
        name="Project 1",
        created_at=_now(),
        updated_at=_now(),
    )
    p2 = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        slug="same-slug",
        name="Project 2",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(p1)
    await session.commit()

    session.add(p2)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await session.commit()
    await session.rollback()


# ---------------------------------------------------------------------------
# ApiToken CRUD (with User + Project FK)
# ---------------------------------------------------------------------------

async def test_create_api_token(session: AsyncSession):
    user = _make_user()
    session.add(user)
    await session.commit()

    project = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        slug="research",
        name="Research",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(project)
    await session.commit()

    token = ApiToken(
        token_id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        name="Claude Code notebook",
        token_hash="sha256ofthetoken",
        scope="project",
        created_at=_now(),
        revoked=False,
    )
    session.add(token)
    await session.commit()

    fetched = await session.get(ApiToken, token.token_id)
    assert fetched is not None
    assert fetched.user_id == user.id
    assert fetched.project_id == project.id
    assert fetched.scope == "project"
    assert fetched.revoked is False


async def test_api_token_null_project(session: AsyncSession):
    """project_id may be NULL (user-scoped token)."""
    user = _make_user()
    session.add(user)
    await session.commit()

    token = ApiToken(
        token_id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=None,
        name="User-level token",
        token_hash="sha256oftoken2",
        scope="user",
        created_at=_now(),
    )
    session.add(token)
    await session.commit()

    fetched = await session.get(ApiToken, token.token_id)
    assert fetched is not None
    assert fetched.project_id is None
    assert fetched.scope == "user"


async def test_cascade_delete_user_removes_project_and_token(session: AsyncSession):
    """Deleting a user must cascade-delete projects and api_tokens."""
    from sqlalchemy import select

    user = _make_user()
    session.add(user)
    await session.commit()

    project = Project(
        id=str(uuid.uuid4()),
        user_id=user.id,
        slug="cascade-test",
        name="Cascade Test",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(project)
    await session.commit()

    token = ApiToken(
        token_id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        name="Token",
        token_hash="hash",
        scope="project",
        created_at=_now(),
    )
    session.add(token)
    await session.commit()

    # Delete the user
    await session.delete(user)
    await session.commit()

    assert await session.get(Project, project.id) is None
    assert await session.get(ApiToken, token.token_id) is None

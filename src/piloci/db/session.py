from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from piloci.config import get_settings
from piloci.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            connect_args={"check_same_thread": False},
        )

        # Enable WAL mode for SQLite
        @event.listens_for(_engine.sync_engine, "connect")
        def _set_wal_mode(dbapi_conn, connection_record):  # type: ignore[misc]
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute(f"PRAGMA synchronous={settings.sqlite_synchronous}")
            dbapi_conn.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA temp_store=MEMORY")

    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _session_factory


@asynccontextmanager
async def async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a database session."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all tables defined in Base.metadata."""
    target = engine or _get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

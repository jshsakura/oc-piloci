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


_SQLITE_ADD_COLUMNS: dict[str, dict[str, str]] = {
    # Idempotent ALTER TABLE migrations for SQLite (create_all does not patch
    # existing tables). Each entry: column-name → SQL type spec.
    "api_tokens": {
        "installed_at": "DATETIME",
        "client_kinds": "TEXT",
        "hostname": "TEXT",
    },
    "projects": {
        "instinct_count": "INTEGER NOT NULL DEFAULT 0",
        "cwd": "TEXT",
    },
    "raw_sessions": {
        "instincts_extracted": "INTEGER NOT NULL DEFAULT 0",
        "distillation_state": "TEXT NOT NULL DEFAULT 'pending'",
        "archived_at": "DATETIME",
        "processing_path": "TEXT",
        "priority": "INTEGER NOT NULL DEFAULT 0",
        "filter_reason": "TEXT",
        "last_attempted_at": "DATETIME",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
    },
}


_SQLITE_BACKFILL: list[str] = [
    # One-shot SQL run after column add. Idempotent — must be safe on every
    # startup. Use to seed legacy rows after a column gains a non-null state.
    # Backfill distillation_state for rows that existed before the column
    # was added. processed_at IS NOT NULL → 'distilled', else 'pending'.
    "UPDATE raw_sessions SET distillation_state = 'distilled' "
    "WHERE distillation_state = 'pending' AND processed_at IS NOT NULL",
    # Migrate legacy RawAnalysis rows into raw_sessions so the unified lazy
    # worker treats them as distilled history. Uses INSERT OR IGNORE keyed
    # on ingest_id (= analyze_id) so re-running is a no-op. analyze_id is
    # carried over verbatim and the transcript is wrapped in JSON to match
    # the raw_sessions storage convention. The synthetic client label
    # 'legacy-analyze' lets the user identify migrated rows in audit views.
    """
    INSERT OR IGNORE INTO raw_sessions (
        ingest_id, user_id, project_id, client, session_id, transcript_json,
        created_at, processed_at, error, memories_extracted, instincts_extracted,
        distillation_state, archived_at, processing_path, priority,
        filter_reason, last_attempted_at, attempt_count
    )
    SELECT
        analyze_id,
        user_id,
        project_id,
        'legacy-analyze',
        NULL,
        json_quote(transcript),
        created_at,
        processed_at,
        error,
        0,
        instincts_extracted,
        CASE
            WHEN processed_at IS NOT NULL THEN 'distilled'
            WHEN error IS NOT NULL THEN 'failed'
            ELSE 'pending'
        END,
        NULL,
        'local',
        0,
        NULL,
        NULL,
        0
    FROM raw_analyses
    """,
]


def _apply_pending_migrations(sync_conn) -> None:  # type: ignore[no-untyped-def]
    """Add columns introduced after a table was first created and run any
    one-shot backfills. SQLite-only — each step is idempotent so this is safe
    to run on every startup."""
    from sqlalchemy import text

    for table, columns in _SQLITE_ADD_COLUMNS.items():
        existing = {
            row[1] for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        }
        for col, spec in columns.items():
            if col not in existing:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {spec}"))

    for sql in _SQLITE_BACKFILL:
        # Backfills are best-effort — a missing legacy table on a fresh
        # install (or a half-migrated dev DB) shouldn't crash startup.
        try:
            sync_conn.execute(text(sql))
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "backfill skipped (%s): %s",
                sql.splitlines()[0][:60],
                exc,
            )


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all tables defined in Base.metadata, then apply pending column migrations."""
    target = engine or _get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_pending_migrations)

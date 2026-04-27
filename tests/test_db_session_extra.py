from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from piloci.db.session import _get_engine, _get_session_factory, async_session, init_db


def test_get_engine_creates_engine_with_pragmas(monkeypatch):
    monkeypatch.setattr("piloci.db.session._engine", None)
    mock_settings = MagicMock()
    mock_settings.database_url = "sqlite+aiosqlite:///:memory:"
    mock_settings.debug = False
    mock_settings.sqlite_synchronous = 1
    mock_settings.sqlite_busy_timeout_ms = 5000
    monkeypatch.setattr("piloci.db.session.get_settings", lambda: mock_settings)

    engine = _get_engine()
    assert engine is not None
    engine.sync_engine.dispose()


def test_get_engine_cached(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.database_url = "sqlite+aiosqlite:///:memory:"
    mock_settings.debug = False
    monkeypatch.setattr("piloci.db.session.get_settings", lambda: mock_settings)

    sentinel = MagicMock()
    monkeypatch.setattr("piloci.db.session._engine", sentinel)
    assert _get_engine() is sentinel


def test_get_session_factory_cached(monkeypatch):
    sentinel = MagicMock()
    monkeypatch.setattr("piloci.db.session._session_factory", sentinel)
    assert _get_session_factory() is sentinel


@pytest.mark.asyncio
async def test_async_session_commits_on_success(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.db.session._get_session_factory", lambda: factory)

    async with async_session():
        pass

    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_async_session_rollbacks_on_error(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("piloci.db.session._get_session_factory", lambda: factory)

    with pytest.raises(ValueError):
        async with async_session():
            raise ValueError("boom")

    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path):
    from piloci.config import Settings

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-secret-32-characters-minimum!",
        session_secret="test-secret-32-characters-minimum!",
    )
    engine = create_async_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    await init_db(engine=engine)
    await engine.dispose()

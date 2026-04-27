"""Tests for auth/session.py — SessionStore singleton factory."""

from types import SimpleNamespace

import pytest

from piloci.auth import session


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    yield
    session._store = None


class TestGetSessionStore:
    def test_creates_singleton(self):
        s = SimpleNamespace(
            redis_url="redis://localhost:6379/0",
            session_expire_days=7,
            session_max_per_user=5,
        )
        store = session.get_session_store(s)
        assert store is not None
        assert isinstance(store, session.SessionStore)

    def test_returns_same_instance(self):
        s = SimpleNamespace(
            redis_url="redis://localhost:6379/0",
            session_expire_days=7,
            session_max_per_user=5,
        )
        store1 = session.get_session_store(s)
        store2 = session.get_session_store(s)
        assert store1 is store2

    def test_session_ttl_computed(self):
        s = SimpleNamespace(
            redis_url="redis://localhost:6379/0",
            session_expire_days=7,
            session_max_per_user=5,
        )
        store = session.get_session_store(s)
        assert store._session_ttl == 7 * 86400

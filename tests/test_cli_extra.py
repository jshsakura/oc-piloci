from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from piloci import cli


class _AsyncSessionContext:
    def __init__(self, db: object) -> None:
        self._db = db

    async def __aenter__(self) -> object:
        return self._db

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar(self) -> int:
        return self._value


def test_main_serve_calls_run_sse(monkeypatch) -> None:
    run_sse_mock = MagicMock()
    load_dotenv_mock = MagicMock()

    monkeypatch.setattr(
        sys, "argv", ["piloci", "serve", "--host", "0.0.0.0", "--port", "9000", "--reload"]
    )
    monkeypatch.setattr("piloci.cli.load_dotenv", load_dotenv_mock)
    monkeypatch.setattr("piloci.main.run_sse", run_sse_mock)

    cli.main()

    load_dotenv_mock.assert_called_once_with()
    run_sse_mock.assert_called_once_with()


def test_main_stdio_calls_run_stdio(monkeypatch) -> None:
    run_stdio_mock = MagicMock()

    monkeypatch.setattr(sys, "argv", ["piloci", "stdio"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.main.run_stdio", run_stdio_mock)

    cli.main()

    run_stdio_mock.assert_called_once_with()


def test_main_bootstrap_calls_run_bootstrap(monkeypatch) -> None:
    run_bootstrap_mock = MagicMock()

    monkeypatch.setattr(sys, "argv", ["piloci", "bootstrap", "--email", "admin@example.com"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_bootstrap", run_bootstrap_mock)

    cli.main()

    args = run_bootstrap_mock.call_args.args[0]
    assert args.command == "bootstrap"
    assert args.email == "admin@example.com"
    assert args.password is None


def test_main_profile_baseline_command_collects_and_prints_json(monkeypatch, capsys) -> None:
    collect_baseline_mock = MagicMock(return_value={"ok": True})
    resolve_defaults_mock = MagicMock(
        return_value={
            "endpoint": "http://env-server:8314",
            "paths": ["/healthz", "/readyz"],
            "samples": 3,
            "timeout": 4.5,
            "token": "env-token",
        }
    )

    monkeypatch.setattr(sys, "argv", ["piloci", "profile-baseline"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.profiling_baseline.collect_baseline", collect_baseline_mock)
    monkeypatch.setattr(
        "piloci.profiling_baseline.resolve_baseline_defaults", resolve_defaults_mock
    )

    cli.main()

    collect_baseline_mock.assert_called_once_with(
        "http://env-server:8314",
        paths=["/healthz", "/readyz"],
        samples=3,
        timeout=4.5,
        token="env-token",
    )
    assert '"ok": true' in capsys.readouterr().out.lower()


def test_run_bootstrap_creates_admin_from_args(monkeypatch, capsys) -> None:
    init_db_mock = AsyncMock()
    hash_password_mock = MagicMock(return_value="hashed-password")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(0)),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    args = argparse.Namespace(email="admin@example.com", password="supersecret")

    monkeypatch.setattr("piloci.db.session.init_db", init_db_mock)
    monkeypatch.setattr("piloci.db.session.async_session", lambda: _AsyncSessionContext(db))
    monkeypatch.setattr("piloci.auth.password.hash_password", hash_password_mock)

    cli._run_bootstrap(args)

    init_db_mock.assert_awaited_once()
    hash_password_mock.assert_called_once_with("supersecret")
    db.commit.assert_awaited_once()

    user = db.add.call_args.args[0]
    assert user.email == "admin@example.com"
    assert user.name == "Admin"
    assert user.is_admin is True
    assert user.approval_status == "approved"
    assert user.password_hash == "hashed-password"
    assert "Admin user created: admin@example.com" in capsys.readouterr().out


def test_run_bootstrap_uses_env_credentials(monkeypatch, capsys) -> None:
    init_db_mock = AsyncMock()
    hash_password_mock = MagicMock(return_value="hashed-from-env")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(0)),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    args = argparse.Namespace(email=None, password=None)

    monkeypatch.setenv("ADMIN_EMAIL", "env-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "envsecret")
    monkeypatch.setattr("piloci.db.session.init_db", init_db_mock)
    monkeypatch.setattr("piloci.db.session.async_session", lambda: _AsyncSessionContext(db))
    monkeypatch.setattr("piloci.auth.password.hash_password", hash_password_mock)

    cli._run_bootstrap(args)

    init_db_mock.assert_awaited_once()
    hash_password_mock.assert_called_once_with("envsecret")
    user = db.add.call_args.args[0]
    assert user.email == "env-admin@example.com"
    assert "Admin user created: env-admin@example.com" in capsys.readouterr().out


def test_run_bootstrap_requires_email(monkeypatch, capsys) -> None:
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(0)),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    args = argparse.Namespace(email=None, password="supersecret")

    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.setattr("piloci.db.session.init_db", AsyncMock())
    monkeypatch.setattr("piloci.db.session.async_session", lambda: _AsyncSessionContext(db))

    with pytest.raises(SystemExit, match="1"):
        cli._run_bootstrap(args)

    assert "ADMIN_EMAIL not set" in capsys.readouterr().out
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


def test_run_bootstrap_requires_minimum_password_length(monkeypatch, capsys) -> None:
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(0)),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    args = argparse.Namespace(email="admin@example.com", password="short")

    monkeypatch.setattr("piloci.db.session.init_db", AsyncMock())
    monkeypatch.setattr("piloci.db.session.async_session", lambda: _AsyncSessionContext(db))

    with pytest.raises(SystemExit, match="1"):
        cli._run_bootstrap(args)

    assert "ADMIN_PASSWORD must be at least 8 characters" in capsys.readouterr().out
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


def test_run_bootstrap_skips_when_users_exist(monkeypatch, capsys) -> None:
    hash_password_mock = MagicMock()
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(2)),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    args = argparse.Namespace(email="admin@example.com", password="supersecret")

    monkeypatch.setattr("piloci.db.session.init_db", AsyncMock())
    monkeypatch.setattr("piloci.db.session.async_session", lambda: _AsyncSessionContext(db))
    monkeypatch.setattr("piloci.auth.password.hash_password", hash_password_mock)

    cli._run_bootstrap(args)

    hash_password_mock.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    assert "2 user(s) already exist" in capsys.readouterr().out

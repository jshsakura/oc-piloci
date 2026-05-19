from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# main() dispatch — covers each elif branch (lines 183, 185, 187, 189, 191, 193)
# ---------------------------------------------------------------------------


def test_main_login_dispatches_to_run_login(monkeypatch) -> None:
    run_login_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "login", "--no-browser"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_login", run_login_mock)

    cli.main()

    args = run_login_mock.call_args.args[0]
    assert args.command == "login"
    assert args.no_browser is True


def test_main_install_dispatches_to_run_install(monkeypatch) -> None:
    run_install_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "install", "--force", "--token", "TKN"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_install", run_install_mock)

    cli.main()

    args = run_install_mock.call_args.args[0]
    assert args.command == "install"
    assert args.force is True
    assert args.token == "TKN"


def test_main_uninstall_dispatches_to_run_uninstall(monkeypatch) -> None:
    run_uninstall_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "uninstall", "--yes", "--no-restore"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_uninstall", run_uninstall_mock)

    cli.main()

    args = run_uninstall_mock.call_args.args[0]
    assert args.yes is True
    assert args.no_restore is True


def test_main_restore_dispatches_to_run_restore(monkeypatch) -> None:
    run_restore_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "restore", "--list"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_restore", run_restore_mock)

    cli.main()

    args = run_restore_mock.call_args.args[0]
    assert args.list is True


def test_main_setup_dispatches_to_run_setup(monkeypatch) -> None:
    run_setup_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "setup", "--server", "https://x"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_setup", run_setup_mock)

    cli.main()

    args = run_setup_mock.call_args.args[0]
    assert args.server == "https://x"


def test_main_backfill_cwd_dispatches_to_run_backfill_cwd(monkeypatch) -> None:
    run_backfill_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "backfill-cwd", "--dry-run", "--user-id", "u1"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.cli._run_backfill_cwd", run_backfill_mock)

    cli.main()

    args = run_backfill_mock.call_args.args[0]
    assert args.dry_run is True
    assert args.user_id == "u1"


def test_main_no_command_prints_help_and_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["piloci"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "usage" in out.lower() or "piloci" in out.lower()


def test_main_serve_without_overrides_does_not_touch_env(monkeypatch) -> None:
    """When no --host/--port/--reload are passed, env vars are untouched."""
    import os

    run_sse_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "serve"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.main.run_sse", run_sse_mock)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("RELOAD", raising=False)

    cli.main()

    assert "HOST" not in os.environ
    assert "PORT" not in os.environ
    assert "RELOAD" not in os.environ
    run_sse_mock.assert_called_once_with()


def test_main_serve_sets_env_from_args(monkeypatch) -> None:
    import os

    run_sse_mock = MagicMock()
    monkeypatch.setattr(sys, "argv", ["piloci", "serve", "--host", "1.2.3.4", "--port", "7777"])
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.main.run_sse", run_sse_mock)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    cli.main()

    assert os.environ["HOST"] == "1.2.3.4"
    assert os.environ["PORT"] == "7777"


# ---------------------------------------------------------------------------
# _resolve_server  (lines 267-287)
# ---------------------------------------------------------------------------


def test_resolve_server_uses_arg_and_strips_trailing_slash(monkeypatch) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    assert cli._resolve_server("https://piloci.example.com/") == "https://piloci.example.com"


def test_resolve_server_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: "https://saved.example.com/")
    assert cli._resolve_server(None) == "https://saved.example.com"


def test_resolve_server_prompts_when_no_default(monkeypatch) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "  piloci.example.com  ")

    # No scheme → prepended with https://
    assert cli._resolve_server(None) == "https://piloci.example.com"


def test_resolve_server_prompt_preserves_explicit_scheme(monkeypatch) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "http://local:8080/")

    assert cli._resolve_server(None) == "http://local:8080"


def test_resolve_server_empty_prompt_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "   ")

    with pytest.raises(SystemExit) as exc:
        cli._resolve_server(None)

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "입력되지 않았습니다" in err


def test_resolve_server_keyboard_interrupt_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)

    def _raise(_prompt="") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _raise)

    with pytest.raises(SystemExit) as exc:
        cli._resolve_server(None)

    assert exc.value.code == 2
    assert "취소됨" in capsys.readouterr().err


def test_resolve_server_eof_error_exits(monkeypatch) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)

    def _raise(_prompt="") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    with pytest.raises(SystemExit) as exc:
        cli._resolve_server(None)

    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# _device_login  (lines 299-392)
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    """Minimal context-manager response for urllib.request.urlopen patches."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _patch_detect_all_targets(monkeypatch, value=None):
    monkeypatch.setattr(
        "piloci.installer.detect_all_targets",
        lambda: value if value is not None else {"claude": True, "cursor": False},
    )


def test_device_login_returns_token_and_targets(monkeypatch) -> None:
    _patch_detect_all_targets(monkeypatch)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "ABCD-1234",
                "device_code": "dev-1",
                "verification_uri": "https://piloci/device",
                "verification_uri_complete": "https://piloci/device?code=ABCD-1234",
                "interval": 1,
                "expires_in": 60,
            }
        ),
        _FakeHTTPResponse({"status": "pending"}),
        _FakeHTTPResponse(
            {"status": "approved", "token": "jwt-abc", "targets": ["claude", "cursor"]}
        ),
    ]

    def _fake_urlopen(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)

    token, targets = cli._device_login("https://piloci/", open_browser=True)

    assert token == "jwt-abc"
    assert targets == ["claude", "cursor"]
    assert responses == []


def test_device_login_no_browser_skips_webbrowser(monkeypatch) -> None:
    _patch_detect_all_targets(monkeypatch)
    opened = MagicMock()
    monkeypatch.setattr("webbrowser.open", opened)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "X",
                "device_code": "d",
                "verification_uri": "https://piloci/device",
                "interval": 1,
                "expires_in": 5,
            }
        ),
        _FakeHTTPResponse({"status": "approved", "token": "t1"}),
    ]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    token, targets = cli._device_login("https://piloci", open_browser=False)

    assert token == "t1"
    assert targets is None
    opened.assert_not_called()


def test_device_login_connection_failure_exits(monkeypatch, capsys) -> None:
    _patch_detect_all_targets(monkeypatch)

    def _raise(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(SystemExit) as exc:
        cli._device_login("https://piloci", open_browser=False)

    assert exc.value.code == 1
    assert "서버 연결 실패" in capsys.readouterr().err


def test_device_login_handles_browser_open_failure(monkeypatch) -> None:
    _patch_detect_all_targets(monkeypatch)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "X",
                "device_code": "d",
                "verification_uri": "https://piloci/device",
                "interval": 1,
                "expires_in": 5,
            }
        ),
        _FakeHTTPResponse({"status": "approved", "token": "tk"}),
    ]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    def _bad_open(*_a, **_k):
        raise RuntimeError("no display")

    monkeypatch.setattr("webbrowser.open", _bad_open)

    token, _ = cli._device_login("https://piloci", open_browser=True)
    assert token == "tk"


def test_device_login_detect_targets_failure_is_swallowed(monkeypatch) -> None:
    def _explode():
        raise RuntimeError("detection broken")

    monkeypatch.setattr("piloci.installer.detect_all_targets", _explode)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "X",
                "device_code": "d",
                "verification_uri": "https://piloci/device",
                "interval": 1,
                "expires_in": 5,
            }
        ),
        _FakeHTTPResponse({"status": "approved", "token": "tk"}),
    ]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    token, _ = cli._device_login("https://piloci", open_browser=False)
    assert token == "tk"


def test_device_login_approved_without_token_exits(monkeypatch, capsys) -> None:
    _patch_detect_all_targets(monkeypatch)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "X",
                "device_code": "d",
                "verification_uri": "https://piloci/device",
                "interval": 1,
                "expires_in": 5,
            }
        ),
        _FakeHTTPResponse({"status": "approved", "token": ""}),
    ]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._device_login("https://piloci", open_browser=False)

    assert exc.value.code == 1
    assert "토큰이 비어있습니다" in capsys.readouterr().err


def test_device_login_denied_exits(monkeypatch, capsys) -> None:
    _patch_detect_all_targets(monkeypatch)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "X",
                "device_code": "d",
                "verification_uri": "https://piloci/device",
                "interval": 1,
                "expires_in": 5,
            }
        ),
        _FakeHTTPResponse({"status": "denied"}),
    ]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._device_login("https://piloci", open_browser=False)

    assert exc.value.code == 1
    assert "승인을 거부" in capsys.readouterr().err


def test_device_login_expired_code_exits(monkeypatch, capsys) -> None:
    _patch_detect_all_targets(monkeypatch)

    code_resp = _FakeHTTPResponse(
        {
            "user_code": "X",
            "device_code": "d",
            "verification_uri": "https://piloci/device",
            "interval": 1,
            "expires_in": 5,
        }
    )
    calls = {"n": 0}

    def _urlopen(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return code_resp
        raise urllib.error.HTTPError("u", 410, "Gone", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._device_login("https://piloci", open_browser=False)

    assert exc.value.code == 1
    assert "만료" in capsys.readouterr().err


def test_device_login_poll_http_500_exits(monkeypatch, capsys) -> None:
    _patch_detect_all_targets(monkeypatch)

    code_resp = _FakeHTTPResponse(
        {
            "user_code": "X",
            "device_code": "d",
            "verification_uri": "https://piloci/device",
            "interval": 1,
            "expires_in": 5,
        }
    )
    calls = {"n": 0}

    def _urlopen(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return code_resp
        raise urllib.error.HTTPError("u", 500, "Server", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._device_login("https://piloci", open_browser=False)

    assert exc.value.code == 1
    assert "폴링 오류" in capsys.readouterr().err


def test_device_login_url_error_during_poll_keeps_polling(monkeypatch) -> None:
    _patch_detect_all_targets(monkeypatch)

    code_resp = _FakeHTTPResponse(
        {
            "user_code": "X",
            "device_code": "d",
            "verification_uri": "https://piloci/device",
            "interval": 1,
            "expires_in": 30,
        }
    )
    approved = _FakeHTTPResponse({"status": "approved", "token": "ok"})
    calls = {"n": 0}

    def _urlopen(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return code_resp
        if calls["n"] == 2:
            raise urllib.error.URLError("transient")
        return approved

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    token, _ = cli._device_login("https://piloci", open_browser=False)
    assert token == "ok"
    assert calls["n"] == 3


def test_device_login_timeout_exits(monkeypatch, capsys) -> None:
    _patch_detect_all_targets(monkeypatch)

    # expires_in=0 → loop body never runs, immediate timeout
    code_resp = _FakeHTTPResponse(
        {
            "user_code": "X",
            "device_code": "d",
            "verification_uri": "https://piloci/device",
            "interval": 1,
            "expires_in": 0,
        }
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: code_resp)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._device_login("https://piloci", open_browser=False)

    assert exc.value.code == 1
    assert "시간 초과" in capsys.readouterr().err


def test_device_login_ignores_non_string_targets(monkeypatch) -> None:
    _patch_detect_all_targets(monkeypatch)

    responses = [
        _FakeHTTPResponse(
            {
                "user_code": "X",
                "device_code": "d",
                "verification_uri": "https://piloci/device",
                "interval": 1,
                "expires_in": 5,
            }
        ),
        _FakeHTTPResponse({"status": "approved", "token": "tk", "targets": [1, 2, "claude", None]}),
    ]
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    token, targets = cli._device_login("https://piloci", open_browser=False)
    assert token == "tk"
    assert targets == ["claude"]


# ---------------------------------------------------------------------------
# _run_login (lines 396-401)
# ---------------------------------------------------------------------------


def test_run_login_writes_config_and_prints_path(monkeypatch, tmp_path, capsys) -> None:
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("piloci.cli._resolve_server", lambda s: "https://piloci")
    monkeypatch.setattr("piloci.cli._device_login", lambda server, open_browser: ("tk", ["claude"]))
    monkeypatch.setattr("piloci.installer.write_config_json", lambda token, server: cfg_file)

    args = argparse.Namespace(server="https://piloci", no_browser=False)
    cli._run_login(args)

    out = capsys.readouterr().out
    assert str(cfg_file) in out
    assert "토큰 저장" in out


# ---------------------------------------------------------------------------
# _run_install (lines 405-474)
# ---------------------------------------------------------------------------


@dataclass
class _StubReport:
    config_path: object
    claude_configured: bool = False
    opencode_configured: bool = False
    notes: list = field(default_factory=list)


def test_run_install_with_full_url_target(monkeypatch, capsys) -> None:
    fetch_mock = MagicMock(return_value={"token": "T", "base_url": "https://piloci"})
    run_install_mock = MagicMock(
        return_value=_StubReport(
            config_path="/tmp/cfg.json",
            claude_configured=True,
            opencode_configured=True,
            notes=["claude: ok"],
        )
    )

    monkeypatch.setattr("piloci.installer.fetch_install_payload", fetch_mock)
    monkeypatch.setattr("piloci.installer.run_install", run_install_mock)
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    args = argparse.Namespace(
        token=None,
        server=None,
        url_or_code="https://piloci.example.com/install/ABCD/",
        force=False,
    )
    cli._run_install(args)

    fetch_mock.assert_called_once_with("https://piloci.example.com/install/ABCD")
    run_install_mock.assert_called_once_with("T", "https://piloci", force=False)
    out = capsys.readouterr().out
    assert "Claude Code 훅 적용" in out
    assert "OpenCode MCP 등록" in out
    assert "claude: ok" in out


def test_run_install_with_code_only_requires_server(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)

    args = argparse.Namespace(token=None, server=None, url_or_code="JUSTACODE", force=False)
    with pytest.raises(SystemExit) as exc:
        cli._run_install(args)

    assert exc.value.code == 2
    assert "--server" in capsys.readouterr().err


def test_run_install_with_code_and_server(monkeypatch) -> None:
    fetch_mock = MagicMock(return_value={"token": "T", "base_url": "https://x"})
    run_install_mock = MagicMock(return_value=_StubReport(config_path="/tmp/cfg.json"))

    monkeypatch.setattr("piloci.installer.fetch_install_payload", fetch_mock)
    monkeypatch.setattr("piloci.installer.run_install", run_install_mock)
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    args = argparse.Namespace(token=None, server="https://x/", url_or_code="CODE123", force=True)
    cli._run_install(args)

    fetch_mock.assert_called_once_with("https://x/install/CODE123")
    run_install_mock.assert_called_once_with("T", "https://x", force=True)


def test_run_install_fetch_failure_exits(monkeypatch, capsys) -> None:
    def _bad_fetch(_url):
        raise RuntimeError("404")

    monkeypatch.setattr("piloci.installer.fetch_install_payload", _bad_fetch)
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("piloci.installer.run_install", MagicMock())
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    args = argparse.Namespace(
        token=None,
        server=None,
        url_or_code="https://piloci/install/CODE",
        force=False,
    )
    with pytest.raises(SystemExit) as exc:
        cli._run_install(args)

    assert exc.value.code == 1
    assert "install URL 조회 실패" in capsys.readouterr().err


def test_run_install_reads_saved_config_token(monkeypatch, tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "piloci"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"token": "saved-token"}))

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: "https://saved")
    run_install_mock = MagicMock(return_value=_StubReport(config_path="/tmp/cfg.json"))
    monkeypatch.setattr("piloci.installer.run_install", run_install_mock)
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    args = argparse.Namespace(token=None, server=None, url_or_code=None, force=False)
    cli._run_install(args)

    run_install_mock.assert_called_once_with("saved-token", "https://saved", force=False)


def test_run_install_saved_config_invalid_json_falls_through(monkeypatch, tmp_path) -> None:
    """Bad JSON in config.json triggers the inline device-login fallback."""
    cfg_dir = tmp_path / ".config" / "piloci"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{ not json")

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("piloci.cli._resolve_server", lambda s: "https://piloci")
    monkeypatch.setattr(
        "piloci.cli._device_login", lambda server, open_browser: ("inline-token", None)
    )
    write_cfg_mock = MagicMock(return_value="/tmp/cfg.json")
    monkeypatch.setattr("piloci.installer.write_config_json", write_cfg_mock)
    run_install_mock = MagicMock(return_value=_StubReport(config_path="/tmp/cfg.json"))
    monkeypatch.setattr("piloci.installer.run_install", run_install_mock)
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    args = argparse.Namespace(token=None, server=None, url_or_code=None, force=False)
    cli._run_install(args)

    write_cfg_mock.assert_called_once_with("inline-token", "https://piloci")
    run_install_mock.assert_called_once_with("inline-token", "https://piloci", force=False)


def test_run_install_inline_login_when_no_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: None)
    monkeypatch.setattr("piloci.cli._resolve_server", lambda s: "https://piloci")
    monkeypatch.setattr(
        "piloci.cli._device_login", lambda server, open_browser: ("inline-tk", None)
    )
    monkeypatch.setattr("piloci.installer.write_config_json", MagicMock())
    run_install_mock = MagicMock(return_value=_StubReport(config_path="/tmp/c.json"))
    monkeypatch.setattr("piloci.installer.run_install", run_install_mock)
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    args = argparse.Namespace(token=None, server=None, url_or_code=None, force=False)
    cli._run_install(args)

    run_install_mock.assert_called_once_with("inline-tk", "https://piloci", force=False)


def test_run_install_runtime_error_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: "https://x")
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)

    def _bad_install(token, base_url, *, force):
        raise RuntimeError("no claude detected")

    monkeypatch.setattr("piloci.installer.run_install", _bad_install)

    args = argparse.Namespace(token="tk", server="https://x", url_or_code=None, force=False)
    with pytest.raises(SystemExit) as exc:
        cli._run_install(args)

    assert exc.value.code == 1
    assert "no claude detected" in capsys.readouterr().err


def test_run_install_version_lookup_failure_uses_unknown(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr("piloci.installer.get_default_server", lambda: "https://x")
    monkeypatch.setattr("piloci.installer.InstallReport", _StubReport)
    monkeypatch.setattr(
        "piloci.installer.run_install",
        MagicMock(return_value=_StubReport(config_path="/tmp/c.json", notes=[])),
    )
    # Break the version import
    import piloci.version

    monkeypatch.delattr(piloci.version, "__version__", raising=False)

    args = argparse.Namespace(token="tk", server="https://x", url_or_code=None, force=False)
    cli._run_install(args)
    out = capsys.readouterr().out
    assert "piLoci v" in out  # version label printed regardless


# ---------------------------------------------------------------------------
# _run_uninstall (lines 478-500)
# ---------------------------------------------------------------------------


def test_run_uninstall_requires_yes_with_backups(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "piloci.installer.list_backups",
        lambda: [("/a.json", "/a.json.piloci-bak"), ("/b.json", "/b.json.piloci-bak")],
    )
    monkeypatch.setattr("piloci.installer.run_uninstall", MagicMock())

    args = argparse.Namespace(yes=False, no_restore=False)
    with pytest.raises(SystemExit) as exc:
        cli._run_uninstall(args)

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "2개" in err
    assert "백업에서 복구 포함" in err


def test_run_uninstall_requires_yes_no_restore(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.list_backups", lambda: [])
    monkeypatch.setattr("piloci.installer.run_uninstall", MagicMock())

    args = argparse.Namespace(yes=False, no_restore=True)
    with pytest.raises(SystemExit) as exc:
        cli._run_uninstall(args)

    assert exc.value.code == 2
    assert "수술적 제거만" in capsys.readouterr().err


def test_run_uninstall_runs_and_prints_items(monkeypatch, capsys) -> None:
    run_mock = MagicMock(return_value=["/path/a", "/path/b"])
    monkeypatch.setattr("piloci.installer.list_backups", lambda: [])
    monkeypatch.setattr("piloci.installer.run_uninstall", run_mock)

    args = argparse.Namespace(yes=True, no_restore=False)
    cli._run_uninstall(args)

    run_mock.assert_called_once_with(restore=True)
    out = capsys.readouterr().out
    assert "/path/a" in out
    assert "/path/b" in out


def test_run_uninstall_no_files_to_remove(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.list_backups", lambda: [])
    monkeypatch.setattr("piloci.installer.run_uninstall", lambda *, restore: [])

    args = argparse.Namespace(yes=True, no_restore=True)
    cli._run_uninstall(args)

    assert "제거할 piloci 파일이 없습니다" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _run_restore (lines 504-526)
# ---------------------------------------------------------------------------


def test_run_restore_no_backups(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.installer.list_backups", lambda: [])
    monkeypatch.setattr("piloci.installer.restore_backups", MagicMock())

    args = argparse.Namespace(yes=False, list=False)
    cli._run_restore(args)

    assert "복구할 백업 파일이 없습니다" in capsys.readouterr().out


def test_run_restore_list_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "piloci.installer.list_backups",
        lambda: [("/a.json", "/a.bak"), ("/b.json", "/b.bak")],
    )
    monkeypatch.setattr("piloci.installer.restore_backups", MagicMock())

    args = argparse.Namespace(yes=False, list=True)
    cli._run_restore(args)

    out = capsys.readouterr().out
    assert "/a.bak" in out and "/a.json" in out
    assert "/b.bak" in out and "/b.json" in out


def test_run_restore_requires_yes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "piloci.installer.list_backups",
        lambda: [("/a.json", "/a.bak")],
    )
    monkeypatch.setattr("piloci.installer.restore_backups", MagicMock())

    args = argparse.Namespace(yes=False, list=False)
    with pytest.raises(SystemExit) as exc:
        cli._run_restore(args)

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "1개 설정 파일을 설치 이전 상태로 복구" in err
    assert "/a.bak" in err


def test_run_restore_executes_and_prints(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "piloci.installer.list_backups",
        lambda: [("/a.json", "/a.bak")],
    )
    monkeypatch.setattr("piloci.installer.restore_backups", MagicMock(return_value=["/a.json"]))

    args = argparse.Namespace(yes=True, list=False)
    cli._run_restore(args)

    assert "복구: /a.json" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _run_setup (lines 531-551)
# ---------------------------------------------------------------------------


def test_run_setup_happy_path(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.cli._resolve_server", lambda s: "https://piloci")
    monkeypatch.setattr(
        "piloci.cli._device_login",
        lambda server, open_browser: ("tk", ["claude", "cursor"]),
    )
    run_install_mock = MagicMock(
        return_value=_StubReport(
            config_path="/tmp/c.json",
            claude_configured=True,
            opencode_configured=True,
            notes=["all good"],
        )
    )
    monkeypatch.setattr("piloci.installer.run_install", run_install_mock)

    args = argparse.Namespace(server=None, no_browser=True, force=True)
    cli._run_setup(args)

    run_install_mock.assert_called_once_with(
        "tk", "https://piloci", force=True, targets=["claude", "cursor"]
    )
    out = capsys.readouterr().out
    assert "Claude Code 훅 적용" in out
    assert "OpenCode MCP 등록" in out
    assert "all good" in out


def test_run_setup_install_failure_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.cli._resolve_server", lambda s: "https://piloci")
    monkeypatch.setattr("piloci.cli._device_login", lambda server, open_browser: ("tk", None))

    def _bad(*a, **k):
        raise RuntimeError("install bombed")

    monkeypatch.setattr("piloci.installer.run_install", _bad)

    args = argparse.Namespace(server=None, no_browser=False, force=False)
    with pytest.raises(SystemExit) as exc:
        cli._run_setup(args)

    assert exc.value.code == 1
    assert "install bombed" in capsys.readouterr().err


def test_run_setup_version_lookup_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr("piloci.cli._resolve_server", lambda s: "https://piloci")
    monkeypatch.setattr("piloci.cli._device_login", lambda server, open_browser: ("tk", None))
    monkeypatch.setattr(
        "piloci.installer.run_install",
        MagicMock(return_value=_StubReport(config_path="/tmp/c.json")),
    )
    import piloci.version

    monkeypatch.delattr(piloci.version, "__version__", raising=False)

    args = argparse.Namespace(server=None, no_browser=False, force=False)
    cli._run_setup(args)

    assert "piLoci v" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _run_backfill_cwd (lines 556-572)
# ---------------------------------------------------------------------------


def test_run_backfill_cwd_prints_summary(monkeypatch, capsys) -> None:
    report = {
        "projects_examined": 5,
        "projects_stamped": 3,
        "projects_split": 1,
        "new_projects": 1,
        "sessions_moved": 7,
    }
    backfill_mock = AsyncMock(return_value=report)
    monkeypatch.setattr("piloci.ops.backfill.backfill_cwd", backfill_mock)

    args = argparse.Namespace(dry_run=False, user_id=None)
    cli._run_backfill_cwd(args)

    backfill_mock.assert_awaited_once_with(dry_run=False, user_id=None)
    out = capsys.readouterr().out
    assert '"projects_examined": 5' in out
    assert "examined=5" in out
    assert "sessions_moved=7" in out
    assert "dry-run" not in out


def test_run_backfill_cwd_dry_run_adds_marker(monkeypatch, capsys) -> None:
    report = {
        "projects_examined": 0,
        "projects_stamped": 0,
        "projects_split": 0,
        "new_projects": 0,
        "sessions_moved": 0,
    }
    monkeypatch.setattr("piloci.ops.backfill.backfill_cwd", AsyncMock(return_value=report))

    args = argparse.Namespace(dry_run=True, user_id="user-1")
    cli._run_backfill_cwd(args)

    out = capsys.readouterr().out
    assert "dry-run — no changes written" in out


# ---------------------------------------------------------------------------
# profile-baseline arg overrides (covers args.endpoint / .paths / etc branches)
# ---------------------------------------------------------------------------


def test_main_profile_baseline_uses_arg_overrides(monkeypatch, capsys) -> None:
    collect_mock = MagicMock(return_value={"latency": 1.0})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "piloci",
            "profile-baseline",
            "--endpoint",
            "http://override:1",
            "--samples",
            "10",
            "--timeout",
            "9.5",
            "--token",
            "override-tk",
            "--path",
            "/foo",
            "--path",
            "/bar",
        ],
    )
    monkeypatch.setattr("piloci.cli.load_dotenv", MagicMock())
    monkeypatch.setattr("piloci.profiling_baseline.collect_baseline", collect_mock)
    monkeypatch.setattr(
        "piloci.profiling_baseline.resolve_baseline_defaults",
        lambda: {
            "endpoint": "http://env:1",
            "paths": ["/x"],
            "samples": 1,
            "timeout": 1.0,
            "token": "env-tk",
        },
    )

    cli.main()

    collect_mock.assert_called_once_with(
        "http://override:1",
        paths=["/foo", "/bar"],
        samples=10,
        timeout=9.5,
        token="override-tk",
    )
    assert '"latency"' in capsys.readouterr().out

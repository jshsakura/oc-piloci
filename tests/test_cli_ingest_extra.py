from __future__ import annotations

import sys
from unittest.mock import MagicMock

from piloci.cli_ingest import (
    _load_claude_code,
    _load_codex,
    _load_gemini,
    _load_opencode,
    _read_config,
    main,
)


def test_read_config_defaults(monkeypatch):
    monkeypatch.delenv("PILOCI_ENDPOINT", raising=False)
    monkeypatch.delenv("PILOCI_TOKEN", raising=False)
    monkeypatch.delenv("PILOCI_PROJECT_ID", raising=False)
    monkeypatch.setattr(
        "piloci.cli_ingest.Path.home",
        lambda: MagicMock(__truediv__=lambda s, o: MagicMock(exists=lambda: False)),
    )
    cfg = _read_config()
    assert cfg["endpoint"] == "http://localhost:8314"
    assert cfg["token"] is None


def test_read_config_from_env(monkeypatch):
    monkeypatch.setenv("PILOCI_ENDPOINT", "http://custom:9999")
    monkeypatch.setenv("PILOCI_TOKEN", "mytoken")
    monkeypatch.setenv("PILOCI_PROJECT_ID", "proj-1")
    monkeypatch.setattr(
        "piloci.cli_ingest.Path.home",
        lambda: MagicMock(__truediv__=lambda s, o: MagicMock(exists=lambda: False)),
    )
    cfg = _read_config()
    assert cfg["endpoint"] == "http://custom:9999"
    assert cfg["token"] == "mytoken"
    assert cfg["project_id"] == "proj-1"


def test_load_claude_code_no_path():
    sid, transcript = _load_claude_code({})
    assert sid is None
    assert transcript == []


def test_load_claude_code_missing_file():
    sid, transcript = _load_claude_code({"transcript_path": "/nonexistent/file.jsonl"})
    assert transcript == []


def test_load_gemini_no_session():
    sid, transcript = _load_gemini(None)
    assert transcript == []


def test_load_gemini_with_env_session(monkeypatch):
    monkeypatch.setenv("GEMINI_SESSION_ID", "gs-123")
    sid, transcript = _load_gemini(None)
    assert sid == "gs-123"
    assert transcript == []


def test_load_codex_missing_file():
    sid, transcript = _load_codex(None)
    assert sid is None
    assert transcript == []


def test_load_opencode_missing_dir(monkeypatch):
    fake_path = MagicMock()
    fake_path.__truediv__ = lambda s, o: MagicMock(exists=lambda: False)
    monkeypatch.setattr("piloci.cli_ingest.Path.home", lambda: fake_path)
    sid, transcript = _load_opencode(None)
    assert transcript == []


def test_main_dry_run_claude_code_no_transcript(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["piloci-ingest", "--client", "claude-code", "--dry-run"])
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: "{}"))
    monkeypatch.setattr(
        "piloci.cli_ingest.Path.home",
        lambda: MagicMock(__truediv__=lambda s, o: MagicMock(exists=lambda: False)),
    )
    rc = main()
    assert rc == 0


def test_main_missing_token(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["piloci-ingest", "--client", "gemini"])
    monkeypatch.delenv("PILOCI_TOKEN", raising=False)
    monkeypatch.delenv("PILOCI_ENDPOINT", raising=False)
    monkeypatch.delenv("PILOCI_PROJECT_ID", raising=False)
    monkeypatch.setattr(
        "piloci.cli_ingest.Path.home",
        lambda: MagicMock(__truediv__=lambda s, o: MagicMock(exists=lambda: False)),
    )
    monkeypatch.setenv("GEMINI_SESSION_ID", "gs-123")
    rc = main()
    assert rc == 0

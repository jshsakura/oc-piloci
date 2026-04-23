"""Tests for piloci-ingest CLI adapters (parse only, no HTTP)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_load_claude_code(tmp_path: Path):
    from piloci.cli_ingest import _load_claude_code

    transcript_file = tmp_path / "transcript.jsonl"
    transcript_file.write_text(
        '{"role":"user","content":"hi"}\n'
        '{"role":"assistant","content":"hello"}\n'
    )
    stdin_data = {"session_id": "sess-1", "transcript_path": str(transcript_file)}
    session_id, transcript = _load_claude_code(stdin_data)

    assert session_id == "sess-1"
    assert len(transcript) == 2
    assert transcript[0]["content"] == "hi"


def test_load_claude_code_missing_file():
    from piloci.cli_ingest import _load_claude_code

    session_id, transcript = _load_claude_code(
        {"session_id": "sess-1", "transcript_path": "/nonexistent"}
    )
    assert session_id == "sess-1"
    assert transcript == []


def test_load_codex(tmp_path: Path):
    from piloci.cli_ingest import _load_codex

    hist = tmp_path / "history.jsonl"
    hist.write_text(
        '{"session_id":"s1","role":"user","content":"a"}\n'
        '{"session_id":"s1","role":"assistant","content":"b"}\n'
    )
    session_id, transcript = _load_codex(str(hist))
    assert session_id == "s1"
    assert len(transcript) == 2


def test_load_codex_missing_file(tmp_path: Path):
    from piloci.cli_ingest import _load_codex

    session_id, transcript = _load_codex(str(tmp_path / "missing.jsonl"))
    assert session_id is None
    assert transcript == []


def test_load_opencode(tmp_path: Path, monkeypatch):
    from piloci.cli_ingest import _load_opencode

    # Fake OpenCode storage layout
    storage = tmp_path / ".local/share/opencode/storage"
    storage.mkdir(parents=True)
    session_file = storage / "session-abc.json"
    session_file.write_text(json.dumps({
        "id": "oc-session-1",
        "messages": [{"role": "user", "content": "hello oc"}],
    }))
    monkeypatch.setenv("HOME", str(tmp_path))
    # pathlib's Path.home() reads from HOME on POSIX
    session_id, transcript = _load_opencode(None)
    assert session_id == "oc-session-1"
    assert len(transcript) == 1
    assert transcript[0]["content"] == "hello oc"


def test_load_opencode_no_storage(tmp_path: Path, monkeypatch):
    from piloci.cli_ingest import _load_opencode

    monkeypatch.setenv("HOME", str(tmp_path))
    session_id, transcript = _load_opencode("given-id")
    assert session_id == "given-id"
    assert transcript == []

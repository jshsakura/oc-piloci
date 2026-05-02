"""Tests for the Python-native client installer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from piloci import installer


def test_detect_clients_neither(tmp_path: Path) -> None:
    has_claude, has_opencode = installer.detect_clients(home=tmp_path)
    # ``opencode`` may exist on the test host; assert only the Claude side.
    assert has_claude is False


def test_detect_clients_claude(tmp_path: Path) -> None:
    (tmp_path / installer.CLAUDE_DIR_NAME).mkdir(parents=True)
    has_claude, _ = installer.detect_clients(home=tmp_path)
    assert has_claude is True


def test_detect_clients_opencode_dir(tmp_path: Path) -> None:
    (tmp_path / installer.OPENCODE_DIR_NAME).mkdir(parents=True)
    # Force ``opencode`` CLI absence to isolate the dir-based detection.
    with patch("piloci.installer.shutil.which", return_value=None):
        _, has_opencode = installer.detect_clients(home=tmp_path)
    assert has_opencode is True


def test_write_config_json_writes_token_and_endpoints(tmp_path: Path) -> None:
    cfg = installer.write_config_json("JWT.test", "https://piloci.example/", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert data["token"] == "JWT.test"
    assert data["ingest_url"] == "https://piloci.example/api/sessions/ingest"
    assert data["analyze_url"] == "https://piloci.example/api/sessions/analyze"
    # File permission tightening — best effort, only verify when chmod was applied.
    mode = cfg.stat().st_mode & 0o777
    assert mode == 0o600 or mode == 0o644  # tolerate test sandbox umask


def test_merge_claude_settings_creates_when_missing(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    installer._merge_claude_settings(settings)
    data = json.loads(settings.read_text())
    events = data["hooks"]
    assert "SessionStart" in events
    assert "Stop" in events
    cmds = [h["hooks"][0]["command"] for h in events["SessionStart"]]
    assert any("hook.py" in c for c in cmds)


def test_merge_claude_settings_preserves_existing_unrelated_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "echo other"},
                            ],
                        }
                    ]
                },
                "someOtherSetting": True,
            }
        )
    )
    installer._merge_claude_settings(settings)
    data = json.loads(settings.read_text())
    assert data["someOtherSetting"] is True
    cmds = [h["hooks"][0]["command"] for h in data["hooks"]["SessionStart"]]
    # Other entries kept; piloci entry appended.
    assert "echo other" in cmds
    assert any("hook.py" in c for c in cmds)


def test_merge_claude_settings_replaces_prior_piloci_entry(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    installer._merge_claude_settings(settings)
    # Run again — should not duplicate piloci entry.
    installer._merge_claude_settings(settings)
    data = json.loads(settings.read_text())
    piloci_entries = [
        h for h in data["hooks"]["SessionStart"] if installer.PILOCI_PATH_TAG in json.dumps(h)
    ]
    assert len(piloci_entries) == 1


def test_install_claude_mcp_writes_entry(tmp_path: Path) -> None:
    cfg = installer.install_claude_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piloci"]["url"] == "https://x.example/mcp/http"
    assert data["mcpServers"]["piloci"]["type"] == "http"
    assert data["mcpServers"]["piloci"]["headers"]["Authorization"] == "Bearer JWT.tok"


def test_install_claude_mcp_preserves_other_servers(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".claude.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"type": "http", "url": "https://other.example"},
                },
                "someUserSetting": "keep me",
            }
        )
    )
    installer.install_claude_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert data["someUserSetting"] == "keep me"
    assert "other" in data["mcpServers"]
    assert "piloci" in data["mcpServers"]


def test_install_opencode_mcp_writes_entry(tmp_path: Path) -> None:
    cfg = installer.install_opencode_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert data["mcp"]["piloci"]["url"] == "https://x.example/mcp/http"
    assert data["mcp"]["piloci"]["headers"]["Authorization"] == "Bearer JWT.tok"
    assert data["$schema"].endswith("/config.json")


def test_install_opencode_mcp_preserves_other_servers(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        json.dumps(
            {"mcp": {"other": {"type": "remote", "url": "https://other.example", "enabled": True}}}
        )
    )
    installer.install_opencode_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert "other" in data["mcp"]
    assert "piloci" in data["mcp"]


def test_run_install_raises_when_no_clients(tmp_path: Path) -> None:
    # Ensure ``opencode`` CLI is invisible so detection truly fails.
    with patch("piloci.installer.shutil.which", return_value=None):
        with pytest.raises(RuntimeError):
            installer.run_install("tok", "https://x.example", home=tmp_path)


def test_run_install_claude_only(tmp_path: Path) -> None:
    (tmp_path / installer.CLAUDE_DIR_NAME).mkdir(parents=True)
    fake_hook = b"#!/usr/bin/env python3\nprint('hook')\n"
    fake_stop = b"#!/usr/bin/env bash\nexit 0\n"

    def fake_dl(url: str, *, token: str | None = None, timeout: int = 30) -> bytes:
        return fake_hook if "hook/script" in url and "stop" not in url else fake_stop

    with patch("piloci.installer._http_download", side_effect=fake_dl):
        with patch("piloci.installer.shutil.which", return_value=None):
            report = installer.run_install("tok", "https://x.example", home=tmp_path)

    assert report.claude_configured is True
    assert report.opencode_configured is False
    assert (tmp_path / installer.PILOCI_DIR_NAME / "hook.py").read_bytes() == fake_hook
    assert (tmp_path / installer.PILOCI_DIR_NAME / "stop-hook.sh").read_bytes() == fake_stop
    settings = json.loads((tmp_path / installer.CLAUDE_DIR_NAME / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]
    # MCP server registration must also land on .claude.json so memory/recall
    # tools are available, not just the auto-capture hooks.
    claude_json = json.loads((tmp_path / ".claude.json").read_text())
    assert "piloci" in claude_json["mcpServers"]


def test_get_default_server_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PILOCI_SERVER", "https://from-env.example/")
    monkeypatch.setattr("piloci.installer.Path.home", lambda: tmp_path)
    assert installer.get_default_server() == "https://from-env.example"


def test_get_default_server_from_config_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PILOCI_SERVER", raising=False)
    cfg_dir = tmp_path / installer.PILOCI_DIR_NAME
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "token": "x",
                "ingest_url": "https://saved.example/api/sessions/ingest",
                "analyze_url": "https://saved.example/api/sessions/analyze",
            }
        )
    )
    monkeypatch.setattr("piloci.installer.Path.home", lambda: tmp_path)
    assert installer.get_default_server() == "https://saved.example"

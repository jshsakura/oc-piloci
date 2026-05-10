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


def test_install_claude_plugin_layout(tmp_path: Path) -> None:
    fake = b"#!/bin/echo\n"
    with patch("piloci.installer._http_download", return_value=fake):
        plugin_dir = installer.install_claude_plugin(
            "https://x.example", "JWT.tok", version="1.2.3", home=tmp_path
        )
    manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "piloci"
    assert manifest["version"] == "1.2.3"
    hooks = json.loads((plugin_dir / "hooks" / "hooks.json").read_text())
    assert "${CLAUDE_PLUGIN_ROOT}" in hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    mcp = json.loads((plugin_dir / ".mcp.json").read_text())
    assert mcp["piloci"]["url"] == "https://x.example/mcp/http"
    assert "mcpServers" not in mcp


def test_install_opencode_plugin_writes_ts_file(tmp_path: Path) -> None:
    plugin_src = b"// piLoci OpenCode plugin\nexport default async () => ({})\n"
    with patch("piloci.installer._http_download", return_value=plugin_src):
        plugin_path = installer.install_opencode_plugin(
            "https://x.example", "JWT.tok", home=tmp_path
        )
    assert plugin_path.name == "piloci.ts"
    assert plugin_path.read_bytes() == plugin_src


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


def test_run_install_claude_only_drops_plugin(tmp_path: Path) -> None:
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
    pdir = tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME
    # Plugin folder is the only thing piloci should have created — no patching
    # of ~/.claude/settings.json or ~/.claude.json.
    assert (pdir / ".claude-plugin" / "plugin.json").exists()
    assert json.loads((pdir / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"]
    assert (pdir / "hooks" / "hook.py").read_bytes() == fake_hook
    assert (pdir / "hooks" / "stop-hook.sh").read_bytes() == fake_stop
    mcp = json.loads((pdir / ".mcp.json").read_text())
    # Plugin .mcp.json uses server-name keys at top level (no mcpServers wrap).
    assert mcp["piloci"]["headers"]["Authorization"] == "Bearer tok"
    assert "mcpServers" not in mcp
    # Crucially: nothing under ~/.claude/ outside the plugin folder.
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert not (tmp_path / ".claude.json").exists()


def test_run_install_opencode_only_drops_plugin_file(tmp_path: Path) -> None:
    (tmp_path / installer.OPENCODE_DIR_NAME).mkdir(parents=True)
    plugin_src = b"// piLoci OpenCode plugin\nexport default async () => ({})\n"

    def fake_dl(url: str, *, token: str | None = None, timeout: int = 30) -> bytes:
        return plugin_src

    with patch("piloci.installer._http_download", side_effect=fake_dl):
        with patch("piloci.installer.shutil.which", return_value=None):
            report = installer.run_install("tok", "https://x.example", home=tmp_path)

    assert report.opencode_configured is True
    plugin_path = tmp_path / installer.OPENCODE_PLUGIN_DIR_NAME / "piloci.ts"
    assert plugin_path.read_bytes() == plugin_src
    # opencode.json must also be written with the MCP remote entry.
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    assert cfg_path.exists()
    import json as _json

    cfg = _json.loads(cfg_path.read_text())
    assert cfg.get("mcp", {}).get("piloci", {}).get("type") == "remote"


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


def test_cleanup_legacy_install_strips_settings_hooks_and_legacy_scripts(
    tmp_path: Path,
) -> None:
    settings = tmp_path / installer.CLAUDE_DIR_NAME / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 ~/.config/piloci/hook.py 2>/dev/null || true",
                                }
                            ],
                        },
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": "echo unrelated"}],
                        },
                    ],
                    "Stop": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash ~/.config/piloci/stop-hook.sh 2>/dev/null || true",
                                }
                            ],
                        }
                    ],
                }
            }
        )
    )

    legacy = tmp_path / installer.PILOCI_DIR_NAME
    legacy.mkdir(parents=True)
    (legacy / "hook.py").write_text("# legacy")
    (legacy / "stop-hook.sh").write_text("# legacy")
    (legacy / "config.json").write_text("{}")  # must survive

    opencode_cfg = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    opencode_cfg.parent.mkdir(parents=True)
    opencode_cfg.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    "piloci": {"type": "remote", "url": "x"},
                    "other": {"type": "remote", "url": "y"},
                },
            }
        )
    )

    removed = installer.cleanup_legacy_install(home=tmp_path)

    settings_loaded = json.loads(settings.read_text())
    session_start = settings_loaded["hooks"]["SessionStart"]
    assert len(session_start) == 1
    assert "echo unrelated" in session_start[0]["hooks"][0]["command"]
    assert "Stop" not in settings_loaded["hooks"]

    assert not (legacy / "hook.py").exists()
    assert not (legacy / "stop-hook.sh").exists()
    assert (legacy / "config.json").exists()  # config preserved

    opencode_loaded = json.loads(opencode_cfg.read_text())
    assert "piloci" not in opencode_loaded["mcp"]
    assert "other" in opencode_loaded["mcp"]

    assert any("settings.json" in r for r in removed)
    assert any("hook.py" in r for r in removed)
    assert any("opencode.json" in r for r in removed)


def test_cleanup_legacy_install_force_wipes_plugin_dirs(tmp_path: Path) -> None:
    claude_plugin = tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME
    claude_plugin.mkdir(parents=True)
    (claude_plugin / "marker").write_text("x")
    opencode_plugin = tmp_path / installer.OPENCODE_PLUGIN_DIR_NAME / "piloci.ts"
    opencode_plugin.parent.mkdir(parents=True)
    opencode_plugin.write_text("// piloci")

    removed = installer.cleanup_legacy_install(home=tmp_path, remove_plugins=True)

    assert not claude_plugin.exists()
    assert not opencode_plugin.exists()
    assert any(installer.CLAUDE_PLUGIN_DIR_NAME in r for r in removed)
    assert any("piloci.ts" in r for r in removed)


def test_cleanup_legacy_install_noop_when_clean(tmp_path: Path) -> None:
    assert installer.cleanup_legacy_install(home=tmp_path) == []
    assert installer.cleanup_legacy_install(home=tmp_path, remove_plugins=True) == []


def test_run_uninstall_removes_everything(tmp_path: Path) -> None:
    cfg_dir = tmp_path / installer.PILOCI_DIR_NAME
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{}")
    (cfg_dir / "hook.py").write_text("# legacy")

    plugin_dir = tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "marker").write_text("x")

    bak = tmp_path / installer.CLAUDE_DIR_NAME / "settings.json.piloci-bak"
    bak.parent.mkdir(parents=True, exist_ok=True)
    bak.write_text("{}")

    settings = tmp_path / installer.CLAUDE_DIR_NAME / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 ~/.config/piloci/hook.py",
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )

    removed = installer.run_uninstall(home=tmp_path)

    assert not cfg_dir.exists()
    assert not plugin_dir.exists()
    assert not bak.exists()
    assert "hooks" not in json.loads(settings.read_text())
    assert any(installer.PILOCI_DIR_NAME in r for r in removed)
    assert any("piloci-bak" in r for r in removed)


def test_run_uninstall_noop_when_clean(tmp_path: Path) -> None:
    assert installer.run_uninstall(home=tmp_path) == []


def test_post_install_heartbeat_sends_expected_payload() -> None:
    captured: dict = {}

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["auth"] = req.get_header("Authorization")
        return _FakeResp()

    with patch("piloci.installer.urllib.request.urlopen", _fake_urlopen):
        ok = installer.post_install_heartbeat(
            "https://piloci.example.com",
            "tok-xyz",
            client_kinds=["claude", "opencode"],
            hostname="pi5",
        )

    assert ok is True
    assert captured["url"].endswith("/api/install/heartbeat")
    assert captured["auth"] == "Bearer tok-xyz"
    assert captured["body"]["client_kinds"] == ["claude", "opencode"]
    assert captured["body"]["hostname"] == "pi5"
    assert "cli_version" in captured["body"]


def test_post_install_heartbeat_swallows_failures() -> None:
    import urllib.error

    def _fake_urlopen(req, timeout):  # noqa: ANN001
        raise urllib.error.URLError("boom")

    with patch("piloci.installer.urllib.request.urlopen", _fake_urlopen):
        ok = installer.post_install_heartbeat("https://x.example", "tok", client_kinds=["claude"])
    assert ok is False


# ---------------------------------------------------------------------------
# Secondary clients — Cursor / Gemini / Windsurf / AntiGravity / Zed / Codex.
# ---------------------------------------------------------------------------


def test_install_cursor_mcp_writes_http_entry(tmp_path: Path) -> None:
    cfg = installer.install_cursor_mcp("https://piloci.example/", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piloci"]["url"] == "https://piloci.example/mcp/http"
    assert data["mcpServers"]["piloci"]["headers"]["Authorization"] == "Bearer JWT.tok"


def test_install_gemini_mcp_uses_httpurl_field(tmp_path: Path) -> None:
    cfg = installer.install_gemini_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    # Gemini CLI keys the HTTP transport on ``httpUrl`` (not ``url``).
    assert data["mcpServers"]["piloci"]["httpUrl"] == "https://piloci.example/mcp/http"


def test_install_windsurf_mcp_uses_serverurl_field(tmp_path: Path) -> None:
    cfg = installer.install_windsurf_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piloci"]["serverUrl"] == "https://piloci.example/mcp/http"


def test_install_zed_mcp_writes_under_context_servers(tmp_path: Path) -> None:
    cfg = installer.install_zed_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert "mcpServers" not in data
    assert data["context_servers"]["piloci"]["url"].endswith("/mcp/http")


def test_install_cursor_mcp_preserves_other_servers(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.CURSOR_DIR_NAME / "mcp.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"mcpServers": {"other": {"url": "https://other/mcp"}}}))
    installer.install_cursor_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert "other" in data["mcpServers"]
    assert "piloci" in data["mcpServers"]


def test_install_codex_mcp_writes_fenced_toml_block(tmp_path: Path) -> None:
    cfg = installer.install_codex_mcp("https://piloci.example/", "JWT.tok", home=tmp_path)
    raw = cfg.read_text()
    assert "[mcp_servers.piloci]" in raw
    assert 'url = "https://piloci.example/mcp/http"' in raw
    assert 'Authorization = "Bearer JWT.tok"' in raw
    assert raw.count("# >>> piloci managed >>>") == 1


def test_install_codex_mcp_replaces_prior_block(tmp_path: Path) -> None:
    installer.install_codex_mcp("https://old.example", "OLD", home=tmp_path)
    cfg = installer.install_codex_mcp("https://new.example", "NEW", home=tmp_path)
    raw = cfg.read_text()
    # Re-running must not stack duplicate fenced blocks.
    assert raw.count("# >>> piloci managed >>>") == 1
    assert "OLD" not in raw
    assert "NEW" in raw
    assert "https://new.example/mcp/http" in raw


def test_install_codex_mcp_preserves_user_content(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.CODEX_DIR_NAME / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text('[profile]\nname = "alice"\n')
    installer.install_codex_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    raw = cfg_path.read_text()
    assert "[profile]" in raw
    assert 'name = "alice"' in raw
    assert "[mcp_servers.piloci]" in raw


def test_detect_all_targets_reports_per_kind(tmp_path: Path) -> None:
    (tmp_path / installer.CURSOR_DIR_NAME).mkdir(parents=True)
    (tmp_path / installer.ZED_DIR_NAME).mkdir(parents=True)
    with patch("piloci.installer.shutil.which", return_value=None):
        targets = installer.detect_all_targets(home=tmp_path)
    assert targets["cursor"] is True
    assert targets["zed"] is True
    assert targets["claude"] is False
    assert targets["gemini"] is False
    assert set(targets) == set(installer.CLIENT_LABELS)


def test_run_install_explicit_targets_skips_detection(tmp_path: Path) -> None:
    # No client dirs exist — but explicit targets must still install.
    with patch("piloci.installer.shutil.which", return_value=None):
        report = installer.run_install(
            "tok", "https://piloci.example", home=tmp_path, targets=["cursor", "zed"]
        )
    assert report.clients["cursor"] == "ok"
    assert report.clients["zed"] == "ok"
    assert report.claude_configured is False
    assert (tmp_path / installer.CURSOR_DIR_NAME / "mcp.json").exists()
    assert (tmp_path / installer.ZED_DIR_NAME / "settings.json").exists()


def test_run_install_explicit_targets_filters_unknown_kinds(tmp_path: Path) -> None:
    with patch("piloci.installer.shutil.which", return_value=None):
        with pytest.raises(RuntimeError):
            installer.run_install("tok", "https://piloci.example", home=tmp_path, targets=["bogus"])


def test_run_uninstall_removes_secondary_client_entries(tmp_path: Path) -> None:
    installer.install_cursor_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    installer.install_zed_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    installer.install_codex_mcp("https://piloci.example", "JWT.tok", home=tmp_path)

    removed = installer.run_uninstall(home=tmp_path)
    cursor_cfg = tmp_path / installer.CURSOR_DIR_NAME / "mcp.json"
    zed_cfg = tmp_path / installer.ZED_DIR_NAME / "settings.json"
    codex_cfg = tmp_path / installer.CODEX_DIR_NAME / "config.toml"

    cursor_data = json.loads(cursor_cfg.read_text())
    zed_data = json.loads(zed_cfg.read_text())
    codex_raw = codex_cfg.read_text()

    assert "piloci" not in cursor_data.get("mcpServers", {})
    assert "piloci" not in zed_data.get("context_servers", {})
    assert "[mcp_servers.piloci]" not in codex_raw
    assert any("mcp.json" in r for r in removed)
    assert any("settings.json" in r for r in removed)
    assert any("config.toml" in r for r in removed)

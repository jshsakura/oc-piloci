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
    d = tmp_path / installer.CLAUDE_DIR_NAME
    d.mkdir(parents=True)
    (d / "settings.json").write_text("{}")  # non-empty = real install signal
    has_claude, _ = installer.detect_clients(home=tmp_path)
    assert has_claude is True


def test_detect_clients_opencode_dir(tmp_path: Path) -> None:
    d = tmp_path / installer.OPENCODE_DIR_NAME
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    # Force ``opencode`` CLI absence to isolate the dir-based detection.
    with patch("piloci.installer.shutil.which", return_value=None):
        _, has_opencode = installer.detect_clients(home=tmp_path)
    assert has_opencode is True


def test_detect_ignores_empty_leftover_dir(tmp_path: Path) -> None:
    # An empty ~/.cursor (left behind after uninstall) must NOT be detected.
    (tmp_path / installer.CURSOR_DIR_NAME).mkdir(parents=True)
    (tmp_path / installer.CLAUDE_DIR_NAME).mkdir(parents=True)
    with patch("piloci.installer.shutil.which", return_value=None):
        targets = installer.detect_all_targets(home=tmp_path)
        has_claude, _ = installer.detect_clients(home=tmp_path)
    assert targets["cursor"] is False
    assert has_claude is False


def test_detect_nonempty_cursor_dir(tmp_path: Path) -> None:
    d = tmp_path / installer.CURSOR_DIR_NAME
    d.mkdir(parents=True)
    (d / "mcp.json").write_text("{}")
    with patch("piloci.installer.shutil.which", return_value=None):
        targets = installer.detect_all_targets(home=tmp_path)
    assert targets["cursor"] is True


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


def test_install_claude_uses_direct_injection(tmp_path: Path) -> None:
    """Claude install must wire hooks directly into settings.json + .claude.json,
    NOT a ~/.claude/plugins folder (which Claude Code never auto-enables)."""
    fake = b"#!/usr/bin/env python3\n"
    with patch("piloci.installer._http_download", return_value=fake):
        settings_path = installer.install_claude_plugin(
            "https://x.example", "JWT.tok", home=tmp_path
        )

    # Hook scripts land in the shared config dir, referenced by settings.json.
    assert (tmp_path / ".config" / "piloci" / "hook.py").read_bytes() == fake
    assert (tmp_path / ".config" / "piloci" / "stop-hook.py").read_bytes() == fake

    # Hooks are merged into settings.json (the path that actually fires).
    assert settings_path == tmp_path / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    for event in ("SessionStart", "Stop"):
        cmds = [h["hooks"][0]["command"] for h in settings["hooks"][event]]
        assert any("~/.config/piloci/" in c and "hook.py" in c for c in cmds)
        assert all("${CLAUDE_PLUGIN_ROOT}" not in c for c in cmds)

    # MCP server registered globally in ~/.claude.json.
    claude_json = json.loads((tmp_path / ".claude.json").read_text())
    assert claude_json["mcpServers"]["piloci"]["url"] == "https://x.example/mcp/http"

    # No broken plugin folder left behind.
    assert not (tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME).exists()


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


def test_run_install_claude_only_injects_hooks(tmp_path: Path) -> None:
    cdir = tmp_path / installer.CLAUDE_DIR_NAME
    cdir.mkdir(parents=True)
    (cdir / "settings.json").write_text("{}")  # non-empty so detection fires
    fake_hook = b"#!/usr/bin/env python3\nprint('hook')\n"
    fake_stop = b"#!/usr/bin/env python3\nexit(0)\n"

    def fake_dl(url: str, *, token: str | None = None, timeout: int = 30) -> bytes:
        return fake_hook if "hook/script" in url and "stop" not in url else fake_stop

    with patch("piloci.installer._http_download", side_effect=fake_dl):
        with patch("piloci.installer.shutil.which", return_value=None):
            report = installer.run_install("tok", "https://x.example", home=tmp_path)

    assert report.claude_configured is True
    assert report.opencode_configured is False

    # No plugin folder — Claude Code never auto-enables it, so hooks go direct.
    assert not (tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME).exists()

    # Hook scripts land in the shared config dir.
    cfg_dir = tmp_path / ".config" / "piloci"
    assert (cfg_dir / "hook.py").read_bytes() == fake_hook
    assert (cfg_dir / "stop-hook.py").read_bytes() == fake_stop

    # SessionStart + Stop hooks merged into settings.json, pointing at config dir.
    settings = json.loads((tmp_path / installer.CLAUDE_DIR_NAME / "settings.json").read_text())
    stop_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "~/.config/piloci/stop-hook.py" in stop_cmd
    assert "${CLAUDE_PLUGIN_ROOT}" not in stop_cmd
    assert settings["hooks"]["SessionStart"]

    # MCP registered globally in ~/.claude.json.
    claude_json = json.loads((tmp_path / ".claude.json").read_text())
    assert claude_json["mcpServers"]["piloci"]["url"].endswith("/mcp/http")
    assert claude_json["mcpServers"]["piloci"]["headers"]["Authorization"] == "Bearer tok"


def test_run_install_opencode_only_drops_plugin_file(tmp_path: Path) -> None:
    odir = tmp_path / installer.OPENCODE_DIR_NAME
    odir.mkdir(parents=True)
    (odir / "config.json").write_text("{}")  # non-empty so detection fires
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
    note = "\n".join(report.notes)
    assert "opencode.json MCP 등록" in note
    assert "설정 파일 안 건드림" not in note


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
    assert not bak.exists()  # backup consumed by restore
    # settings restored from backup ({}) — hooks are gone
    assert "hooks" not in json.loads(settings.read_text())
    assert any(installer.PILOCI_DIR_NAME in r for r in removed)
    # restore is reported (원본 복구)
    assert any("복구" in r for r in removed)


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


def test_install_codex_mcp_cleans_legacy_unmarked_block(tmp_path: Path) -> None:
    """A pre-marker [mcp_servers.piloci] block from an old install must be
    removed before the new marker-wrapped block is appended — otherwise Codex
    refuses the TOML with a duplicate key error."""

    cfg_path = tmp_path / installer.CODEX_DIR_NAME / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        "[mcp_servers.piloci]\n"
        'url = "https://old.example/mcp/http"\n'
        "[mcp_servers.piloci.http_headers]\n"
        'Authorization = "Bearer OLD"\n'
    )
    installer.install_codex_mcp("https://new.example", "NEW", home=tmp_path)
    raw = cfg_path.read_text()
    # Exactly one piloci section header (the new marker-wrapped one).
    assert raw.count("[mcp_servers.piloci]") == 1
    assert raw.count("[mcp_servers.piloci.http_headers]") == 1
    assert "OLD" not in raw
    assert "NEW" in raw
    assert installer._CODEX_BLOCK_BEGIN in raw


def test_install_codex_mcp_cleans_both_legacy_and_marker(tmp_path: Path) -> None:
    """Legacy unmarked piloci + marker-wrapped block coexist (the broken state
    that produced the duplicate-key error in v0.3.98). Install must wipe both."""

    cfg_path = tmp_path / installer.CODEX_DIR_NAME / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        "[mcp_servers.piloci]\n"
        'url = "https://legacy.example/mcp/http"\n'
        "[mcp_servers.piloci.http_headers]\n"
        'Authorization = "Bearer LEGACY"\n'
        "\n"
        f"{installer._CODEX_BLOCK_BEGIN}\n"
        "[mcp_servers.piloci]\n"
        'url = "https://prev.example/mcp/http"\n'
        "[mcp_servers.piloci.http_headers]\n"
        'Authorization = "Bearer PREV"\n'
        f"{installer._CODEX_BLOCK_END}\n"
    )
    installer.install_codex_mcp("https://new.example", "NEW", home=tmp_path)
    raw = cfg_path.read_text()
    assert raw.count("[mcp_servers.piloci]") == 1
    assert "LEGACY" not in raw
    assert "PREV" not in raw
    assert "NEW" in raw


def test_install_codex_mcp_preserves_other_mcp_servers(tmp_path: Path) -> None:
    """A user-owned [mcp_servers.something] table must be left intact even when
    a legacy piloci block is being cleaned up next to it."""

    cfg_path = tmp_path / installer.CODEX_DIR_NAME / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        "[mcp_servers.piloci]\n"
        'url = "https://old.example/mcp/http"\n'
        "\n"
        "[mcp_servers.foobar]\n"
        'url = "https://foobar.example/mcp"\n'
        "[mcp_servers.foobar.http_headers]\n"
        'X-Key = "user-token"\n'
    )
    installer.install_codex_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    raw = cfg_path.read_text()
    assert "[mcp_servers.foobar]" in raw
    assert "user-token" in raw
    assert raw.count("[mcp_servers.piloci]") == 1
    assert "https://old.example" not in raw


def test_install_codex_mcp_preserves_user_session_start(tmp_path: Path) -> None:
    """A user-owned [[SessionStart]] hook (not from piloci) must survive."""

    cfg_path = tmp_path / installer.CODEX_DIR_NAME / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        "[[SessionStart]]\n"
        "[[SessionStart.hooks]]\n"
        'type = "command"\n'
        'command = "echo hello-from-user"\n'
        "\n"
        "[mcp_servers.piloci]\n"
        'url = "https://old.example/mcp/http"\n'
    )
    installer.install_codex_mcp("https://piloci.example", "JWT.tok", home=tmp_path)
    raw = cfg_path.read_text()
    assert "echo hello-from-user" in raw
    assert raw.count("[mcp_servers.piloci]") == 1


def test_strip_legacy_codex_piloci_counts_removed_headers() -> None:
    """The helper reports how many piloci section headers it removed so
    callers can surface the cleanup in install reports if desired."""

    raw = (
        "[unrelated]\n"
        "x = 1\n"
        "[mcp_servers.piloci]\n"
        'url = "x"\n'
        "[mcp_servers.piloci.http_headers]\n"
        'Authorization = "y"\n'
        "[other]\n"
        "y = 2\n"
    )
    cleaned, removed = installer._strip_legacy_codex_piloci(raw)
    assert removed == 2
    assert "[mcp_servers.piloci]" not in cleaned
    assert "[mcp_servers.piloci.http_headers]" not in cleaned
    assert "[unrelated]" in cleaned
    assert "[other]" in cleaned


def test_strip_legacy_codex_piloci_no_op_on_clean_file() -> None:
    raw = '[profile]\nname = "alice"\n'
    cleaned, removed = installer._strip_legacy_codex_piloci(raw)
    assert removed == 0
    assert cleaned == raw


def test_detect_all_targets_reports_per_kind(tmp_path: Path) -> None:
    cur = tmp_path / installer.CURSOR_DIR_NAME
    cur.mkdir(parents=True)
    (cur / "mcp.json").write_text("{}")  # non-empty = real install signal
    zed = tmp_path / installer.ZED_DIR_NAME
    zed.mkdir(parents=True)
    (zed / "settings.json").write_text("{}")
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


# ---------------------------------------------------------------------------
# JSONC parser + Python launcher quirks
# ---------------------------------------------------------------------------


def test_parse_jsonc_preserves_newlines_in_block_comment() -> None:
    """Block comments are wiped but newlines kept so error line numbers stay sane."""
    text = '{\n  /* multi\n     line\n     comment */\n  "k": 1\n}'
    out = installer._parse_jsonc(text)
    assert out == {"k": 1}


def test_parse_jsonc_strips_trailing_commas_and_line_comments() -> None:
    text = '{\n  "k": 1, // trailing line comment\n  "arr": [1, 2,],\n}'
    assert installer._parse_jsonc(text) == {"k": 1, "arr": [1, 2]}


def test_python_cmd_windows_with_py_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(
        installer.shutil, "which", lambda name: "/win/py.exe" if name == "py" else None
    )
    assert installer._python_cmd() == "py"


def test_python_cmd_windows_without_py_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
    assert installer._python_cmd() == "python"


# ---------------------------------------------------------------------------
# chmod PermissionError swallows (write_config_json, plugin installs, ...)
# ---------------------------------------------------------------------------


def _chmod_always_raises(self, mode: int) -> None:
    raise PermissionError("simulated read-only filesystem")


def test_write_config_json_swallows_chmod_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "chmod", _chmod_always_raises)
    cfg = installer.write_config_json("tok", "https://x.example/", home=tmp_path)
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert data["token"] == "tok"


def test_install_claude_plugin_swallows_chmod_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "chmod", _chmod_always_raises)
    with patch("piloci.installer._http_download", return_value=b"hook"):
        installer.install_claude_plugin("https://x.example", "JWT.tok", home=tmp_path)
    cfg_dir = tmp_path / ".config" / "piloci"
    assert (cfg_dir / "hook.py").exists()
    assert (cfg_dir / "stop-hook.py").exists()
    assert (tmp_path / installer.CLAUDE_DIR_NAME / "settings.json").exists()


def test_install_claude_plugin_removes_legacy_stop_hook_sh(tmp_path: Path) -> None:
    # Pre-create the legacy bash stop-hook so install_claude_plugin's cleanup
    # branch (the legacy_sh.unlink path) runs.
    hooks_dir = tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME / "hooks"
    hooks_dir.mkdir(parents=True)
    legacy = hooks_dir / "stop-hook.sh"
    legacy.write_text("# legacy bash")
    with patch("piloci.installer._http_download", return_value=b"hook"):
        installer.install_claude_plugin("https://x.example", "JWT.tok", home=tmp_path)
    assert not legacy.exists()


def test_install_claude_plugin_legacy_sh_unlink_oserror_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks_dir = tmp_path / installer.CLAUDE_PLUGIN_DIR_NAME / "hooks"
    hooks_dir.mkdir(parents=True)
    legacy = hooks_dir / "stop-hook.sh"
    legacy.write_text("# legacy bash")

    real_unlink = Path.unlink

    def _unlink(self, *a, **kw):  # noqa: ANN001
        if self.name == "stop-hook.sh":
            raise OSError("locked")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _unlink)
    with patch("piloci.installer._http_download", return_value=b"hook"):
        # Must not raise.
        installer.install_claude_plugin("https://x.example", "JWT.tok", home=tmp_path)


def test_install_opencode_plugin_swallows_chmod_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "chmod", _chmod_always_raises)
    with patch("piloci.installer._http_download", return_value=b"// ts"):
        installer.install_opencode_plugin("https://x.example", "JWT.tok", home=tmp_path)
    cfg = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    assert cfg.exists()


def test_install_opencode_mcp_swallows_chmod_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "chmod", _chmod_always_raises)
    cfg = installer.install_opencode_mcp("https://x.example", "JWT.tok", home=tmp_path)
    assert cfg.exists()


def test_merge_json_mcp_swallows_chmod_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "chmod", _chmod_always_raises)
    cfg = installer.install_cursor_mcp("https://x.example", "JWT.tok", home=tmp_path)
    assert cfg.exists()


def test_install_codex_mcp_swallows_chmod_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "chmod", _chmod_always_raises)
    with patch("piloci.installer._http_download", return_value=b"hook"):
        cfg = installer.install_codex_mcp("https://x.example", "JWT.tok", home=tmp_path)
    assert cfg.exists()


# ---------------------------------------------------------------------------
# Corrupt-JSON handling — merger functions back the file up and start clean
# ---------------------------------------------------------------------------


def test_merge_claude_settings_handles_corrupt_json(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{ not valid json")
    installer._merge_claude_settings(settings)
    data = json.loads(settings.read_text())
    assert "SessionStart" in data["hooks"]
    assert settings.with_suffix(".json.piloci-corrupt-bak").exists()


def test_merge_claude_settings_handles_non_dict_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": ["this should be dict but is list"]}))
    installer._merge_claude_settings(settings)
    data = json.loads(settings.read_text())
    # Replaced wholesale with a fresh dict.
    assert isinstance(data["hooks"], dict)
    assert "SessionStart" in data["hooks"]


def test_merge_claude_settings_handles_non_list_event(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionStart": "garbage", "Stop": 5}}))
    installer._merge_claude_settings(settings)
    data = json.loads(settings.read_text())
    assert isinstance(data["hooks"]["SessionStart"], list)
    assert isinstance(data["hooks"]["Stop"], list)


def test_install_opencode_plugin_handles_corrupt_existing_cfg(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("{ broken json")
    with patch("piloci.installer._http_download", return_value=b"// ts"):
        installer.install_opencode_plugin("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert data["mcp"]["piloci"]["url"].endswith("/mcp/http")
    assert cfg_path.with_suffix(".json.piloci-corrupt-bak").exists()


def test_install_opencode_plugin_makes_backup_for_existing_cfg(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"other": "kept"}))
    with patch("piloci.installer._http_download", return_value=b"// ts"):
        installer.install_opencode_plugin("https://x.example", "JWT.tok", home=tmp_path)
    bak = cfg_path.with_suffix(".json.piloci-bak")
    assert bak.exists()
    assert json.loads(bak.read_text()) == {"other": "kept"}


def test_install_opencode_plugin_handles_non_dict_mcp(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"mcp": ["wrong type"]}))
    with patch("piloci.installer._http_download", return_value=b"// ts"):
        installer.install_opencode_plugin("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert isinstance(data["mcp"], dict)
    assert "piloci" in data["mcp"]


def test_install_opencode_mcp_handles_corrupt_cfg(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("{ broken json")
    installer.install_opencode_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert "piloci" in data["mcp"]
    assert cfg_path.with_suffix(".json.piloci-corrupt-bak").exists()


def test_install_opencode_mcp_handles_non_dict_mcp(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"mcp": 42}))
    installer.install_opencode_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert isinstance(data["mcp"], dict)
    assert "piloci" in data["mcp"]


def test_merge_json_mcp_handles_corrupt_cfg(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.CURSOR_DIR_NAME / "mcp.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("{ corrupt")
    installer.install_cursor_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert "piloci" in data["mcpServers"]
    assert cfg_path.with_suffix(".json.piloci-corrupt-bak").exists()


def test_merge_json_mcp_handles_non_dict_parent_bucket(tmp_path: Path) -> None:
    cfg_path = tmp_path / installer.CURSOR_DIR_NAME / "mcp.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"mcpServers": "wrong"}))
    installer.install_cursor_mcp("https://x.example", "JWT.tok", home=tmp_path)
    data = json.loads(cfg_path.read_text())
    assert isinstance(data["mcpServers"], dict)
    assert "piloci" in data["mcpServers"]


# ---------------------------------------------------------------------------
# _remove_json_mcp_entry — defensive guards
# ---------------------------------------------------------------------------


def test_remove_json_mcp_entry_missing_file(tmp_path: Path) -> None:
    assert (
        installer._remove_json_mcp_entry(
            tmp_path / "no.json", parent_key="mcpServers", server_name="piloci"
        )
        is False
    )


def test_remove_json_mcp_entry_corrupt_file_returns_false(tmp_path: Path) -> None:
    cfg = tmp_path / "x.json"
    cfg.write_text("{ corrupt")
    assert (
        installer._remove_json_mcp_entry(cfg, parent_key="mcpServers", server_name="piloci")
        is False
    )


def test_remove_json_mcp_entry_non_dict_root_returns_false(tmp_path: Path) -> None:
    cfg = tmp_path / "x.json"
    cfg.write_text(json.dumps(["not", "a", "dict"]))
    assert (
        installer._remove_json_mcp_entry(cfg, parent_key="mcpServers", server_name="piloci")
        is False
    )


def test_remove_json_mcp_entry_absent_server_returns_false(tmp_path: Path) -> None:
    cfg = tmp_path / "x.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {}}}))
    assert (
        installer._remove_json_mcp_entry(cfg, parent_key="mcpServers", server_name="piloci")
        is False
    )


# ---------------------------------------------------------------------------
# install_antigravity_mcp + install_gemini_mcp — round trip
# ---------------------------------------------------------------------------


def test_install_antigravity_mcp_writes_http_entry(tmp_path: Path) -> None:
    cfg = installer.install_antigravity_mcp("https://x.example/", "JWT.tok", home=tmp_path)
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["piloci"]["url"] == "https://x.example/mcp/http"
    assert data["mcpServers"]["piloci"]["headers"]["Authorization"] == "Bearer JWT.tok"


# ---------------------------------------------------------------------------
# install_codex_mcp — http_download exceptions are swallowed
# ---------------------------------------------------------------------------


def test_install_codex_mcp_swallows_hook_download_failures(tmp_path: Path) -> None:
    def _boom(url: str, *, token: str | None = None, timeout: int = 30) -> bytes:
        raise OSError("network down")

    with patch("piloci.installer._http_download", side_effect=_boom):
        cfg = installer.install_codex_mcp("https://x.example", "JWT.tok", home=tmp_path)
    # Despite hook download failing, the TOML block is still appended.
    assert "[mcp_servers.piloci]" in cfg.read_text()


# ---------------------------------------------------------------------------
# cleanup_legacy_install — corrupt JSON inputs are tolerated
# ---------------------------------------------------------------------------


def test_cleanup_legacy_install_tolerates_corrupt_settings(tmp_path: Path) -> None:
    settings = tmp_path / installer.CLAUDE_DIR_NAME / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{ broken json")
    # Does not raise; file is left as-is because parse failed.
    installer.cleanup_legacy_install(home=tmp_path)


def test_cleanup_legacy_install_tolerates_non_list_hook_event(tmp_path: Path) -> None:
    settings = tmp_path / installer.CLAUDE_DIR_NAME / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"SessionStart": "not-a-list"}}))
    installer.cleanup_legacy_install(home=tmp_path)


def test_cleanup_legacy_install_empties_hooks_dict_when_only_piloci(tmp_path: Path) -> None:
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
                                    "command": "python3 ~/.config/piloci/hook.py",
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )
    installer.cleanup_legacy_install(home=tmp_path)
    data = json.loads(settings.read_text())
    # The whole 'hooks' key is removed when no events remain.
    assert "hooks" not in data


def test_cleanup_legacy_install_tolerates_corrupt_opencode(tmp_path: Path) -> None:
    cfg = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{ also broken")
    installer.cleanup_legacy_install(home=tmp_path)


def test_cleanup_legacy_install_empties_opencode_mcp_when_only_piloci(tmp_path: Path) -> None:
    cfg = tmp_path / installer.OPENCODE_DIR_NAME / "opencode.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"mcp": {"piloci": {"type": "remote", "url": "x"}}}))
    installer.cleanup_legacy_install(home=tmp_path)
    data = json.loads(cfg.read_text())
    # 'mcp' key removed once empty.
    assert "mcp" not in data


# ---------------------------------------------------------------------------
# _cli_version fallback — import failure path
# ---------------------------------------------------------------------------


def test_cli_version_returns_unknown_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    original = sys.modules.pop("piloci.version", None)

    class _BrokenFinder:
        def find_spec(self, name, path=None, target=None):  # noqa: ANN001
            if name == "piloci.version":
                raise RuntimeError("import broken")
            return None

    sys.meta_path.insert(0, _BrokenFinder())
    try:
        assert installer._cli_version() == "unknown"
    finally:
        sys.meta_path.pop(0)
        if original is not None:
            sys.modules["piloci.version"] = original


# ---------------------------------------------------------------------------
# run_install — failure path + heartbeat note + cleanup notes
# ---------------------------------------------------------------------------


def test_run_install_records_sweep_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Pre-create a legacy hook.py so cleanup_legacy_install has something to remove.
    legacy = tmp_path / installer.PILOCI_DIR_NAME
    legacy.mkdir(parents=True)
    (legacy / "hook.py").write_text("# legacy")

    monkeypatch.setattr("piloci.installer.post_install_heartbeat", lambda *a, **kw: False)
    with patch("piloci.installer.shutil.which", return_value=None):
        report = installer.run_install(
            "tok", "https://x.example", home=tmp_path, targets=["cursor"]
        )
    assert any("정리" in n for n in report.notes)


def test_run_install_records_install_failure_in_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*a, **kw):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr("piloci.installer.install_cursor_mcp", _boom)
    monkeypatch.setattr("piloci.installer.post_install_heartbeat", lambda *a, **kw: False)
    with patch("piloci.installer.shutil.which", return_value=None):
        report = installer.run_install(
            "tok", "https://x.example", home=tmp_path, targets=["cursor"]
        )
    assert report.clients["cursor"].startswith("failed:")
    assert any("설치 실패" in n for n in report.notes)


def test_run_install_heartbeat_success_appends_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("piloci.installer.post_install_heartbeat", lambda *a, **kw: True)
    with patch("piloci.installer.shutil.which", return_value=None):
        report = installer.run_install(
            "tok", "https://x.example", home=tmp_path, targets=["cursor"]
        )
    assert any("설치 시그널 전송" in n for n in report.notes)


def test_run_install_hostname_oserror_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def _boom() -> str:
        raise OSError("no hostname")

    captured: dict = {}

    def _fake_heartbeat(base_url, token, *, client_kinds, hostname=None, timeout=5):  # noqa: ANN001
        captured["hostname"] = hostname
        return True

    monkeypatch.setattr(socket, "gethostname", _boom)
    monkeypatch.setattr("piloci.installer.post_install_heartbeat", _fake_heartbeat)
    with patch("piloci.installer.shutil.which", return_value=None):
        installer.run_install("tok", "https://x.example", home=tmp_path, targets=["cursor"])
    assert captured["hostname"] is None


# ---------------------------------------------------------------------------
# fetch_install_payload — happy path + malformed payload
# ---------------------------------------------------------------------------


def test_fetch_install_payload_parses_response() -> None:
    body = json.dumps({"token": "JWT.tok", "base_url": "https://piloci.example"}).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return body

    captured: dict = {}

    def _fake_urlopen(req, timeout):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["accept"] = req.get_header("Accept")
        return _Resp()

    with patch("piloci.installer.urllib.request.urlopen", _fake_urlopen):
        out = installer.fetch_install_payload("https://x.example/install/abc")
    assert out == {"token": "JWT.tok", "base_url": "https://piloci.example"}
    assert captured["accept"] == "application/json"


def test_fetch_install_payload_raises_on_missing_keys() -> None:
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"token": "x"}).encode()  # base_url missing

    with patch("piloci.installer.urllib.request.urlopen", lambda *a, **kw: _Resp()):
        with pytest.raises(ValueError):
            installer.fetch_install_payload("https://x.example/install/abc")


# ---------------------------------------------------------------------------
# get_default_server — extra branches
# ---------------------------------------------------------------------------


def test_get_default_server_returns_none_when_no_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PILOCI_SERVER", raising=False)
    monkeypatch.setattr("piloci.installer.Path.home", lambda: tmp_path)
    assert installer.get_default_server() is None


def test_get_default_server_returns_none_on_corrupt_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PILOCI_SERVER", raising=False)
    cfg_dir = tmp_path / installer.PILOCI_DIR_NAME
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{ broken")
    monkeypatch.setattr("piloci.installer.Path.home", lambda: tmp_path)
    assert installer.get_default_server() is None


def test_get_default_server_returns_none_when_ingest_url_unexpected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PILOCI_SERVER", raising=False)
    cfg_dir = tmp_path / installer.PILOCI_DIR_NAME
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"ingest_url": "https://x/unexpected"}))
    monkeypatch.setattr("piloci.installer.Path.home", lambda: tmp_path)
    assert installer.get_default_server() is None


# ---------------------------------------------------------------------------
# _http_download — basic round trip exercising the response.read() line
# ---------------------------------------------------------------------------


def test_http_download_returns_body_with_token() -> None:
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"payload-bytes"

    def _fake_urlopen(req, timeout):  # noqa: ANN001
        captured["auth"] = req.get_header("Authorization")
        return _Resp()

    with patch("piloci.installer.urllib.request.urlopen", _fake_urlopen):
        out = installer._http_download("https://x.example/api/hook/script", token="JWT.tok")
    assert out == b"payload-bytes"
    assert captured["auth"] == "Bearer JWT.tok"

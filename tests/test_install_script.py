from __future__ import annotations

from piloci.tools.install_script import (
    CODEX_STOP_HOOK_SCRIPT,
    STOP_HOOK_SCRIPT,
    build_install_script,
    build_powershell_install_script,
)


def test_build_install_script_inlines_token_and_base() -> None:
    script = build_install_script(token="tk-abc", base_url="https://piloci.example/")
    assert "tk-abc" in script
    assert "https://piloci.example" in script
    # Trailing slash on base_url must be stripped before substitution.
    assert "https://piloci.example//api" not in script
    # Stop hook is now python — bash script still uses curl + python but the
    # hook command embedded in hooks.json must point at the .py variant.
    assert "stop-hook.py" in script
    assert "bash ${CLAUDE_PLUGIN_ROOT}/hooks/stop-hook.sh" not in script


def test_stop_hook_script_is_python_not_bash() -> None:
    # Hard guarantee that the shared Stop hook served at /api/hook/stop-script
    # is now cross-platform Python (Mac/Linux/Windows) instead of bash.
    assert STOP_HOOK_SCRIPT.lstrip().startswith("#!/usr/bin/env python")
    assert "set -euo pipefail" not in STOP_HOOK_SCRIPT
    # And matches the existing Codex variant's shape — same imports + main().
    assert "urllib.request" in STOP_HOOK_SCRIPT
    assert "def main" in STOP_HOOK_SCRIPT
    # Codex version is unchanged — it was already Python.
    assert CODEX_STOP_HOOK_SCRIPT.lstrip().startswith("#!/usr/bin/env python")


def test_build_powershell_install_script_inlines_token_and_base() -> None:
    script = build_powershell_install_script(token="tk-windows", base_url="https://piloci.example/")
    assert "tk-windows" in script
    assert "https://piloci.example" in script
    assert "https://piloci.example//api" not in script
    # PowerShell-only constructs that must appear so the script actually runs.
    assert "$PILOCI_BASE" in script
    assert "$PILOCI_TOKEN" in script
    assert "Invoke-WebRequest" in script
    assert "USERPROFILE" in script
    # Stop hook must reference .py — Windows has no bash. The script does
    # mention 'stop-hook.sh' in the legacy cleanup branch, but only as a
    # variable name target for Remove-Item — never as a hook command.
    assert "stop-hook.py" in script
    # No actual command invocation of bash or .sh hooks — comments mentioning
    # the word "bash" are fine (the script removes legacy bash artifacts).
    assert "bash hook" not in script
    assert "bash ${" not in script
    assert "stop-hook.sh 2>" not in script
    # PowerShell 5.1 compatibility — null-coalescing operator '??' is 7-only.
    assert "??" not in script


def test_build_powershell_install_script_picks_py_launcher_first() -> None:
    # Embedded hook command lines should let the script discover ``py`` or
    # ``python`` at install time, not bake one in. The Find-PythonCommand
    # helper is the contract.
    script = build_powershell_install_script(token="t", base_url="https://x.example")
    assert "Find-PythonCommand" in script
    assert "Get-Command py" in script
    assert "Get-Command python" in script

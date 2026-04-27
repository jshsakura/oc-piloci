import sys
from unittest.mock import MagicMock, patch

import httpx

from piloci import cli_ingest


def _patch_argv(*args):
    return patch.object(sys, "argv", ["ingest"] + list(args))


def _env(**extra):
    env = {"PILOCI_ENDPOINT": "http://localhost:8000", "PILOCI_TOKEN": "tok"}
    env.update(extra)
    return env


class TestMainDryRun:
    def test_dry_run_with_claude_code(self, capsys, tmp_path):
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"role":"user","content":"hi"}')
        stdin_data = f'{{"transcript_path":"{transcript_file}","session_id":"sid-1"}}'
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = stdin_data
        with (
            _patch_argv("--client", "claude-code", "--dry-run"),
            patch.dict("os.environ", _env()),
            patch.object(sys, "stdin", mock_stdin),
        ):
            ret = cli_ingest.main()
        assert ret == 0
        out = capsys.readouterr().out
        assert "endpoint" in out

    def test_dry_run_with_project(self, capsys, tmp_path):
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"role":"user","content":"hi"}')
        stdin_data = f'{{"transcript_path":"{transcript_file}","session_id":"sid-1"}}'
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = stdin_data
        with (
            _patch_argv("--client", "claude-code", "--dry-run", "--project-id", "myproj"),
            patch.dict("os.environ", _env()),
            patch.object(sys, "stdin", mock_stdin),
        ):
            ret = cli_ingest.main()
        assert ret == 0


class TestMainMissingToken:
    def test_returns_1_without_token(self, capsys, tmp_path):
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"role":"user","content":"hi"}')
        stdin_data = f'{{"transcript_path":"{transcript_file}","session_id":"sid-1"}}'
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = stdin_data
        with (
            _patch_argv("--client", "claude-code"),
            patch.dict("os.environ", {"PILOCI_ENDPOINT": "http://localhost:8000"}, clear=True),
            patch.object(sys, "stdin", mock_stdin),
        ):
            ret = cli_ingest.main()
        assert ret == 1


class TestMainSuccessPost:
    def test_successful_post(self, tmp_path):
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"role":"user","content":"hi"}')
        stdin_data = f'{{"transcript_path":"{transcript_file}","session_id":"sid-1"}}'
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = stdin_data
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with (
            _patch_argv("--client", "claude-code"),
            patch.dict("os.environ", _env()),
            patch.object(sys, "stdin", mock_stdin),
            patch("piloci.cli_ingest.httpx.post", return_value=mock_resp),
        ):
            ret = cli_ingest.main()
        assert ret == 0

    def test_server_error_returns_1(self, capsys, tmp_path):
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"role":"user","content":"hi"}')
        stdin_data = f'{{"transcript_path":"{transcript_file}","session_id":"sid-1"}}'
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = stdin_data
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with (
            _patch_argv("--client", "claude-code"),
            patch.dict("os.environ", _env()),
            patch.object(sys, "stdin", mock_stdin),
            patch("piloci.cli_ingest.httpx.post", return_value=mock_resp),
        ):
            ret = cli_ingest.main()
        assert ret == 1

    def test_network_error_returns_1(self, capsys, tmp_path):
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"role":"user","content":"hi"}')
        stdin_data = f'{{"transcript_path":"{transcript_file}","session_id":"sid-1"}}'
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = stdin_data
        with (
            _patch_argv("--client", "claude-code"),
            patch.dict("os.environ", _env()),
            patch.object(sys, "stdin", mock_stdin),
            patch("piloci.cli_ingest.httpx.post", side_effect=httpx.HTTPError("conn")),
        ):
            ret = cli_ingest.main()
        assert ret == 1


class TestMainEmptyTranscript:
    def test_returns_0_on_empty_stdin(self, capsys):
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = ""
        with (
            _patch_argv("--client", "claude-code"),
            patch.dict("os.environ", _env()),
            patch.object(sys, "stdin", mock_stdin),
        ):
            ret = cli_ingest.main()
        assert ret == 0

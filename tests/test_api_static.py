"""Tests for api/static.py — StaticFiles app factory."""

from unittest.mock import patch

from piloci.api import static


class TestGetStaticApp:
    def test_returns_none_when_dir_missing(self, tmp_path):
        nonexistent = tmp_path / "no_such_dir"
        with patch.object(static, "_STATIC_DIR", nonexistent):
            assert static.get_static_app() is None

    def test_returns_none_when_dir_empty(self, tmp_path):
        empty_dir = tmp_path / "empty_static"
        empty_dir.mkdir()
        with patch.object(static, "_STATIC_DIR", empty_dir):
            assert static.get_static_app() is None

    def test_returns_static_files_when_dir_has_files(self, tmp_path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html></html>")
        with patch.object(static, "_STATIC_DIR", static_dir):
            app = static.get_static_app()
            assert app is not None
            assert app.directory == str(static_dir)
            assert app.html is True

    def test_returns_static_files_with_subdirectories(self, tmp_path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "_next").mkdir()
        (static_dir / "_next" / "bundle.js").write_text("console.log(1)")
        with patch.object(static, "_STATIC_DIR", static_dir):
            app = static.get_static_app()
            assert app is not None

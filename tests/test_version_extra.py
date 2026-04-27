from __future__ import annotations

from importlib import import_module

import pytest

version_mod = import_module("piloci.version")


def test_version_from_pyproject_finds_version():
    v = version_mod._version_from_pyproject()
    assert isinstance(v, str)
    assert "." in v


def test_version_from_pyproject_missing_project_table(tmp_path, monkeypatch):
    bad_toml = tmp_path / "pyproject.toml"
    bad_toml.write_text("[tool.something]\nfoo = 1\n")

    original_resolve = version_mod.Path(__file__).resolve

    def fake_resolve(self):
        result = original_resolve(self)
        if str(self).endswith("version.py"):

            class FakePath(type(result)):
                @property
                def parents(self):
                    return [tmp_path]

            return FakePath(result)
        return result

    monkeypatch.setattr(version_mod.Path, "resolve", fake_resolve)
    with pytest.raises(RuntimeError, match="missing a \\[project\\] table"):
        version_mod._version_from_pyproject()


def test_version_from_pyproject_missing_version_string(tmp_path, monkeypatch):
    bad_toml = tmp_path / "pyproject.toml"
    bad_toml.write_text("[project]\nname = 'test'\n")

    original_resolve = version_mod.Path(__file__).resolve

    def fake_resolve(self):
        result = original_resolve(self)
        if str(self).endswith("version.py"):

            class FakePath(type(result)):
                @property
                def parents(self):
                    return [tmp_path]

            return FakePath(result)
        return result

    monkeypatch.setattr(version_mod.Path, "resolve", fake_resolve)
    with pytest.raises(RuntimeError, match="missing a string"):
        version_mod._version_from_pyproject()


def test_version_from_pyproject_no_pyproject_found(monkeypatch):
    def fake_parents(self):
        return []

    monkeypatch.setattr(version_mod.Path, "parents", property(lambda self: []))
    monkeypatch.setattr(version_mod.Path, "resolve", lambda self: self)
    with pytest.raises(RuntimeError, match="Could not resolve"):
        version_mod._version_from_pyproject()


def test_dunder_version_is_string():
    import piloci

    assert isinstance(piloci.__version__, str)
    assert len(piloci.__version__) > 0

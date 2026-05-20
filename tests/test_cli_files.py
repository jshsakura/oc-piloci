"""Unit tests for the token-free team file push / pull CLI helpers.

All HTTP is served by an ``httpx.MockTransport`` so nothing leaves the box;
the focus is the idempotent create/update/skip logic, path normalization,
and the zip-slip-safe pull extraction.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from piloci import cli_files

# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def _write_config(home: Path, data: dict) -> None:
    cfg_dir = home / cli_files.PILOCI_DIR_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(data))


def test_load_config_derives_base_url_from_ingest(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"token": "JWT.tok", "ingest_url": "https://piloci.example/api/sessions/ingest"},
    )
    token, base_url = cli_files.load_config(home=tmp_path)
    assert token == "JWT.tok"
    assert base_url == "https://piloci.example"


def test_load_config_prefers_explicit_base_url(tmp_path: Path) -> None:
    _write_config(tmp_path, {"token": "T", "base_url": "https://x.example/"})
    _, base_url = cli_files.load_config(home=tmp_path)
    assert base_url == "https://x.example"


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="config.json이 없습니다"):
        cli_files.load_config(home=tmp_path)


def test_load_config_missing_token_raises(tmp_path: Path) -> None:
    _write_config(tmp_path, {"ingest_url": "https://x/api/sessions/ingest"})
    with pytest.raises(RuntimeError, match="token이 없습니다"):
        cli_files.load_config(home=tmp_path)


# ---------------------------------------------------------------------------
# _expand_paths / _rel_path
# ---------------------------------------------------------------------------


def test_expand_paths_globs_and_dirs(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a")
    (tmp_path / "docs" / "b.md").write_text("b")
    (tmp_path / "top.md").write_text("t")

    files = cli_files._expand_paths([str(tmp_path / "docs"), str(tmp_path / "top.md")])
    names = {f.name for f in files}
    assert names == {"a.md", "b.md", "top.md"}


def test_expand_paths_dedupes(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text("x")
    files = cli_files._expand_paths([str(f), str(f), str(tmp_path / "*.md")])
    assert len(files) == 1


def test_rel_path_strips_base_dir_and_adds_prefix(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "domain" / "a.md"
    rel = cli_files._rel_path(f, base_dir=tmp_path, prefix="sorin")
    assert rel == "sorin/docs/domain/a.md"


def test_rel_path_drops_dotdot(tmp_path: Path) -> None:
    rel = cli_files._rel_path(Path("../../etc/passwd"), base_dir=None, prefix="")
    assert ".." not in rel
    assert rel == "etc/passwd"


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


def _push_with_transport(monkeypatch, handler, **push_kwargs):
    """Patch httpx.Client to use a MockTransport, then call push."""
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("base_url", None)
        return real_client(
            base_url="http://test", **{k: v for k, v in kwargs.items() if k != "base_url"}
        )

    monkeypatch.setattr(cli_files.httpx, "Client", _client)
    return cli_files.push(**push_kwargs)


def test_push_creates_updates_skips(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "new.md").write_text("brand new")
    (tmp_path / "changed.md").write_text("new body")
    (tmp_path / "same.md").write_text("identical")
    same_hash = cli_files._content_hash("identical")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/documents"):
            return httpx.Response(
                200,
                json=[
                    {"id": "d-changed", "path": "changed.md", "content_hash": "OLD"},
                    {"id": "d-same", "path": "same.md", "content_hash": same_hash},
                ],
            )
        if request.method == "PUT":
            return httpx.Response(200, json={"version": 2})
        if request.method == "POST":
            return httpx.Response(201, json={"id": "d-new"})
        return httpx.Response(500)

    summary = _push_with_transport(
        monkeypatch,
        handler,
        team_id="team-1",
        patterns=[str(tmp_path / "*.md")],
        base_url="http://test",
        token="T",
        base_dir=tmp_path,
    )
    assert summary["created"] == ["new.md"]
    assert summary["updated"] == ["changed.md"]
    assert summary["unchanged"] == ["same.md"]
    assert summary["errors"] == []


def test_push_skips_binary(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "img.bin").write_bytes(b"\x89PNG\x00\xff\xfe")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": "x"})

    summary = _push_with_transport(
        monkeypatch,
        handler,
        team_id="t",
        patterns=[str(tmp_path / "*.bin")],
        base_url="http://test",
        token="T",
        base_dir=tmp_path,
    )
    assert summary["binary_skipped"] == ["img.bin"]
    assert summary["created"] == []


def test_push_records_errors(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "x.md").write_text("body")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(409, text="A document at this path already exists")

    summary = _push_with_transport(
        monkeypatch,
        handler,
        team_id="t",
        patterns=[str(tmp_path / "x.md")],
        base_url="http://test",
        token="T",
        base_dir=tmp_path,
    )
    assert summary["created"] == []
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["status"] == 409


def test_push_listing_failure_raises(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "x.md").write_text("body")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    with pytest.raises(RuntimeError, match="문서 목록 조회 실패"):
        _push_with_transport(
            monkeypatch,
            handler,
            team_id="t",
            patterns=[str(tmp_path / "x.md")],
            base_url="http://test",
            token="T",
            base_dir=tmp_path,
        )


def test_push_include_exclude_filters(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "keep.md").write_text("k")
    (tmp_path / "drop.log").write_text("d")
    (tmp_path / "skip.md").write_text("s")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": "x"})

    summary = _push_with_transport(
        monkeypatch,
        handler,
        team_id="t",
        patterns=[str(tmp_path / "*")],
        base_url="http://test",
        token="T",
        base_dir=tmp_path,
        include=["*.md"],
        exclude=["*skip*"],
    )
    assert summary["created"] == ["keep.md"]


# ---------------------------------------------------------------------------
# push_spec — JSON single / bulk
# ---------------------------------------------------------------------------


def test_push_spec_single_uses_explicit_path(tmp_path: Path, monkeypatch) -> None:
    f = tmp_path / "yko-index.md"
    f.write_text("index body")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "x"})

    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["base_url"] = "http://test"
        return real_client(**kwargs)

    monkeypatch.setattr(cli_files.httpx, "Client", _client)
    spec = {"team_id": "t", "path": "sorin/docs/reference/yko-index.md", "local_path": str(f)}
    summary = cli_files.push_spec(spec, base_url="http://test", token="T")
    assert summary["created"] == ["sorin/docs/reference/yko-index.md"]
    assert seen["body"]["path"] == "sorin/docs/reference/yko-index.md"


def test_push_spec_bulk_root_with_filters(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a")
    (tmp_path / "docs" / "workspace").mkdir()
    (tmp_path / "docs" / "workspace" / "log.md").write_text("log")
    (tmp_path / "docs" / "notes.txt").write_text("t")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": "x"})

    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["base_url"] = "http://test"
        return real_client(**kwargs)

    monkeypatch.setattr(cli_files.httpx, "Client", _client)
    spec = {
        "team_id": "t",
        "root": str(tmp_path / "docs"),
        "include": ["**/*.md"],
        "exclude": ["**/workspace/**"],
        "prefix": "sorin",
    }
    summary = cli_files.push_spec(spec, base_url="http://test", token="T")
    assert summary["created"] == ["sorin/a.md"]


def test_push_spec_requires_team_id(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="team_id"):
        cli_files.push_spec({}, base_url="http://test", token="T")


def test_push_spec_requires_source(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="local_path.*root|root"):
        cli_files.push_spec({"team_id": "t"}, base_url="http://test", token="T")


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_pull_extracts_zip(tmp_path: Path, monkeypatch) -> None:
    payload = _zip_bytes({"team/index.md": b"# index", "team/docs/a.md": b"a"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/export.zip")
        assert request.headers["Authorization"] == "Bearer T"
        return httpx.Response(200, content=payload)

    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["base_url"] = "http://test"
        return real_client(**kwargs)

    monkeypatch.setattr(cli_files.httpx, "Client", _client)

    out = tmp_path / "dl"
    result = cli_files.pull("team-1", out, base_url="http://test", token="T")
    assert result["count"] == 2
    assert (out / "team" / "index.md").read_text() == "# index"
    assert (out / "team" / "docs" / "a.md").read_text() == "a"


def test_pull_zip_slip_guard(tmp_path: Path, monkeypatch) -> None:
    payload = _zip_bytes({"../escape.md": b"nope", "safe.md": b"ok"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    real_client = httpx.Client

    def _client(*args, **kwargs):
        return real_client(
            base_url="http://test", transport=httpx.MockTransport(handler), timeout=60
        )

    monkeypatch.setattr(cli_files.httpx, "Client", _client)

    out = tmp_path / "dl"
    result = cli_files.pull("t", out, base_url="http://test", token="T")
    # The escaping entry is silently dropped; the safe one lands.
    assert (out / "safe.md").exists()
    assert not (tmp_path / "escape.md").exists()
    assert "safe.md" in result["extracted"]


def test_pull_one_matches_path_and_saves(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/documents"):
            return httpx.Response(200, json=[{"id": "d1", "path": "sorin/docs/a.md"}])
        if request.url.path.endswith("/raw"):
            return httpx.Response(200, content=b"file body")
        return httpx.Response(404)

    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["base_url"] = "http://test"
        return real_client(**kwargs)

    monkeypatch.setattr(cli_files.httpx, "Client", _client)
    out = tmp_path / "dl"
    out.mkdir()
    result = cli_files.pull_one("t", "sorin/docs/a.md", out, base_url="http://test", token="T")
    assert (out / "a.md").read_bytes() == b"file body"
    assert result["bytes"] == 9


def test_pull_one_missing_path_raises(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "d1", "path": "other.md"}])

    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["base_url"] = "http://test"
        return real_client(**kwargs)

    monkeypatch.setattr(cli_files.httpx, "Client", _client)
    with pytest.raises(RuntimeError, match="찾을 수 없습니다"):
        cli_files.pull_one("t", "missing.md", tmp_path, base_url="http://test", token="T")


def test_pull_download_failure_raises(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not found")

    real_client = httpx.Client

    def _client(*args, **kwargs):
        return real_client(
            base_url="http://test", transport=httpx.MockTransport(handler), timeout=60
        )

    monkeypatch.setattr(cli_files.httpx, "Client", _client)

    with pytest.raises(RuntimeError, match="export.zip 다운로드 실패"):
        cli_files.pull("t", tmp_path / "dl", base_url="http://test", token="T")

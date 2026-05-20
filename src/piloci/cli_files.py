"""Token-free team file push / pull for the piloci CLI.

The agent invokes these through its shell (e.g. ``piloci push --team X
docs/**/*.md``). The local process does *all* file I/O and talks to the
server with **Bearer auth** — which the CSRF middleware exempts — so a
scripted upload never hits the ``403 CSRF`` wall and, crucially, **no file
content ever crosses the LLM token stream**. Only the command line and a
compact JSON summary do.

Text files go up as team documents (the wiki pipeline digests them). Binary
files are reported as skipped here; full any-format support lands with the
team-file blob store (multipart endpoint).
"""

from __future__ import annotations

import fnmatch
import glob as _glob
import hashlib
import json
import sys
from pathlib import Path

import httpx

from piloci.installer import PILOCI_DIR_NAME


def _content_hash(content: str) -> str:
    """Mirror the server's ``team_routes._content_hash`` so unchanged files
    can be skipped without a pointless version bump."""
    return hashlib.sha256(content.encode()).hexdigest()


def load_config(home: Path | None = None) -> tuple[str, str]:
    """Return ``(token, base_url)`` from ``~/.config/piloci/config.json``.

    ``base_url`` is taken directly when present, else derived from the stored
    ``ingest_url`` (``…/api/sessions/ingest``) for backward compatibility.
    """
    h = home or Path.home()
    cfg = h / PILOCI_DIR_NAME / "config.json"
    if not cfg.exists():
        raise RuntimeError(
            "config.json이 없습니다 — 먼저 `piloci login` 또는 `piloci setup`을 실행하세요."
        )
    data = json.loads(cfg.read_text())
    token = data.get("token")
    if not token:
        raise RuntimeError("config.json에 token이 없습니다.")
    base_url = data.get("base_url")
    if not base_url:
        ingest = data.get("ingest_url", "")
        base_url = ingest.split("/api/sessions/ingest", 1)[0] if ingest else ""
    if not base_url:
        raise RuntimeError("config.json에서 base_url을 확인할 수 없습니다.")
    return token, base_url.rstrip("/")


def _expand_paths(patterns: list[str]) -> list[Path]:
    """Resolve globs + directories into a sorted, de-duped list of files.

    A directory expands to every file beneath it (recursive). Explicit globs
    (``**``) are honoured. Order is stable so summaries are reproducible.
    """
    out: list[Path] = []
    seen: set[Path] = set()
    for pat in patterns:
        matches = [Path(m) for m in _glob.glob(pat, recursive=True)]
        if not matches and not any(ch in pat for ch in "*?["):
            matches = [Path(pat)]
        for m in matches:
            if m.is_dir():
                for child in sorted(m.rglob("*")):
                    if child.is_file() and child not in seen:
                        seen.add(child)
                        out.append(child)
            elif m.is_file() and m not in seen:
                seen.add(m)
                out.append(m)
    return sorted(out)


def _rel_path(f: Path, base_dir: Path | None, prefix: str) -> str:
    """Compute the stored team-document path for a local file.

    ``base_dir`` strips a leading directory; ``prefix`` prepends one. The
    result is POSIX-style, leading-``./`` and ``..`` removed (zip-slip safe).
    """
    p = f
    if base_dir:
        try:
            p = f.relative_to(base_dir)
        except ValueError:
            p = Path(f.name)
    rel = p.as_posix().lstrip("./")
    rel = "/".join(part for part in rel.split("/") if part not in ("", ".", ".."))
    if prefix:
        rel = prefix.strip("/") + "/" + rel
    return rel


def _read_text(p: Path) -> str | None:
    """Return UTF-8 text, or ``None`` if the file is binary / unreadable."""
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _filter_pairs(
    pairs: list[tuple[Path, str]],
    include: list[str] | None,
    exclude: list[str] | None,
) -> list[tuple[Path, str]]:
    """Keep pairs whose *stored* path matches ``include`` and not ``exclude``.

    Globs match the stored (relative) path so a caller can write
    ``include=["**/*.md"]`` / ``exclude=["workspace/**"]`` intuitively.
    """
    out = pairs
    if include:
        out = [p for p in out if any(fnmatch.fnmatch(p[1], g) for g in include)]
    if exclude:
        out = [p for p in out if not any(fnmatch.fnmatch(p[1], g) for g in exclude)]
    return out


def _upload_pairs(
    team_id: str,
    pairs: list[tuple[Path, str]],
    *,
    base_url: str,
    token: str,
    timeout: float = 30.0,
) -> dict:
    """Upload ``(local_file, stored_path)`` pairs as team documents.

    Idempotent: unchanged (server hash matches) → skipped; existing path →
    update (version bump, optimistic ``parent_hash``); new path → create.
    """
    summary: dict = {
        "created": [],
        "updated": [],
        "unchanged": [],
        "binary_skipped": [],
        "errors": [],
    }
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "piloci-cli"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        listing = client.get(f"/api/teams/{team_id}/documents")
        if listing.status_code != 200:
            raise RuntimeError(f"문서 목록 조회 실패 ({listing.status_code}): {listing.text[:200]}")
        existing = {d["path"]: d for d in listing.json()}

        for local_file, stored in pairs:
            text = _read_text(local_file)
            if text is None:
                summary["binary_skipped"].append(stored)
                continue
            cur = existing.get(stored)
            if cur:
                if cur.get("content_hash") == _content_hash(text):
                    summary["unchanged"].append(stored)
                    continue
                resp = client.put(
                    f"/api/teams/{team_id}/documents/{cur['id']}",
                    json={"content": text, "parent_hash": cur.get("content_hash")},
                )
                if resp.status_code == 200:
                    summary["updated"].append(stored)
                else:
                    summary["errors"].append(
                        {"path": stored, "status": resp.status_code, "body": resp.text[:200]}
                    )
            else:
                resp = client.post(
                    f"/api/teams/{team_id}/documents",
                    json={"path": stored, "content": text},
                )
                if resp.status_code == 201:
                    summary["created"].append(stored)
                else:
                    summary["errors"].append(
                        {"path": stored, "status": resp.status_code, "body": resp.text[:200]}
                    )
    return summary


def push(
    team_id: str,
    patterns: list[str],
    *,
    base_url: str,
    token: str,
    base_dir: Path | None = None,
    prefix: str = "",
    timeout: float = 30.0,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict:
    """Glob/dir flavour: expand ``patterns`` → upload as team documents."""
    pairs = [(f, _rel_path(f, base_dir, prefix)) for f in _expand_paths(patterns)]
    pairs = _filter_pairs(pairs, include, exclude)
    return _upload_pairs(team_id, pairs, base_url=base_url, token=token, timeout=timeout)


def push_spec(spec: dict, *, base_url: str, token: str, timeout: float = 30.0) -> dict:
    """JSON-spec flavour. The agent emits a tiny spec (paths only, no content
    → minimal tokens); the local CLI reads files and uploads.

    Single::

        {"team_id": "...", "path": "sorin/docs/x.md", "local_path": "/abs/x.md"}

    Bulk::

        {"team_id": "...", "root": "/abs/docs",
         "include": ["**/*.md"], "exclude": ["workspace/**"], "prefix": "sorin"}
    """
    team_id = spec.get("team_id")
    if not team_id:
        raise RuntimeError("spec에 team_id가 필요합니다.")

    if spec.get("local_path"):
        stored = (
            _rel_path(Path(spec["path"]), base_dir=None, prefix="")
            if spec.get("path")
            else Path(spec["local_path"]).name
        )
        pairs = [(Path(spec["local_path"]), stored)]
        return _upload_pairs(team_id, pairs, base_url=base_url, token=token, timeout=timeout)

    root = spec.get("root")
    if not root:
        raise RuntimeError("spec에 local_path(단건) 또는 root(대량)가 필요합니다.")
    root_path = Path(root)
    prefix = spec.get("prefix", "") or ""
    pairs = [(f, _rel_path(f, root_path, prefix)) for f in _expand_paths([str(root_path)])]
    pairs = _filter_pairs(pairs, spec.get("include"), spec.get("exclude"))
    return _upload_pairs(team_id, pairs, base_url=base_url, token=token, timeout=timeout)


def pull(
    team_id: str,
    out_dir: Path,
    *,
    base_url: str,
    token: str,
    timeout: float = 60.0,
) -> dict:
    """Download the team's export bundle (zip) and unpack it into ``out_dir``.

    Token-free: the zip is streamed to disk and unpacked locally; the LLM only
    sees the returned summary.
    """
    import io
    import zipfile

    headers = {"Authorization": f"Bearer {token}", "User-Agent": "piloci-cli"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        resp = client.get(f"/api/teams/{team_id}/export.zip")
        if resp.status_code != 200:
            raise RuntimeError(f"export.zip 다운로드 실패 ({resp.status_code}): {resp.text[:200]}")
        payload = resp.content

    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for name in zf.namelist():
            # zip-slip guard: resolve target stays under out_dir
            target = (out_dir / name).resolve()
            if not str(target).startswith(str(out_dir.resolve())):
                continue
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            extracted.append(name)
    return {"out_dir": str(out_dir), "extracted": extracted, "count": len(extracted)}


def run_push(args) -> None:
    """``piloci push`` entrypoint — prints a compact JSON summary to stdout.

    Two surfaces: ``--spec`` (JSON single/bulk, ``-`` reads stdin) or the
    flag form (positional globs + ``--team``/``--base-dir``/``--prefix``).
    """
    token, base_url = load_config()
    if args.server:
        base_url = args.server.rstrip("/")

    if getattr(args, "spec", None):
        raw = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text()
        spec = json.loads(raw)
        if args.team:
            spec.setdefault("team_id", args.team)
        summary = push_spec(spec, base_url=base_url, token=token)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if summary["errors"]:
            sys.exit(1)
        return

    if not args.team:
        raise RuntimeError("--team이 필요합니다 (또는 --spec 사용).")
    if not args.paths:
        raise RuntimeError("업로드할 경로를 지정하거나 --spec을 사용하세요.")
    summary = push(
        args.team,
        args.paths,
        base_url=base_url,
        token=token,
        base_dir=Path(args.base_dir) if args.base_dir else None,
        prefix=args.prefix or "",
        include=args.include or None,
        exclude=args.exclude or None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    counts = {k: len(v) for k, v in summary.items()}
    print(
        f"\n✓ created={counts['created']} updated={counts['updated']} "
        f"unchanged={counts['unchanged']} binary_skipped={counts['binary_skipped']} "
        f"errors={counts['errors']}",
        file=sys.stderr,
    )
    if summary["errors"]:
        sys.exit(1)


def pull_one(
    team_id: str,
    path: str,
    out: Path,
    *,
    base_url: str,
    token: str,
    timeout: float = 30.0,
) -> dict:
    """Download a single team document (matched by its stored path) to ``out``.

    ``out`` may be a directory (the file keeps its basename) or a full file
    path. Token-free — content streams straight to disk.
    """
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "piloci-cli"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        listing = client.get(f"/api/teams/{team_id}/documents")
        if listing.status_code != 200:
            raise RuntimeError(f"문서 목록 조회 실패 ({listing.status_code}): {listing.text[:200]}")
        match = next((d for d in listing.json() if d["path"] == path), None)
        if not match:
            raise RuntimeError(f"문서를 찾을 수 없습니다: {path}")
        raw = client.get(f"/api/teams/{team_id}/documents/{match['id']}/raw")
        if raw.status_code != 200:
            raise RuntimeError(f"다운로드 실패 ({raw.status_code}): {raw.text[:200]}")

    target = out / Path(path).name if out.is_dir() or not out.suffix else out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw.content)
    return {"path": path, "saved_to": str(target), "bytes": len(raw.content)}


def run_pull(args) -> None:
    """``piloci pull`` entrypoint. ``--path`` fetches one file; otherwise the
    whole team bundle (zip) is downloaded and unpacked."""
    token, base_url = load_config()
    if args.server:
        base_url = args.server.rstrip("/")
    if getattr(args, "path", None):
        result = pull_one(args.team, args.path, Path(args.out), base_url=base_url, token=token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\n✓ {result['path']} → {result['saved_to']}", file=sys.stderr)
        return
    result = pull(args.team, Path(args.out), base_url=base_url, token=token)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ {result['count']}개 파일 → {result['out_dir']}", file=sys.stderr)

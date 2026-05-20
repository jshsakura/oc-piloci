from __future__ import annotations

"""Content-addressed blob store for team binary files.

Layout: ``<base_dir>/<team_id>/<sha256-hex>``. The blob name *is* its SHA-256,
so writing the same bytes always lands on the same path (dedup is free and
idempotent). Text team documents keep their body inline in SQL; only binary
uploads (PDF/img/zip/…) flow through here.

Every public function sanitizes its inputs against path traversal: a resolved
target must stay strictly under ``base_dir`` or the call raises ``ValueError``.
"""

import hashlib
import re
from pathlib import Path

# team_id is a UUID hex in practice; be permissive but reject separators and
# dot-segments that could climb out of base_dir.
_TEAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# storage_key == "<team_id>/<sha256>". Exactly one slash, hex digest tail.
_STORAGE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+/[a-f0-9]{64}$")


def _sanitize_team_id(team_id: str) -> str:
    if not team_id or not _TEAM_ID_RE.match(team_id):
        raise ValueError("invalid team_id")
    return team_id


def _resolve_under(base_dir: Path, *parts: str) -> Path:
    """Join ``parts`` under ``base_dir`` and verify the resolved path does not
    escape it (defends against ``..`` and absolute components)."""
    base = base_dir.resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise ValueError("path traversal detected")
    return target


def save_blob(base_dir: Path, team_id: str, data: bytes) -> tuple[str, str, int]:
    """Write ``data`` to the content-addressed store.

    Returns ``(sha256_hex, storage_key, size)`` where
    ``storage_key == f"{team_id}/{sha256_hex}"``. Idempotent: identical bytes
    map to the same path, so a re-upload is a cheap no-op rewrite.
    """
    team_id = _sanitize_team_id(team_id)
    sha = hashlib.sha256(data).hexdigest()
    storage_key = f"{team_id}/{sha}"
    target = _resolve_under(base_dir, team_id, sha)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Only write when missing — dedup keeps repeated uploads from churning disk.
    if not target.exists():
        target.write_bytes(data)
    return sha, storage_key, len(data)


def read_blob(base_dir: Path, storage_key: str) -> bytes:
    """Read bytes for ``storage_key``. Raises ``ValueError`` for a malformed
    or traversing key, ``FileNotFoundError`` if the blob is missing."""
    if not storage_key or ".." in storage_key or not _STORAGE_KEY_RE.match(storage_key):
        raise ValueError("invalid storage_key")
    team_id, sha = storage_key.split("/", 1)
    _sanitize_team_id(team_id)
    target = _resolve_under(base_dir, team_id, sha)
    return target.read_bytes()


def delete_blob(base_dir: Path, storage_key: str) -> bool:
    """Delete the blob for ``storage_key``. Returns True if a file was removed,
    False if it was already absent. Malformed keys raise ``ValueError``."""
    if not storage_key or ".." in storage_key or not _STORAGE_KEY_RE.match(storage_key):
        raise ValueError("invalid storage_key")
    team_id, sha = storage_key.split("/", 1)
    _sanitize_team_id(team_id)
    target = _resolve_under(base_dir, team_id, sha)
    if target.exists():
        target.unlink()
        return True
    return False

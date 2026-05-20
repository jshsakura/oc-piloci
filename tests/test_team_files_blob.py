from __future__ import annotations

import hashlib

import pytest

from piloci.storage.team_files import delete_blob, read_blob, save_blob


def test_save_read_roundtrip(tmp_path):
    data = b"\x00\x01binary\xffpayload"
    sha, key, size = save_blob(tmp_path, "team-1", data)

    assert sha == hashlib.sha256(data).hexdigest()
    assert key == f"team-1/{sha}"
    assert size == len(data)
    assert read_blob(tmp_path, key) == data
    # File lives at <base>/<team>/<sha>
    assert (tmp_path / "team-1" / sha).is_file()


def test_save_is_content_addressed_dedup(tmp_path):
    data = b"same bytes"
    sha1, key1, _ = save_blob(tmp_path, "team-1", data)
    sha2, key2, _ = save_blob(tmp_path, "team-1", data)

    assert (sha1, key1) == (sha2, key2)
    # Only one physical blob for the team.
    files = list((tmp_path / "team-1").iterdir())
    assert len(files) == 1

    # Different bytes -> different key.
    sha3, key3, _ = save_blob(tmp_path, "team-1", b"other bytes")
    assert sha3 != sha1
    assert key3 != key1


def test_delete_blob(tmp_path):
    sha, key, _ = save_blob(tmp_path, "team-1", b"to delete")
    assert delete_blob(tmp_path, key) is True
    assert delete_blob(tmp_path, key) is False  # already gone
    with pytest.raises(FileNotFoundError):
        read_blob(tmp_path, key)


def test_teams_are_isolated_by_dir(tmp_path):
    data = b"shared"
    sha_a, key_a, _ = save_blob(tmp_path, "team-a", data)
    sha_b, key_b, _ = save_blob(tmp_path, "team-b", data)
    # Same content hash, but separate per-team paths.
    assert sha_a == sha_b
    assert key_a != key_b
    assert (tmp_path / "team-a" / sha_a).is_file()
    assert (tmp_path / "team-b" / sha_b).is_file()


@pytest.mark.parametrize(
    "bad_key",
    [
        "../escape/" + "a" * 64,
        "team-1/../" + "a" * 64,
        "..%2f" + "a" * 64,
        "team-1/short",
        "team-1/" + "g" * 64,  # non-hex
        "noslash" + "a" * 64,
        "",
    ],
)
def test_read_rejects_traversal_and_malformed(tmp_path, bad_key):
    with pytest.raises(ValueError):
        read_blob(tmp_path, bad_key)


def test_delete_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        delete_blob(tmp_path, "../" + "a" * 64)


def test_save_rejects_bad_team_id(tmp_path):
    with pytest.raises(ValueError):
        save_blob(tmp_path, "../evil", b"x")
    with pytest.raises(ValueError):
        save_blob(tmp_path, "team/with/slash", b"x")

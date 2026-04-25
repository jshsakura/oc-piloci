"""Tests for EmbeddingCache (LRU)."""

from __future__ import annotations

from piloci.storage.cache import EmbeddingCache


def test_get_miss_returns_none():
    cache = EmbeddingCache()
    assert cache.get("foo") is None


def test_set_and_get():
    cache = EmbeddingCache()
    cache.set("hello", [0.1, 0.2, 0.3])
    assert cache.get("hello") == [0.1, 0.2, 0.3]


def test_size_increments():
    cache = EmbeddingCache()
    assert cache.size == 0
    cache.set("a", [1.0])
    assert cache.size == 1
    cache.set("b", [2.0])
    assert cache.size == 2


def test_set_existing_updates_without_duplicate():
    cache = EmbeddingCache()
    cache.set("x", [0.1])
    cache.set("x", [0.9])
    assert cache.get("x") == [0.9]
    assert cache.size == 1


def test_lru_eviction_when_full():
    cache = EmbeddingCache(maxsize=2)
    cache.set("a", [1.0])
    cache.set("b", [2.0])
    cache.set("c", [3.0])  # evicts "a"
    assert cache.size == 2
    assert cache.get("a") is None
    assert cache.get("b") == [2.0]
    assert cache.get("c") == [3.0]


def test_clear_empties_cache():
    cache = EmbeddingCache()
    cache.set("a", [1.0])
    cache.set("b", [2.0])
    cache.clear()
    assert cache.size == 0
    assert cache.get("a") is None


def test_update_moves_to_end_of_lru():
    """Re-setting an existing key should not evict it before others."""
    cache = EmbeddingCache(maxsize=2)
    cache.set("a", [1.0])
    cache.set("b", [2.0])
    cache.set("a", [1.1])  # refresh "a"
    cache.set("c", [3.0])  # evicts "b" (oldest unrefreshed)
    assert cache.get("a") == [1.1]
    assert cache.get("b") is None
    assert cache.get("c") == [3.0]


def test_get_moves_key_to_end_of_lru():
    cache = EmbeddingCache(maxsize=2)
    cache.set("a", [1.0])
    cache.set("b", [2.0])

    assert cache.get("a") == [1.0]

    cache.set("c", [3.0])
    assert cache.get("a") == [1.0]
    assert cache.get("b") is None
    assert cache.get("c") == [3.0]

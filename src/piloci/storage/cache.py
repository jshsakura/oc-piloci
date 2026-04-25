from __future__ import annotations


class EmbeddingCache:
    """Simple LRU cache for text embeddings."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._maxsize = maxsize
        self._cache: dict[str, list[float]] = {}
        self._keys: list[str] = []

    def get(self, text: str) -> list[float] | None:
        vector = self._cache.get(text)
        if vector is None:
            return None
        self._keys.remove(text)
        self._keys.append(text)
        return vector

    def set(self, text: str, vector: list[float]) -> None:
        if text in self._cache:
            self._keys.remove(text)
        elif len(self._keys) >= self._maxsize:
            oldest = self._keys.pop(0)
            del self._cache[oldest]
        self._cache[text] = vector
        self._keys.append(text)

    def clear(self) -> None:
        self._cache.clear()
        self._keys.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

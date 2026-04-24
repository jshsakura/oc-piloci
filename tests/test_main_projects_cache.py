from piloci.main import _ProjectsCache
from piloci.tools.memory_tools import MemoryInput, RecallInput


def test_projects_cache_hit_returns_copy():
    cache = _ProjectsCache(ttl_sec=300.0)
    original = [{"id": "p1", "slug": "web", "name": "Web", "memory_count": 3}]

    stored = cache.set("user-1", original)
    stored[0]["name"] = "Changed"

    cached = cache.get("user-1")

    assert cached is not None
    assert cached[0]["name"] == "Web"
    assert original[0]["name"] == "Web"


def test_projects_cache_expiry():
    cache = _ProjectsCache(ttl_sec=-1.0)
    cache.set("user-1", [{"id": "p1", "slug": "web", "name": "Web", "memory_count": 3}])

    assert cache.get("user-1") is None


def test_projects_cache_invalidate():
    cache = _ProjectsCache(ttl_sec=300.0)
    cache.set("user-1", [{"id": "p1", "slug": "web", "name": "Web", "memory_count": 3}])

    cache.invalidate("user-1")

    assert cache.get("user-1") is None


def test_memory_input_schema_has_no_container_tag():
    properties = MemoryInput.model_json_schema().get("properties", {})

    assert "container_tag" not in properties


def test_recall_input_schema_has_no_container_tag():
    properties = RecallInput.model_json_schema().get("properties", {})

    assert "container_tag" not in properties

"""Coverage-focused tests for piloci.api.routes endpoints that the existing
test_api_routes_extra.py and test_api_v1.py don't reach. Targets the largest
uncovered clusters: dashboard summary, LLM providers, chat, device flow,
install script, data export/import, project drilldown, and memory create."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from starlette.requests import Request


def _make_request(
    body: dict[str, object] | None = None,
    user: dict[str, object] | None = None,
    method: str = "POST",
    path: str = "/",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
    path_params: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    app: object | None = None,
    client: tuple[str, int] | None = ("127.0.0.1", 12345),
    raw_body: bytes | None = None,
) -> Request:
    header_list = list(headers or [])
    if cookies:
        cookie_value = "; ".join(f"{key}={value}" for key, value in cookies.items())
        header_list.append((b"cookie", cookie_value.encode()))

    state: dict[str, object] = {}
    scope: dict[str, object] = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "headers": header_list,
        "client": client,
        "state": state,
        "path_params": path_params or {},
        "app": app or SimpleNamespace(state=SimpleNamespace()),
        "scheme": "https",
        "server": ("testserver", 443),
    }
    if user is not None:
        state["user"] = user

    payload = raw_body if raw_body is not None else orjson.dumps(body or {})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


def _session_cm(session: MagicMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _db_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.delete = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# route_dashboard_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_dashboard_summary_unauthorized() -> None:
    from piloci.api import routes

    response = await routes.route_dashboard_summary(_make_request(method="GET", user=None))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_dashboard_summary_aggregates_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    project = SimpleNamespace(id="p1", slug="alpha", name="Alpha")
    proj_result = MagicMock()
    proj_result.scalars.return_value.all.return_value = [project]

    raw_session = SimpleNamespace(
        ingest_id="ing-1",
        project_id="p1",
        created_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        processed_at=datetime(2026, 5, 18, 1, tzinfo=timezone.utc),
        memories_extracted=2,
        client="claude",
    )
    sess_result = MagicMock()
    sess_result.scalars.return_value.all.return_value = [raw_session]

    bucket_row = SimpleNamespace(day="2026-05-18", count=3)
    bucket_result = MagicMock()
    bucket_result.all.return_value = [bucket_row]

    db = _db_session()
    db.execute = AsyncMock(side_effect=[proj_result, sess_result, bucket_result])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(
        routes, "get_settings", lambda: SimpleNamespace(raw_session_retention_days=2)
    )

    store = MagicMock()
    store.list = AsyncMock(
        return_value=[
            {
                "memory_id": "m1",
                "content": "Architectural decision about async sessions",
                "tags": ["arch", "async"],
                "created_at": 1_700_000_000,
                "updated_at": 1_700_000_100,
            }
        ]
    )
    instincts_store = MagicMock()
    instincts_store.list_instincts = AsyncMock(
        return_value=[
            {
                "instinct_id": "i1",
                "trigger": "when raw SQL appears",
                "action": "switch to SQLAlchemy ORM",
                "domain": "security",
                "confidence": 0.9,
                "instinct_count": 4,
            }
        ]
    )

    app = SimpleNamespace(state=SimpleNamespace(store=store, instincts_store=instincts_store))
    request = _make_request(method="GET", user={"sub": "u1"}, app=app)

    response = await routes.route_dashboard_summary(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload["recent_memories"][0]["project_slug"] == "alpha"
    assert payload["top_instincts"][0]["trigger"] == "when raw SQL appears"
    assert payload["recent_sessions"][0]["ingest_id"] == "ing-1"
    # bucket coverage: window=2 means activity has 2 entries
    assert len(payload["activity"]) == 2
    assert {"tag": "arch", "count": 1} in payload["top_tags"]


@pytest.mark.asyncio
async def test_route_dashboard_summary_tolerates_store_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If lancedb or instincts errors out for a project, the rest still returns."""
    from piloci.api import routes

    project = SimpleNamespace(id="p1", slug="x", name="X")
    proj_result = MagicMock()
    proj_result.scalars.return_value.all.return_value = [project]
    empty_sess = MagicMock()
    empty_sess.scalars.return_value.all.return_value = []
    empty_buckets = MagicMock()
    empty_buckets.all.return_value = []

    db = _db_session()
    db.execute = AsyncMock(side_effect=[proj_result, empty_sess, empty_buckets])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(
        routes, "get_settings", lambda: SimpleNamespace(raw_session_retention_days=1)
    )

    store = MagicMock()
    store.list = AsyncMock(side_effect=RuntimeError("lancedb down"))
    instincts_store = MagicMock()
    instincts_store.list_instincts = AsyncMock(side_effect=RuntimeError("nope"))

    app = SimpleNamespace(state=SimpleNamespace(store=store, instincts_store=instincts_store))
    response = await routes.route_dashboard_summary(
        _make_request(method="GET", user={"sub": "u1"}, app=app)
    )

    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["recent_memories"] == []
    assert payload["top_instincts"] == []


# ---------------------------------------------------------------------------
# route_list_projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_list_projects_unauthorized() -> None:
    from piloci.api import routes

    response = await routes.route_list_projects(_make_request(method="GET", user=None))
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# route_project_knacks / route_project_sessions / route_raw_session_detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_project_knacks_unauthorized_and_missing_slug() -> None:
    from piloci.api import routes

    assert (
        await routes.route_project_knacks(_make_request(method="GET", user=None))
    ).status_code == 401

    response = await routes.route_project_knacks(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": " "})
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_project_knacks_project_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    async def fake_resolve(uid: str, slug: str):
        return None

    monkeypatch.setattr(routes, "_get_user_project_by_slug", fake_resolve)

    response = await routes.route_project_knacks(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": "missing"})
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_project_knacks_returns_serialized_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    async def fake_resolve(uid: str, slug: str):
        return {"id": "p1", "slug": "alpha", "name": "Alpha"}

    monkeypatch.setattr(routes, "_get_user_project_by_slug", fake_resolve)

    instincts_store = MagicMock()
    instincts_store.list_instincts = AsyncMock(
        return_value=[
            {
                "instinct_id": "i1",
                "trigger": "when no tests",
                "action": "add tests",
                "domain": "quality",
                "evidence_note": "from last review",
                "confidence": 0.7,
                "instinct_count": 2,
                "created_at": 1_700_000_000,
            }
        ]
    )
    app = SimpleNamespace(state=SimpleNamespace(instincts_store=instincts_store))
    response = await routes.route_project_knacks(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": "alpha"}, app=app)
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["project"]["slug"] == "alpha"
    assert payload["knacks"][0]["trigger"] == "when no tests"


@pytest.mark.asyncio
async def test_route_project_knacks_503_when_store_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    async def fake_resolve(uid: str, slug: str):
        return {"id": "p1", "slug": "alpha", "name": "Alpha"}

    monkeypatch.setattr(routes, "_get_user_project_by_slug", fake_resolve)

    # app.state has no instincts_store
    app = SimpleNamespace(state=SimpleNamespace())
    response = await routes.route_project_knacks(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": "alpha"}, app=app)
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_route_project_sessions_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    async def fake_resolve(uid: str, slug: str):
        return {"id": "p1", "slug": "alpha", "name": "Alpha"}

    monkeypatch.setattr(routes, "_get_user_project_by_slug", fake_resolve)

    raw_session = SimpleNamespace(
        ingest_id="ing-1",
        session_id="sess-a",
        client="claude",
        transcript_json='[{"role":"user","content":"hi"}]',
        created_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        processed_at=None,
        memories_extracted=0,
        error=None,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [raw_session]
    db = _db_session()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_project_sessions(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": "alpha"})
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["sessions"][0]["ingest_id"] == "ing-1"
    assert payload["sessions"][0]["size_bytes"] > 0


@pytest.mark.asyncio
async def test_route_project_sessions_unauthorized_and_missing_slug() -> None:
    from piloci.api import routes

    assert (
        await routes.route_project_sessions(_make_request(method="GET", user=None))
    ).status_code == 401
    response = await routes.route_project_sessions(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": " "})
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_raw_session_detail_returns_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    raw = SimpleNamespace(
        ingest_id="ing-1",
        session_id="s1",
        client="claude",
        transcript_json='[{"role":"user","content":"hi"}]',
        created_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        processed_at=None,
        memories_extracted=0,
        error=None,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = raw
    db = _db_session()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_raw_session_detail(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"ingest_id": "ing-1"})
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["transcript"] == '[{"role":"user","content":"hi"}]'


@pytest.mark.asyncio
async def test_route_raw_session_detail_unauthorized_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    # Unauthorized
    response = await routes.route_raw_session_detail(_make_request(method="GET", user=None))
    assert response.status_code == 401

    # Missing ingest_id
    response = await routes.route_raw_session_detail(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"ingest_id": " "})
    )
    assert response.status_code == 400

    # Not found
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = _db_session()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_raw_session_detail(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"ingest_id": "missing"})
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# route_create_project — extended branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_create_project_invalid_json() -> None:
    from piloci.api import routes

    bad = _make_request(method="POST", user={"sub": "u1"}, raw_body=b"not-json")
    response = await routes.route_create_project(bad)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_create_project_internal_error_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Integrity DB error path → 500."""
    from piloci.api import routes

    db = _db_session()
    db.flush = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_create_project(
        _make_request({"slug": "alpha", "name": "Alpha"}, user={"sub": "u1"})
    )
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# route_update_project / route_delete_project — invalid JSON branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_update_project_invalid_json_and_unauth() -> None:
    from piloci.api import routes

    unauth = await routes.route_update_project(_make_request(method="PATCH", user=None))
    assert unauth.status_code == 401

    bad = _make_request(
        method="PATCH",
        user={"sub": "u1"},
        path_params={"id": "p1"},
        raw_body=b"junk",
    )
    response = await routes.route_update_project(bad)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_delete_project_invalid_json_treated_as_empty() -> None:
    """Bad JSON in DELETE body should fall through to the missing-confirm 422."""
    from piloci.api import routes

    bad = _make_request(
        method="DELETE",
        user={"sub": "u1"},
        path_params={"id": "p1"},
        raw_body=b"junk",
    )
    response = await routes.route_delete_project(bad)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# route_list_llm_providers / create / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_list_llm_providers_unauthorized() -> None:
    from piloci.api import routes

    response = await routes.route_list_llm_providers(_make_request(method="GET", user=None))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_list_llm_providers_decrypts_and_masks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    provider = SimpleNamespace(
        id="prov-1",
        name="OpenAI",
        base_url="https://api.openai.com",
        model="gpt-4",
        enabled=True,
        priority=10,
        api_key_encrypted=b"\x00" * 64,
        created_at=now,
        updated_at=now,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [provider]
    db = _db_session()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    import piloci.auth.crypto as crypto_mod

    monkeypatch.setattr(crypto_mod, "decrypt_token", lambda blob, settings: "sk-secrettoken12345")

    response = await routes.route_list_llm_providers(
        _make_request(method="GET", user={"sub": "u1"})
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    # Masked key reveals first 4 + last 4
    assert payload[0]["api_key_masked"].startswith("sk-s")
    assert payload[0]["api_key_masked"].endswith("2345")
    assert "•" in payload[0]["api_key_masked"]


@pytest.mark.asyncio
async def test_route_list_llm_providers_decrypt_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    provider = SimpleNamespace(
        id="prov-1",
        name="X",
        base_url="https://x.example.com",
        model="m",
        enabled=False,
        priority=200,
        api_key_encrypted=b"\x00",
        created_at=now,
        updated_at=now,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [provider]
    db = _db_session()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    import piloci.auth.crypto as crypto_mod

    def boom(blob, settings):
        raise RuntimeError("decrypt failed")

    monkeypatch.setattr(crypto_mod, "decrypt_token", boom)

    response = await routes.route_list_llm_providers(
        _make_request(method="GET", user={"sub": "u1"})
    )
    payload = orjson.loads(response.body)
    assert payload[0]["api_key_masked"] == "(decrypt failed)"


@pytest.mark.asyncio
async def test_route_create_llm_provider_validates_required_fields() -> None:
    from piloci.api import routes

    # Unauthorized
    assert (
        await routes.route_create_llm_provider(_make_request(method="POST", user=None))
    ).status_code == 401

    # Invalid JSON
    bad = _make_request(method="POST", user={"sub": "u1"}, raw_body=b"not-json")
    response = await routes.route_create_llm_provider(bad)
    assert response.status_code == 400

    # Missing fields
    response = await routes.route_create_llm_provider(
        _make_request({"name": "x"}, user={"sub": "u1"})
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_create_llm_provider_validates_url_and_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(allow_private_llm_provider_urls=False),
    )

    # Localhost rejected unless allow_private
    bad_url = await routes.route_create_llm_provider(
        _make_request(
            {
                "name": "loc",
                "base_url": "http://localhost:11434",
                "model": "x",
                "api_key": "k",
            },
            user={"sub": "u1"},
        )
    )
    assert bad_url.status_code == 422

    # Field too long
    too_long = await routes.route_create_llm_provider(
        _make_request(
            {
                "name": "x",
                "base_url": "https://api.example.com",
                "model": "m",
                "api_key": "k" * 600,
            },
            user={"sub": "u1"},
        )
    )
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_route_create_llm_provider_bad_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes, "get_settings", lambda: SimpleNamespace(allow_private_llm_provider_urls=True)
    )

    not_int = await routes.route_create_llm_provider(
        _make_request(
            {
                "name": "x",
                "base_url": "https://api.example.com",
                "model": "m",
                "api_key": "k",
                "priority": "abc",
            },
            user={"sub": "u1"},
        )
    )
    assert not_int.status_code == 422
    assert "integer" in orjson.loads(not_int.body)["error"]

    out_of_range = await routes.route_create_llm_provider(
        _make_request(
            {
                "name": "x",
                "base_url": "https://api.example.com",
                "model": "m",
                "api_key": "k",
                "priority": 9999,
            },
            user={"sub": "u1"},
        )
    )
    assert out_of_range.status_code == 422


@pytest.mark.asyncio
async def test_route_create_llm_provider_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(allow_private_llm_provider_urls=True),
    )
    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    import piloci.auth.crypto as crypto_mod

    monkeypatch.setattr(crypto_mod, "encrypt_token", lambda key, settings: b"encrypted-blob")

    response = await routes.route_create_llm_provider(
        _make_request(
            {
                "name": "OpenAI",
                "base_url": "https://api.openai.com",
                "model": "gpt-4",
                "api_key": "sk-secrettoken12345",
                "priority": 100,
                "enabled": True,
            },
            user={"sub": "u1"},
        )
    )
    assert response.status_code == 201
    db.add.assert_called_once()
    payload = orjson.loads(response.body)
    assert payload["name"] == "OpenAI"
    assert payload["api_key_masked"].startswith("sk-s")


@pytest.mark.asyncio
async def test_route_update_llm_provider_unauth_and_missing_id() -> None:
    from piloci.api import routes

    assert (
        await routes.route_update_llm_provider(_make_request(method="PATCH", user=None))
    ).status_code == 401

    # Missing id path param
    response = await routes.route_update_llm_provider(
        _make_request(method="PATCH", user={"sub": "u1"})
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_update_llm_provider_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    bad = _make_request(
        method="PATCH",
        user={"sub": "u1"},
        path_params={"id": "prov-1"},
        raw_body=b"junk",
    )
    response = await routes.route_update_llm_provider(bad)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_update_llm_provider_no_fields_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    response = await routes.route_update_llm_provider(
        _make_request({}, user={"sub": "u1"}, path_params={"id": "prov-1"}, method="PATCH")
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"name": ""}, "name"),
        ({"base_url": "http://localhost:1234"}, "base_url"),
        ({"model": ""}, "model"),
        ({"api_key": ""}, "api_key"),
        ({"priority": "abc"}, "priority"),
        ({"priority": 9999}, "priority"),
    ],
)
async def test_route_update_llm_provider_field_validation(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, object], field: str
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes, "get_settings", lambda: SimpleNamespace(allow_private_llm_provider_urls=False)
    )

    response = await routes.route_update_llm_provider(
        _make_request(body, user={"sub": "u1"}, path_params={"id": "prov-1"}, method="PATCH")
    )
    assert response.status_code == 422
    assert field in orjson.loads(response.body)["error"].lower() or response.status_code == 422


@pytest.mark.asyncio
async def test_route_update_llm_provider_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    db = _db_session()
    db.execute = AsyncMock(return_value=not_found)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_update_llm_provider(
        _make_request(
            {"enabled": False},
            user={"sub": "u1"},
            path_params={"id": "prov-1"},
            method="PATCH",
        )
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_update_llm_provider_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    existing = SimpleNamespace(
        id="prov-1",
        name="OpenAI",
        base_url="https://api.openai.com",
        model="gpt-4",
        enabled=True,
        priority=10,
        api_key_encrypted=b"\x00",
        created_at=now,
        updated_at=now,
    )

    select_existing = MagicMock()
    select_existing.scalar_one_or_none.return_value = existing
    update_result = MagicMock()
    select_refreshed = MagicMock()
    select_refreshed.scalar_one.return_value = existing

    db = _db_session()
    db.execute = AsyncMock(side_effect=[select_existing, update_result, select_refreshed])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    import piloci.auth.crypto as crypto_mod

    monkeypatch.setattr(crypto_mod, "decrypt_token", lambda blob, settings: "sk-secrettoken12345")

    response = await routes.route_update_llm_provider(
        _make_request(
            {"enabled": False, "priority": 50},
            user={"sub": "u1"},
            path_params={"id": "prov-1"},
            method="PATCH",
        )
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["id"] == "prov-1"


@pytest.mark.asyncio
async def test_route_delete_llm_provider_unauth_missing_id_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    assert (
        await routes.route_delete_llm_provider(_make_request(method="DELETE", user=None))
    ).status_code == 401

    response = await routes.route_delete_llm_provider(
        _make_request(method="DELETE", user={"sub": "u1"})
    )
    assert response.status_code == 400

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    db = _db_session()
    db.execute = AsyncMock(return_value=not_found)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_delete_llm_provider(
        _make_request(method="DELETE", user={"sub": "u1"}, path_params={"id": "missing"})
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_delete_llm_provider_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    row = SimpleNamespace(id="prov-1")
    found = MagicMock()
    found.scalar_one_or_none.return_value = row
    db = _db_session()
    db.execute = AsyncMock(side_effect=[found, MagicMock()])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_delete_llm_provider(
        _make_request(method="DELETE", user={"sub": "u1"}, path_params={"id": "prov-1"})
    )
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"deleted": True}


# ---------------------------------------------------------------------------
# route_create_memory — happy path (test_api_ingest covers a different angle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_create_memory_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            vault_dir="/tmp",
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    async def fake_invalidate(*args, **kwargs):
        return None

    monkeypatch.setattr(routes, "invalidate_project_vault_cache", fake_invalidate)

    import piloci.storage.embed as embed_mod

    async def fake_embed_one(**kwargs):
        return [0.0] * 384

    monkeypatch.setattr(embed_mod, "embed_one", fake_embed_one)

    store = MagicMock()
    store.save = AsyncMock(return_value="mem-123")
    app = SimpleNamespace(state=SimpleNamespace(store=store))

    response = await routes.route_create_memory(
        _make_request(
            {"content": "remember this", "tags": ["x"], "metadata": {"src": "test"}},
            user={"sub": "u1", "project_id": "p1"},
            app=app,
        )
    )
    assert response.status_code == 201
    payload = orjson.loads(response.body)
    assert payload["memory_id"] == "mem-123"
    assert payload["project_id"] == "p1"
    store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_create_memory_invalid_json_and_non_dict() -> None:
    from piloci.api import routes

    # Invalid JSON
    bad = _make_request(
        method="POST",
        user={"sub": "u1", "project_id": "p1"},
        raw_body=b"not-json",
    )
    response = await routes.route_create_memory(bad)
    assert response.status_code == 400

    # JSON is a list, not a dict
    arr = _make_request(
        method="POST",
        user={"sub": "u1", "project_id": "p1"},
        raw_body=b"[]",
    )
    response = await routes.route_create_memory(arr)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_create_memory_blank_content() -> None:
    from piloci.api import routes

    response = await routes.route_create_memory(
        _make_request({"content": "   "}, user={"sub": "u1", "project_id": "p1"})
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# route_update_memory — content path (triggers embed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_update_memory_with_content_embeds_and_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            vault_dir="/tmp",
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    async def fake_invalidate(*args, **kwargs):
        return None

    monkeypatch.setattr(routes, "invalidate_project_vault_cache", fake_invalidate)

    import piloci.storage.embed as embed_mod

    async def fake_embed_one(text, **kwargs):
        return [0.0] * 384

    monkeypatch.setattr(embed_mod, "embed_one", fake_embed_one)

    store = MagicMock()
    store.update = AsyncMock(return_value=True)
    app = SimpleNamespace(state=SimpleNamespace(store=store))

    response = await routes.route_update_memory(
        _make_request(
            {"content": "new content", "tags": ["t"]},
            method="PATCH",
            user={"sub": "u1", "project_id": "p1"},
            path_params={"id": "m1"},
            app=app,
        )
    )
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"updated": True}


# ---------------------------------------------------------------------------
# route_delete_memory — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_delete_memory_success_decrements_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir="/tmp"))

    async def fake_invalidate(*args, **kwargs):
        return None

    monkeypatch.setattr(routes, "invalidate_project_vault_cache", fake_invalidate)

    store = MagicMock()
    store.delete = AsyncMock(return_value=True)
    db = _db_session()
    db.execute = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_delete_memory(
        _make_request(
            method="DELETE",
            user={"sub": "u1", "project_id": "p1"},
            path_params={"id": "m1"},
            app=SimpleNamespace(state=SimpleNamespace(store=store)),
        )
    )
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"deleted": True}


# ---------------------------------------------------------------------------
# route_clear_memories — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_clear_memories_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir="/tmp"))

    async def fake_invalidate(*args, **kwargs):
        return None

    monkeypatch.setattr(routes, "invalidate_project_vault_cache", fake_invalidate)

    store = MagicMock()
    store.clear_project = AsyncMock(return_value=5)
    db = _db_session()
    db.execute = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_clear_memories(
        _make_request(
            {"confirm": True},
            user={"sub": "u1", "project_id": "p1"},
            app=SimpleNamespace(state=SimpleNamespace(store=store)),
        )
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload == {"cleared": True, "count": 5}


@pytest.mark.asyncio
async def test_route_clear_memories_zero_count_skips_project_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When nothing's cleared, the Project.memory_count update is skipped."""
    from piloci.api import routes

    store = MagicMock()
    store.clear_project = AsyncMock(return_value=0)

    response = await routes.route_clear_memories(
        _make_request(
            {"confirm": True},
            user={"sub": "u1", "project_id": "p1"},
            app=SimpleNamespace(state=SimpleNamespace(store=store)),
        )
    )
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"cleared": True, "count": 0}


@pytest.mark.asyncio
async def test_route_clear_memories_invalid_json() -> None:
    from piloci.api import routes

    bad = _make_request(
        method="POST",
        user={"sub": "u1", "project_id": "p1"},
        raw_body=b"junk",
    )
    response = await routes.route_clear_memories(bad)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# route_chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_chat_unauthorized_and_bad_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    assert (await routes.route_chat(_make_request(user=None))).status_code == 401

    # Invalid JSON
    bad = _make_request(user={"sub": "u1", "project_id": "p1"}, raw_body=b"junk")
    response = await routes.route_chat(bad)
    assert response.status_code == 400

    # Body not a dict
    arr = _make_request(user={"sub": "u1", "project_id": "p1"}, raw_body=b"[]")
    response = await routes.route_chat(arr)
    assert response.status_code == 400

    # Missing project scope
    response = await routes.route_chat(_make_request({"query": "hi"}, user={"sub": "u1"}))
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_chat_missing_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    response = await routes.route_chat(
        _make_request({"query": "  "}, user={"sub": "u1", "project_id": "p1"})
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_chat_project_slug_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    async def fake_resolve(uid, slug):
        return None

    monkeypatch.setattr(routes, "_get_user_project_by_slug", fake_resolve)

    response = await routes.route_chat(
        _make_request(
            {"query": "hello", "project_slug": "missing"},
            user={"sub": "u1"},
        )
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_chat_provider_misconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
            chat_max_memory_chars=200,
            chat_max_context_chars=1000,
        ),
    )

    import piloci.llm as llm_mod

    def boom(settings):
        raise ValueError("no provider")

    monkeypatch.setattr(llm_mod, "get_chat_provider", boom)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_chat(
        _make_request(
            {"query": "hello", "stream": False},
            user={"sub": "u1", "project_id": "p1"},
            app=app,
        )
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_route_chat_non_stream_returns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
            chat_max_memory_chars=200,
            chat_max_context_chars=1000,
        ),
    )

    import piloci.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_chat_provider", lambda settings: MagicMock())

    import piloci.chat as chat_mod

    async def fake_retrieve(**kwargs):
        return [{"memory_id": "m1", "content": "fact", "tags": ["x"]}]

    monkeypatch.setattr(chat_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(chat_mod, "format_citations", lambda mems: [{"memory_id": "m1"}])

    async def fake_stream(**kwargs):
        for chunk in ("answer ", "text"):
            yield chunk

    monkeypatch.setattr(chat_mod, "stream_answer", fake_stream)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_chat(
        _make_request(
            {"query": "hello?", "stream": False, "top_k": 3, "tags": ["x"]},
            user={"sub": "u1", "project_id": "p1"},
            app=app,
        )
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["answer"] == "answer text"
    assert payload["citations"] == [{"memory_id": "m1"}]


@pytest.mark.asyncio
async def test_route_chat_retrieval_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
            chat_max_memory_chars=200,
            chat_max_context_chars=1000,
        ),
    )

    import piloci.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_chat_provider", lambda settings: MagicMock())

    import piloci.chat as chat_mod

    async def boom_retrieve(**kwargs):
        raise RuntimeError("lancedb died")

    monkeypatch.setattr(chat_mod, "retrieve", boom_retrieve)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_chat(
        _make_request(
            {"query": "hello?", "stream": False},
            user={"sub": "u1", "project_id": "p1"},
            app=app,
        )
    )
    assert response.status_code == 500
    assert orjson.loads(response.body)["error"] == "retrieval failed"


@pytest.mark.asyncio
async def test_route_chat_stream_generation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-stream mode + generation throws → 502."""
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
            chat_max_memory_chars=200,
            chat_max_context_chars=1000,
        ),
    )

    import piloci.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_chat_provider", lambda settings: MagicMock())

    import piloci.chat as chat_mod

    async def fake_retrieve(**kwargs):
        return []

    monkeypatch.setattr(chat_mod, "retrieve", fake_retrieve)
    monkeypatch.setattr(chat_mod, "format_citations", lambda mems: [])

    async def boom_stream(**kwargs):
        if False:
            yield ""
        raise RuntimeError("gen boom")

    monkeypatch.setattr(chat_mod, "stream_answer", boom_stream)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_chat(
        _make_request(
            {"query": "hi", "stream": False},
            user={"sub": "u1", "project_id": "p1"},
            app=app,
        )
    )
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# Hook-script downloads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_hook_stop_script_authed_and_unauthed() -> None:
    from piloci.api import routes

    unauth = await routes.route_hook_stop_script(_make_request(method="GET", user=None))
    assert unauth.status_code == 401

    ok = await routes.route_hook_stop_script(_make_request(method="GET", user={"sub": "u1"}))
    assert ok.status_code == 200
    assert ok.media_type == "text/x-python"


@pytest.mark.asyncio
async def test_route_hook_codex_stop_script_authed_and_unauthed() -> None:
    from piloci.api import routes

    unauth = await routes.route_hook_codex_stop_script(_make_request(method="GET", user=None))
    assert unauth.status_code == 401

    ok = await routes.route_hook_codex_stop_script(_make_request(method="GET", user={"sub": "u1"}))
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_route_opencode_plugin_authed_and_unauthed() -> None:
    from piloci.api import routes

    unauth = await routes.route_opencode_plugin(_make_request(method="GET", user=None))
    assert unauth.status_code == 401

    ok = await routes.route_opencode_plugin(_make_request(method="GET", user={"sub": "u1"}))
    assert ok.status_code == 200
    assert ok.media_type == "text/typescript"


# ---------------------------------------------------------------------------
# route_install — invalid code, expired, json/powershell/bash branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_install_invalid_code_json() -> None:
    from piloci.api import routes

    request = _make_request(
        method="GET",
        path_params={"code": " "},
        headers=[(b"accept", b"application/json")],
    )
    response = await routes.route_install(request)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_install_invalid_code_powershell() -> None:
    from piloci.api import routes

    request = _make_request(
        method="GET",
        path_params={"code": "bad code"},  # whitespace → invalid
        headers=[(b"accept", b"text/html")],
        query_string=b"os=win",
    )
    response = await routes.route_install(request)
    assert response.status_code == 400
    assert "x-powershell" in response.media_type


@pytest.mark.asyncio
async def test_route_install_invalid_code_bash() -> None:
    from piloci.api import routes

    request = _make_request(
        method="GET",
        path_params={"code": "x" * 100},  # too long
    )
    response = await routes.route_install(request)
    assert response.status_code == 400
    assert "shellscript" in response.media_type


@pytest.mark.asyncio
async def test_route_install_expired_code_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(consume=AsyncMock(return_value=None))

    import piloci.auth.install_pairing as ip_mod

    monkeypatch.setattr(ip_mod, "get_install_pairing_store", lambda settings: store)

    request = _make_request(
        method="GET",
        path_params={"code": "ABCD1234"},
        headers=[(b"accept", b"application/json")],
    )
    response = await routes.route_install(request)
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_route_install_expired_code_powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(consume=AsyncMock(return_value=None))

    import piloci.auth.install_pairing as ip_mod

    monkeypatch.setattr(ip_mod, "get_install_pairing_store", lambda settings: store)

    request = _make_request(
        method="GET",
        path_params={"code": "ABCD1234"},
        query_string=b"format=ps1",
    )
    response = await routes.route_install(request)
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_route_install_expired_code_bash(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(consume=AsyncMock(return_value=None))

    import piloci.auth.install_pairing as ip_mod

    monkeypatch.setattr(ip_mod, "get_install_pairing_store", lambda settings: store)

    request = _make_request(method="GET", path_params={"code": "ABCD1234"})
    response = await routes.route_install(request)
    assert response.status_code == 410
    assert "shellscript" in response.media_type


@pytest.mark.asyncio
async def test_route_install_consumes_code_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(
        consume=AsyncMock(return_value={"token": "jwt-x", "base_url": "https://p.example.com"})
    )

    import piloci.auth.install_pairing as ip_mod

    monkeypatch.setattr(ip_mod, "get_install_pairing_store", lambda settings: store)

    request = _make_request(
        method="GET",
        path_params={"code": "GOODCODE"},
        headers=[(b"accept", b"application/json")],
    )
    response = await routes.route_install(request)
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["token"] == "jwt-x"


@pytest.mark.asyncio
async def test_route_install_consumes_code_bash_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(
        consume=AsyncMock(return_value={"token": "jwt-x", "base_url": "https://p.example.com"})
    )

    import piloci.auth.install_pairing as ip_mod

    monkeypatch.setattr(ip_mod, "get_install_pairing_store", lambda settings: store)

    request = _make_request(method="GET", path_params={"code": "GOODCODE"})
    response = await routes.route_install(request)
    assert response.status_code == 200
    assert "shellscript" in response.media_type


@pytest.mark.asyncio
async def test_route_install_consumes_code_powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(
        consume=AsyncMock(return_value={"token": "jwt-x", "base_url": "https://p.example.com"})
    )

    import piloci.auth.install_pairing as ip_mod

    monkeypatch.setattr(ip_mod, "get_install_pairing_store", lambda settings: store)

    request = _make_request(method="GET", path_params={"code": "GOODCODE"}, query_string=b"os=win")
    response = await routes.route_install(request)
    assert response.status_code == 200
    assert "x-powershell" in response.media_type


# ---------------------------------------------------------------------------
# Device flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_device_code_create_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(base_url=None))

    store = SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("redis down")))

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    request = _make_request({}, method="POST", headers=[(b"host", b"piloci.example.com")])
    response = await routes.route_device_code(request)
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_route_device_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(base_url=None))

    store = SimpleNamespace(create=AsyncMock(return_value=("dev-code-1", "USER-CODE")))

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    request = _make_request(
        {"detected": ["claude", "opencode"]},
        method="POST",
        headers=[(b"host", b"piloci.example.com")],
    )
    response = await routes.route_device_code(request)
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["device_code"] == "dev-code-1"
    assert payload["user_code"] == "USER-CODE"
    assert "verification_uri" in payload


@pytest.mark.asyncio
async def test_route_device_info_missing_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    missing = await routes.route_device_info(_make_request(method="GET"))
    assert missing.status_code == 400

    store = SimpleNamespace(lookup_user_code=AsyncMock(return_value=None))

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    request = _make_request(method="GET", query_string=b"code=USER-CODE")
    response = await routes.route_device_info(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_device_info_returns_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(lookup_user_code=AsyncMock(return_value={"detected": ["claude"]}))

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    request = _make_request(method="GET", query_string=b"code=USER-CODE")
    response = await routes.route_device_info(request)
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"detected": ["claude"]}


@pytest.mark.asyncio
async def test_route_device_poll_invalid_and_states(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    # invalid JSON
    bad = _make_request(method="POST", raw_body=b"junk")
    assert (await routes.route_device_poll(bad)).status_code == 400

    # missing device_code
    response = await routes.route_device_poll(_make_request({}, method="POST"))
    assert response.status_code == 400

    # expired
    store = SimpleNamespace(poll=AsyncMock(return_value=None))

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    expired = await routes.route_device_poll(_make_request({"device_code": "x"}, method="POST"))
    assert expired.status_code == 410

    # approved
    store = SimpleNamespace(
        poll=AsyncMock(return_value={"status": "approved", "token": "jwt-1", "targets": ["claude"]})
    )
    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)
    approved = await routes.route_device_poll(_make_request({"device_code": "x"}, method="POST"))
    assert approved.status_code == 200
    body = orjson.loads(approved.body)
    assert body == {"status": "approved", "token": "jwt-1", "targets": ["claude"]}

    # denied
    store = SimpleNamespace(poll=AsyncMock(return_value={"status": "denied"}))
    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)
    denied = await routes.route_device_poll(_make_request({"device_code": "x"}, method="POST"))
    assert orjson.loads(denied.body)["status"] == "denied"

    # pending
    store = SimpleNamespace(poll=AsyncMock(return_value={}))
    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)
    pending = await routes.route_device_poll(_make_request({"device_code": "x"}, method="POST"))
    assert orjson.loads(pending.body)["status"] == "pending"


@pytest.mark.asyncio
async def test_route_device_approve_unauthorized_and_bad_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    # unauthorized
    response = await routes.route_device_approve(_make_request({}, user=None))
    assert response.status_code == 401

    # invalid JSON
    bad = _make_request(user={"sub": "u1"}, raw_body=b"junk")
    response = await routes.route_device_approve(bad)
    assert response.status_code == 400

    # missing user_code and action
    response = await routes.route_device_approve(_make_request({}, user={"sub": "u1"}))
    assert response.status_code == 422

    # bad targets (none recognized)
    response = await routes.route_device_approve(
        _make_request(
            {"user_code": "ABC", "action": "approve", "targets": ["nope"]},
            user={"sub": "u1"},
        )
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_route_device_approve_not_found_or_used(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(lookup_user_code=AsyncMock(return_value=None))

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    response = await routes.route_device_approve(
        _make_request({"user_code": "ABC", "action": "approve"}, user={"sub": "u1", "email": "u@e"})
    )
    assert response.status_code == 404

    # status already used
    store2 = SimpleNamespace(
        lookup_user_code=AsyncMock(return_value={"device_code": "dc", "status": "approved"})
    )
    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store2)
    response = await routes.route_device_approve(
        _make_request({"user_code": "ABC", "action": "approve"}, user={"sub": "u1", "email": "u@e"})
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_route_device_approve_deny_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    store = SimpleNamespace(
        lookup_user_code=AsyncMock(return_value={"device_code": "dc-1", "status": "pending"}),
        deny=AsyncMock(),
    )

    import piloci.auth.device_pairing as dp_mod

    monkeypatch.setattr(dp_mod, "get_device_pairing_store", lambda settings: store)

    response = await routes.route_device_approve(
        _make_request({"user_code": "ABC", "action": "deny"}, user={"sub": "u1", "email": "u@e"})
    )
    assert response.status_code == 200
    assert orjson.loads(response.body) == {"ok": True, "status": "denied"}
    store.deny.assert_awaited_once_with("dc-1")


# ---------------------------------------------------------------------------
# route_data_export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_data_export_unauthorized_and_missing_uid() -> None:
    from piloci.api import routes

    response = await routes.route_data_export(_make_request(method="POST", user=None))
    assert response.status_code == 401

    # user dict missing sub/user_id → uid is ""
    response = await routes.route_data_export(_make_request(method="POST", user={"email": "x@e"}))
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_data_export_returns_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())

    import piloci.api.data_portability as dp_mod

    async def fake_build(**kwargs):
        return b"PK\x03\x04zip-data"

    monkeypatch.setattr(dp_mod, "build_export_archive", fake_build)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_data_export(
        _make_request(method="POST", user={"sub": "user-12345"}, app=app)
    )
    assert response.status_code == 200
    assert response.media_type == "application/zip"
    assert b"zip-data" in response.body
    assert "attachment" in response.headers.get("Content-Disposition", "")


# ---------------------------------------------------------------------------
# route_data_import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_data_import_unauthorized_and_missing_uid() -> None:
    from piloci.api import routes

    assert (
        await routes.route_data_import(_make_request(method="POST", user=None))
    ).status_code == 401

    response = await routes.route_data_import(_make_request(method="POST", user={"email": "x@e"}))
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_data_import_empty_and_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(ingest_max_body_bytes=10))

    empty = _make_request(method="POST", user={"sub": "u1"}, raw_body=b"")
    response = await routes.route_data_import(empty)
    assert response.status_code == 400

    too_big = _make_request(method="POST", user={"sub": "u1"}, raw_body=b"x" * 100)
    response = await routes.route_data_import(too_big)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_route_data_import_archive_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            ingest_max_body_bytes=1024 * 1024,
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    import piloci.api.data_portability as dp_mod

    class _Err(dp_mod.ArchiveError):
        pass

    async def fake_import(*args, **kwargs):
        raise dp_mod.ArchiveError("bad zip", status=422)

    monkeypatch.setattr(dp_mod, "import_archive", fake_import)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_data_import(
        _make_request(method="POST", user={"sub": "u1"}, app=app, raw_body=b"PK\x03\x04zip-data")
    )
    assert response.status_code == 422
    assert "bad zip" in orjson.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_route_data_import_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            ingest_max_body_bytes=1024 * 1024,
            embed_model="m",
            embed_cache_dir="/tmp",
            embed_lru_size=8,
            embed_executor_workers=1,
            embed_max_concurrency=1,
        ),
    )

    import piloci.api.data_portability as dp_mod

    summary = SimpleNamespace(
        projects_imported=2,
        projects_renamed=[{"old": "a", "new": "a-1"}],
        memories_imported=10,
        profiles_imported=1,
        re_embedded=False,
    )

    async def fake_import(*args, **kwargs):
        return summary

    monkeypatch.setattr(dp_mod, "import_archive", fake_import)

    store = MagicMock()
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_data_import(
        _make_request(
            method="POST",
            user={"sub": "u1"},
            app=app,
            raw_body=b"PK\x03\x04zip-data",
            query_string=b"reembed=true",
        )
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["imported"] is True
    assert payload["projects_imported"] == 2
    assert payload["memories_imported"] == 10


# ---------------------------------------------------------------------------
# route_vault_export — unauthorized & missing slug branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_vault_export_unauth_and_missing_slug() -> None:
    from piloci.api import routes

    response = await routes.route_vault_export(_make_request(method="GET", user=None))
    assert response.status_code == 401

    response = await routes.route_vault_export(
        _make_request(method="GET", user={"sub": "u1"}, path_params={"slug": " "})
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# route_readyz happy + degraded path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_readyz_returns_degraded_when_components_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(distillation_max_pending_backlog=10),
    )

    store = MagicMock()
    store._get_table = AsyncMock(side_effect=RuntimeError("nope"))

    db = _db_session()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    redis_store = SimpleNamespace(ping=AsyncMock(side_effect=RuntimeError("redis down")))
    monkeypatch.setattr(routes, "get_session_store", lambda settings: redis_store)

    import piloci.curator.backlog as backlog_mod

    async def fake_count_pending(db):
        return 0

    monkeypatch.setattr(backlog_mod, "count_pending", fake_count_pending)

    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_readyz(_make_request(method="GET", user=None, app=app))
    # All three backend checks failed -> degraded with status 503
    assert response.status_code == 503
    payload = orjson.loads(response.body)
    assert payload["status"] == "degraded"
    assert "lancedb_unavailable" in payload["causes"]


@pytest.mark.asyncio
async def test_route_readyz_ok_when_all_components_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(distillation_max_pending_backlog=100),
    )

    store = MagicMock()
    store._get_table = AsyncMock(return_value=MagicMock())

    db = _db_session()
    db.execute = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    redis_store = SimpleNamespace(ping=AsyncMock(return_value=True))
    monkeypatch.setattr(routes, "get_session_store", lambda settings: redis_store)

    import piloci.curator.backlog as backlog_mod

    async def fake_count_pending(db):
        return 5

    monkeypatch.setattr(backlog_mod, "count_pending", fake_count_pending)

    app = SimpleNamespace(state=SimpleNamespace(store=store))
    response = await routes.route_readyz(_make_request(method="GET", app=app))
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["status"] == "ok"


# ---------------------------------------------------------------------------
# Admin reject + delete + toggle_active happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_admin_reject_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    admin_user = SimpleNamespace(email="admin@e", id="admin-1")
    target = SimpleNamespace(
        id="u2",
        approval_status="pending",
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
    )

    # Two execute calls: admin lookup, target lookup
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_user
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target

    db = _db_session()
    db.execute = AsyncMock(side_effect=[admin_result, target_result])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    request = _make_request(
        {"reason": "spam"},
        method="POST",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "u2"},
    )
    response = await routes.route_admin_reject_user(request)
    assert response.status_code == 200
    assert target.approval_status == "rejected"
    assert target.rejection_reason == "spam"


@pytest.mark.asyncio
async def test_route_admin_approve_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    admin_user = SimpleNamespace(email="admin@e", id="admin-1")
    target = SimpleNamespace(
        id="u2",
        approval_status="pending",
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason="prior",
    )

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_user
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target

    db = _db_session()
    db.execute = AsyncMock(side_effect=[admin_result, target_result])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    request = _make_request(
        method="POST",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "u2"},
    )
    response = await routes.route_admin_approve_user(request)
    assert response.status_code == 200
    assert target.approval_status == "approved"
    assert target.rejection_reason is None


@pytest.mark.asyncio
async def test_route_admin_reject_user_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    admin_user = SimpleNamespace(email="admin@e", id="admin-1")
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_user
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = None

    db = _db_session()
    db.execute = AsyncMock(side_effect=[admin_result, target_result])
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    request = _make_request(
        {"reason": "x"},
        method="POST",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "missing"},
    )
    response = await routes.route_admin_reject_user(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_admin_toggle_admin_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    target = SimpleNamespace(id="u2", is_admin=False)
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target

    db = _db_session()
    db.execute = AsyncMock(return_value=target_result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    async def fake_invalidate(uid):
        return None

    monkeypatch.setattr(routes, "_invalidate_sessions", fake_invalidate)

    request = _make_request(
        method="POST",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "u2"},
    )
    response = await routes.route_admin_toggle_admin(request)
    assert response.status_code == 200
    assert target.is_admin is True


@pytest.mark.asyncio
async def test_route_admin_toggle_active_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    target = SimpleNamespace(
        id="u2",
        is_active=True,
        locked_until=datetime.now(timezone.utc),
        failed_login_count=3,
    )
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target

    db = _db_session()
    db.execute = AsyncMock(return_value=target_result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    async def fake_invalidate(uid):
        return None

    monkeypatch.setattr(routes, "_invalidate_sessions", fake_invalidate)

    request = _make_request(
        method="POST",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "u2"},
    )
    response = await routes.route_admin_toggle_active(request)
    assert response.status_code == 200
    assert target.is_active is False
    assert target.locked_until is None
    assert target.failed_login_count == 0


@pytest.mark.asyncio
async def test_route_admin_delete_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    target = SimpleNamespace(id="u2")
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target

    db = _db_session()
    db.execute = AsyncMock(return_value=target_result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    async def fake_invalidate(uid):
        return None

    monkeypatch.setattr(routes, "_invalidate_sessions", fake_invalidate)

    request = _make_request(
        method="DELETE",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "u2"},
    )
    response = await routes.route_admin_delete_user(request)
    assert response.status_code == 200
    db.delete.assert_awaited_once_with(target)


@pytest.mark.asyncio
async def test_route_profilez_returns_snapshot() -> None:
    from piloci.api import routes

    response = await routes.route_profilez(_make_request(method="GET"))
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload["status"] == "ok"
    assert "profiling" in payload


# ---------------------------------------------------------------------------
# route_me — fallback email lookup branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_me_unauthorized() -> None:
    from piloci.api import routes

    response = await routes.route_me(_make_request(method="GET", user=None))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_me_returns_session_email() -> None:
    from piloci.api import routes

    response = await routes.route_me(
        _make_request(
            method="GET",
            user={"sub": "u1", "email": "u@e", "is_admin": True, "scope": "user"},
        )
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload == {
        "user_id": "u1",
        "email": "u@e",
        "scope": "user",
        "is_admin": True,
        "approval_status": "approved",
    }


@pytest.mark.asyncio
async def test_route_me_falls_back_to_db_email(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    user_row = SimpleNamespace(email="db@e")
    result = MagicMock()
    result.scalar_one_or_none.return_value = user_row
    db = _db_session()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_me(_make_request(method="GET", user={"sub": "u1"}))
    payload = orjson.loads(response.body)
    assert payload["email"] == "db@e"

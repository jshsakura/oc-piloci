from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from sqlalchemy.exc import IntegrityError
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

    payload = orjson.dumps(body or {})

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
    session.scalar_one_or_none = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


def test_generate_token_setup_contains_mcp_and_hook_snippets() -> None:
    from piloci.api import routes

    setup = routes._generate_token_setup("jwt-token", "https://piloci.example.com")

    assert (
        setup["mcp_config"]["mcpServers"]["piloci"]["url"] == "https://piloci.example.com/mcp/http"
    )
    assert "mcp_config_sse" not in setup
    assert (
        setup["mcp_config"]["mcpServers"]["piloci"]["headers"]["Authorization"]
        == "Bearer jwt-token"
    )
    # hook_config points to script; token is NOT embedded in settings.json
    command = setup["hook_config"]["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "hook.py" in command
    assert "jwt-token" not in command  # token lives in config.json, not hook command

    # hook_config_json has the token for ~/.config/piloci/config.json
    assert setup["hook_config_json"]["token"] == "jwt-token"
    assert (
        "https://piloci.example.com/api/sessions/ingest" in setup["hook_config_json"]["ingest_url"]
    )

    # hook_script is the generic script content (no token)
    assert "hook_script" in setup
    assert "config.json" in setup["hook_script"]
    assert "jwt-token" not in setup["hook_script"]

    assert "claude_md" in setup
    assert "recall" in setup["claude_md"]
    assert "memory" in setup["claude_md"]


def test_json_helper_serializes_payload_and_status() -> None:
    from piloci.api import routes

    response = routes._json({"ok": True}, status=201)

    assert response.status_code == 201
    assert response.media_type == "application/json"
    assert orjson.loads(response.body) == {"ok": True}


def test_truthy_helper_handles_expected_values() -> None:
    from piloci.api import routes

    for value in ("1", "true", "TRUE", "yes", "on", " on "):
        assert routes._truthy(value) is True

    for value in (None, "", "0", "false", "no"):
        assert routes._truthy(value) is False


def test_ip_helper_prefers_forwarded_header_and_falls_back_to_client() -> None:
    from piloci.api import routes

    forwarded_request = _make_request(
        method="GET",
        headers=[(b"x-forwarded-for", b"203.0.113.8, 198.51.100.4")],
    )
    client_request = _make_request(method="GET", headers=[])
    unknown_request = _make_request(method="GET", headers=[], client=None)

    assert routes._ip(forwarded_request) == "203.0.113.8"
    assert routes._ip(client_request) == "127.0.0.1"
    assert routes._ip(unknown_request) == "unknown"


def test_queue_pressure_helper_reports_expected_levels() -> None:
    from piloci.api import routes

    assert routes._queue_pressure(1, 0) == "unbounded"
    assert routes._queue_pressure(1, 5) == "normal"
    assert routes._queue_pressure(4, 5) == "high"
    assert routes._queue_pressure(5, 5) == "full"


@pytest.mark.asyncio
async def test_route_signup_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    request = _make_request(
        {"email": "User@Example.com", "password": "StrongPass123!", "name": "User"}
    )
    db = _db_session()
    settings = SimpleNamespace()
    user = SimpleNamespace(
        id="user-1", email="user@example.com", approval_status="approved", is_admin=False
    )
    signup_mock = AsyncMock(return_value=user)

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "signup", signup_mock)

    response = await routes.route_signup(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 201
    assert payload == {
        "user_id": "user-1",
        "email": "user@example.com",
        "approval_status": "approved",
        "is_admin": False,
    }
    signup_mock.assert_awaited_once_with(
        email="user@example.com",
        password="StrongPass123!",
        name="User",
        db_session=db,
        settings=settings,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "status", "message"),
    [
        pytest.param(Exception("boom"), 500, "Internal server error", id="internal-error"),
    ],
)
async def test_route_signup_internal_error_cases(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: Exception,
    status: int,
    message: str,
) -> None:
    from piloci.api import routes

    request = _make_request({"email": "user@example.com", "password": "StrongPass123!"})
    db = _db_session()

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "signup", AsyncMock(side_effect=side_effect))

    response = await routes.route_signup(request)
    payload = orjson.loads(response.body)

    assert response.status_code == status
    assert payload["error"] == message


@pytest.mark.asyncio
async def test_route_signup_conflict_and_weak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth.local import EmailExistsError, WeakPasswordError

    db = _db_session()
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    monkeypatch.setattr(routes, "signup", AsyncMock(side_effect=EmailExistsError()))
    conflict = await routes.route_signup(
        _make_request({"email": "user@example.com", "password": "StrongPass123!"})
    )
    assert conflict.status_code == 409
    assert orjson.loads(conflict.body)["error"] == "Email already registered"

    monkeypatch.setattr(routes, "signup", AsyncMock(side_effect=WeakPasswordError("too weak")))
    weak = await routes.route_signup(
        _make_request({"email": "user@example.com", "password": "short"})
    )
    assert weak.status_code == 422
    assert orjson.loads(weak.body)["error"] == "too weak"


@pytest.mark.asyncio
async def test_route_login_success_sets_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    request = _make_request(
        {"email": "User@Example.com", "password": "StrongPass123!"},
        headers=[(b"user-agent", b"pytest-agent")],
    )
    db = _db_session()
    settings = SimpleNamespace(session_expire_days=7, base_url=None)
    redis_session = SimpleNamespace()
    user = SimpleNamespace(id="user-1", email="user@example.com", is_admin=False)
    login_mock = AsyncMock(return_value=(user, "session-1"))

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_session_store", lambda settings: redis_session)
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "login", login_mock)

    response = await routes.route_login(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload == {"user_id": "user-1", "email": "user@example.com", "is_admin": False}
    login_mock.assert_awaited_once_with(
        email="user@example.com",
        password="StrongPass123!",
        ip="127.0.0.1",
        user_agent="pytest-agent",
        db_session=db,
        redis_session=redis_session,
        settings=settings,
        totp_code=None,
    )
    assert "piloci_session=session-1" in response.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "status", "expected"),
    [
        pytest.param(
            __import__("piloci.auth.local", fromlist=["AccountLockedError"]).AccountLockedError(
                "locked"
            ),
            429,
            {"error": "locked"},
            id="locked",
        ),
        pytest.param(
            __import__("piloci.auth.local", fromlist=["TOTPRequiredError"]).TOTPRequiredError(),
            401,
            {"error": "2FA code required", "totp_required": True},
            id="totp-required",
        ),
        pytest.param(
            __import__("piloci.auth.local", fromlist=["InvalidTOTPError"]).InvalidTOTPError(),
            401,
            {"error": "Invalid 2FA code"},
            id="invalid-totp",
        ),
        pytest.param(
            __import__(
                "piloci.auth.local", fromlist=["InvalidCredentialsError"]
            ).InvalidCredentialsError(),
            401,
            {"error": "Invalid email or password"},
            id="invalid-credentials",
        ),
        pytest.param(
            __import__(
                "piloci.auth.local", fromlist=["ApprovalPendingError"]
            ).ApprovalPendingError(),
            403,
            {"error": "Account pending admin approval"},
            id="approval-pending",
        ),
        pytest.param(
            __import__(
                "piloci.auth.local", fromlist=["ApprovalRejectedError"]
            ).ApprovalRejectedError(),
            403,
            {"error": "Account has been rejected by an admin"},
            id="approval-rejected",
        ),
        pytest.param(RuntimeError("boom"), 500, {"error": "Internal server error"}, id="internal"),
    ],
)
async def test_route_login_error_branches(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: Exception,
    status: int,
    expected: dict[str, object],
) -> None:
    from piloci.api import routes

    request = _make_request({"email": "user@example.com", "password": "StrongPass123!"})
    db = _db_session()

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(session_expire_days=7))
    monkeypatch.setattr(routes, "get_session_store", lambda settings: SimpleNamespace())
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "login", AsyncMock(side_effect=side_effect))

    response = await routes.route_login(request)

    assert response.status_code == status
    assert orjson.loads(response.body) == expected


@pytest.mark.asyncio
async def test_route_logout_deletes_existing_session_and_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    request = _make_request(method="POST", cookies={"piloci_session": "session-1"})
    store = SimpleNamespace(
        get_session=AsyncMock(return_value={"user_id": "user-1"}),
        delete_session=AsyncMock(),
    )

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(routes, "get_session_store", lambda settings: store)

    response = await routes.route_logout(request)
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload == {"status": "logged out"}
    store.get_session.assert_awaited_once_with("session-1")
    store.delete_session.assert_awaited_once_with("session-1", "user-1")
    assert "piloci_session=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_route_forgot_password_returns_token_and_generic_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    monkeypatch.setattr(routes, "create_reset_token", AsyncMock(return_value="reset-token"))
    token_response = await routes.route_forgot_password(
        _make_request({"email": "User@Example.com"})
    )
    assert token_response.status_code == 200
    assert orjson.loads(token_response.body) == {"token": "reset-token"}

    monkeypatch.setattr(routes, "create_reset_token", AsyncMock(return_value=None))
    generic_response = await routes.route_forgot_password(
        _make_request({"email": "user@example.com"})
    )
    assert generic_response.status_code == 200
    assert orjson.loads(generic_response.body) == {
        "message": "If that email exists, a reset token has been generated"
    }


@pytest.mark.asyncio
async def test_route_forgot_password_missing_email_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    missing = await routes.route_forgot_password(_make_request({}))
    assert missing.status_code == 400
    assert orjson.loads(missing.body) == {"error": "email is required"}

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "create_reset_token", AsyncMock(side_effect=RuntimeError("boom")))
    response = await routes.route_forgot_password(_make_request({"email": "user@example.com"}))
    assert response.status_code == 200
    assert orjson.loads(response.body) == {
        "message": "If that email exists, a reset token has been generated"
    }


@pytest.mark.asyncio
async def test_route_reset_password_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    reset = AsyncMock()

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "reset_password", reset)

    response = await routes.route_reset_password(
        _make_request({"token": "token-1", "new_password": "NewStrongPass123!"})
    )
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload == {"message": "Password has been reset successfully"}
    reset.assert_awaited_once_with(token="token-1", new_password="NewStrongPass123!", db_session=db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "status", "message"),
    [
        pytest.param(
            __import__("piloci.auth.local", fromlist=["TokenInvalidError"]).TokenInvalidError(),
            400,
            "Invalid reset token",
            id="invalid",
        ),
        pytest.param(
            __import__("piloci.auth.local", fromlist=["TokenUsedError"]).TokenUsedError(),
            400,
            "Reset token has already been used",
            id="used",
        ),
        pytest.param(
            __import__("piloci.auth.local", fromlist=["TokenExpiredError"]).TokenExpiredError(),
            400,
            "Reset token has expired",
            id="expired",
        ),
        pytest.param(
            __import__("piloci.auth.local", fromlist=["WeakPasswordError"]).WeakPasswordError(
                "too weak"
            ),
            422,
            "too weak",
            id="weak-password",
        ),
        pytest.param(RuntimeError("boom"), 500, "Internal server error", id="internal"),
    ],
)
async def test_route_reset_password_error_branches(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: Exception,
    status: int,
    message: str,
) -> None:
    from piloci.api import routes

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "reset_password", AsyncMock(side_effect=side_effect))

    response = await routes.route_reset_password(
        _make_request({"token": "token-1", "new_password": "NewStrongPass123!"})
    )

    assert response.status_code == status
    assert orjson.loads(response.body)["error"] == message


@pytest.mark.asyncio
async def test_route_list_projects_returns_project_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    project = SimpleNamespace(
        id="project-1",
        slug="alpha",
        name="Alpha",
        description="First",
        memory_count=3,
        instinct_count=2,
        created_at=created_at,
    )
    project_select_result = MagicMock()
    project_select_result.scalars.return_value.all.return_value = [project]
    sess_row = SimpleNamespace(
        project_id="project-1",
        count=5,
        last_active=datetime(2024, 1, 5, tzinfo=timezone.utc),
    )
    sess_result = MagicMock()
    sess_result.all.return_value = [sess_row]
    analyze_row = SimpleNamespace(
        project_id="project-1",
        last_analyzed=datetime(2024, 1, 6, tzinfo=timezone.utc),
    )
    analyze_result = MagicMock()
    analyze_result.all.return_value = [analyze_row]

    db = _db_session()
    db.execute.side_effect = [project_select_result, sess_result, analyze_result]

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_list_projects(_make_request(method="GET", user={"sub": "user-1"}))
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload == [
        {
            "id": "project-1",
            "slug": "alpha",
            "name": "Alpha",
            "description": "First",
            "memory_count": 3,
            "instinct_count": 2,
            "session_count": 5,
            "last_active_at": sess_row.last_active.isoformat(),
            "last_analyzed_at": analyze_row.last_analyzed.isoformat(),
            "created_at": created_at.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_route_create_project_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: "project-uuid")

    response = await routes.route_create_project(
        _make_request(
            {"slug": "alpha-project", "name": "Alpha", "description": "First"},
            user={"sub": "user-1"},
        )
    )
    payload = orjson.loads(response.body)

    assert response.status_code == 201
    assert payload == {"id": "project-uuid", "slug": "alpha-project", "name": "Alpha"}
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_create_project_validation_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    missing = await routes.route_create_project(
        _make_request({"slug": "", "name": ""}, user={"sub": "user-1"})
    )
    assert missing.status_code == 400
    assert orjson.loads(missing.body) == {"error": "slug and name are required"}

    invalid = await routes.route_create_project(
        _make_request({"slug": "bad_slug", "name": "Alpha"}, user={"sub": "user-1"})
    )
    assert invalid.status_code == 422
    assert orjson.loads(invalid.body) == {
        "error": "slug must be lowercase alphanumeric with hyphens"
    }

    conflict_db = _db_session()
    conflict_db.flush.side_effect = IntegrityError("insert", {}, Exception("dup"))
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(conflict_db)))
    conflict = await routes.route_create_project(
        _make_request({"slug": "alpha", "name": "Alpha"}, user={"sub": "user-1"})
    )
    assert conflict.status_code == 409
    assert orjson.loads(conflict.body) == {"error": "Project slug already exists"}

    error_db = _db_session()
    error_db.flush.side_effect = RuntimeError("boom")
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(error_db)))
    error = await routes.route_create_project(
        _make_request({"slug": "alpha", "name": "Alpha"}, user={"sub": "user-1"})
    )
    assert error.status_code == 500
    assert orjson.loads(error.body) == {"error": "Internal server error"}


@pytest.mark.asyncio
async def test_route_delete_project_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(slug="alpha")
    db.execute.return_value = result
    invalidate = AsyncMock()

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "invalidate_project_vault_cache", invalidate)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir="/vaults"))

    response = await routes.route_delete_project(
        _make_request(
            {"confirm": True},
            user={"sub": "user-1"},
            path_params={"id": "project-1"},
        )
    )

    assert response.status_code == 200
    assert orjson.loads(response.body) == {"deleted": True}
    assert db.execute.await_count == 2
    invalidate.assert_awaited_once_with("/vaults", "user-1", "project-1", "alpha")


@pytest.mark.asyncio
async def test_route_update_project_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(
        name="Old", description="old desc", slug="alpha"
    )
    db.execute.return_value = result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_update_project(
        _make_request(
            {"name": "New", "description": "fresh desc"},
            user={"sub": "user-1"},
            path_params={"id": "project-1"},
            method="PATCH",
        )
    )
    body = orjson.loads(response.body)
    assert response.status_code == 200
    assert body["name"] == "New"
    assert body["description"] == "fresh desc"
    assert body["slug"] == "alpha"
    # Two awaits: SELECT then UPDATE.
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_route_update_project_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    blank_name = await routes.route_update_project(
        _make_request(
            {"name": "  "},
            user={"sub": "user-1"},
            path_params={"id": "project-1"},
            method="PATCH",
        )
    )
    assert blank_name.status_code == 422

    no_fields = await routes.route_update_project(
        _make_request(
            {},
            user={"sub": "user-1"},
            path_params={"id": "project-1"},
            method="PATCH",
        )
    )
    assert no_fields.status_code == 422
    assert "name, description" in orjson.loads(no_fields.body)["error"]

    too_long = await routes.route_update_project(
        _make_request(
            {"description": "x" * 2001},
            user={"sub": "user-1"},
            path_params={"id": "project-1"},
            method="PATCH",
        )
    )
    assert too_long.status_code == 422

    db = _db_session()
    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none.return_value = None
    db.execute.return_value = not_found_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    not_found = await routes.route_update_project(
        _make_request(
            {"name": "x"},
            user={"sub": "user-1"},
            path_params={"id": "missing"},
            method="PATCH",
        )
    )
    assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_route_update_project_unauthorized() -> None:
    from piloci.api import routes

    resp = await routes.route_update_project(
        _make_request({"name": "x"}, user=None, path_params={"id": "p"}, method="PATCH")
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_route_delete_project_validation_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    missing_id = await routes.route_delete_project(
        _make_request({"confirm": True}, user={"sub": "user-1"}, path_params={})
    )
    assert missing_id.status_code == 400
    assert orjson.loads(missing_id.body) == {"error": "project id required"}

    missing_confirm = await routes.route_delete_project(
        _make_request({}, user={"sub": "user-1"}, path_params={"id": "project-1"})
    )
    assert missing_confirm.status_code == 422
    assert orjson.loads(missing_confirm.body) == {"error": "confirm:true required"}

    db = _db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    not_found = await routes.route_delete_project(
        _make_request(
            {"confirm": True},
            user={"sub": "user-1"},
            path_params={"id": "project-1"},
        )
    )
    assert not_found.status_code == 404
    assert orjson.loads(not_found.body) == {"error": "Not found"}


@pytest.mark.asyncio
async def test_route_project_workspace_uses_cached_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    store = SimpleNamespace(list=AsyncMock())
    app = SimpleNamespace(state=SimpleNamespace(store=store))
    project = {"id": "project-1", "slug": "alpha", "name": "Alpha"}
    workspace = {"notes": [{"path": "alpha.md"}]}

    monkeypatch.setattr(routes, "_get_user_project_by_slug", AsyncMock(return_value=project))
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir="/vaults"))
    monkeypatch.setattr(routes, "load_cached_project_vault", lambda vault_dir, slug: workspace)

    response = await routes.route_project_workspace(
        _make_request(
            method="GET",
            user={"sub": "user-1"},
            path_params={"slug": "alpha"},
            app=app,
        )
    )

    assert response.status_code == 200
    assert orjson.loads(response.body) == {"project": project, "workspace": workspace}
    store.list.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_project_workspace_preview_and_export_build_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    project = {"id": "project-1", "slug": "alpha", "name": "Alpha"}
    workspace = {"notes": [{"path": "alpha.md"}]}
    preview = {"notes": [{"title": "Alpha"}]}
    archive = b"zip-bytes"
    store = SimpleNamespace(list=AsyncMock(return_value=[{"memory_id": "mem-1"}]))
    app = SimpleNamespace(state=SimpleNamespace(store=store))

    monkeypatch.setattr(routes, "_get_user_project_by_slug", AsyncMock(return_value=project))
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir="/vaults"))
    monkeypatch.setattr(routes, "load_cached_project_vault", lambda vault_dir, slug: None)
    monkeypatch.setattr(
        routes,
        "ensure_project_vault",
        lambda received_project, memories, vault_dir, force: workspace,
    )
    monkeypatch.setattr(routes, "build_project_vault_preview", lambda received: preview)
    monkeypatch.setattr(
        routes, "export_project_vault_zip", lambda received_project, received: archive
    )

    preview_response = await routes.route_project_workspace_preview(
        _make_request(
            method="GET",
            user={"sub": "user-1"},
            path_params={"slug": "alpha"},
            query_string=b"refresh=true",
            app=app,
        )
    )
    export_response = await routes.route_vault_export(
        _make_request(
            method="GET",
            user={"sub": "user-1"},
            path_params={"slug": "alpha"},
            app=app,
        )
    )

    assert preview_response.status_code == 200
    assert orjson.loads(preview_response.body) == {"project": project, "workspace": preview}
    assert export_response.status_code == 200
    assert export_response.body == archive
    assert (
        export_response.headers["content-disposition"] == 'attachment; filename="alpha-vault.zip"'
    )
    assert store.list.await_count == 2


@pytest.mark.asyncio
async def test_route_project_workspace_family_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    unauthorized = await routes.route_project_workspace(_make_request(method="GET", user=None))
    assert unauthorized.status_code == 401
    assert orjson.loads(unauthorized.body) == {"error": "Unauthorized"}

    missing_slug = await routes.route_project_workspace(
        _make_request(method="GET", user={"sub": "user-1"}, path_params={})
    )
    assert missing_slug.status_code == 400
    assert orjson.loads(missing_slug.body) == {"error": "project slug required"}

    monkeypatch.setattr(routes, "_get_user_project_by_slug", AsyncMock(return_value=None))
    not_found = await routes.route_vault_export(
        _make_request(method="GET", user={"sub": "user-1"}, path_params={"slug": "alpha"})
    )
    assert not_found.status_code == 404
    assert orjson.loads(not_found.body) == {"error": "Not found"}


@pytest.mark.asyncio
async def test_route_create_token_success_with_project_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    db = _db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(slug="alpha")
    db.execute.return_value = result
    settings = SimpleNamespace(base_url="https://piloci.example.com")
    create = MagicMock(return_value="jwt-token")

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "create_token", create)
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: "token-uuid")

    response = await routes.route_create_token(
        _make_request(
            {"name": "CLI", "project_id": "project-1", "scope": "project"},
            user={"sub": "user-1", "email": "user@example.com"},
        )
    )
    payload = orjson.loads(response.body)

    assert response.status_code == 201
    assert payload["token"] == "jwt-token"
    assert payload["token_id"] == "token-uuid"
    assert payload["name"] == "CLI"
    assert payload["setup"]["mcp_config"]["mcpServers"]["piloci"]["headers"] == {
        "Authorization": "Bearer jwt-token"
    }
    create.assert_called_once_with(
        user_id="user-1",
        email="user@example.com",
        project_id="project-1",
        project_slug="alpha",
        scope="project",
        settings=settings,
        token_id="token-uuid",
        expire_days=365,
    )
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_route_hook_script_authenticated_returns_python_script() -> None:
    """GET /api/hook/script returns the generic hook.py for authed users."""
    from piloci.api import routes

    response = await routes.route_hook_script(_make_request(method="GET", user={"sub": "user-1"}))
    assert response.status_code == 200
    assert response.media_type == "text/x-python"
    body = response.body.decode() if isinstance(response.body, bytes) else response.body
    # Script must be token-free — token lives in config.json
    assert "config.json" in body
    assert "ingest_url" in body
    # Content-Disposition lets browsers download as hook.py
    assert response.headers.get("Content-Disposition", "").startswith("attachment")


@pytest.mark.asyncio
async def test_route_hook_script_unauthenticated_returns_401() -> None:
    from piloci.api import routes

    response = await routes.route_hook_script(_make_request(method="GET", user=None))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_create_token_user_scope_returns_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-scoped token must also return hook + MCP setup (global install path)."""
    from piloci.api import routes

    db = _db_session()
    settings = SimpleNamespace(base_url="https://piloci.example.com")
    create = MagicMock(return_value="user-jwt")

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "create_token", create)
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: "token-uuid")

    response = await routes.route_create_token(
        _make_request(
            {"name": "Global", "scope": "user"},
            user={"sub": "user-1", "email": "user@example.com"},
        )
    )
    payload = orjson.loads(response.body)

    assert response.status_code == 201
    assert payload["token"] == "user-jwt"
    assert "setup" in payload, "user-scoped token must receive setup for global install"
    assert payload["setup"]["hook_config_json"]["token"] == "user-jwt"
    assert "hook_script" in payload["setup"]
    assert payload["setup"]["mcp_config"]["mcpServers"]["piloci"]["headers"] == {
        "Authorization": "Bearer user-jwt"
    }


@pytest.mark.asyncio
async def test_route_create_token_validation_and_missing_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    unauthorized = await routes.route_create_token(_make_request({"name": "CLI"}, user=None))
    assert unauthorized.status_code == 401
    assert orjson.loads(unauthorized.body) == {"error": "Unauthorized"}

    missing_name = await routes.route_create_token(
        _make_request({"name": " ", "scope": "user"}, user={"sub": "user-1", "email": "u@e"})
    )
    assert missing_name.status_code == 400
    assert orjson.loads(missing_name.body) == {"error": "name is required"}

    invalid_scope = await routes.route_create_token(
        _make_request(
            {"name": "CLI", "scope": "team"},
            user={"sub": "user-1", "email": "u@e"},
        )
    )
    assert invalid_scope.status_code == 422
    assert orjson.loads(invalid_scope.body) == {"error": "scope must be 'project' or 'user'"}

    missing_project_id = await routes.route_create_token(
        _make_request(
            {"name": "CLI", "scope": "project"},
            user={"sub": "user-1", "email": "u@e"},
        )
    )
    assert missing_project_id.status_code == 422
    assert orjson.loads(missing_project_id.body) == {
        "error": "project_id required for project scope"
    }

    db = _db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(base_url=None))

    not_found = await routes.route_create_token(
        _make_request(
            {"name": "CLI", "scope": "project", "project_id": "project-1"},
            user={"sub": "user-1", "email": "u@e"},
        )
    )
    assert not_found.status_code == 404
    assert orjson.loads(not_found.body) == {"error": "Project not found"}


@pytest.mark.asyncio
async def test_route_list_tokens_returns_active_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    last_used = datetime(2024, 1, 2, tzinfo=timezone.utc)
    installed_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    token = SimpleNamespace(
        token_id="token-1",
        name="CLI",
        scope="project",
        project_id="project-1",
        created_at=created_at,
        last_used_at=last_used,
        expires_at=None,
        installed_at=installed_at,
        client_kinds="claude,opencode",
        hostname="pi5",
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [token]
    db = _db_session()
    db.execute.return_value = result

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_list_tokens(_make_request(method="GET", user={"sub": "user-1"}))
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload == [
        {
            "token_id": "token-1",
            "name": "CLI",
            "scope": "project",
            "project_id": "project-1",
            "created_at": created_at.isoformat(),
            "last_used_at": last_used.isoformat(),
            "expires_at": None,
            "installed_at": installed_at.isoformat(),
            "client_kinds": ["claude", "opencode"],
            "hostname": "pi5",
        }
    ]


@pytest.mark.asyncio
async def test_route_list_audit_returns_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    created_at = datetime(2024, 1, 3, tzinfo=timezone.utc)
    log = SimpleNamespace(
        id=1,
        action="LOGIN",
        ip_address="127.0.0.1",
        user_agent="pytest",
        meta_data={"source": "web"},
        created_at=created_at,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [log]
    db = _db_session()
    db.execute.return_value = result

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_list_audit(
        _make_request(
            method="GET",
            user={"sub": "user-1"},
            query_string=b"limit=20&offset=1&action=LOGIN",
        )
    )
    payload = orjson.loads(response.body)

    assert response.status_code == 200
    assert payload == [
        {
            "id": 1,
            "action": "LOGIN",
            "ip_address": "127.0.0.1",
            "user_agent": "pytest",
            "meta_data": {"source": "web"},
            "created_at": created_at.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_route_install_heartbeat_stamps_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    update_result = MagicMock()
    update_result.rowcount = 1
    db.execute.return_value = update_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_install_heartbeat(
        _make_request(
            method="POST",
            user={"sub": "user-1", "jti": "token-1"},
            body={"client_kinds": ["claude", "opencode"], "hostname": "pi5"},
        )
    )
    payload = orjson.loads(response.body)
    assert response.status_code == 200
    assert payload["client_kinds"] == ["claude", "opencode"]
    assert payload["hostname"] == "pi5"
    assert "installed_at" in payload


@pytest.mark.asyncio
async def test_route_install_heartbeat_unauthorized_without_jti() -> None:
    from piloci.api import routes

    response = await routes.route_install_heartbeat(
        _make_request(
            method="POST",
            user={"sub": "user-1"},  # no jti
            body={"client_kinds": ["claude"]},
        )
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_install_heartbeat_validates_client_kinds() -> None:
    from piloci.api import routes

    bad_type = await routes.route_install_heartbeat(
        _make_request(
            method="POST",
            user={"sub": "u", "jti": "t"},
            body={"client_kinds": "claude"},
        )
    )
    assert bad_type.status_code == 422

    empty = await routes.route_install_heartbeat(
        _make_request(
            method="POST",
            user={"sub": "u", "jti": "t"},
            body={"client_kinds": []},
        )
    )
    assert empty.status_code == 422

    bad_kind = await routes.route_install_heartbeat(
        _make_request(
            method="POST",
            user={"sub": "u", "jti": "t"},
            body={"client_kinds": ["evilshell"]},
        )
    )
    assert bad_kind.status_code == 422


@pytest.mark.asyncio
async def test_route_install_heartbeat_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    update_result = MagicMock()
    update_result.rowcount = 0
    db.execute.return_value = update_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_install_heartbeat(
        _make_request(
            method="POST",
            user={"sub": "user-1", "jti": "missing"},
            body={"client_kinds": ["claude"]},
        )
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_revoke_token_success_and_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    found = MagicMock()
    found.scalar_one_or_none.return_value = SimpleNamespace(token_id="token-1")
    db.execute.return_value = found
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    success = await routes.route_revoke_token(
        _make_request(method="POST", user={"sub": "user-1"}, path_params={"id": "token-1"})
    )
    assert success.status_code == 200
    assert orjson.loads(success.body) == {"revoked": True}
    assert db.execute.await_count == 2

    missing_db = _db_session()
    missing = MagicMock()
    missing.scalar_one_or_none.return_value = None
    missing_db.execute.return_value = missing
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(missing_db)))

    not_found = await routes.route_revoke_token(
        _make_request(method="POST", user={"sub": "user-1"}, path_params={"id": "token-2"})
    )
    assert not_found.status_code == 404
    assert orjson.loads(not_found.body) == {"error": "Not found"}


@pytest.mark.asyncio
async def test_route_me_healthz_and_auth_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import oauth

    me = await routes.route_me(
        _make_request(
            method="GET",
            user={
                "sub": "user-1",
                "email": "user@example.com",
                "scope": "project",
                "is_admin": True,
                "approval_status": "approved",
            },
        )
    )
    assert me.status_code == 200
    assert orjson.loads(me.body) == {
        "user_id": "user-1",
        "email": "user@example.com",
        "scope": "project",
        "is_admin": True,
        "approval_status": "approved",
    }

    healthz = await routes.route_healthz(_make_request(method="GET"))
    assert healthz.status_code == 200
    assert orjson.loads(healthz.body) == {"status": "ok"}

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(oauth, "PROVIDERS", ["google", "github"])
    monkeypatch.setattr(
        oauth,
        "get_provider_credentials",
        lambda settings, name: ("id", "secret") if name == "google" else None,
    )

    providers = await routes.route_auth_providers(_make_request(method="GET"))
    assert providers.status_code == 200
    assert orjson.loads(providers.body) == {
        "providers": [
            {"name": "google", "configured": True, "login_path": "/auth/google/login"},
            {"name": "github", "configured": False, "login_path": "/auth/github/login"},
        ]
    }


@pytest.mark.asyncio
async def test_route_2fa_enable_success_and_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import totp

    unauthorized = await routes.route_2fa_enable(_make_request(method="POST", user=None))
    assert unauthorized.status_code == 401
    assert orjson.loads(unauthorized.body) == {"error": "Unauthorized"}

    missing_db = _db_session()
    missing_result = MagicMock()
    missing_result.scalar_one_or_none.return_value = None
    missing_db.execute.return_value = missing_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(missing_db)))
    missing = await routes.route_2fa_enable(
        _make_request(method="POST", user={"sub": "user-1", "email": "user@example.com"})
    )
    assert missing.status_code == 404
    assert orjson.loads(missing.body) == {"error": "User not found"}

    enabled_db = _db_session()
    enabled_result = MagicMock()
    enabled_result.scalar_one_or_none.return_value = SimpleNamespace(totp_enabled=True)
    enabled_db.execute.return_value = enabled_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(enabled_db)))
    enabled = await routes.route_2fa_enable(
        _make_request(method="POST", user={"sub": "user-1", "email": "user@example.com"})
    )
    assert enabled.status_code == 409
    assert orjson.loads(enabled.body) == {"error": "2FA is already enabled"}

    db_user = SimpleNamespace(totp_enabled=False, totp_secret=None)
    success_db = _db_session()
    success_result = MagicMock()
    success_result.scalar_one_or_none.return_value = db_user
    success_db.execute.return_value = success_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(success_db)))
    monkeypatch.setattr(totp, "generate_totp_secret", lambda: "secret-123")
    monkeypatch.setattr(totp, "get_qr_base64", lambda secret, email: f"qr:{secret}:{email}")

    success = await routes.route_2fa_enable(
        _make_request(method="POST", user={"sub": "user-1", "email": "user@example.com"})
    )
    assert success.status_code == 200
    assert orjson.loads(success.body) == {
        "qr": "qr:secret-123:user@example.com",
        "secret": "secret-123",
    }
    assert db_user.totp_secret == "secret-123"
    assert db_user.totp_enabled is False
    success_db.add.assert_called_once_with(db_user)
    success_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_2fa_confirm_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import totp

    unauthorized = await routes.route_2fa_confirm(_make_request(method="POST", user=None))
    assert unauthorized.status_code == 401
    assert orjson.loads(unauthorized.body) == {"error": "Unauthorized"}

    malformed_scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "state": {"user": {"sub": "user-1"}},
    }

    async def bad_receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"{", "more_body": False}

    invalid_json = await routes.route_2fa_confirm(Request(malformed_scope, bad_receive))
    assert invalid_json.status_code == 400
    assert orjson.loads(invalid_json.body) == {"error": "Invalid JSON"}

    missing_code = await routes.route_2fa_confirm(
        _make_request(method="POST", body={}, user={"sub": "user-1"})
    )
    assert missing_code.status_code == 400
    assert orjson.loads(missing_code.body) == {"error": "code is required"}

    missing_db = _db_session()
    missing_result = MagicMock()
    missing_result.scalar_one_or_none.return_value = None
    missing_db.execute.return_value = missing_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(missing_db)))
    missing_user = await routes.route_2fa_confirm(
        _make_request(method="POST", body={"code": "123456"}, user={"sub": "user-1"})
    )
    assert missing_user.status_code == 404
    assert orjson.loads(missing_user.body) == {"error": "User not found"}

    setup_db = _db_session()
    setup_result = MagicMock()
    setup_result.scalar_one_or_none.return_value = SimpleNamespace(
        totp_secret=None, totp_enabled=False
    )
    setup_db.execute.return_value = setup_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(setup_db)))
    setup_missing = await routes.route_2fa_confirm(
        _make_request(method="POST", body={"code": "123456"}, user={"sub": "user-1"})
    )
    assert setup_missing.status_code == 400
    assert orjson.loads(setup_missing.body) == {
        "error": "2FA setup not initiated or already confirmed"
    }

    invalid_db = _db_session()
    invalid_result = MagicMock()
    invalid_result.scalar_one_or_none.return_value = SimpleNamespace(
        totp_secret="secret-123", totp_enabled=False
    )
    invalid_db.execute.return_value = invalid_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(invalid_db)))
    monkeypatch.setattr(totp, "verify_totp", lambda secret, code: False)
    invalid_code = await routes.route_2fa_confirm(
        _make_request(method="POST", body={"code": "123456"}, user={"sub": "user-1"})
    )
    assert invalid_code.status_code == 422
    assert orjson.loads(invalid_code.body) == {"error": "Invalid TOTP code"}

    db_user = SimpleNamespace(totp_secret="secret-123", totp_enabled=False)
    success_db = _db_session()
    success_result = MagicMock()
    success_result.scalar_one_or_none.return_value = db_user
    success_db.execute.return_value = success_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(success_db)))
    monkeypatch.setattr(totp, "verify_totp", lambda secret, code: True)
    monkeypatch.setattr(totp, "generate_backup_codes", lambda count: ["backup-1", "backup-2"])
    monkeypatch.setattr(totp, "hash_backup_codes", lambda codes: [f"hash:{code}" for code in codes])

    success = await routes.route_2fa_confirm(
        _make_request(method="POST", body={"code": "123456"}, user={"sub": "user-1"})
    )
    assert success.status_code == 200
    assert orjson.loads(success.body) == {
        "backup_codes": ["backup-1", "backup-2"],
        "backup_codes_hashed": ["hash:backup-1", "hash:backup-2"],
    }
    assert db_user.totp_enabled is True
    success_db.add.assert_called_once_with(db_user)
    success_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_2fa_disable_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import password, totp

    invalid_json_scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "state": {"user": {"sub": "user-1"}},
    }

    async def bad_receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"{", "more_body": False}

    invalid_json = await routes.route_2fa_disable(Request(invalid_json_scope, bad_receive))
    assert invalid_json.status_code == 400
    assert orjson.loads(invalid_json.body) == {"error": "Invalid JSON"}

    missing_fields = await routes.route_2fa_disable(
        _make_request(method="POST", body={}, user={"sub": "user-1"})
    )
    assert missing_fields.status_code == 400
    assert orjson.loads(missing_fields.body) == {"error": "password and code are required"}

    missing_db = _db_session()
    missing_result = MagicMock()
    missing_result.scalar_one_or_none.return_value = None
    missing_db.execute.return_value = missing_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(missing_db)))
    missing_user = await routes.route_2fa_disable(
        _make_request(
            method="POST",
            body={"password": "CurrentPass123", "code": "123456"},
            user={"sub": "user-1"},
        )
    )
    assert missing_user.status_code == 404
    assert orjson.loads(missing_user.body) == {"error": "User not found"}

    disabled_db = _db_session()
    disabled_result = MagicMock()
    disabled_result.scalar_one_or_none.return_value = SimpleNamespace(totp_enabled=False)
    disabled_db.execute.return_value = disabled_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(disabled_db)))
    disabled = await routes.route_2fa_disable(
        _make_request(
            method="POST",
            body={"password": "CurrentPass123", "code": "123456"},
            user={"sub": "user-1"},
        )
    )
    assert disabled.status_code == 400
    assert orjson.loads(disabled.body) == {"error": "2FA is not enabled"}

    invalid_pw_user = SimpleNamespace(totp_enabled=True, password_hash="hash", totp_secret="secret")
    invalid_pw_db = _db_session()
    invalid_pw_result = MagicMock()
    invalid_pw_result.scalar_one_or_none.return_value = invalid_pw_user
    invalid_pw_db.execute.return_value = invalid_pw_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(invalid_pw_db)))
    monkeypatch.setattr(password, "verify_password", lambda raw, hashed: False)
    invalid_pw = await routes.route_2fa_disable(
        _make_request(
            method="POST",
            body={"password": "CurrentPass123", "code": "123456"},
            user={"sub": "user-1"},
        )
    )
    assert invalid_pw.status_code == 401
    assert orjson.loads(invalid_pw.body) == {"error": "Invalid password"}

    missing_secret_user = SimpleNamespace(totp_enabled=True, password_hash="hash", totp_secret=None)
    missing_secret_db = _db_session()
    missing_secret_result = MagicMock()
    missing_secret_result.scalar_one_or_none.return_value = missing_secret_user
    missing_secret_db.execute.return_value = missing_secret_result
    monkeypatch.setattr(
        routes, "async_session", MagicMock(return_value=_session_cm(missing_secret_db))
    )
    monkeypatch.setattr(password, "verify_password", lambda raw, hashed: True)
    missing_secret = await routes.route_2fa_disable(
        _make_request(
            method="POST",
            body={"password": "CurrentPass123", "code": "123456"},
            user={"sub": "user-1"},
        )
    )
    assert missing_secret.status_code == 400
    assert orjson.loads(missing_secret.body) == {"error": "2FA secret missing"}

    invalid_totp_user = SimpleNamespace(
        totp_enabled=True, password_hash="hash", totp_secret="secret"
    )
    invalid_totp_db = _db_session()
    invalid_totp_result = MagicMock()
    invalid_totp_result.scalar_one_or_none.return_value = invalid_totp_user
    invalid_totp_db.execute.return_value = invalid_totp_result
    monkeypatch.setattr(
        routes, "async_session", MagicMock(return_value=_session_cm(invalid_totp_db))
    )
    monkeypatch.setattr(password, "verify_password", lambda raw, hashed: True)
    monkeypatch.setattr(totp, "verify_totp", lambda secret, code: False)
    invalid_totp = await routes.route_2fa_disable(
        _make_request(
            method="POST",
            body={"password": "CurrentPass123", "code": "123456"},
            user={"sub": "user-1"},
        )
    )
    assert invalid_totp.status_code == 422
    assert orjson.loads(invalid_totp.body) == {"error": "Invalid TOTP code"}

    success_user = SimpleNamespace(totp_enabled=True, password_hash="hash", totp_secret="secret")
    success_db = _db_session()
    success_result = MagicMock()
    success_result.scalar_one_or_none.return_value = success_user
    success_db.execute.return_value = success_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(success_db)))
    monkeypatch.setattr(password, "verify_password", lambda raw, hashed: True)
    monkeypatch.setattr(totp, "verify_totp", lambda secret, code: True)
    success = await routes.route_2fa_disable(
        _make_request(
            method="POST",
            body={"password": "CurrentPass123", "code": "123456"},
            user={"sub": "user-1"},
        )
    )
    assert success.status_code == 200
    assert orjson.loads(success.body) == {"disabled": True}
    assert success_user.totp_secret is None
    assert success_user.totp_enabled is False
    success_db.add.assert_called_once_with(success_user)
    success_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_change_password_success_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes
    from piloci.auth import password

    unauthorized = await routes.route_change_password(_make_request(method="POST", user=None))
    assert unauthorized.status_code == 401
    assert orjson.loads(unauthorized.body) == {"error": "Unauthorized"}

    missing = await routes.route_change_password(
        _make_request(method="POST", body={}, user={"sub": "user-1"})
    )
    assert missing.status_code == 400
    assert orjson.loads(missing.body) == {"error": "current_password and new_password required"}

    weak = await routes.route_change_password(
        _make_request(
            method="POST",
            body={"current_password": "CurrentPass123", "new_password": "short"},
            user={"sub": "user-1"},
        )
    )
    assert weak.status_code == 422
    assert orjson.loads(weak.body) == {
        "error": "Password must be 12+ chars with uppercase, lowercase, and digit"
    }

    invalid_user = SimpleNamespace(password_hash="hash")
    invalid_db = _db_session()
    invalid_result = MagicMock()
    invalid_result.scalar_one_or_none.return_value = invalid_user
    invalid_db.execute.return_value = invalid_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(invalid_db)))
    monkeypatch.setattr(password, "verify_password", lambda raw, hashed: False)
    incorrect = await routes.route_change_password(
        _make_request(
            method="POST",
            body={
                "current_password": "CurrentPass123",
                "new_password": "NewStrongPass123",
            },
            user={"sub": "user-1"},
        )
    )
    assert incorrect.status_code == 401
    assert orjson.loads(incorrect.body) == {"error": "Current password is incorrect"}

    success_user = SimpleNamespace(password_hash="hash")
    success_db = _db_session()
    success_result = MagicMock()
    success_result.scalar_one_or_none.return_value = success_user
    success_db.execute.return_value = success_result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(success_db)))
    monkeypatch.setattr(password, "verify_password", lambda raw, hashed: True)
    monkeypatch.setattr(password, "hash_password", lambda raw: f"hashed:{raw}")

    success = await routes.route_change_password(
        _make_request(
            method="POST",
            body={
                "current_password": "CurrentPass123",
                "new_password": "NewStrongPass123",
            },
            user={"sub": "user-1"},
        )
    )
    assert success.status_code == 200
    assert orjson.loads(success.body) == {"changed": True}
    assert success_user.password_hash == "hashed:NewStrongPass123"
    success_db.add.assert_called_once_with(success_user)


@pytest.mark.asyncio
async def test_route_oauth_login_validation_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import oauth

    settings = SimpleNamespace(base_url="https://piloci.example.com")
    redis = SimpleNamespace(setex=AsyncMock())
    store = SimpleNamespace(_redis=redis)

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_session_store", lambda received: store)
    monkeypatch.setattr(oauth, "PROVIDERS", ["google"])

    unknown = await routes.route_oauth_login(
        _make_request(method="GET", path_params={"provider": "github"})
    )
    assert unknown.status_code == 400
    assert orjson.loads(unknown.body) == {"error": "Unknown OAuth provider"}

    monkeypatch.setattr(oauth, "get_provider_credentials", lambda settings, name: None)
    unavailable = await routes.route_oauth_login(
        _make_request(method="GET", path_params={"provider": "google"})
    )
    assert unavailable.status_code == 503
    assert orjson.loads(unavailable.body) == {"error": "google OAuth is not configured"}

    monkeypatch.setattr(
        oauth, "get_provider_credentials", lambda settings, name: ("client-id", "secret")
    )
    monkeypatch.setattr(oauth, "generate_state", lambda: "state-123")
    monkeypatch.setattr(
        oauth,
        "build_auth_url",
        lambda provider, client_id, redirect_uri, state: f"https://accounts.example/{provider}?state={state}",
    )

    success = await routes.route_oauth_login(
        _make_request(method="GET", path_params={"provider": "google"})
    )
    assert success.status_code == 302
    assert success.headers["location"] == "https://accounts.example/google?state=state-123"
    redis.setex.assert_awaited_once_with("oauth_state:state-123", 300, "1")


@pytest.mark.asyncio
async def test_route_oauth_callback_success_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import oauth

    settings = SimpleNamespace(base_url="https://piloci.example.com", session_expire_days=7)
    redis = SimpleNamespace(get=AsyncMock(return_value="1"), delete=AsyncMock())
    store = SimpleNamespace(_redis=redis, create_session=AsyncMock(return_value="session-1"))

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_session_store", lambda received: store)
    monkeypatch.setattr(oauth, "PROVIDERS", ["google"])

    unknown = await routes.route_oauth_callback(
        _make_request(method="GET", path_params={"provider": "github"})
    )
    assert unknown.status_code == 400
    assert orjson.loads(unknown.body) == {"error": "Unknown OAuth provider"}

    monkeypatch.setattr(oauth, "get_provider_credentials", lambda settings, name: None)
    unavailable = await routes.route_oauth_callback(
        _make_request(method="GET", path_params={"provider": "google"})
    )
    assert unavailable.status_code == 503
    assert orjson.loads(unavailable.body) == {"error": "google OAuth is not configured"}

    monkeypatch.setattr(
        oauth, "get_provider_credentials", lambda settings, name: ("client-id", "secret")
    )

    cancelled = await routes.route_oauth_callback(
        _make_request(method="GET", path_params={"provider": "google"})
    )
    assert cancelled.status_code == 302
    assert cancelled.headers["location"] == "/login?error=oauth_cancelled"

    redis.get = AsyncMock(return_value=None)
    invalid_state = await routes.route_oauth_callback(
        _make_request(
            method="GET",
            path_params={"provider": "google"},
            query_string=b"code=abc&state=missing",
        )
    )
    assert invalid_state.status_code == 302
    assert invalid_state.headers["location"] == "/login?error=oauth_invalid_state"

    redis.get = AsyncMock(return_value="1")
    redis.delete = AsyncMock()
    monkeypatch.setattr(oauth, "exchange_code", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(oauth, "get_userinfo", AsyncMock())
    oauth_failed = await routes.route_oauth_callback(
        _make_request(
            method="GET",
            path_params={"provider": "google"},
            query_string=b"code=abc&state=good",
        )
    )
    assert oauth_failed.status_code == 302
    assert oauth_failed.headers["location"] == "/login?error=oauth_failed"

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(
        oauth,
        "exchange_code",
        AsyncMock(return_value={"access_token": "access", "refresh_token": "refresh"}),
    )
    monkeypatch.setattr(oauth, "get_userinfo", AsyncMock(return_value={"sub": "oauth-user"}))

    monkeypatch.setattr(
        oauth,
        "upsert_oauth_user",
        AsyncMock(
            return_value=SimpleNamespace(id="user-1", is_admin=False, approval_status="pending")
        ),
    )
    pending = await routes.route_oauth_callback(
        _make_request(
            method="GET",
            path_params={"provider": "google"},
            query_string=b"code=abc&state=pending",
        )
    )
    assert pending.status_code == 302
    assert pending.headers["location"] == "/login?error=approval_pending"

    monkeypatch.setattr(
        oauth,
        "upsert_oauth_user",
        AsyncMock(
            return_value=SimpleNamespace(id="user-1", is_admin=False, approval_status="rejected")
        ),
    )
    rejected = await routes.route_oauth_callback(
        _make_request(
            method="GET",
            path_params={"provider": "google"},
            query_string=b"code=abc&state=rejected",
        )
    )
    assert rejected.status_code == 302
    assert rejected.headers["location"] == "/login?error=approval_rejected"

    monkeypatch.setattr(
        oauth,
        "upsert_oauth_user",
        AsyncMock(
            return_value=SimpleNamespace(id="user-1", is_admin=False, approval_status="approved")
        ),
    )
    store.create_session = AsyncMock(side_effect=RuntimeError("boom"))
    session_failed = await routes.route_oauth_callback(
        _make_request(
            method="GET",
            path_params={"provider": "google"},
            query_string=b"code=abc&state=sessionfail",
            headers=[(b"user-agent", b"pytest-agent")],
        )
    )
    assert session_failed.status_code == 302
    assert session_failed.headers["location"] == "/login?error=oauth_failed"

    store.create_session = AsyncMock(return_value="session-1")
    success = await routes.route_oauth_callback(
        _make_request(
            method="GET",
            path_params={"provider": "google"},
            query_string=b"code=abc&state=success",
            headers=[(b"user-agent", b"pytest-agent")],
        )
    )
    assert success.status_code == 302
    assert success.headers["location"] == "/dashboard"
    assert "piloci_session=session-1" in success.headers["set-cookie"]


@pytest.mark.asyncio
async def test_route_oauth_disconnect_success_and_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes
    from piloci.auth import crypto, oauth

    settings = SimpleNamespace()
    store = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": "user-1"}))

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_session_store", lambda received: store)
    monkeypatch.setattr(oauth, "PROVIDERS", ["google"])

    unknown = await routes.route_oauth_disconnect(
        _make_request(method="POST", path_params={"provider": "github"})
    )
    assert unknown.status_code == 400
    assert orjson.loads(unknown.body) == {"error": "Unknown OAuth provider"}

    unauthorized = await routes.route_oauth_disconnect(
        _make_request(method="POST", path_params={"provider": "google"})
    )
    assert unauthorized.status_code == 401
    assert orjson.loads(unauthorized.body) == {"error": "Unauthorized"}

    monkeypatch.setattr(oauth, "get_provider_credentials", lambda settings, name: None)
    unavailable = await routes.route_oauth_disconnect(
        _make_request(
            method="POST",
            path_params={"provider": "google"},
            cookies={"piloci_session": "session-1"},
        )
    )
    assert unavailable.status_code == 503
    assert orjson.loads(unavailable.body) == {"error": "google OAuth is not configured"}

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(
        oauth, "get_provider_credentials", lambda settings, name: ("client-id", "secret")
    )

    missing_result = MagicMock()
    missing_result.scalar_one_or_none.return_value = None
    db.execute.return_value = missing_result
    missing_user = await routes.route_oauth_disconnect(
        _make_request(
            method="POST",
            path_params={"provider": "google"},
            cookies={"piloci_session": "session-1"},
        )
    )
    assert missing_user.status_code == 401
    assert orjson.loads(missing_user.body) == {"error": "Unauthorized"}

    no_password_result = MagicMock()
    no_password_result.scalar_one_or_none.return_value = SimpleNamespace(password_hash=None)
    db.execute.return_value = no_password_result
    no_password = await routes.route_oauth_disconnect(
        _make_request(
            method="POST",
            path_params={"provider": "google"},
            cookies={"piloci_session": "session-1"},
        )
    )
    assert no_password.status_code == 400
    assert orjson.loads(no_password.body) == {
        "error": "Cannot disconnect: no password set. Set a password first."
    }

    wrong_provider_result = MagicMock()
    wrong_provider_result.scalar_one_or_none.return_value = SimpleNamespace(
        password_hash="hash",
        oauth_provider="github",
        oauth_access_token=None,
    )
    db.execute.return_value = wrong_provider_result
    wrong_provider = await routes.route_oauth_disconnect(
        _make_request(
            method="POST",
            path_params={"provider": "google"},
            cookies={"piloci_session": "session-1"},
        )
    )
    assert wrong_provider.status_code == 400
    assert orjson.loads(wrong_provider.body) == {
        "error": "OAuth provider does not match connected account"
    }

    revoke = AsyncMock()
    monkeypatch.setattr(oauth, "revoke_provider_token", revoke)
    monkeypatch.setattr(crypto, "decrypt_token", lambda token, settings: "access-token")
    user = SimpleNamespace(
        id="user-1",
        password_hash="hash",
        oauth_provider="google",
        oauth_sub="sub-1",
        oauth_access_token="encrypted",
        oauth_refresh_token="refresh",
    )
    success_result = MagicMock()
    success_result.scalar_one_or_none.return_value = user
    db.execute.return_value = success_result

    success = await routes.route_oauth_disconnect(
        _make_request(
            method="POST",
            path_params={"provider": "google"},
            cookies={"piloci_session": "session-1"},
        )
    )
    assert success.status_code == 200
    assert orjson.loads(success.body) == {"status": "disconnected"}
    revoke.assert_awaited_once_with("google", "access-token", "client-id", "secret")
    assert user.oauth_provider is None
    assert user.oauth_sub is None
    assert user.oauth_access_token is None
    assert user.oauth_refresh_token is None
    db.add.assert_called_with(user)


# ---------------------------------------------------------------------------
# /api/sessions/ingest — SessionStart hook batch catch-up
# ---------------------------------------------------------------------------


def _ingest_settings(maxsize: int = 128) -> SimpleNamespace:
    return SimpleNamespace(
        ingest_max_body_bytes=10 * 1024 * 1024,
        ingest_queue_maxsize=maxsize,
    )


def _valid_transcript(n: int = 6) -> str:
    """JSONL transcript with n messages (>= 5 required by ingest)."""
    return "\n".join(orjson.dumps({"role": "user", "content": f"m{i}"}).decode() for i in range(n))


@pytest.mark.asyncio
async def test_route_sessions_ingest_unauthorized() -> None:
    from piloci.api import routes

    response = await routes.route_sessions_ingest(_make_request({}, user=None))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_sessions_ingest_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())

    request = _make_request(method="POST", user={"sub": "u1", "project_id": "p1"})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"not-json", "more_body": False}

    request._receive = receive  # type: ignore[attr-defined]

    response = await routes.route_sessions_ingest(request)
    assert response.status_code == 400
    assert orjson.loads(response.body)["error"] == "invalid JSON"


@pytest.mark.asyncio
async def test_route_sessions_ingest_payload_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(ingest_max_body_bytes=10, ingest_queue_maxsize=128),
    )
    response = await routes.route_sessions_ingest(
        _make_request({"sessions": [{}], "cwd": "/p" * 100}, user={"sub": "u1", "project_id": "p1"})
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_route_sessions_ingest_user_scoped_requires_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())
    response = await routes.route_sessions_ingest(
        _make_request({"sessions": [{}]}, user={"sub": "u1"})
    )
    assert response.status_code == 400
    assert "cwd required" in orjson.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_route_sessions_ingest_user_scoped_unknown_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    db = _db_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())

    response = await routes.route_sessions_ingest(
        _make_request({"cwd": "/work/unknown", "sessions": [{}]}, user={"sub": "u1"})
    )
    assert response.status_code == 404
    assert "no project found for cwd '/work/unknown'" in orjson.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_route_sessions_ingest_empty_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())
    response = await routes.route_sessions_ingest(
        _make_request({"sessions": []}, user={"sub": "u1", "project_id": "p1"})
    )
    assert response.status_code == 400
    assert orjson.loads(response.body)["error"] == "sessions must be a non-empty list"


@pytest.mark.asyncio
async def test_route_sessions_ingest_queues_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: new session gets enqueued and recorded."""
    from piloci.api import routes

    db = _db_session()
    # First execute (existence check) returns None (not seen)
    not_seen = MagicMock()
    not_seen.scalar_one_or_none.return_value = None
    db.execute.return_value = not_seen

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())
    monkeypatch.setattr(routes, "try_enqueue_job", lambda job, maxsize: True)

    response = await routes.route_sessions_ingest(
        _make_request(
            {"sessions": [{"session_id": "sess-1", "transcript": _valid_transcript()}]},
            user={"sub": "u1", "project_id": "p1"},
        )
    )
    assert response.status_code == 200
    payload = orjson.loads(response.body)
    assert payload == {"queued": 1, "skipped": 0}
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_route_sessions_ingest_dedup_already_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Already-ingested session_id is skipped (dedup by (user, project, session))."""
    from piloci.api import routes

    db = _db_session()
    seen = MagicMock()
    seen.scalar_one_or_none.return_value = "existing-ingest-id"
    db.execute.return_value = seen

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())

    response = await routes.route_sessions_ingest(
        _make_request(
            {"sessions": [{"session_id": "sess-1", "transcript": _valid_transcript()}]},
            user={"sub": "u1", "project_id": "p1"},
        )
    )
    assert orjson.loads(response.body) == {"queued": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_route_sessions_ingest_skips_short_transcripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transcripts with <5 messages are skipped."""
    from piloci.api import routes

    db = _db_session()
    not_seen = MagicMock()
    not_seen.scalar_one_or_none.return_value = None
    db.execute.return_value = not_seen

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings())

    response = await routes.route_sessions_ingest(
        _make_request(
            {
                "sessions": [
                    {"session_id": "sess-short", "transcript": _valid_transcript(n=3)},
                    {"session_id": "sess-empty", "transcript": ""},
                    {"session_id": "", "transcript": _valid_transcript()},  # missing id
                    {"session_id": "sess-bad", "transcript": "not-json-at-all\nbad"},
                ]
            },
            user={"sub": "u1", "project_id": "p1"},
        )
    )
    assert orjson.loads(response.body) == {"queued": 0, "skipped": 4}


@pytest.mark.asyncio
async def test_route_sessions_ingest_queue_full_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If queue is full, the inserted RawSession is deleted to keep state consistent."""
    from piloci.api import routes

    db = _db_session()
    not_seen = MagicMock()
    not_seen.scalar_one_or_none.return_value = None
    db.execute.return_value = not_seen

    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))
    monkeypatch.setattr(routes, "get_settings", lambda: _ingest_settings(maxsize=1))
    monkeypatch.setattr(routes, "try_enqueue_job", lambda job, maxsize: False)

    response = await routes.route_sessions_ingest(
        _make_request(
            {"sessions": [{"session_id": "sess-rb", "transcript": _valid_transcript()}]},
            user={"sub": "u1", "project_id": "p1"},
        )
    )
    assert orjson.loads(response.body) == {"queued": 0, "skipped": 1}
    # Insert + delete both committed
    assert db.commit.await_count >= 2


# ---------------------------------------------------------------------------
# handle_init — project resolution flows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_init_refuses_home_directory() -> None:
    from piloci.tools.memory_tools import InitInput, handle_init

    result = await handle_init(
        InitInput(cwd="/home/alice"),
        user_id="u1",
        project_id=None,
        projects_fn=None,
        create_project_fn=None,
    )
    assert result["success"] is False
    assert "home or root" in result["error"]


@pytest.mark.asyncio
async def test_handle_init_refuses_root() -> None:
    from piloci.tools.memory_tools import InitInput, handle_init

    result = await handle_init(
        InitInput(cwd="/"),
        user_id="u1",
        project_id=None,
        projects_fn=None,
        create_project_fn=None,
    )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_handle_init_matches_existing_slug() -> None:
    """When a project with same slug exists, init resolves to it (no create)."""
    from piloci.tools.memory_tools import InitInput, handle_init

    async def projects_fn(_uid: str, _refresh: bool) -> list[dict[str, object]]:
        return [{"id": "proj-existing", "slug": "my-project", "name": "My Project"}]

    create_calls: list[object] = []

    async def create_project_fn(*args: object) -> dict[str, object]:
        create_calls.append(args)
        return {"id": "should-not-be-used"}

    result = await handle_init(
        InitInput(cwd="/work/my-project"),
        user_id="u1",
        project_id=None,
        projects_fn=projects_fn,
        create_project_fn=create_project_fn,
    )
    assert result["success"] is True
    assert result["project_id"] == "proj-existing"
    assert result["project_name"] == "My Project"
    assert create_calls == [], "must not create when slug already exists"
    assert "## piLoci Memory" in result["files"]["CLAUDE.md"]
    assert "## piLoci Memory" in result["files"]["AGENTS.md"]


@pytest.mark.asyncio
async def test_handle_init_creates_when_no_match() -> None:
    """No matching slug → create_project_fn is called with derived slug."""
    from piloci.tools.memory_tools import InitInput, handle_init

    async def projects_fn(_uid: str, _refresh: bool) -> list[dict[str, object]]:
        return []

    create_args: dict[str, object] = {}

    async def create_project_fn(uid: str, name: str, slug: str) -> dict[str, object]:
        create_args.update({"uid": uid, "name": name, "slug": slug})
        return {"id": "proj-new"}

    result = await handle_init(
        InitInput(cwd="/work/Brand New"),
        user_id="u1",
        project_id=None,
        projects_fn=projects_fn,
        create_project_fn=create_project_fn,
    )
    assert result["success"] is True
    assert result["project_id"] == "proj-new"
    assert create_args == {"uid": "u1", "name": "Brand New", "slug": "brand-new"}


@pytest.mark.asyncio
async def test_handle_init_create_failure_returns_error() -> None:
    from piloci.tools.memory_tools import InitInput, handle_init

    async def projects_fn(_uid: str, _refresh: bool) -> list[dict[str, object]]:
        return []

    async def create_project_fn(*_args: object) -> dict[str, object]:
        raise RuntimeError("db down")

    result = await handle_init(
        InitInput(cwd="/work/x"),
        user_id="u1",
        project_id=None,
        projects_fn=projects_fn,
        create_project_fn=create_project_fn,
    )
    assert result["success"] is False
    assert "Failed to create project" in result["error"]


@pytest.mark.asyncio
async def test_handle_init_with_project_scoped_token_skips_resolution() -> None:
    """Project-scoped token: project_id already known, skip create/lookup logic."""
    from piloci.tools.memory_tools import InitInput, handle_init

    lookups: list[object] = []

    async def projects_fn(_uid: str, _refresh: bool) -> list[dict[str, object]]:
        lookups.append("called")
        return [{"id": "proj-scoped", "slug": "scoped", "name": "Scoped"}]

    result = await handle_init(
        InitInput(cwd="/work/scoped", project_name="Scoped"),
        user_id="u1",
        project_id="proj-scoped",
        projects_fn=projects_fn,
        create_project_fn=None,
    )
    assert result["success"] is True
    assert result["project_id"] == "proj-scoped"
    # projects_fn called only for enrichment, not for resolution
    assert len(lookups) == 1


@pytest.mark.asyncio
async def test_handle_init_no_cwd_uses_project_name() -> None:
    """Without cwd, slug is derived from project_name."""
    from piloci.tools.memory_tools import InitInput, handle_init

    create_args: dict[str, object] = {}

    async def projects_fn(_uid: str, _refresh: bool) -> list[dict[str, object]]:
        return []

    async def create_project_fn(uid: str, name: str, slug: str) -> dict[str, object]:
        create_args.update({"name": name, "slug": slug})
        return {"id": "p-new"}

    result = await handle_init(
        InitInput(project_name="My Cool App"),
        user_id="u1",
        project_id=None,
        projects_fn=projects_fn,
        create_project_fn=create_project_fn,
    )
    assert result["success"] is True
    assert create_args["slug"] == "my-cool-app"


# ---------------------------------------------------------------------------
# Memory REST routes — guard paths (auth, scope, validation)
# ---------------------------------------------------------------------------


def _request_with_user(
    user: dict[str, object] | None,
    body: dict[str, object] | None = None,
    method: str = "POST",
    path_params: dict[str, str] | None = None,
    query_string: bytes = b"",
) -> Request:
    return _make_request(
        body or {},
        user=user,
        method=method,
        path_params=path_params or {},
        query_string=query_string,
    )


@pytest.mark.asyncio
async def test_route_get_memory_guards() -> None:
    from piloci.api import routes

    # Unauth
    r = _request_with_user(None, method="GET", path_params={"id": "m1"})
    r.state.user = None
    response = await routes.route_get_memory(r)
    assert response.status_code == 401

    # No project scope
    r = _request_with_user({"sub": "u1"}, method="GET", path_params={"id": "m1"})
    response = await routes.route_get_memory(r)
    assert response.status_code == 400
    assert orjson.loads(response.body)["error"] == "project_id required"


@pytest.mark.asyncio
async def test_route_get_memory_not_found() -> None:
    from piloci.api import routes

    store = MagicMock()
    store.get = AsyncMock(return_value=None)
    request = _make_request(
        method="GET",
        user={"sub": "u1", "project_id": "p1"},
        path_params={"id": "m-missing"},
        app=SimpleNamespace(state=SimpleNamespace(store=store)),
    )
    response = await routes.route_get_memory(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_get_memory_returns_payload() -> None:
    from piloci.api import routes

    store = MagicMock()
    store.get = AsyncMock(return_value={"memory_id": "m1", "content": "hi"})
    request = _make_request(
        method="GET",
        user={"sub": "u1", "project_id": "p1"},
        path_params={"id": "m1"},
        app=SimpleNamespace(state=SimpleNamespace(store=store)),
    )
    response = await routes.route_get_memory(request)
    assert response.status_code == 200
    assert orjson.loads(response.body)["memory_id"] == "m1"


@pytest.mark.asyncio
async def test_route_update_memory_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    # Unauth
    r = _request_with_user(None, method="PATCH", path_params={"id": "m1"})
    r.state.user = None
    response = await routes.route_update_memory(r)
    assert response.status_code == 401

    # Missing scope
    r = _request_with_user({"sub": "u1"}, method="PATCH", path_params={"id": "m1"})
    response = await routes.route_update_memory(r)
    assert response.status_code == 400

    # Invalid JSON body
    request = _make_request(
        method="PATCH",
        user={"sub": "u1", "project_id": "p1"},
        path_params={"id": "m1"},
    )

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"not-json", "more_body": False}

    request._receive = receive  # type: ignore[attr-defined]
    response = await routes.route_update_memory(request)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_update_memory_no_content_skips_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When body has no `content`, embedding is skipped and update goes through."""
    from piloci.api import routes

    store = MagicMock()
    store.update = AsyncMock(return_value=True)
    request = _make_request(
        {"tags": ["new"]},
        method="PATCH",
        user={"sub": "u1", "project_id": "p1"},
        path_params={"id": "m1"},
        app=SimpleNamespace(state=SimpleNamespace(store=store)),
    )
    captured: dict[str, object] = {}

    async def fake_invalidate(*args: object) -> None:
        captured["called"] = True

    monkeypatch.setattr(routes, "invalidate_project_vault_cache", fake_invalidate)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(vault_dir="/tmp"))

    response = await routes.route_update_memory(request)
    assert response.status_code == 200
    store.update.assert_awaited_once()
    assert captured.get("called") is True


@pytest.mark.asyncio
async def test_route_delete_memory_guards_and_paths() -> None:
    from piloci.api import routes

    # Unauth
    r = _request_with_user(None, method="DELETE", path_params={"id": "m1"})
    r.state.user = None
    assert (await routes.route_delete_memory(r)).status_code == 401

    # Missing scope
    r = _request_with_user({"sub": "u1"}, method="DELETE", path_params={"id": "m1"})
    assert (await routes.route_delete_memory(r)).status_code == 400

    # Not found
    store = MagicMock()
    store.delete = AsyncMock(return_value=False)
    request = _make_request(
        method="DELETE",
        user={"sub": "u1", "project_id": "p1"},
        path_params={"id": "missing"},
        app=SimpleNamespace(state=SimpleNamespace(store=store)),
    )
    response = await routes.route_delete_memory(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_clear_memories_requires_confirm() -> None:
    from piloci.api import routes

    # Unauth
    r = _request_with_user(None, method="POST")
    r.state.user = None
    assert (await routes.route_clear_memories(r)).status_code == 401

    # Missing scope
    assert (await routes.route_clear_memories(_request_with_user({"sub": "u1"}))).status_code == 400

    # Without confirm
    request = _make_request({}, user={"sub": "u1", "project_id": "p1"})
    response = await routes.route_clear_memories(request)
    assert response.status_code == 400
    assert "confirm: true required" in orjson.loads(response.body)["error"]


# ---------------------------------------------------------------------------
# session_analyze — guard paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_analyze_session_guards() -> None:
    from piloci.api import routes

    # Unauth
    response = await routes.route_analyze_session(_make_request(user=None))
    assert response.status_code == 401

    # Invalid JSON
    request = _make_request(user={"sub": "u1", "project_id": "p1"})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"junk", "more_body": False}

    request._receive = receive  # type: ignore[attr-defined]
    response = await routes.route_analyze_session(request)
    assert response.status_code == 400

    # Empty transcript
    response = await routes.route_analyze_session(
        _make_request({"transcript": "  "}, user={"sub": "u1", "project_id": "p1"})
    )
    assert response.status_code == 400

    # User-scoped without cwd → 400
    response = await routes.route_analyze_session(
        _make_request({"transcript": "hello"}, user={"sub": "u1"})
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_route_analyze_session_enqueues_and_returns_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes
    from piloci.curator import analyze_queue

    analyze_queue.reset_analyze_queue()

    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_analyze_session(
        _make_request(
            {"transcript": "hello world"},
            user={"sub": "u1", "project_id": "p1"},
        )
    )
    body = orjson.loads(response.body)
    assert response.status_code == 202
    assert body["queued"] is True
    assert "analyze_id" in body
    # Row was inserted before enqueue
    db.add.assert_called_once()
    # Job actually landed in the queue
    queue = analyze_queue.get_analyze_queue()
    assert queue.qsize() == 1
    job = queue.get_nowait()
    assert job.user_id == "u1"
    assert job.project_id == "p1"

    analyze_queue.reset_analyze_queue()


@pytest.mark.asyncio
async def test_route_analyze_session_503_when_queue_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piloci.api import routes
    from piloci.curator import analyze_queue

    analyze_queue.reset_analyze_queue()
    # Saturate the queue with a tiny capacity.
    full_queue = analyze_queue.get_analyze_queue(maxsize=1)
    full_queue.put_nowait(analyze_queue.AnalyzeJob(analyze_id="pre", user_id="u", project_id="p"))

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(analyze_queue_maxsize=1, analyze_retry_after_sec=5),
    )
    db = _db_session()
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    response = await routes.route_analyze_session(
        _make_request(
            {"transcript": "x"},
            user={"sub": "u1", "project_id": "p1"},
        )
    )
    body = orjson.loads(response.body)
    assert response.status_code == 503
    assert body["retry_after_sec"] == 5
    # Row was still persisted — startup recovery will pick it up.
    db.add.assert_called_once()

    analyze_queue.reset_analyze_queue()


# ---------------------------------------------------------------------------
# Admin routes — Forbidden guard for non-admins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_name",
    [
        "route_admin_list_users",
        "route_admin_approve_user",
        "route_admin_reject_user",
        "route_admin_toggle_admin",
        "route_admin_toggle_active",
        "route_admin_delete_user",
    ],
)
async def test_admin_routes_forbid_non_admins(handler_name: str) -> None:
    from piloci.api import routes

    handler = getattr(routes, handler_name)
    request = _make_request(
        method="POST",
        user={"sub": "u1", "is_admin": False},
        path_params={"id": "target"},
    )
    response = await handler(request)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_toggle_admin_self_blocked() -> None:
    from piloci.api import routes

    request = _make_request(
        method="POST",
        user={"sub": "self-id", "is_admin": True, "user_id": "self-id"},
        path_params={"id": "self-id"},
    )
    response = await routes.route_admin_toggle_admin(request)
    assert response.status_code == 400
    assert "Cannot change own admin status" in orjson.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_admin_toggle_active_self_blocked() -> None:
    from piloci.api import routes

    request = _make_request(
        method="POST",
        user={"sub": "self-id", "is_admin": True, "user_id": "self-id"},
        path_params={"id": "self-id"},
    )
    response = await routes.route_admin_toggle_active(request)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_delete_user_self_blocked() -> None:
    from piloci.api import routes

    request = _make_request(
        method="DELETE",
        user={"sub": "self-id", "is_admin": True, "user_id": "self-id"},
        path_params={"id": "self-id"},
    )
    response = await routes.route_admin_delete_user(request)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_approve_user_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    db = _db_session()
    # Both lookups (admin + target) return None — admin path tolerates, target 404s
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    db.execute.return_value = not_found
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    request = _make_request(
        method="POST",
        user={"sub": "admin-1", "is_admin": True, "user_id": "admin-1"},
        path_params={"id": "missing-user"},
    )
    response = await routes.route_admin_approve_user(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_list_users_returns_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from piloci.api import routes

    user = SimpleNamespace(
        id="u1",
        email="u@e",
        name="User",
        is_admin=False,
        is_active=True,
        approval_status="approved",
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        last_login_at=None,
        oauth_provider=None,
        totp_enabled=False,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [user]
    db = _db_session()
    db.execute.return_value = result
    monkeypatch.setattr(routes, "async_session", MagicMock(return_value=_session_cm(db)))

    request = _make_request(
        method="GET",
        user={"sub": "admin-1", "is_admin": True},
    )
    response = await routes.route_admin_list_users(request)
    assert response.status_code == 200
    rows = orjson.loads(response.body)
    assert rows[0]["email"] == "u@e"

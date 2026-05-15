from datetime import datetime
from types import SimpleNamespace

import orjson
import pytest

from piloci.api import distillation_routes


def _request(user=None):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_require_user_and_uid_helpers_handle_session_shapes() -> None:
    assert distillation_routes._require_user(_request()) is None
    assert distillation_routes._require_user(_request({"user_id": "user-1"})) == {
        "user_id": "user-1"
    }
    assert distillation_routes._uid({"user_id": "user-1", "id": "fallback"}) == "user-1"
    assert distillation_routes._uid({"id": 42}) == "42"
    assert distillation_routes._uid({}) == ""


def test_next_idle_window_returns_none_for_unset_or_invalid_specs() -> None:
    now = datetime(2026, 5, 15, 13, 0)

    assert distillation_routes._next_idle_window(now, None) is None
    assert distillation_routes._next_idle_window(now, "not-a-window") is None


def test_next_idle_window_uses_today_or_tomorrow_start() -> None:
    before_window = datetime(2026, 5, 15, 1, 30)
    after_window = datetime(2026, 5, 15, 4, 0)

    assert distillation_routes._next_idle_window(before_window, "02:00-03:00") == datetime(
        2026, 5, 15, 2, 0
    )
    assert distillation_routes._next_idle_window(after_window, "02:00-03:00") == datetime(
        2026, 5, 16, 2, 0
    )


@pytest.mark.asyncio
async def test_distillation_status_rejects_unauthenticated_request() -> None:
    response = await distillation_routes.route_distillation_status(_request())

    assert response.status_code == 401
    assert orjson.loads(response.body) == {"error": "unauthorized"}

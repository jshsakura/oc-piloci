from types import SimpleNamespace

import pytest

from piloci.curator import llm_providers


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement):
        return _ExecuteResult(self._rows)


def _settings(**overrides):
    data = {
        "external_llm_endpoint": None,
        "external_llm_model": None,
        "external_llm_api_key": None,
        "external_llm_label": "external",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _provider(**overrides):
    data = {
        "id": "provider-1",
        "name": "fast",
        "base_url": "https://llm.example.com/v1",
        "model": "gpt-test",
        "api_key_encrypted": "ciphertext",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_normalize_endpoint_accepts_common_openai_compatible_urls() -> None:
    assert (
        llm_providers._normalize_endpoint("https://llm.example.com/v1")
        == "https://llm.example.com/v1/chat/completions"
    )
    assert (
        llm_providers._normalize_endpoint("https://llm.example.com")
        == "https://llm.example.com/v1/chat/completions"
    )
    assert (
        llm_providers._normalize_endpoint("https://llm.example.com/v1/chat/completions/")
        == "https://llm.example.com/v1/chat/completions"
    )


@pytest.mark.asyncio
async def test_load_user_fallbacks_returns_user_providers_before_system_fallback(
    monkeypatch,
) -> None:
    rows = [
        _provider(name="primary", base_url="https://primary.example.com/v1"),
        _provider(name="secondary", base_url="https://secondary.example.com"),
    ]
    monkeypatch.setattr(llm_providers, "async_session", lambda: _Session(rows))
    monkeypatch.setattr(
        llm_providers,
        "get_settings",
        lambda: _settings(
            external_llm_endpoint="https://system.example.com/v1",
            external_llm_model="system-model",
            external_llm_api_key="system-key",
            external_llm_label="system",
        ),
    )
    monkeypatch.setattr(
        llm_providers,
        "decrypt_token",
        lambda ciphertext, settings: f"plain:{ciphertext}",
    )

    targets = await llm_providers.load_user_fallbacks("user-1")

    assert [target.label for target in targets] == [
        "provider:primary",
        "provider:secondary",
        "system",
    ]
    assert targets[0].endpoint == "https://primary.example.com/v1/chat/completions"
    assert targets[0].model == "gpt-test"
    assert targets[0].api_key == "plain:ciphertext"
    assert targets[1].endpoint == "https://secondary.example.com/v1/chat/completions"
    assert targets[2].endpoint == "https://system.example.com/v1/chat/completions"
    assert targets[2].model == "system-model"
    assert targets[2].api_key == "system-key"


@pytest.mark.asyncio
async def test_load_user_fallbacks_skips_provider_when_decrypt_fails(monkeypatch) -> None:
    rows = [
        _provider(id="bad", name="bad", api_key_encrypted="broken"),
        _provider(id="good", name="good", api_key_encrypted="ok"),
    ]
    monkeypatch.setattr(llm_providers, "async_session", lambda: _Session(rows))
    monkeypatch.setattr(llm_providers, "get_settings", lambda: _settings())

    def decrypt(ciphertext, settings):
        if ciphertext == "broken":
            raise ValueError("cannot decrypt")
        return "good-key"

    monkeypatch.setattr(llm_providers, "decrypt_token", decrypt)

    targets = await llm_providers.load_user_fallbacks("user-1")

    assert len(targets) == 1
    assert targets[0].label == "provider:good"
    assert targets[0].api_key == "good-key"


@pytest.mark.asyncio
async def test_load_user_fallbacks_omits_incomplete_system_fallback(monkeypatch) -> None:
    monkeypatch.setattr(llm_providers, "async_session", lambda: _Session([]))
    monkeypatch.setattr(
        llm_providers,
        "get_settings",
        lambda: _settings(
            external_llm_endpoint="https://system.example.com/v1",
            external_llm_model="system-model",
            external_llm_api_key=None,
        ),
    )

    targets = await llm_providers.load_user_fallbacks("user-1")

    assert targets == []

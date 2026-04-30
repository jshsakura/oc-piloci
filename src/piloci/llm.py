from __future__ import annotations

"""LLM provider abstraction.

Streaming chat over a provider-neutral interface. The route layer never
talks to a specific backend directly — it asks for a ``ChatProvider`` from
``get_chat_provider(settings)`` and iterates ``stream(messages)``.

Supported providers (selected via ``settings.chat_provider``):
- ``gemma_local``    — local llama-server (default, free, runs on Pi)
- ``openai_compat``  — any OpenAI-compatible endpoint (Groq, Together, vLLM, …)
- ``anthropic``      — Claude API (paid, fast, accurate)

Adding a new backend = one class implementing ``ChatProvider.stream`` and one
branch in ``get_chat_provider``. No call-site changes.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
import orjson

from piloci.curator.gemma import chat_stream as _local_gemma_stream

logger = logging.getLogger(__name__)


class ChatProvider(Protocol):
    """Streaming chat provider — yields text deltas.

    ``stream`` is implemented as an ``async def`` with ``yield`` (an async
    generator). Declared as a sync-returning method here because async
    generator functions return their iterator directly, not a coroutine.
    """

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]: ...


class LocalGemmaProvider:
    """Local llama-server via OpenAI-compatible endpoint."""

    def __init__(self, *, endpoint: str, model: str, timeout: float = 120.0) -> None:
        self._endpoint = endpoint
        self._model = model
        self._timeout = timeout

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        async for chunk in _local_gemma_stream(
            messages,
            endpoint=self._endpoint,
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._timeout,
        ):
            yield chunk


class OpenAICompatProvider:
    """Generic OpenAI-compatible streaming (Groq, Together, vLLM, OpenAI itself)."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not endpoint:
            raise ValueError("openai_compat provider requires endpoint")
        self._endpoint = endpoint.rstrip("/")
        if not self._endpoint.endswith("/chat/completions"):
            self._endpoint = f"{self._endpoint}/chat/completions"
        self._model = model
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._timeout = timeout

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", self._endpoint, json=payload, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if not body or body == "[DONE]":
                        continue
                    try:
                        chunk = orjson.loads(body)
                    except orjson.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    text = (choices[0].get("delta") or {}).get("content")
                    if text:
                        yield text


class AnthropicProvider:
    """Anthropic Messages API streaming."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        version: str = "2023-06-01",
    ) -> None:
        if not api_key:
            raise ValueError("anthropic provider requires api_key")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._version = version

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        # Anthropic separates `system` from `messages`; merge any system roles.
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": self._version,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if not body:
                        continue
                    try:
                        ev = orjson.loads(body)
                    except orjson.JSONDecodeError:
                        continue
                    if ev.get("type") == "content_block_delta":
                        delta = ev.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            text = delta.get("text")
                            if text:
                                yield text


def get_chat_provider(settings: Any) -> ChatProvider:
    """Resolve the chat provider from settings. Falls back to local Gemma.

    Reads ``settings.chat_provider`` (default ``"gemma_local"``) and any
    provider-specific config. Missing required config raises ``ValueError``
    so misconfigurations are visible at the request boundary.
    """
    provider = (getattr(settings, "chat_provider", None) or "gemma_local").lower()

    if provider == "gemma_local":
        return LocalGemmaProvider(
            endpoint=settings.gemma_endpoint,
            model=settings.gemma_model,
        )

    if provider == "openai_compat":
        endpoint = getattr(settings, "openai_compat_endpoint", None)
        if not endpoint:
            raise ValueError("openai_compat_endpoint required for chat_provider=openai_compat")
        return OpenAICompatProvider(
            endpoint=endpoint,
            model=getattr(settings, "openai_compat_model", "gpt-4o-mini"),
            api_key=getattr(settings, "openai_compat_api_key", None),
        )

    if provider == "anthropic":
        api_key = getattr(settings, "anthropic_api_key", None)
        if not api_key:
            raise ValueError("anthropic_api_key required for chat_provider=anthropic")
        return AnthropicProvider(
            api_key=api_key,
            model=getattr(settings, "anthropic_model", "claude-haiku-4-5"),
        )

    raise ValueError(f"unknown chat_provider: {provider}")

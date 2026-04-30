from __future__ import annotations

"""OpenAI-compatible HTTP client for local Gemma (llama-server on :9090)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import orjson

logger = logging.getLogger(__name__)

# Limit concurrent Gemma calls to protect Pi 5 CPU
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(1)
    return _semaphore


async def chat_json(
    messages: list[dict[str, str]],
    endpoint: str = "http://localhost:9090/v1/chat/completions",
    model: str = "gemma",
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: float = 120.0,
    retries: int = 3,
) -> dict[str, Any]:
    """Call Gemma and parse its response as JSON.

    Returns the parsed JSON object from the assistant reply.
    Raises ValueError on parse failure after all retries.
    """
    last_err: Exception | None = None
    async with _get_semaphore():
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(retries):
                try:
                    resp = await client.post(
                        endpoint,
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    # Gemma sometimes wraps in ```json ... ``` fences
                    text = text.strip()
                    if text.startswith("```"):
                        text = text.split("```", 2)[1]
                        if text.startswith("json"):
                            text = text[4:]
                        text = text.strip("`\n ")
                    return orjson.loads(text)
                except (httpx.HTTPError, orjson.JSONDecodeError, KeyError) as e:
                    last_err = e
                    logger.warning(
                        "Gemma call attempt %d/%d failed: %s",
                        attempt + 1,
                        retries,
                        e,
                    )
                    if attempt + 1 < retries:
                        await asyncio.sleep(2**attempt)
    raise ValueError(f"Gemma call failed after {retries} retries: {last_err}")


async def chat_stream(
    messages: list[dict[str, str]],
    endpoint: str = "http://localhost:9090/v1/chat/completions",
    model: str = "gemma",
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """Stream Gemma response as plain-text token chunks.

    Yields content deltas from the OpenAI-compatible streaming response.
    Skips control chunks ([DONE], non-content deltas). Honors the same
    semaphore as ``chat_json`` so streaming and JSON calls do not contend.
    """
    async with _get_semaphore():
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                endpoint,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = orjson.loads(payload)
                    except orjson.JSONDecodeError:
                        logger.debug("ignoring malformed stream chunk: %s", payload[:80])
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield text

from __future__ import annotations

"""OpenAI-compatible HTTP client for local Gemma (llama-server on :9090).

Supports a fallback chain: primary endpoint first, then any number of
OpenAI-compatible external providers (e.g. Z.AI, OpenAI, Together) supplied
by the caller. Used by curator workers so that when Gemma's single CPU slot
is saturated they can spill over to a hosted provider instead of stalling.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import orjson

logger = logging.getLogger(__name__)

# Limit concurrent Gemma calls to protect Pi 5 CPU. Only applies to the local
# (no-auth) endpoint — external providers don't share the slot.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(1)
    return _semaphore


@dataclass
class ProviderTarget:
    """One endpoint to try in the fallback chain."""

    endpoint: str
    model: str
    api_key: str | None = None  # Bearer auth for external OpenAI-compatible APIs
    label: str = "primary"  # for logging


async def _call_one(
    target: ProviderTarget,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    """Run the existing retry loop against a single provider target."""
    last_err: Exception | None = None
    headers = {}
    if target.api_key:
        headers["Authorization"] = f"Bearer {target.api_key}"

    # Local Gemma: hold the CPU semaphore. External providers: don't —
    # otherwise primary failures still serialize on the Pi 5 slot.
    use_semaphore = not target.api_key

    async def _do() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(retries):
                try:
                    resp = await client.post(
                        target.endpoint,
                        json={
                            "model": target.model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "response_format": {"type": "json_object"},
                        },
                        headers=headers or None,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    text = text.strip()
                    if text.startswith("```"):
                        text = text.split("```", 2)[1]
                        if text.startswith("json"):
                            text = text[4:]
                        text = text.strip("`\n ")
                    return orjson.loads(text)
                except (httpx.HTTPError, orjson.JSONDecodeError, KeyError) as exc:
                    nonlocal last_err
                    last_err = exc
                    logger.warning(
                        "%s call attempt %d/%d failed: %s",
                        target.label,
                        attempt + 1,
                        retries,
                        exc,
                    )
                    if attempt + 1 < retries:
                        await asyncio.sleep(2**attempt)
        raise ValueError(f"{target.label} failed after {retries} retries: {last_err}")

    if use_semaphore:
        async with _get_semaphore():
            return await _do()
    return await _do()


async def chat_json(
    messages: list[dict[str, str]],
    endpoint: str = "http://localhost:9090/v1/chat/completions",
    model: str = "gemma",
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: float = 120.0,
    retries: int = 3,
    fallbacks: list[ProviderTarget] | None = None,
    targets: list[ProviderTarget] | None = None,
    record_target: list[str] | None = None,
) -> dict[str, Any]:
    """Call the primary LLM and parse its response as JSON; cascade to fallbacks.

    The primary defaults to local Gemma. ``fallbacks`` are tried in the order
    given when the primary exhausts its retries (or any fallback fails). The
    first successful call wins. Each target gets its own retry budget.

    ``targets`` overrides the (primary + fallbacks) construction entirely —
    pass an explicit ordered chain when overflow scheduling needs to put an
    external provider first or skip the local endpoint.

    Raises ValueError when every target has been exhausted.
    """
    if targets is None:
        targets = [ProviderTarget(endpoint=endpoint, model=model, label="primary")]
        if fallbacks:
            targets.extend(fallbacks)
    if not targets:
        raise ValueError("chat_json: no providers to call")

    last_err: Exception | None = None
    for target in targets:
        try:
            result = await _call_one(
                target,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                retries=retries,
            )
            if record_target is not None:
                record_target.append(target.label)
            return result
        except Exception as exc:
            last_err = exc
            logger.warning("LLM target %s exhausted: %s", target.label, exc)
            continue
    raise ValueError(f"All LLM targets failed: {last_err}")


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

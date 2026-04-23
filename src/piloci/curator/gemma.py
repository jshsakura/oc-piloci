from __future__ import annotations
"""OpenAI-compatible HTTP client for local Gemma (llama-server on :9090)."""

import asyncio
import json
import logging
from typing import Any

import httpx

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
                    return json.loads(text)
                except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                    last_err = e
                    logger.warning(
                        "Gemma call attempt %d/%d failed: %s",
                        attempt + 1, retries, e,
                    )
                    if attempt + 1 < retries:
                        await asyncio.sleep(2 ** attempt)
    raise ValueError(f"Gemma call failed after {retries} retries: {last_err}")

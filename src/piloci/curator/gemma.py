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


class TruncatedResponseError(Exception):
    """The model stopped because it hit ``max_tokens`` (finish_reason ==
    'length'). Only raised when the caller opts in via ``raise_on_truncation``
    so it can retry with a larger budget instead of silently using a cut-off
    (and often unparseable) response."""


async def _call_one(
    target: ProviderTarget,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
    retries: int,
    raise_on_truncation: bool = False,
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
                    choice = data["choices"][0]
                    # Detect a length-capped response BEFORE parsing: a cut-off
                    # JSON usually won't parse anyway, and retrying at the same
                    # size is pointless. Surfacing it lets chat_json retry with
                    # a bigger budget. Opt-in so other callers keep prior behavior.
                    if raise_on_truncation and choice.get("finish_reason") == "length":
                        raise TruncatedResponseError(f"{target.label}: hit max_tokens={max_tokens}")
                    text = choice["message"]["content"]
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
    expand_on_truncation: int = 0,
    truncation_ceiling: int = 24000,
) -> dict[str, Any]:
    """Call the primary LLM and parse its response as JSON; cascade to fallbacks.

    The primary defaults to local Gemma. ``fallbacks`` are tried in the order
    given when the primary exhausts its retries (or any fallback fails). The
    first successful call wins. Each target gets its own retry budget.

    ``targets`` overrides the (primary + fallbacks) construction entirely —
    pass an explicit ordered chain when overflow scheduling needs to put an
    external provider first or skip the local endpoint.

    ``expand_on_truncation`` > 0 opts into output-truncation healing: if a
    target stops at ``max_tokens`` (finish_reason == 'length'), retry the *same*
    target with the budget doubled (capped at ``truncation_ceiling``), up to
    this many times, before giving up on it. Default 0 keeps prior behavior for
    all other callers.

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
        current_max = max_tokens
        expansions = 0
        while True:
            try:
                result = await _call_one(
                    target,
                    messages,
                    temperature=temperature,
                    max_tokens=current_max,
                    timeout=timeout,
                    retries=retries,
                    raise_on_truncation=expand_on_truncation > 0,
                )
                if record_target is not None:
                    record_target.append(target.label)
                return result
            except TruncatedResponseError as exc:
                last_err = exc
                if expansions < expand_on_truncation and current_max < truncation_ceiling:
                    expansions += 1
                    current_max = min(current_max * 2, truncation_ceiling)
                    logger.warning(
                        "%s output truncated; expanding max_tokens to %d and retrying",
                        target.label,
                        current_max,
                    )
                    continue
                logger.warning("%s output truncated; budget exhausted", target.label)
                break
            except Exception as exc:
                last_err = exc
                logger.warning("LLM target %s exhausted: %s", target.label, exc)
                break
    raise ValueError(f"All LLM targets failed: {last_err}")


async def _call_one_text(
    target: ProviderTarget,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
    retries: int,
) -> tuple[str, str | None]:
    """Like ``_call_one`` but for free-form text (no ``response_format``). Returns
    ``(content, finish_reason)`` so the caller can detect length-capped output
    and continue it."""
    last_err: Exception | None = None
    headers = {}
    if target.api_key:
        headers["Authorization"] = f"Bearer {target.api_key}"
    use_semaphore = not target.api_key

    async def _do() -> tuple[str, str | None]:
        nonlocal last_err
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
                        },
                        headers=headers or None,
                    )
                    resp.raise_for_status()
                    choice = resp.json()["choices"][0]
                    return (choice["message"]["content"] or "", choice.get("finish_reason"))
                except (httpx.HTTPError, KeyError) as exc:
                    last_err = exc
                    logger.warning(
                        "%s text attempt %d/%d failed: %s",
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


_CONTINUE_HINT = (
    "끊긴 지점부터 이어서 계속 작성하세요. 이미 쓴 내용을 반복하지 말고, "
    "새 인사말/머리말 없이 바로 이어쓰며, 글을 끝까지 완성하세요."
)


async def chat_text(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 4000,
    timeout: float = 180.0,
    retries: int = 2,
    targets: list[ProviderTarget],
    record_target: list[str] | None = None,
    max_continuations: int = 4,
) -> str:
    """Free-form text completion that NEVER silently truncates.

    Unlike ``chat_json`` (which packs the body into a JSON string the model may
    self-truncate to keep the JSON valid), this returns the raw assistant text.
    If the response stops at ``max_tokens`` (finish_reason == 'length') we feed
    the partial back and ask the model to continue, stitching up to
    ``max_continuations`` times — so an arbitrarily long article completes.
    """
    if not targets:
        raise ValueError("chat_text: no providers to call")
    last_err: Exception | None = None
    for target in targets:
        try:
            parts: list[str] = []
            convo = list(messages)
            for _ in range(max_continuations + 1):
                text, finish = await _call_one_text(
                    target,
                    convo,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    retries=retries,
                )
                parts.append(text)
                if finish != "length":
                    break
                convo = convo + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": _CONTINUE_HINT},
                ]
            if record_target is not None:
                record_target.append(target.label)
            return "".join(parts)
        except Exception as exc:
            last_err = exc
            logger.warning("chat_text target %s exhausted: %s", target.label, exc)
            continue
    raise ValueError(f"chat_text: all targets failed: {last_err}")


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

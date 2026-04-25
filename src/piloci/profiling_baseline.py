from __future__ import annotations

import argparse
import os
import time
from collections.abc import Sequence
from typing import Any

import httpx
import orjson
from dotenv import load_dotenv

DEFAULT_PATHS = ["/healthz", "/readyz", "/profilez"]
DEFAULT_ENDPOINT = "http://localhost:8314"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 2)
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[rank], 2)


def summarize_latencies(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        return {
            "count": 0,
            "last_ms": 0.0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
        }
    ordered = sorted(samples)
    return {
        "count": len(samples),
        "last_ms": round(samples[-1], 2),
        "avg_ms": round(sum(samples) / len(samples), 2),
        "p50_ms": _percentile(ordered, 0.50),
        "p95_ms": _percentile(ordered, 0.95),
        "max_ms": round(max(samples), 2),
    }


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    try:
        return {"json": response.json()}
    except ValueError:
        return {"text": response.text[:500]}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_paths() -> list[str]:
    raw = os.environ.get("PILOCI_PROFILE_BASELINE_PATHS")
    if not raw:
        return list(DEFAULT_PATHS)
    parsed = [part.strip() for part in raw.split(",") if part.strip()]
    return parsed or list(DEFAULT_PATHS)


def resolve_baseline_defaults() -> dict[str, Any]:
    load_dotenv()
    return {
        "endpoint": os.environ.get("PILOCI_PROFILE_BASELINE_ENDPOINT")
        or os.environ.get("PILOCI_ENDPOINT")
        or DEFAULT_ENDPOINT,
        "samples": _env_int("PILOCI_PROFILE_BASELINE_SAMPLES", 5),
        "timeout": _env_float("PILOCI_PROFILE_BASELINE_TIMEOUT", 5.0),
        "token": os.environ.get("PILOCI_PROFILE_BASELINE_TOKEN") or os.environ.get("PILOCI_TOKEN"),
        "paths": _env_paths(),
    }


def collect_baseline_with_client(
    client: httpx.Client,
    *,
    paths: Sequence[str],
    samples: int,
    token: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    results: list[dict[str, Any]] = []

    for path in paths:
        latencies: list[float] = []
        status_codes: list[int] = []
        last_payload: dict[str, Any] | None = None

        for _ in range(samples):
            started = time.perf_counter()
            response = client.get(path, headers=headers)
            latencies.append((time.perf_counter() - started) * 1000)
            status_codes.append(response.status_code)
            last_payload = _decode_response(response)

        results.append(
            {
                "path": path,
                "ok": all(200 <= code < 400 for code in status_codes),
                "status_codes": status_codes,
                "latency_ms": summarize_latencies(latencies),
                "last_response": last_payload,
            }
        )

    return {
        "endpoint": str(client.base_url).rstrip("/"),
        "samples_per_path": samples,
        "paths": list(paths),
        "results": results,
    }


def collect_baseline(
    endpoint: str,
    *,
    paths: Sequence[str] | None = None,
    samples: int = 5,
    timeout: float = 5.0,
    token: str | None = None,
) -> dict[str, Any]:
    selected_paths = list(paths or DEFAULT_PATHS)
    with httpx.Client(
        base_url=endpoint.rstrip("/"), timeout=timeout, follow_redirects=True
    ) as client:
        return collect_baseline_with_client(
            client,
            paths=selected_paths,
            samples=samples,
            token=token,
        )


def main(argv: Sequence[str] | None = None) -> int:
    defaults = resolve_baseline_defaults()
    parser = argparse.ArgumentParser(
        prog="piloci-profile-baseline",
        description="Collect an idle runtime baseline from piLoci health and profiling endpoints.",
    )
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--samples", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        default=None,
        help="Optional extra GET path to include. Defaults to /healthz,/readyz,/profilez.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = collect_baseline(
        args.endpoint or defaults["endpoint"],
        paths=args.paths or defaults["paths"],
        samples=args.samples or defaults["samples"],
        timeout=args.timeout or defaults["timeout"],
        token=args.token or defaults["token"],
    )
    print(orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode())
    return 0

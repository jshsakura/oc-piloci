from __future__ import annotations

import json
import httpx

from piloci import cli
from piloci.profiling_baseline import (
    collect_baseline_with_client,
    main,
    resolve_baseline_defaults,
    summarize_latencies,
)


def test_summarize_latencies_reports_expected_fields() -> None:
    summary = summarize_latencies([10.0, 20.0, 30.0])

    assert summary["count"] == 3
    assert summary["last_ms"] == 30.0
    assert summary["avg_ms"] == 20.0
    assert summary["p50_ms"] == 20.0
    assert summary["p95_ms"] == 30.0
    assert summary["max_ms"] == 30.0


def test_collect_baseline_with_client_collects_public_paths() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {"path": request.url.path}
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    with httpx.Client(base_url="http://testserver", transport=transport) as client:
        result = collect_baseline_with_client(
            client,
            paths=["/healthz", "/readyz", "/profilez"],
            samples=2,
        )

    assert result["endpoint"] == "http://testserver"
    assert result["samples_per_path"] == 2
    assert len(result["results"]) == 3
    assert all(entry["ok"] is True for entry in result["results"])
    assert result["results"][0]["status_codes"] == [200, 200]
    assert result["results"][2]["last_response"]["json"]["path"] == "/profilez"


def test_collect_baseline_with_client_passes_bearer_token() -> None:
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(base_url="http://testserver", transport=transport) as client:
        result = collect_baseline_with_client(
            client,
            paths=["/profilez"],
            samples=1,
            token="secret-token",
        )

    assert seen_auth == ["Bearer secret-token"]
    assert result["results"][0]["status_codes"] == [200]


def test_collect_baseline_with_client_marks_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/readyz":
            return httpx.Response(503, json={"status": "degraded"})
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(base_url="http://testserver", transport=transport) as client:
        result = collect_baseline_with_client(
            client,
            paths=["/healthz", "/readyz"],
            samples=1,
        )

    assert result["results"][0]["ok"] is True
    assert result["results"][1]["ok"] is False
    assert result["results"][1]["status_codes"] == [503]
    assert result["results"][1]["last_response"]["json"]["status"] == "degraded"


def test_resolve_baseline_defaults_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_ENDPOINT", "http://env-server:9999")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_SAMPLES", "9")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_TIMEOUT", "12.5")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_TOKEN", "env-token")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_PATHS", "/healthz,/profilez,/custom")

    defaults = resolve_baseline_defaults()

    assert defaults["endpoint"] == "http://env-server:9999"
    assert defaults["samples"] == 9
    assert defaults["timeout"] == 12.5
    assert defaults["token"] == "env-token"
    assert defaults["paths"] == ["/healthz", "/profilez", "/custom"]


def test_resolve_baseline_defaults_falls_back_to_shared_piloci_env(monkeypatch) -> None:
    monkeypatch.delenv("PILOCI_PROFILE_BASELINE_ENDPOINT", raising=False)
    monkeypatch.delenv("PILOCI_PROFILE_BASELINE_TOKEN", raising=False)
    monkeypatch.delenv("PILOCI_PROFILE_BASELINE_PATHS", raising=False)
    monkeypatch.setenv("PILOCI_ENDPOINT", "http://shared-server:8314")
    monkeypatch.setenv("PILOCI_TOKEN", "shared-token")

    defaults = resolve_baseline_defaults()

    assert defaults["endpoint"] == "http://shared-server:8314"
    assert defaults["token"] == "shared-token"
    assert defaults["paths"] == ["/healthz", "/readyz", "/profilez"]


def test_main_uses_env_defaults_when_flags_omitted(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_ENDPOINT", "http://env-server:8314")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_SAMPLES", "3")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_TIMEOUT", "7")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_TOKEN", "env-token")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_PATHS", "/healthz,/profilez")

    captured: dict[str, object] = {}

    def fake_collect_baseline(
        endpoint: str,
        *,
        paths: list[str],
        samples: int,
        timeout: float,
        token: str | None,
    ) -> dict[str, object]:
        captured.update(
            {
                "endpoint": endpoint,
                "paths": paths,
                "samples": samples,
                "timeout": timeout,
                "token": token,
            }
        )
        return {"ok": True}

    monkeypatch.setattr("piloci.profiling_baseline.collect_baseline", fake_collect_baseline)

    exit_code = main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert captured == {
        "endpoint": "http://env-server:8314",
        "paths": ["/healthz", "/profilez"],
        "samples": 3,
        "timeout": 7.0,
        "token": "env-token",
    }
    assert '"ok": true' in output.lower()


def test_cli_profile_baseline_uses_env_defaults(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_ENDPOINT", "http://env-cli:8314")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_SAMPLES", "4")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_TIMEOUT", "2.5")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_TOKEN", "env-cli-token")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_PATHS", "/healthz,/readyz")

    captured: dict[str, object] = {}

    def fake_collect_baseline(
        endpoint: str,
        *,
        paths: list[str],
        samples: int,
        timeout: float,
        token: str | None,
    ) -> dict[str, object]:
        captured.update(
            {
                "endpoint": endpoint,
                "paths": paths,
                "samples": samples,
                "timeout": timeout,
                "token": token,
            }
        )
        return {"ok": True}

    monkeypatch.setattr("piloci.profiling_baseline.collect_baseline", fake_collect_baseline)
    monkeypatch.setattr("sys.argv", ["piloci", "profile-baseline"])

    cli.main()

    assert captured == {
        "endpoint": "http://env-cli:8314",
        "paths": ["/healthz", "/readyz"],
        "samples": 4,
        "timeout": 2.5,
        "token": "env-cli-token",
    }
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_cli_profile_baseline_flags_override_env(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_ENDPOINT", "http://env-cli:8314")
    monkeypatch.setenv("PILOCI_PROFILE_BASELINE_SAMPLES", "4")

    captured: dict[str, object] = {}

    def fake_collect_baseline(
        endpoint: str,
        *,
        paths: list[str],
        samples: int,
        timeout: float,
        token: str | None,
    ) -> dict[str, object]:
        captured.update(
            {
                "endpoint": endpoint,
                "paths": paths,
                "samples": samples,
                "timeout": timeout,
                "token": token,
            }
        )
        return {"ok": True}

    monkeypatch.setattr("piloci.profiling_baseline.collect_baseline", fake_collect_baseline)
    monkeypatch.setattr(
        "sys.argv",
        [
            "piloci",
            "profile-baseline",
            "--endpoint",
            "http://flag-cli:8314",
            "--samples",
            "2",
            "--timeout",
            "9.0",
            "--token",
            "flag-token",
            "--path",
            "/profilez",
        ],
    )

    cli.main()

    assert captured == {
        "endpoint": "http://flag-cli:8314",
        "paths": ["/profilez"],
        "samples": 2,
        "timeout": 9.0,
        "token": "flag-token",
    }
    assert json.loads(capsys.readouterr().out) == {"ok": True}

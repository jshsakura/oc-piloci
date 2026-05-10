"""CLI entry point: `piloci` command."""

from __future__ import annotations

import argparse
import sys

import orjson
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="piloci",
        description="piLoci — self-hosted LLM memory service",
    )
    sub = parser.add_subparsers(dest="command")

    # serve command
    serve = sub.add_parser("serve", help="Start HTTP SSE server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")

    # stdio command (dev/testing)
    sub.add_parser("stdio", help="Run MCP server over stdio")

    # bootstrap command — create first admin user
    bootstrap = sub.add_parser("bootstrap", help="Create first admin user from env vars")
    bootstrap.add_argument("--email", default=None, help="Override ADMIN_EMAIL env var")
    bootstrap.add_argument("--password", default=None, help="Override ADMIN_PASSWORD env var")

    baseline = sub.add_parser(
        "profile-baseline", help="Collect idle runtime baseline via health endpoints"
    )
    baseline.add_argument("--endpoint", default=None)
    baseline.add_argument("--samples", type=int, default=None)
    baseline.add_argument("--timeout", type=float, default=None)
    baseline.add_argument("--token", default=None)
    baseline.add_argument(
        "--path",
        action="append",
        dest="paths",
        default=None,
        help="Optional GET path to include. Defaults to /healthz,/readyz,/profilez.",
    )

    login_p = sub.add_parser(
        "login",
        help="Pair this device via browser-based device flow (no token copy/paste).",
    )
    login_p.add_argument(
        "--server",
        default=None,
        help="piLoci server base URL (defaults to PILOCI_SERVER env or saved config).",
    )
    login_p.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the verification URL instead of opening a browser.",
    )

    install_p = sub.add_parser(
        "install",
        help="Configure detected Claude Code / OpenCode clients on this machine.",
    )
    install_p.add_argument(
        "url_or_code",
        nargs="?",
        default=None,
        help=(
            "One-time install URL (e.g. https://piloci.example.com/install/CODE). "
            "Omit to use the token already saved by ``piloci login``."
        ),
    )
    install_p.add_argument(
        "--server",
        default=None,
        help="piLoci server base URL (used when only a code is supplied, or to override).",
    )
    install_p.add_argument(
        "--token",
        default=None,
        help="Use this token directly instead of resolving an install URL.",
    )
    install_p.add_argument(
        "--force",
        action="store_true",
        help="Wipe the existing piloci plugin folder(s) and reinstall fresh.",
    )

    uninstall_p = sub.add_parser(
        "uninstall",
        help="Remove every piloci artifact (plugin folders, legacy hooks, config, backup).",
    )
    uninstall_p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )

    backfill_p = sub.add_parser(
        "backfill-cwd",
        help=(
            "Recover from the legacy slug-collision bug: parse raw_session "
            "transcripts, stamp Project.cwd, split misattributed sessions."
        ),
    )
    backfill_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing.",
    )
    backfill_p.add_argument(
        "--user-id",
        default=None,
        help="Restrict to a single user id.",
    )

    setup_p = sub.add_parser(
        "setup",
        help="``login`` followed by ``install`` — the recommended one-shot flow.",
    )
    setup_p.add_argument(
        "--server",
        default=None,
        help="piLoci server base URL (defaults to PILOCI_SERVER env).",
    )
    setup_p.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the verification URL instead of opening a browser.",
    )
    setup_p.add_argument(
        "--force",
        action="store_true",
        help="Wipe the existing piloci plugin folder(s) and reinstall fresh.",
    )

    args = parser.parse_args()

    if args.command == "stdio":
        from piloci.main import run_stdio

        run_stdio()
    elif args.command == "profile-baseline":
        from piloci.profiling_baseline import collect_baseline, resolve_baseline_defaults

        defaults = resolve_baseline_defaults()

        payload = collect_baseline(
            args.endpoint or defaults["endpoint"],
            paths=args.paths or defaults["paths"],
            samples=args.samples or defaults["samples"],
            timeout=args.timeout or defaults["timeout"],
            token=args.token or defaults["token"],
        )
        print(orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode())
    elif args.command == "bootstrap":
        _run_bootstrap(args)
    elif args.command == "login":
        _run_login(args)
    elif args.command == "install":
        _run_install(args)
    elif args.command == "uninstall":
        _run_uninstall(args)
    elif args.command == "setup":
        _run_setup(args)
    elif args.command == "backfill-cwd":
        _run_backfill_cwd(args)
    elif args.command == "serve":
        if args.host or args.port or args.reload:
            import os

            if args.host:
                os.environ["HOST"] = args.host
            if args.port:
                os.environ["PORT"] = str(args.port)
            if args.reload:
                os.environ["RELOAD"] = "true"
        from piloci.main import run_sse

        run_sse()
    else:
        parser.print_help()
        sys.exit(1)


def _run_bootstrap(args: argparse.Namespace) -> None:
    import asyncio
    import os
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from piloci.auth.password import hash_password
    from piloci.db.models import User
    from piloci.db.session import async_session, init_db

    async def _bootstrap() -> None:
        await init_db()

        async with async_session() as db:
            user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
            if user_count > 0:
                print(f"[bootstrap] {user_count} user(s) already exist — skipping admin creation")
                return

            email = args.email or os.environ.get("ADMIN_EMAIL", "").strip()
            password = args.password or os.environ.get("ADMIN_PASSWORD", "")

            if not email:
                print("[bootstrap] ERROR: ADMIN_EMAIL not set (env var or --email flag)")
                sys.exit(1)
            if len(password) < 8:
                print("[bootstrap] ERROR: ADMIN_PASSWORD must be at least 8 characters")
                sys.exit(1)

            now = datetime.now(timezone.utc)
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                name="Admin",
                password_hash=hash_password(password),
                is_admin=True,
                approval_status="approved",
                created_at=now,
            )
            db.add(user)
            await db.commit()
            print(f"[bootstrap] Admin user created: {email}")

    asyncio.run(_bootstrap())


# ---------------------------------------------------------------------------
# login / install / setup — Phase 2 device-flow CLI
# ---------------------------------------------------------------------------


def _resolve_server(arg_server: str | None) -> str:
    """Resolve the piLoci server URL from --server / env / saved config / prompt."""
    from piloci.installer import get_default_server

    candidate = arg_server or get_default_server()
    if candidate:
        return candidate.rstrip("/")

    # Interactive fallback — ask the user instead of exiting
    try:
        url = input("[piloci] 서버 URL을 입력하세요 (예: https://piloci.example.com): ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("\n[piloci] 취소됨\n")
        sys.exit(2)

    if not url:
        sys.stderr.write("[piloci] URL이 입력되지 않았습니다.\n")
        sys.exit(2)

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return url.rstrip("/")


def _device_login(server: str, *, open_browser: bool) -> tuple[str, list[str] | None]:
    """Run the device flow against ``server``.

    Returns ``(jwt_token, targets)`` where ``targets`` is the list of client
    kinds the user picked on the /device page (``["claude", "cursor", ...]``)
    or ``None`` when the server does not return a selection — in that case
    ``run_install`` falls back to local auto-detection so older servers keep
    working.
    """
    import json as _json
    import time
    import urllib.error
    import urllib.request

    server = server.rstrip("/")
    code_req = urllib.request.Request(
        server + "/auth/device/code",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json", "User-Agent": "piloci-cli"},
    )
    try:
        with urllib.request.urlopen(code_req, timeout=15) as resp:
            data = _json.loads(resp.read())
    except urllib.error.URLError as e:
        sys.stderr.write(f"[piloci] 서버 연결 실패: {e}\n")
        sys.exit(1)

    user_code = data["user_code"]
    device_code = data["device_code"]
    verification_uri = data["verification_uri"]
    verification_uri_complete = data.get("verification_uri_complete", verification_uri)
    interval = max(1, int(data.get("interval", 3)))
    expires_in = int(data.get("expires_in", 600))

    print(f"\n  브라우저: {verification_uri}")
    print(f"  인증 코드: {user_code}\n")
    print("  코드 입력 페이지가 열려 있으면 위 코드를 붙여넣고 승인하세요.")
    print(f"  ({expires_in // 60}분 안에 완료해 주세요)\n")

    if open_browser:
        try:
            import webbrowser

            opened = webbrowser.open(verification_uri_complete)
        except Exception:
            opened = False
        if opened:
            # Browser may cover the terminal — re-print so users don't miss the code.
            print(f"  브라우저: {verification_uri}")
            print(f"  인증 코드: {user_code}\n")

    deadline = time.time() + expires_in
    poll_body = _json.dumps({"device_code": device_code}).encode()
    while time.time() < deadline:
        time.sleep(interval)
        poll_req = urllib.request.Request(
            server + "/auth/device/poll",
            method="POST",
            data=poll_body,
            headers={"Content-Type": "application/json", "User-Agent": "piloci-cli"},
        )
        try:
            with urllib.request.urlopen(poll_req, timeout=10) as resp:
                payload = _json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 410:
                sys.stderr.write("[piloci] 인증 코드가 만료되었습니다.\n")
                sys.exit(1)
            sys.stderr.write(f"[piloci] 폴링 오류: {e}\n")
            sys.exit(1)
        except urllib.error.URLError:
            continue  # transient — keep polling

        status = payload.get("status")
        if status == "approved":
            token = payload.get("token")
            if not token:
                sys.stderr.write("[piloci] 승인됐으나 토큰이 비어있습니다.\n")
                sys.exit(1)
            raw_targets = payload.get("targets")
            targets: list[str] | None = None
            if isinstance(raw_targets, list):
                targets = [str(t) for t in raw_targets if isinstance(t, str)] or None
            print("  ✓ 승인됨")
            if targets:
                print(f"  ↳ 설치 대상: {', '.join(targets)}")
            return token, targets
        if status == "denied":
            sys.stderr.write("[piloci] 사용자가 승인을 거부했습니다.\n")
            sys.exit(1)

    sys.stderr.write("[piloci] 시간 초과 — 다시 시도해 주세요.\n")
    sys.exit(1)


def _run_login(args: argparse.Namespace) -> None:
    from piloci.installer import write_config_json

    server = _resolve_server(args.server)
    token, _targets = _device_login(server, open_browser=not args.no_browser)
    cfg = write_config_json(token, server)
    print(f"  ✓ 토큰 저장: {cfg}")


def _run_install(args: argparse.Namespace) -> None:
    from piloci.installer import (
        InstallReport,
        fetch_install_payload,
        get_default_server,
        run_install,
    )

    token: str | None = args.token
    base_url: str | None = args.server or get_default_server()

    target = args.url_or_code
    if target:
        # Treat as either full URL or bare code (in which case --server is required)
        if target.startswith(("http://", "https://")):
            install_url = target.rstrip("/")
        else:
            if not base_url:
                sys.stderr.write("[piloci] 코드만 주려면 --server 도 함께 지정해 주세요.\n")
                sys.exit(2)
            install_url = base_url.rstrip("/") + "/install/" + target
        try:
            payload = fetch_install_payload(install_url)
        except Exception as e:
            sys.stderr.write(f"[piloci] install URL 조회 실패: {e}\n")
            sys.exit(1)
        token = payload["token"]
        base_url = payload["base_url"]

    if not token:
        # Fall back to saved config.json (set by ``piloci login``).
        from pathlib import Path

        cfg_path = Path.home() / ".config" / "piloci" / "config.json"
        if cfg_path.exists():
            try:
                import json as _json

                cfg = _json.loads(cfg_path.read_text())
                token = cfg.get("token")
            except Exception:
                token = None

    if not token or not base_url:
        # No token saved — run the device login flow inline
        print("[piloci] 저장된 토큰이 없습니다. 브라우저 로그인 플로우를 시작합니다...\n")
        server = _resolve_server(args.server)
        token, targets = _device_login(server, open_browser=True)
        from piloci.installer import write_config_json

        write_config_json(token, server)
        base_url = server

    try:
        report: InstallReport = run_install(token, base_url, force=args.force)
    except RuntimeError as e:
        sys.stderr.write(f"[piloci] {e}\n")
        sys.exit(1)

    print(f"  ✓ config.json: {report.config_path}")
    if report.claude_configured:
        print("  ✓ Claude Code 훅 적용")
    if report.opencode_configured:
        print("  ✓ OpenCode MCP 등록")
    for note in report.notes:
        print(f"    · {note}")


def _run_uninstall(args: argparse.Namespace) -> None:
    from piloci.installer import run_uninstall

    if not args.yes:
        sys.stderr.write(
            "[piloci] piloci 관련 파일을 모두 제거합니다 "
            "(플러그인 폴더, 훅, ~/.config/piloci, settings 백업).\n"
            "         계속하려면 --yes 를 붙여 다시 실행해 주세요.\n"
        )
        sys.exit(2)

    removed = run_uninstall()
    if not removed:
        print("  (제거할 piloci 파일이 없습니다.)")
        return
    for item in removed:
        print(f"  ✓ 제거: {item}")


def _run_setup(args: argparse.Namespace) -> None:
    """One-shot: login + install. Honors the platform multi-select from /device."""
    from piloci.installer import run_install

    server = _resolve_server(args.server)
    token, targets = _device_login(server, open_browser=not args.no_browser)
    try:
        report = run_install(token, server, force=args.force, targets=targets)
    except RuntimeError as e:
        sys.stderr.write(f"[piloci] {e}\n")
        sys.exit(1)
    print(f"\n  ✓ config.json: {report.config_path}")
    if report.claude_configured:
        print("  ✓ Claude Code 훅 적용")
    if report.opencode_configured:
        print("  ✓ OpenCode MCP 등록")
    for note in report.notes:
        print(f"    · {note}")


def _run_backfill_cwd(args: argparse.Namespace) -> None:
    """Walk legacy projects and split misattributed sessions by transcript cwd."""
    import asyncio

    from piloci.ops.backfill import backfill_cwd

    report = asyncio.run(backfill_cwd(dry_run=args.dry_run, user_id=args.user_id))
    print(orjson.dumps(report, option=orjson.OPT_INDENT_2).decode())

    summary = (
        f"\n  examined={report['projects_examined']}  "
        f"stamped={report['projects_stamped']}  "
        f"split={report['projects_split']}  "
        f"new_projects={report['new_projects']}  "
        f"sessions_moved={report['sessions_moved']}"
    )
    if args.dry_run:
        summary += "  (dry-run — no changes written)"
    print(summary)


if __name__ == "__main__":
    main()

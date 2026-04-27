from __future__ import annotations

"""CLI entry point: `piloci` command."""

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


if __name__ == "__main__":
    main()

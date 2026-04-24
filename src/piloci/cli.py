from __future__ import annotations
"""CLI entry point: `piloci` command."""

import argparse
import json
import sys

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

    baseline = sub.add_parser("profile-baseline", help="Collect idle runtime baseline via health endpoints")
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
        print(json.dumps(payload, indent=2))
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


if __name__ == "__main__":
    main()

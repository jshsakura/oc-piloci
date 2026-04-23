from __future__ import annotations
"""CLI entry point: `piloci` command."""

import argparse
import sys


def main() -> None:
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

    args = parser.parse_args()

    if args.command == "stdio":
        from piloci.main import run_stdio
        run_stdio()
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

#!/usr/bin/env python3
"""piLoci launcher — kill existing and restart.

Usage:
  python run.py          # native backend only on :8314
  python run.py --dev    # docker (nginx:28314 + piloci:8314) + native pnpm dev(:3000)
  python run.py --down   # stop docker dev stack + pnpm dev
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent
LOG_DIR = ROOT / "logs"
BACKEND_PORT = 8314
FRONTEND_PORT = 3000
DEV_COMPOSE = "docker-compose.dev.yml"
PUBLIC_BASE_URL = os.environ.get("PILOCI_PUBLIC_URL", "")


def kill_on_port(port: int) -> None:
    result = subprocess.run(
        ["ss", "-Htlnp", f"sport = :{port}"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "pid=" in line:
            try:
                pid = int(line.split("pid=")[1].split(",")[0])
                os.kill(pid, 15)
                print(f"  stopped PID {pid} (:{port})")
                time.sleep(0.3)
            except (ProcessLookupError, ValueError):
                pass


def pkill(pattern: str) -> None:
    subprocess.run(["pkill", "-f", pattern], capture_output=True)


def compose(args: list[str]) -> None:
    subprocess.run(
        ["docker", "compose", "-f", DEV_COMPOSE, *args],
        cwd=ROOT, check=True,
    )


def dev_up() -> None:
    LOG_DIR.mkdir(exist_ok=True)

    # Stop existing
    print("[ dev ] stopping existing...")
    subprocess.run(["docker", "compose", "-f", DEV_COMPOSE, "down"], cwd=ROOT, capture_output=True)
    pkill("pnpm dev")
    pkill("next dev")
    kill_on_port(FRONTEND_PORT)
    time.sleep(1)

    # Docker: nginx + piloci + redis
    print("[ dev ] starting docker stack...")
    compose(["up", "-d", "--build"])

    # Native: pnpm dev
    web_dir = ROOT / "web"
    if not (web_dir / "node_modules").exists():
        print("[ dev ] pnpm install...")
        subprocess.run(["pnpm", "install"], cwd=web_dir, check=True)

    frontend_log = open(LOG_DIR / "frontend.log", "a")
    frontend = subprocess.Popen(
        ["pnpm", "dev", "--port", str(FRONTEND_PORT), "--hostname", "0.0.0.0"],
        cwd=web_dir,
        stdout=frontend_log,
        stderr=frontend_log,
    )
    print(f"[ dev ] pnpm dev  PID={frontend.pid}  :{FRONTEND_PORT}  → logs/frontend.log")
    print()
    print(f"  proxy    http://localhost:28314  (tunnel entry)")
    print(f"  backend  http://localhost:{BACKEND_PORT}  (direct)")
    print(f"  logs:    docker compose -f {DEV_COMPOSE} logs -f")


def dev_down() -> None:
    print("[ dev ] stopping...")
    subprocess.run(["docker", "compose", "-f", DEV_COMPOSE, "down"], cwd=ROOT, capture_output=True)
    pkill("pnpm dev")
    pkill("next dev")
    kill_on_port(FRONTEND_PORT)
    print("  done.")


def native_up() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    print("[ piloci ] stopping existing process...")
    kill_on_port(BACKEND_PORT)
    pkill("piloci serve")
    time.sleep(1)

    backend_log = open(LOG_DIR / "piloci.log", "a")
    backend = subprocess.Popen(
        ["uv", "run", "piloci", "serve"],
        cwd=ROOT,
        stdout=backend_log,
        stderr=backend_log,
    )
    print(f"[ piloci ] PID={backend.pid}  :{BACKEND_PORT}  → logs/piloci.log")
    print()
    print(f"  http://localhost:{BACKEND_PORT}")
    if PUBLIC_BASE_URL:
        print(f"  {PUBLIC_BASE_URL}")


def main() -> None:
    parser = argparse.ArgumentParser(description="piLoci launcher")
    parser.add_argument("--dev", action="store_true", help="docker stack + native pnpm dev")
    parser.add_argument("--down", action="store_true", help="stop dev stack")
    args = parser.parse_args()

    if args.down:
        dev_down()
    elif args.dev:
        dev_up()
    else:
        native_up()


if __name__ == "__main__":
    main()

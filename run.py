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
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent
LOG_DIR = ROOT / "logs"
STATIC_DIR = ROOT / "src" / "piloci" / "static"
WEB_OUT_DIR = ROOT / "web" / "out"
BACKEND_PORT = 8314
FRONTEND_PORT = 3000
DEV_COMPOSE = "docker-compose.dev.yml"
PROD_COMPOSE = "docker-compose.yml"
PUBLIC_BASE_URL = os.environ.get("PILOCI_PUBLIC_URL", "")


def kill_on_port(port: int) -> None:
    pids: set[int] = set()
    for _ in range(3):
        result = subprocess.run(
            ["ss", "-Htlnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
        )
        found = False
        for line in result.stdout.splitlines():
            for token in line.split("pid=")[1:]:
                try:
                    pid = int(token.split(",")[0].split(")")[0])
                    pids.add(pid)
                    found = True
                except (ValueError, IndexError):
                    pass
        if not found:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        pids.clear()
        time.sleep(0.5)


def wait_port_free(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["ss", "-Htlnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            return True
        time.sleep(0.3)
    return False


def pkill(pattern: str) -> None:
    subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)


def compose(args: list[str], compose_file: str = DEV_COMPOSE) -> None:
    subprocess.run(
        ["docker", "compose", "-f", compose_file, *args],
        cwd=ROOT,
        check=True,
    )


def dev_up() -> None:
    LOG_DIR.mkdir(exist_ok=True)

    print("[ dev ] stopping existing...")
    subprocess.run(
        ["docker", "compose", "-f", PROD_COMPOSE, "down"],
        cwd=ROOT,
        capture_output=True,
    )
    subprocess.run(
        ["docker", "compose", "-f", DEV_COMPOSE, "down"],
        cwd=ROOT,
        capture_output=True,
    )
    pkill("pnpm dev")
    pkill("next dev")
    pkill("next-server")
    kill_on_port(FRONTEND_PORT)
    kill_on_port(28314)
    if not wait_port_free(FRONTEND_PORT):
        print(f"[ dev ] ERROR: port {FRONTEND_PORT} still in use, aborting")
        return

    print("[ dev ] starting docker stack...")
    compose(["up", "-d", "--build"])

    web_dir = ROOT / "web"
    if not (web_dir / "node_modules").exists():
        print("[ dev ] pnpm install...")
        subprocess.run(["pnpm", "install"], cwd=web_dir, check=True)

    frontend_log = open(LOG_DIR / "frontend.log", "w")
    frontend = subprocess.Popen(
        ["pnpm", "dev", "--port", str(FRONTEND_PORT), "--hostname", "0.0.0.0"],
        cwd=web_dir,
        stdout=frontend_log,
        stderr=frontend_log,
    )
    print(f"[ dev ] pnpm dev  PID={frontend.pid}  :{FRONTEND_PORT}  → logs/frontend.log")
    print()
    print("  proxy    http://localhost:28314  (tunnel entry)")
    print(f"  backend  http://localhost:{BACKEND_PORT}  (direct)")
    print(f"  logs:    docker compose -f {DEV_COMPOSE} logs -f")


def dev_down() -> None:
    print("[ dev ] stopping...")
    subprocess.run(
        ["docker", "compose", "-f", PROD_COMPOSE, "down"],
        cwd=ROOT,
        capture_output=True,
    )
    subprocess.run(
        ["docker", "compose", "-f", DEV_COMPOSE, "down"],
        cwd=ROOT,
        capture_output=True,
    )
    pkill("pnpm dev")
    pkill("next dev")
    pkill("next-server")
    kill_on_port(FRONTEND_PORT)
    kill_on_port(28314)
    kill_on_port(BACKEND_PORT)
    print("  done.")


def sync_static() -> None:
    """Build web if needed and sync web/out → src/piloci/static."""
    web_dir = ROOT / "web"
    if not (WEB_OUT_DIR / "index.html").exists():
        print("[ prod ] building web...")
        if not (web_dir / "node_modules").exists():
            subprocess.run(["pnpm", "install"], cwd=web_dir, check=True)
        subprocess.run(["pnpm", "build"], cwd=web_dir, check=True)

    if WEB_OUT_DIR.exists():
        import shutil

        if STATIC_DIR.exists():
            shutil.rmtree(STATIC_DIR)
        shutil.copytree(WEB_OUT_DIR, STATIC_DIR)
        print(f"[ prod ] synced web/out → {STATIC_DIR.relative_to(ROOT)}")


def native_up() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    sync_static()

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

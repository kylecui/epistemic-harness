#!/usr/bin/env python3
"""Safe restart for the ONLY-EXIT router (harness-backend :8787).

The gateway is the single LLM egress for every pi session; a bare
`docker compose up -d --build` drops all in-flight and new requests into a
connection failure. This script is the escape mechanism:

  1. POST /admin/drain  -> gateway refuses NEW chat requests with 503+Retry-After
  2. poll /admin/status until in_flight == 0 (clients retry on their own)
  3. tag the current image :local -> :prev (rollback anchor)
  4. docker compose up -d --build
  5. health-gate: retry /health until ok
  6. on failure: retag :prev -> :local, recreate, health-gate again, report

Usage: python scripts/router_safe_restart.py [--dry-run] [--no-build]

Incident record (2026-11-24): a previous "restart" edited Docker Desktop's
settings-store.json while running and force-killed its processes, wedging WSL
integration (WSAETIMEDOUT). Never touch the Docker engine globally; this script
restarts ONE container through the compose API only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
GATEWAY = os.environ.get("HARNESS_GATEWAY", "http://127.0.0.1:8787")
IMAGE = "epistemic-harness-backend:local"
PREV = "epistemic-harness-backend:prev"


def _env(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val.strip().strip('"').strip("'")
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    raise RuntimeError(f"missing {key} (env or .env)")


def _post(path: str, token: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{GATEWAY}{path}", data=json.dumps(payload or {}).encode("utf-8"),
        headers={"content-type": "application/json", "x-admin-token": token},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _health() -> bool:
    try:
        with urllib.request.urlopen(f"{GATEWAY}/health", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _run(cmd: list[str], dry: bool) -> None:
    print("+ " + " ".join(cmd), flush=True)
    if not dry:
        subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def _wait_health(attempts: int = 30, delay: float = 2.0) -> bool:
    for _ in range(attempts):
        if _health():
            return True
        time.sleep(delay)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true", help="recreate only, no image rebuild")
    args = ap.parse_args()
    token = _env("HARNESS_ADMIN_TOKEN")

    print("1) drain")
    print("   ", _post("/admin/drain", token))
    for _ in range(60):
        st = _post("/admin/status", token)
        if st.get("in_flight", -1) == 0:
            break
        time.sleep(2)
    else:
        print("drain timeout: in-flight requests did not finish in 120s; aborting", file=sys.stderr)
        _post("/admin/undrain", token)
        return 1

    print("2) anchor previous image")
    inspect = subprocess.run(["docker", "image", "inspect", IMAGE, "-q"],
                             capture_output=True, text=True)
    if inspect.returncode == 0 and inspect.stdout.strip():
        _run(["docker", "tag", IMAGE, PREV], args.dry_run)

    print("3) recreate")
    up = ["docker", "compose", "up", "-d"]
    if not args.no_build:
        up.append("--build")
    _run(up, args.dry_run)

    if args.dry_run:
        print("dry-run: would health-gate now")
        return 0

    print("4) health gate")
    if _wait_health():
        _post("/admin/undrain", token)
        print("restart OK; drain lifted")
        return 0

    print("5) ROLLBACK to :prev")
    _run(["docker", "tag", PREV, IMAGE], args.dry_run)
    _run(["docker", "compose", "up", "-d"], args.dry_run)
    if _wait_health():
        _post("/admin/undrain", token)
        print("rollback OK; new image was bad — investigate before retrying", file=sys.stderr)
        return 2
    print("rollback FAILED — gateway down; manual recovery required", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

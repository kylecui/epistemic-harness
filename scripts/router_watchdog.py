#!/usr/bin/env python3
"""Router self-healing watchdog — the escape hatch for the ONLY-EXIT gateway.

Why this exists (2026-11-24 incident): the gateway is the single LLM egress for
every session. A bad deploy leaves the agent unable to even talk to the user, so
recovery must not depend on the agent or on the user typing commands.

Behaviour (loop, runs detached):
  1. probe GET /health every INTERVAL (default 15s), with a short timeout
  2. after FAIL_THRESHOLD consecutive failures:
       a. compose up -d            (restart the container)
       b. if still down: retag :prev -> :local and compose up -d   (image rollback)
       c. if still down: write FAILED to the status file and keep retrying
  3. every action is appended to .pi/router_watchdog.jsonl and mirrored into
     .pi/router_watchdog.status for humans and the agent to read

It NEVER edits policy, never rebuilds images, never touches Docker global config —
only container lifecycle through the compose API, which is the safe surface.

Usage:
    python scripts/router_watchdog.py                 # foreground loop
    python scripts/router_watchdog.py --once          # single probe+repair pass
    start "" pythonw scripts/router_watchdog.py       # detached (Windows)
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
STATUS_PATH = REPO_ROOT / ".pi" / "router_watchdog.status"
LOG_PATH = REPO_ROOT / ".pi" / "router_watchdog.jsonl"

INTERVAL = 15.0
FAIL_THRESHOLD = 3


def _log(event: str, detail: str = "") -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, "detail": detail}) + "\n")
    except OSError:
        pass
    if event in ("repair_ok", "repair_failed", "rollback_ok", "rollback_failed", "degraded"):
        try:
            STATUS_PATH.write_text(f"{event} {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {detail}\n", encoding="utf-8")
        except OSError:
            pass
        print(f"[watchdog] {event} {detail}", flush=True)


def healthy(timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(f"{GATEWAY}/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def compose_up() -> bool:
    out = subprocess.run(["docker", "compose", "up", "-d"], cwd=str(REPO_ROOT),
                         capture_output=True, text=True, timeout=180)
    _log("compose_up", f"rc={out.returncode} {out.stderr.strip()[-200:]}")
    return out.returncode == 0


def has_prev_image() -> bool:
    out = subprocess.run(["docker", "image", "inspect", PREV], capture_output=True, text=True)
    return out.returncode == 0


def rollback_image() -> bool:
    tag = subprocess.run(["docker", "tag", PREV, IMAGE], capture_output=True, text=True)
    if tag.returncode != 0:
        _log("rollback_tag_failed", tag.stderr.strip()[-200:])
        return False
    return compose_up()


def wait_health(attempts: int = 20, delay: float = 3.0) -> bool:
    for _ in range(attempts):
        if healthy():
            return True
        time.sleep(delay)
    return False


def repair() -> bool:
    _log("repair_start")
    compose_up()
    if wait_health():
        _log("repair_ok", "compose up recovered the gateway")
        return True
    if has_prev_image():
        _log("rollback_start", "trying :prev image")
        if rollback_image() and wait_health():
            _log("rollback_ok", "rolled back to the previous image")
            return True
        _log("rollback_failed", "gateway still unhealthy after rollback")
    else:
        _log("rollback_failed", "no :prev image available")
    return False


def one_pass(failures: int) -> int:
    if healthy():
        if failures:
            _log("recovered", f"after {failures} failed probe(s)")
        return 0
    failures += 1
    if failures >= FAIL_THRESHOLD:
        if repair():
            return 0
        _log("degraded", f"{failures} consecutive failures; repair unsuccessful")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=INTERVAL)
    args = ap.parse_args()

    _log("watchdog_start", f"gateway={GATEWAY} interval={args.interval}s")
    if args.once:
        return 0 if one_pass(0) == 0 else 1
    failures = 0
    while True:
        try:
            failures = one_pass(failures)
        except Exception as exc:  # noqa: BLE001 - the watchdog must outlive its own bugs
            _log("watchdog_error", f"{type(exc).__name__}: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())

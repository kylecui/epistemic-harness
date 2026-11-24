#!/usr/bin/env python3
"""Block a model or a pool on the router for a while, or release it.

    python scripts/hold_model.py kimi-for-coding 240 "weekly cap spent"
    python scripts/hold_model.py kimi_allegretto 60 --pool
    python scripts/hold_model.py --release kimi-for-coding
    python scripts/hold_model.py --list

Talks to the running gateway's /admin endpoints (token from HARNESS_ADMIN_TOKEN or .env), so the hold
applies immediately and survives a restart (persisted next to the quota ledger). Write operations
require the token; --list only reads the unauthenticated /quota view.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent


def _admin_token() -> str:
    token = os.getenv("HARNESS_ADMIN_TOKEN", "")
    env_file = REPO_ROOT / ".env"
    if not token and env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("HARNESS_ADMIN_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token


def main() -> int:
    ap = argparse.ArgumentParser(description="Hold or release a model/pool on the harness router")
    ap.add_argument("target", nargs="?", help="model key, or pool id together with --pool")
    ap.add_argument("minutes", nargs="?", type=int, default=60, help="how long to block (default 60)")
    ap.add_argument("reason", nargs="?", default="", help="why (shown in the skip reason)")
    ap.add_argument("--release", action="store_true", help="release the hold instead of creating one")
    ap.add_argument("--list", action="store_true", help="show active holds and quota alerts")
    ap.add_argument("--pool", action="store_true", help="target is a pool id, not a model key")
    ap.add_argument("--url", default=os.getenv("HARNESS_ADMIN_URL", "http://127.0.0.1:8787"))
    args = ap.parse_args()

    try:
        if args.list:
            data = httpx.get(f"{args.url}/quota", timeout=10).json()
            print(json.dumps({k: data.get(k) for k in ("holds", "alerts")}, ensure_ascii=False, indent=1))
            return 0
        if not args.target:
            print("a target is required (model key, or pool id with --pool)", file=sys.stderr)
            return 2
        token = _admin_token()
        if not token:
            print("HARNESS_ADMIN_TOKEN is not set (environment or .env)", file=sys.stderr)
            return 2
        headers = {"x-admin-token": token}
        if args.release:
            resp = httpx.post(f"{args.url}/admin/unhold", headers=headers, json={"target": args.target}, timeout=10)
        else:
            resp = httpx.post(f"{args.url}/admin/hold", headers=headers, timeout=10,
                              json={"target": args.target, "minutes": args.minutes, "reason": args.reason})
        print(resp.status_code, resp.text[:400])
        return 0 if resp.status_code < 400 else 1
    except httpx.HTTPError as exc:
        print(f"cannot reach the gateway at {args.url}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

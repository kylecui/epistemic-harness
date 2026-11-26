"""Switch the router gate between backends without touching the client.

    python scripts/router_switch.py status
    python scripts/router_switch.py switch green

The gate answers on the port pi already uses, so an upgrade is: start the idle backend, health-check
it, `switch` to it, then rebuild the other side. Nothing the client holds ever points at a container.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

GATE = os.environ.get("HARNESS_GATE_URL", "http://127.0.0.1:8787")


def call(path: str, method: str = "GET") -> tuple[int, dict]:
    req = urllib.request.Request(f"{GATE}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.reason}
    except OSError as exc:
        return 0, {"error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "switch"])
    ap.add_argument("target", nargs="?", default="")
    args = ap.parse_args()
    if args.action == "status":
        code, body = call("/__gate/status")
        print(json.dumps({"http": code, **body}, ensure_ascii=False, indent=2))
        return 0 if code == 200 else 1
    if not args.target:
        print("switch needs a backend name (status lists them)", file=sys.stderr)
        return 2
    code, body = call(f"/__gate/active?active={args.target}", method="POST")
    print(json.dumps({"http": code, **body}, ensure_ascii=False))
    return 0 if code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())

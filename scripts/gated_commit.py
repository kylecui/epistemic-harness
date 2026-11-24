#!/usr/bin/env python3
"""Gated commit: run the test suite FIRST, commit only if it is green.

Incident class (2026-11-24, three times in one day): a PowerShell chain
`tests; git commit; git push` ran the commit regardless of the test exit code,
so red code reached the remote and the running container. Good intentions are
not a mechanism; this script is.

Usage:
    uv run --frozen python scripts/gated_commit.py -m "subject" [-m "body"] [--no-push]

Exit codes: 0 committed+pushed, 2 tests/docs red (nothing committed), 1 other error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", action="append", required=True)
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--skip-tests", action="store_true", help="docs-only commits; still runs check_docs")
    args = ap.parse_args()

    if not args.skip_tests:
        # docker-first (operator rule): the commit gate runs the full suite in the verify
        # container through verify.py, which prints the runner and never falls back silently.
        tests = run([sys.executable, "scripts/verify.py", "--runner", "docker", "--policy"],
                    capture_output=True, text=True, timeout=900)
        lines = [l for l in tests.stdout.splitlines() if l.strip()]
        runner = next((l for l in lines if l.startswith("runner=")), "")
        tail = [l for l in lines if l.strip()][-1:]
        print(f"tests: rc={tests.returncode} {runner} {tail[0] if tail else ''}".rstrip())
        if tests.returncode != 0:
            print("REFUSING TO COMMIT: tests are red.", file=sys.stderr)
            return 2
    docs = run([sys.executable, "scripts/check_docs.py"], capture_output=True, text=True, timeout=120)
    print(f"docs: rc={docs.returncode}")
    if docs.returncode != 0:
        print("REFUSING TO COMMIT: docs drift.", file=sys.stderr)
        return 2

    run(["git", "add", "-A"])
    cmd = ["git", "commit"]
    for m in args.message:
        cmd += ["-m", m]
    commit = run(cmd, capture_output=True, text=True)
    print(commit.stdout.strip().splitlines()[-1] if commit.stdout.strip() else commit.stderr.strip()[-200:])
    if commit.returncode != 0:
        return 1
    if not args.no_push:
        push = run(["git", "push"], capture_output=True, text=True)
        print(push.stderr.strip().splitlines()[-1] if push.stderr.strip() else "pushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

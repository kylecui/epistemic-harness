#!/usr/bin/env python3
"""Portable verify entry point for `.pi/exit_gate.json`.

The gate config must name one command that works on any machine of this repo.
A bare `python -m unittest ...` picks whatever interpreter is on PATH, which may
lack the project deps; this wrapper re-execs the local venv interpreter when one
exists and then runs the test suite.

Usage:
    python scripts/verify.py             # full unittest discovery
    python scripts/verify.py -p "test_gate_*"   # pass a discovery pattern
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def _local_python() -> Path | None:
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        cand = ROOT / ".venv" / Path(*rel)
        if cand.exists():
            return cand
    return None


def main() -> int:
    local = _local_python()
    if local and Path(sys.executable).resolve() != local.resolve():
        return subprocess.call([str(local), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=str(ROOT))

    pattern = "test_*.py"
    args = sys.argv[1:]
    if "-p" in args:
        pattern = args[args.index("-p") + 1]
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern],
        cwd=str(ROOT),
    )


if __name__ == "__main__":
    raise SystemExit(main())

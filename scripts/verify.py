#!/usr/bin/env python3
"""Portable verify entry point for `.pi/exit_gate.json` — with an explicit runner.

The gate config must name one command that means the same thing on every machine.
Two sources of divergence bit us already: the host shell (`cmd.exe` vs a POSIX
shell) and the interpreter (`python` on PATH vs the venv). This script removes
the interpreter question and makes the shell question explicit:

    python scripts/verify.py                 # auto: docker when usable, else host
    python scripts/verify.py --runner docker # POSIX sandbox, no silent fallback
    python scripts/verify.py --runner host   # degraded: whatever shell the host has
    python scripts/verify.py -p "test_gate_*"

Runner policy:
  * docker — runs the suite inside the image built from `Dockerfile.verify`
    (POSIX shell, pinned Python, LF fixtures). Same bytes on Windows/macOS/Linux.
  * host   — finds the local venv interpreter and runs the suite there. Shell
    behaviour is whatever the host provides; use only when Docker is missing.
  * auto   — docker iff the docker CLI works AND the image exists locally;
    otherwise host with a printed warning. Never silent: the chosen runner is
    always printed, and the exit gate records it.

Exit codes: 0 green, 1 red, 2 usage, 3 runner unavailable (no silent fallback).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE = "epistemic-verify:local"
MOUNT = "/work"


def _local_python() -> Path | None:
    """Pick the venv interpreter that matches THIS platform.

    A Windows venv mounted into a Linux container is not executable; matching on
    the platform keeps the docker runner from trying to launch it.
    """
    if Path("/.dockerenv").exists():
        return None  # inside the verify image: the image's own interpreter is authoritative
    rels = (("Scripts", "python.exe"),) if sys.platform.startswith("win") else (("bin", "python"),)
    for rel in rels:
        cand = ROOT / ".venv" / Path(*rel)
        if cand.exists():
            return cand
    return None


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd, cwd=str(ROOT))


def _docker_ok(image: str) -> tuple[bool, bool, str]:
    """Return (docker_cli, image_present, reason)."""
    if not shutil.which("docker"):
        return False, False, "docker CLI not found on PATH"
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, False, f"docker unusable: {exc}"
    if proc.returncode != 0:
        return True, False, f"image {image} not built (docker build -f Dockerfile.verify -t {image} .)"
    return True, True, "ok"


def _git_rev() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _run_docker(args: list[str], image: str) -> int:
    inner = ["python", "scripts/verify.py", "--runner", "host", *args]
    cmd = [
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{ROOT}:{MOUNT}", "-w", MOUNT, image, *inner,
    ]
    print(f"runner=docker image={image} rev={_git_rev()}", flush=True)
    return _run(cmd)


def _host_test_command(args: list[str]) -> list[str]:
    """The unittest invocation for the interpreter that actually runs the tests.

    `--modules a b` (each `tests.x`) runs exactly those modules; `-p pattern` discovers.
    Split out so the argument handling can be unit-tested without running anything.
    """
    local = _local_python()
    python = str(local) if local else sys.executable
    if "--modules" in args:
        modules = args[args.index("--modules") + 1:]
        return [python, "-m", "unittest", *modules]
    pattern = "test_*.py"
    if "-p" in args:
        pattern = args[args.index("-p") + 1]
    return [python, "-m", "unittest", "discover", "-s", "tests", "-p", pattern]


def _run_host(args: list[str]) -> int:
    local = _local_python()
    python = str(local) if local else sys.executable
    if os.environ.get("HARNESS_VERIFY_REEXEC") == "1":
        return _run(_host_test_command(args))
    where = "docker(container)" if Path("/.dockerenv").exists() else "host"
    print(f"runner={where} python={python} rev={_git_rev()}", flush=True)
    if local and Path(sys.executable).resolve() != local.resolve():
        env = {**os.environ, "HARNESS_VERIFY_REEXEC": "1"}
        return subprocess.call([str(local), str(Path(__file__).resolve()), "--runner", "host", *args],
                               cwd=str(ROOT), env=env)
    rc = subprocess.run([python, "-c", "import yaml, pydantic, fastapi, httpx"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                        cwd=str(ROOT)).returncode
    if rc != 0:
        print("RUNNER_UNAVAILABLE: this interpreter cannot import the project deps "
              "(yaml/pydantic/fastapi/httpx). Create .venv or use --runner docker.",
              file=sys.stderr, flush=True)
        return 3
    tests_rc = _run(_host_test_command(args))
    if "--policy" in args:
        policy = subprocess.run([python, "scripts/gate_policy.py"], cwd=str(ROOT), text=True)
        # The gate must see a failure from either part; tests still run so the log has everything.
        return max(tests_rc, policy.returncode)
    return tests_rc

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", choices=["auto", "docker", "host"],
                    default=os.environ.get("HARNESS_GATE_RUNNER", "auto"))
    ap.add_argument("--image", default=os.environ.get("HARNESS_VERIFY_IMAGE", DEFAULT_IMAGE))
    ap.add_argument("-p", dest="pattern", help="unittest discovery pattern")
    ap.add_argument("--policy", action="store_true",
                    help="also run scripts/gate_policy.py (the five host gate entries, now in-container)")
    ap.add_argument("--modules", nargs="*", help="explicit test modules (tests.x) instead of discovery")
    args, _unknown = ap.parse_known_args()

    extra = ["--modules", *args.modules] if args.modules else (["-p", args.pattern] if args.pattern else [])
    if args.policy:
        extra = ["--policy", *extra]

    if args.runner == "host":
        return _run_host(extra)

    cli, image_present, reason = _docker_ok(args.image)
    if args.runner == "docker":
        if not (cli and image_present):
            print(f"RUNNER_UNAVAILABLE: {reason}", file=sys.stderr)
            return 3
        return _run_docker(extra, args.image)

    if cli and image_present:
        return _run_docker(extra, args.image)
    print(f"runner=host (auto fallback: {reason})", file=sys.stderr, flush=True)
    return _run_host(extra)


if __name__ == "__main__":
    raise SystemExit(main())

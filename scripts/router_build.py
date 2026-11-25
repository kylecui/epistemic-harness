"""Build the router image behind an import gate.

On 2026-11-25 a rebuild baked a working tree that had a SyntaxError in orchestrator/exit_gate.py.
Nothing checked the image before it replaced the running one, so the container entered a
`Restarting` loop and pi answered every turn with `connect ECONNREFUSED 127.0.0.1:8787`.

This builds under a staging tag, imports the two entry modules inside the image, and only then
moves `:local` (and `:prev`, which is what the watchdog rolls back to) forward.

    python scripts/router_build.py            # build + import gate + promote
    python scripts/router_build.py --dry-run  # print the plan, touch nothing
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

STAGING = "epistemic-harness-backend:staging"
LOCAL = "epistemic-harness-backend:local"
PREV = "epistemic-harness-backend:prev"
SMOKE = "import orchestrator.server, proxy_gateway.app, harness_backend"


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def smoke(image: str) -> tuple[bool, str]:
    """Import the entry modules inside the built image: a syntax error must die here, not in prod."""
    proc = run(["docker", "run", "--rm", "--entrypoint", "python", image, "-c", SMOKE], timeout=300)
    detail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
    return proc.returncode == 0, detail[0][:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-build", action="store_true", help="gate an already-built :staging image")
    args = ap.parse_args()
    if not shutil.which("docker"):
        print("docker CLI not found", file=sys.stderr)
        return 3
    steps = ([["docker", "build", "-t", STAGING, "."]] if not args.skip_build else []) + [
        ["docker", "image", "inspect", STAGING],  # exists?
    ]
    if args.dry_run:
        for step in steps:
            print("would run:", " ".join(step))
        print(f"would smoke: docker run --rm --entrypoint python {STAGING} -c \"{SMOKE}\"")
        print(f"would promote: {STAGING} -> {LOCAL} (and {LOCAL} -> {PREV} first)")
        return 0
    for step in steps:
        proc = run(step)
        if proc.returncode != 0:
            print(f"FAILED: {' '.join(step)}\n{(proc.stdout + proc.stderr)[-400:]}", file=sys.stderr)
            return 2
    ok, detail = smoke(STAGING)
    if not ok:
        print(f"REFUSING TO PROMOTE: the image cannot import its entry modules — {detail}", file=sys.stderr)
        print(f"the running {LOCAL} image is untouched; nothing was replaced", file=sys.stderr)
        return 2
    run(["docker", "tag", LOCAL, PREV])
    proc = run(["docker", "tag", STAGING, LOCAL])
    if proc.returncode != 0:
        print(f"could not promote: {(proc.stdout + proc.stderr)[-300:]}", file=sys.stderr)
        return 1
    print(f"promoted {STAGING} -> {LOCAL} (previous kept as {PREV}); import smoke passed: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

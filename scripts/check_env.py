#!/usr/bin/env python3
"""check_env — verify every runtime plane is aligned and usable.

Planes: spec / session contract / repo contract / install stamp / global
install / pi settings / docker / images / backend health.

git and gh are WORKTREE tools, not harness planes: when missing we print
configuration guidance (notify-style) instead of failing the harness.

Usage:
    python scripts/check_env.py             # full plane report, exit 1 on drift
    python scripts/check_env.py --skip-stamp  # mid-upgrade: stamp not yet written
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_HOME = Path.home() / ".pi" / "harness"
AGENT_DIR = Path.home() / ".pi" / "agent"
SETTINGS = AGENT_DIR / "settings.json"


def spec_version() -> str:
    data = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8")) or {}
    return str(data.get("version", "0.0.0"))


def header_version(path: Path) -> str | None:
    import re
    if not path.exists():
        return None
    m = re.search(r"\(v(\d+\.\d+\.\d+)\)", path.read_text(encoding="utf-8", errors="replace")[:200])
    return m.group(1) if m else None


def check(name: str, ok: bool, detail: str, remediation: str = "") -> bool:
    line = f"{'OK  ' if ok else 'DRIFT'} {name:<18} {detail}"
    if not ok and remediation:
        line += f"  -> {remediation}"
    print(line)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-stamp", action="store_true", help="mid-upgrade: do not require the install stamp")
    ap.add_argument("--no-docker", action="store_true", help="host-only install: skip docker/image/health planes")
    args = ap.parse_args()

    problems = 0
    spec = spec_version()
    problems += not check("spec", bool(spec), f"harness.yaml v{spec}")

    sess = header_version(AGENT_DIR / "AGENTS.md")
    problems += not check("session contract", sess == spec, f"{AGENT_DIR / 'AGENTS.md'} v{sess}",
                          "run scripts/compile_clients.py + scripts/install_global.py, then restart pi")
    repo_v = header_version(REPO_ROOT / "AGENTS.md")
    problems += not check("repo contract", repo_v == spec, f"AGENTS.md v{repo_v}",
                          "run scripts/compile_clients.py")

    if not args.skip_stamp:
        stamp = REPO_ROOT / ".pi" / "installed_version"
        stamp_v = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None
        problems += not check("install stamp", stamp_v == f"v{spec}", f"installed={stamp_v}",
                              "run scripts/upgrade.py")

    required = ["harness.yaml", "scripts/harness_version.py", "sandbox/compose.yaml", "sandbox/Dockerfile"]
    missing = [f for f in required if not (HARNESS_HOME / f).exists()]
    problems += not check("global install", not missing, str(HARNESS_HOME),
                          f"run scripts/install_global.py (missing: {missing})" if missing else "")

    st: dict = {}
    if SETTINGS.exists():
        try:
            st = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            problems += not check("pi settings", False, str(SETTINGS), "fix JSON or delete the file")
    need = {"+sh", "+powershell", "+grep", "+find", "+ls"}
    miss = sorted(need - set(st.get("defaultTools") or []))
    problems += not check("pi settings", not miss, str(SETTINGS),
                          f"run scripts/install_global.py (missing defaultTools: {miss})" if miss else "")

    if not args.no_docker:
        docker = shutil.which("docker")
        problems += not check("docker", bool(docker), docker or "not on PATH",
                              "install Docker Desktop; shell falls back to host Git Bash until then")
        if docker:
            imgs = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                                  capture_output=True, text=True, timeout=30)
            have = set(imgs.stdout.split())
            problems += not check("backend image", "epistemic-harness-backend:local" in have,
                                  "epistemic-harness-backend:local",
                                  "run scripts/upgrade.py (docker rebuild)")
            problems += not check("sandbox image", "harness-sandbox:local" in have,
                                  "harness-sandbox:local", "run scripts/upgrade.py (sandbox build)")
            try:
                with urllib.request.urlopen("http://127.0.0.1:8787/health", timeout=5) as resp:
                    healthy = resp.status == 200
            except Exception:
                healthy = False
            problems += not check("backend health", healthy, "http://127.0.0.1:8787/health",
                                  "docker compose up -d")

    for tool, hint in (
        ("git", "worktree tool missing: install Git for Windows (ships Git Bash)"),
        ("gh", "worktree tool missing: winget install GitHub.cli, then gh auth login"),
    ):
        if not shutil.which(tool):
            print(f"NOTE  {tool:<18} {hint}")

    print()
    print("all planes aligned" if not problems else f"{problems} plane(s) need attention")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())

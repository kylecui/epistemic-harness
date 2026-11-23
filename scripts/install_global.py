#!/usr/bin/env python3
"""Install the harness GLOBALLY so it works from ANY working directory.

Architecture (2026-11-23, after pilot feedback that the harness must not
require its own repo as the working directory):

  GLOBAL (installed once, lives in the user's home):
    ~/.pi/agent/extensions/harness-guard.ts   pi's global extension slot (live)
    ~/.pi/harness/scripts/*.py                version banner, upgrade helpers
    ~/.pi/harness/skills/*/SKILL.md           source for user-level skill sync
    ~/.pi/harness/{harness.yaml,RELEASE-NOTES.md}  version + what's-new content

  PROJECT (working-directory specific, never touched by this installer):
    .pi/exit_gate.json, .pi/task_contract.json, .pi/mcp.json
    traces/, knowledge/, and other agents' files

The extension resolves HARNESS_HOME (env override) or ~/.pi/harness, falling
back to the current repo for development sessions.

Usage:
    python scripts/install_global.py           # sync global install, report
    python scripts/install_global.py --check   # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_EXT = Path.home() / ".pi" / "agent" / "extensions" / "harness-guard.ts"
HARNESS_HOME = Path.home() / ".pi" / "harness"


def _copy(src: Path, dest: Path, check: bool, copied: list[str], drift: list[str]) -> None:
    if not src.exists():
        return
    text = src.read_text(encoding="utf-8")
    if dest.exists() and dest.read_text(encoding="utf-8", errors="replace") == text:
        return
    if check:
        drift.append(str(dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    copied.append(str(dest))


def sync(check: bool = False) -> dict:
    copied: list[str] = []
    drift: list[str] = []
    jobs = [
        (REPO_ROOT / "extensions" / "harness-guard.ts", GLOBAL_EXT),
        (REPO_ROOT / "harness.yaml", HARNESS_HOME / "harness.yaml"),
        (REPO_ROOT / "docs" / "RELEASE-NOTES.md", HARNESS_HOME / "RELEASE-NOTES.md"),
    ]
    for script in ("harness_version.py", "install_user_skills.py", "upgrade.py"):
        jobs.append((REPO_ROOT / "scripts" / script, HARNESS_HOME / "scripts" / script))
    for src, dest in jobs:
        _copy(src, dest, check, copied, drift)
    # skills source: repo skills/pi-native -> HARNESS_HOME/skills
    src_skills = REPO_ROOT / "skills" / "pi-native"
    if src_skills.exists():
        for skill_dir in sorted(src_skills.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                _copy(skill_dir / "SKILL.md", HARNESS_HOME / "skills" / skill_dir.name / "SKILL.md",
                      check, copied, drift)
    return {"copied": copied, "drift": drift, "harness_home": str(HARNESS_HOME)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    result = sync(check=args.check)
    for c in result["copied"]:
        print(f"synced: {c}")
    for d in result["drift"]:
        print(f"drift: {d}", file=sys.stderr)
    if not result["copied"] and not result["drift"]:
        print("global install in sync")
    if result["copied"] and not args.check:
        print("\nnext: restart pi (global extension reloaded); "
              "user-level skills sync on next upgrade or run install_user_skills.py")
    return 1 if result["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

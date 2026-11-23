#!/usr/bin/env python3
"""Sync harness skill wrappers to the USER-level skills directory (~/.agents/skills).

Why: pi discovers project `.agents/skills/` only from the working directory
up to the repo root — pilots running pi outside the repo (global harness
mode) saw no harness-* skills (reported 2026-11-23). User-level
`~/.agents/skills/` makes them available in every directory.

Idempotent: copies only when content differs; never deletes unrelated user
skills. Called by scripts/install.py and scripts/upgrade.py.

Usage:
    python scripts/install_user_skills.py          # sync, report
    python scripts/install_user_skills.py --check  # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_HOME = Path.home() / ".pi" / "harness"
SOURCE = Path(__import__("os").environ.get("HARNESS_HOME") or HARNESS_HOME) / "skills"
# Fallback for development checkouts without a global install:
if not SOURCE.exists():
    SOURCE = REPO_ROOT / "skills" / "pi-native"


def user_skills_dir() -> Path:
    return Path.home() / ".agents" / "skills"


def sync(check: bool = False) -> dict:
    target = user_skills_dir()
    copied: list[str] = []
    missing: list[str] = []
    if not SOURCE.exists():
        return {"copied": [], "missing": ["(source skills absent — run install_global.py first)"], "target": str(target)}
    home = str(user_skills_dir().parent.parent)  # ~/.pi/harness lives beside ~/.agents
    harness_home = Path(home) / ".pi" / "harness"
    for skill_dir in sorted(SOURCE.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        dest = target / skill_dir.name
        src_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        # substitute the global-install path so wrappers work from any cwd
        src_text = src_text.replace("{{HARNESS_HOME}}", str(harness_home))
        if dest.exists() and (dest / "SKILL.md").read_text(encoding="utf-8", errors="replace") == src_text:
            continue
        if check:
            missing.append(skill_dir.name)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(src_text, encoding="utf-8")
        copied.append(skill_dir.name)
    return {"copied": copied, "missing": missing, "target": str(target)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    result = sync(check=args.check)
    if result["copied"]:
        print(f"user skills synced ({len(result['copied'])}): {', '.join(result['copied'])} -> {result['target']}")
    if result["missing"]:
        print(f"user skills drift: {', '.join(result['missing'])}", file=sys.stderr)
    if not result["copied"] and not result["missing"]:
        print("user skills in sync")
    return 1 if result["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

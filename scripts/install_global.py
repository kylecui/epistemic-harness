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
import json
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_EXT = Path.home() / ".pi" / "agent" / "extensions" / "harness-guard.ts"
HARNESS_HOME = Path.home() / ".pi" / "harness"
AGENT_DIR = Path.home() / ".pi" / "agent"
GLOBAL_SANDBOX_EXT = AGENT_DIR / "extensions" / "sandbox-shell.ts"
SETTINGS_JSON = AGENT_DIR / "settings.json"
REQUIRED_DEFAULT_TOOLS = ["+sh", "+powershell", "+grep", "+find", "+ls"]
DEFAULT_SHELL_PATH = r"C:\Program Files\Git\bin\bash.exe"


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


def merge_pi_settings(existing: dict) -> dict:
    """Additive, idempotent pi settings merge (pure function, testable).

    shellPath is only set when absent (a user override wins); defaultTools
    gains the sandbox + fallback tools without touching existing entries.
    """
    merged = dict(existing)
    tools = list(merged.get("defaultTools") or [])
    for token in REQUIRED_DEFAULT_TOOLS:
        if token not in tools:
            tools.append(token)
    merged["defaultTools"] = tools
    merged.setdefault("shellPath", DEFAULT_SHELL_PATH)
    return merged


def sync(check: bool = False) -> dict:
    copied: list[str] = []
    drift: list[str] = []
    jobs = [
        (REPO_ROOT / "extensions" / "harness-guard.ts", GLOBAL_EXT),
        (REPO_ROOT / "extensions" / "sandbox-shell.ts", GLOBAL_SANDBOX_EXT),
        # Product-level extension: dispatches must be visible in EVERY project, not
        # just the harness repo (dogfooding must not ship project-local only).
        (REPO_ROOT / "extensions" / "dispatch-visibility.ts", AGENT_DIR / "extensions" / "dispatch-visibility.ts"),
        (REPO_ROOT / "harness.yaml", HARNESS_HOME / "harness.yaml"),
        # compiled contract -> the file pi actually injects into every session;
        # must run AFTER compile_clients (upgrade orders it that way)
        (REPO_ROOT / "AGENTS.md", AGENT_DIR / "AGENTS.md"),
        (REPO_ROOT / "docs" / "RELEASE-NOTES.md", HARNESS_HOME / "RELEASE-NOTES.md"),
        (REPO_ROOT / "sandbox" / "Dockerfile", HARNESS_HOME / "sandbox" / "Dockerfile"),
        (REPO_ROOT / "sandbox" / "compose.yaml", HARNESS_HOME / "sandbox" / "compose.yaml"),
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
    # pi settings: additive merge (sandbox tool + fallback channels + shell)
    existing = None
    if SETTINGS_JSON.exists():
        try:
            existing = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            drift.append(f"{SETTINGS_JSON} (unparseable JSON — fix or delete)")
    if isinstance(existing, dict):
        desired = json.dumps(merge_pi_settings(existing), ensure_ascii=False, indent=2) + "\n"
        current = SETTINGS_JSON.read_text(encoding="utf-8") if SETTINGS_JSON.exists() else ""
        if current != desired:
            if check:
                drift.append(str(SETTINGS_JSON))
            else:
                SETTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
                SETTINGS_JSON.write_text(desired, encoding="utf-8")
                copied.append(str(SETTINGS_JSON))
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

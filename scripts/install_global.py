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
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_EXT = Path.home() / ".pi" / "agent" / "extensions" / "harness-guard.ts"
HARNESS_HOME = Path.home() / ".pi" / "harness"
AGENT_DIR = Path.home() / ".pi" / "agent"
GLOBAL_SANDBOX_EXT = AGENT_DIR / "extensions" / "sandbox-shell.ts"
GLOBAL_ROUTE_STATUS_EXT = AGENT_DIR / "extensions" / "model-route-status.ts"
SETTINGS_JSON = AGENT_DIR / "settings.json"
REQUIRED_DEFAULT_TOOLS = ["+sh", "+powershell", "+grep", "+find", "+ls"]
DEFAULT_SHELL_PATH = r"C:\Program Files\Git\bin\bash.exe"
# The router is the only model exit, so a fresh workspace must start on it: without these two fields pi
# picks its own built-in default provider and bypasses the harness entirely (found 2026-11-24, a scratch
# workspace answered from Gemini with its free tier exhausted).
HARNESS_PROVIDER = "harness-router"
DEFAULT_PROVIDER_MODEL = "opencode-deepseek-v4.1-flash"
MODELS_JSON = AGENT_DIR / "models.json"


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
    # Only defaults: a workspace or user that picked a model on purpose keeps it.
    merged.setdefault("defaultProvider", HARNESS_PROVIDER)
    merged.setdefault("defaultModel", DEFAULT_PROVIDER_MODEL)
    return merged


def harness_router_models(policy_path: Path) -> list[dict[str, Any]]:
    """The router's model list straight from quota_policy.yaml, so pi's catalog cannot go stale."""
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    out: list[dict[str, Any]] = []
    for model_key, cfg in (policy.get("models") or {}).items():
        out.append({"id": model_key, "contextWindow": int(cfg.get("context_window") or 1048576)})
    return out


def merge_models_json(existing: dict, policy_path: Path) -> dict:
    """Replace only the harness-router provider block; other providers are left alone."""
    merged = dict(existing or {})
    providers = dict(merged.get("providers") or {})
    current = dict(providers.get(HARNESS_PROVIDER) or {})
    current.update({"baseUrl": "http://127.0.0.1:8787/v1", "api": "openai-completions",
                    "apiKey": "local-harness-proxy", "models": harness_router_models(policy_path)})
    providers[HARNESS_PROVIDER] = current
    merged["providers"] = providers
    return merged


def _jobs() -> list[tuple[Path, Path]]:
    """Everything install_global must copy: (repo source, installed destination).

    Exposed as a function so a test can assert that every extension in extensions/ is listed here —
    a fixed list silently skipped a new extension once (model-route-status.ts, 2026-11-24).
    """
    jobs = [
        (REPO_ROOT / "extensions" / "harness-guard.ts", GLOBAL_EXT),
        (REPO_ROOT / "extensions" / "sandbox-shell.ts", GLOBAL_SANDBOX_EXT),
        # Product-level extension: dispatches must be visible in EVERY project, not
        # just the harness repo (dogfooding must not ship project-local only).
        (REPO_ROOT / "extensions" / "dispatch-visibility.ts", AGENT_DIR / "extensions" / "dispatch-visibility.ts"),
        (REPO_ROOT / "extensions" / "model-route-status.ts", GLOBAL_ROUTE_STATUS_EXT),
        (REPO_ROOT / "harness.yaml", HARNESS_HOME / "harness.yaml"),
        # compiled contract -> the file pi actually injects into every session;
        # must run AFTER compile_clients (upgrade orders it that way)
        (REPO_ROOT / "AGENTS.md", AGENT_DIR / "AGENTS.md"),
        (REPO_ROOT / "docs" / "RELEASE-NOTES.md", HARNESS_HOME / "RELEASE-NOTES.md"),
        (REPO_ROOT / "sandbox" / "Dockerfile", HARNESS_HOME / "sandbox" / "Dockerfile"),
        (REPO_ROOT / "sandbox" / "compose.yaml", HARNESS_HOME / "sandbox" / "compose.yaml"),
    ]
    for script in ("harness_version.py", "install_user_skills.py", "upgrade.py", "gate_universal.py"):
        jobs.append((REPO_ROOT / "scripts" / script, HARNESS_HOME / "scripts" / script))
    return jobs


def sync(check: bool = False) -> dict:
    copied: list[str] = []
    drift: list[str] = []
    jobs = _jobs()
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
    # pi's model catalog: keep the router's entries derived from quota_policy.yaml
    policy_path = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"
    existing_models: dict = {}
    if policy_path.exists():
        if MODELS_JSON.exists():
            try:
                existing_models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                drift.append(f"{MODELS_JSON} (unparseable JSON — fix or delete)")
        if isinstance(existing_models, dict):
            desired_models = json.dumps(merge_models_json(existing_models, policy_path),
                                       ensure_ascii=False, indent=2) + "\n"
            current_models = MODELS_JSON.read_text(encoding="utf-8") if MODELS_JSON.exists() else ""
            if current_models != desired_models:
                if check:
                    drift.append(str(MODELS_JSON))
                else:
                    MODELS_JSON.write_text(desired_models, encoding="utf-8")
                    copied.append(str(MODELS_JSON))
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

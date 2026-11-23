#!/usr/bin/env python3
"""Harness version triangulation: what is specified, what is loaded, what is stamped.

Answers "which harness version is THIS pi session actually running?" — the
question that triggered this script (2026-11-23) after a pilot could not tell
whether a restarted session had picked up a new contract.

Three sources, three meanings:
  spec      harness.yaml `version:` — what the code in this checkout declares
  loaded    AGENTS.md header `(vX.Y.Z)` — what pi actually loaded into the
            session context (the effective runtime contract)
  installed .pi/installed_version — what scripts/upgrade.py last stamped here

Usage:
    python scripts/harness_version.py          # human report, exit 1 on drift
    python scripts/harness_version.py --json   # machine-readable
    python scripts/harness_version.py --banner # startup banner text; first
        # display of a version appends its release notes (docs/RELEASE-NOTES.md)
        # and stamps .pi/last_banner_version so notes show only once per version
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENTS_HEADER_RE = re.compile(r"epistemic-dual-process-harness \(v(\d+\.\d+\.\d+)\)")


def spec_version() -> str | None:
    try:
        data = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8")) or {}
        return str(data.get("version") or "") or None
    except Exception:
        return None


def loaded_version() -> str | None:
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.exists():
        return None
    for line in agents.read_text(encoding="utf-8", errors="replace").splitlines()[:5]:
        m = AGENTS_HEADER_RE.search(line)
        if m:
            return m.group(1)
    return None


def installed_version() -> str | None:
    stamp = REPO_ROOT / ".pi" / "installed_version"
    if stamp.exists():
        return stamp.read_text(encoding="utf-8").strip() or None
    return "0.4.0" if (REPO_ROOT / ".pi" / "exit_gate.json").exists() else None


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def collect() -> dict:
    spec, loaded, installed = spec_version(), loaded_version(), installed_version()
    drift = []
    if spec and loaded and spec != loaded:
        drift.append(f"spec v{spec} != loaded contract v{loaded} — run scripts/compile_clients.py then restart pi")
    if installed and spec and installed != f"v{spec}":
        drift.append(f"installed {installed} != spec v{spec} — run scripts/upgrade.py")
    return {
        "spec_version": spec,
        "loaded_contract_version": loaded,
        "installed_version": installed,
        "git_sha": git_sha(),
        "drift": drift,
    }


RELEASE_NOTES = REPO_ROOT / "docs" / "RELEASE-NOTES.md"
BANNER_STAMP = REPO_ROOT / ".pi" / "last_banner_version"


def banner_text(repo_root: Path = REPO_ROOT) -> tuple[list[str], bool]:
    """Startup banner lines. Returns (lines, stamped_new_version).

    First time a loaded contract version is displayed, its release-notes
    section is appended and the stamp updated — so "what changed" appears
    exactly once per version, at the first session that loads it.
    """
    global REPO_ROOT
    orig = REPO_ROOT
    REPO_ROOT = repo_root
    try:
        info = collect()
        loaded = info["loaded_contract_version"] or "?"
        sha = info["git_sha"] or "?"
        lines = [f"[harness] contract v{loaded} loaded (git {sha})"]
        for d in info["drift"]:
            lines.append(f"[harness] DRIFT: {d}")
        stamp_path = repo_root / ".pi" / "last_banner_version"
        prev = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.exists() else ""
        stamped = False
        if loaded != "?" and prev != loaded:
            notes = _release_notes_section(loaded, repo_root)
            if notes:
                lines.append(f"[harness] new in v{loaded}:")
                lines.extend("  " + ln for ln in notes)
            try:
                stamp_path.parent.mkdir(parents=True, exist_ok=True)
                stamp_path.write_text(loaded + "\n", encoding="utf-8")
                stamped = True
            except OSError:
                pass
        return lines, stamped
    finally:
        REPO_ROOT = orig


def _release_notes_section(version: str, repo_root: Path) -> list[str]:
    path = repo_root / "docs" / "RELEASE-NOTES.md"
    if not path.exists():
        return []
    out: list[str] = []
    in_section = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("## v"):
            in_section = raw.startswith(f"## v{version}")
            continue
        if in_section:
            if raw.strip():
                out.append(raw.strip())
            if len(out) >= 8:  # keep the startup banner readable
                out.append("… (docs/RELEASE-NOTES.md)")
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--banner", action="store_true", help="startup banner (with once-per-version release notes)")
    args = ap.parse_args()

    if args.banner:
        lines, _ = banner_text()
        for ln in lines:
            print(ln)
        return 0

    info = collect()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"spec (harness.yaml)      : v{info['spec_version']}")
        print(f"loaded contract (AGENTS) : v{info['loaded_contract_version']}")
        print(f"installed (.pi stamp)    : {info['installed_version']}")
        print(f"git                      : {info['git_sha']}")
        for d in info["drift"]:
            print(f"DRIFT: {d}")
        if not info["drift"]:
            print("versions aligned")
    return 1 if info["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

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

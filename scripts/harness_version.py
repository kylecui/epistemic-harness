#!/usr/bin/env python3
"""Harness version triangulation across ALL runtime planes.

Answers "which harness version is THIS pi session actually running?" —
per plane, with drift reported faithfully (fixes the false-green class
where the old script read the repo's own AGENTS.md and called it "loaded").

Planes and meanings:
  spec           harness.yaml `version:` — what this checkout declares
  session        ~/.pi/agent/AGENTS.md — the contract pi injects into every
                 session (the effective global runtime contract)
  repo           <repo>/AGENTS.md — compiled contract for sessions whose cwd
                 is this repo; must equal session, else restart has not
                 picked up the new contract
  installed      <repo>/.pi/installed_version — what scripts/upgrade.py last
                 stamped; MISSING stamp is drift, never guessed

Usage:
    python scripts/harness_version.py          # human report, exit 1 on drift
    python scripts/harness_version.py --json   # machine-readable
    python scripts/harness_version.py --banner # startup banner (with
        # once-per-version release notes via .pi/last_banner_version)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME_DIR = Path.home()
AGENTS_HEADER_RE = re.compile(
    # The product was renamed once (epistemic-harness -> epistemic-dual-process-harness), so a stale
    # contract written by an older compiler must still be READ and named by version rather than
    # reported as unparseable (issue #5).
    r"(?:epistemic-dual-process-harness|epistemic-harness|harness)\s*\(v(\d+\.\d+\.\d+)\)",
    re.IGNORECASE,
)


def spec_version() -> str | None:
    try:
        data = yaml.safe_load((REPO_ROOT / "harness.yaml").read_text(encoding="utf-8")) or {}
        return str(data.get("version") or "") or None
    except Exception:
        return None


def detect_loaded_version(path: Path) -> str | None:
    """Header version of one AGENTS.md file, or None if absent/unparseable."""
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]:
        m = AGENTS_HEADER_RE.search(line)
        if m:
            return m.group(1)
    return None


def installed_version() -> str | None:
    stamp = REPO_ROOT / ".pi" / "installed_version"
    if stamp.exists():
        return stamp.read_text(encoding="utf-8").strip() or None
    return None


def stamp_drift(spec: str, installed: str | None) -> list[str]:
    """Missing stamp is drift with remediation, never a silent skip."""
    if installed is None:
        return ["installed stamp missing — run scripts/upgrade.py to align all planes"]
    if installed != f"v{spec}":
        return [f"installed {installed} != spec v{spec} — run scripts/upgrade.py"]
    return []


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def collect(repo_root: Path | None = None, home: Path | None = None) -> dict:
    # resolve at call time: tests swap the module-global REPO_ROOT/HOME_DIR,
    # and a def-time default argument would freeze the original path object
    repo_root = repo_root or REPO_ROOT
    home = home or HOME_DIR
    spec = spec_version()
    session_loaded = detect_loaded_version(home / ".pi" / "agent" / "AGENTS.md")
    repo_loaded = detect_loaded_version(repo_root / "AGENTS.md")
    installed = installed_version()

    drift: list[str] = []
    if spec:
        drift += stamp_drift(spec, installed)
        # "I cannot read this plane" is not "this plane is fine" (issue #5): an unparseable or
        # absent contract used to be skipped, so the script printed 'all planes aligned' while
        # the session ran something else entirely.
        session_path = home / ".pi" / "agent" / "AGENTS.md"
        repo_path = repo_root / "AGENTS.md"
        if session_loaded is None:
            drift.append(f"session contract unreadable at {session_path} — cannot verify what pi "
                         f"is running; run scripts/install_global.py, then restart pi")
        if repo_loaded is None:
            drift.append(f"repo contract unreadable at {repo_path} — cannot verify the checkout "
                         f"plane; run scripts/compile_clients.py")
        for label, lv in (("session contract", session_loaded), ("repo contract", repo_loaded)):
            if lv is not None and lv != spec:
                drift.append(
                    f"{label} v{lv} != spec v{spec} — run scripts/compile_clients.py + "
                    f"scripts/install_global.py, then restart pi"
                )
        if session_loaded and repo_loaded and session_loaded != repo_loaded:
            drift.append(
                f"session contract v{session_loaded} != repo contract v{repo_loaded} — "
                f"run scripts/install_global.py, then restart pi"
            )
    return {
        "spec_version": spec,
        # compat key: the contract the session actually runs
        "loaded_contract_version": session_loaded,
        "session_contract_version": session_loaded,
        "repo_contract_version": repo_loaded,
        "installed_version": installed,
        "git_sha": git_sha(),
        "drift": drift,
    }


RELEASE_NOTES = REPO_ROOT / "docs" / "RELEASE-NOTES.md"


def _release_notes_section(version: str, path: Path = RELEASE_NOTES) -> list[str]:
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


def banner_text(repo_root: Path = REPO_ROOT, home: Path | None = None) -> tuple[list[str], bool]:
    """Startup banner lines. Returns (lines, stamped_new_version)."""
    info = collect(repo_root=repo_root, home=home)
    # effective contract: the session file wins; fall back to the repo copy
    # (fresh containers / test fixtures have no ~/.pi/agent/AGENTS.md)
    loaded = info["loaded_contract_version"] or info["repo_contract_version"] or "?"
    sha = info["git_sha"] or "?"
    lines = [f"[harness] contract v{loaded} loaded (git {sha})"]
    for d in info["drift"]:
        lines.append(f"[harness] DRIFT: {d}")
    stamp_path = repo_root / ".pi" / "last_banner_version"
    prev = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.exists() else ""
    stamped = False
    if loaded != "?" and prev != loaded:
        notes = _release_notes_section(loaded, repo_root / "docs" / "RELEASE-NOTES.md")
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
        def fmt(v: str | None) -> str:
            return f"v{v}" if v else "missing"
        print(f"spec (harness.yaml)        : {fmt(info['spec_version'])}")
        print(f"session contract (~/.pi)   : {fmt(info['session_contract_version'])}")
        print(f"repo contract (AGENTS.md)  : {fmt(info['repo_contract_version'])}")
        print(f"installed (.pi stamp)      : {info['installed_version'] or 'missing'}")
        print(f"git                        : {info['git_sha'] or 'unknown'}")
        for d in info["drift"]:
            print(f"DRIFT: {d}")
        if not info["drift"]:
            print("all planes aligned")
    return 1 if info["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

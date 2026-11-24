#!/usr/bin/env python3
"""Universal exit-gate checks for projects that do not declare their own gate.

A gate that runs an unknown project's tests is not realistic (toolchain, duration, side effects).
These three invariants are cheap, deterministic and language-agnostic, and each has bitten for real:
leftover scratch files, CRLF committed into .sh/.py (a Linux container then dies with "bad interpreter"),
and a credential written into a tracked file.

Only runs inside a git repository: "untracked" has no meaning otherwise and a tree walk would flag
legitimate sources (critic review, 2026-11-24). EOL is read from the git INDEX, not the working tree,
so core.autocrlf=true does not produce a failure on every turn.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

RESIDUE = re.compile(r"(\.tmp|\.bak|\.orig|~)$|^(debug_.*\.py|scratch_.*|tmp_.*)$", re.IGNORECASE)
SECRET = re.compile(r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                    r"-----BEGIN (?:RSA|OPENSSH) PRIVATE KEY-----|xox[baprs]-[A-Za-z0-9-]{10,})")
SKIP_UNTRACKED = re.compile(r"(^|/)(\.env|\.env\..*|.*\.example|.*\.sample)$")
NOISE_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__"}


def _git(cwd: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _scan_secrets(cwd: Path, paths: list[str]) -> list[str]:
    hits: list[str] = []
    for rel in paths:
        path = cwd / rel
        try:
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if SECRET.search(text):
            hits.append(rel)
    return hits


def main() -> int:
    cwd = Path.cwd()
    if _git(cwd, "rev-parse", "--is-inside-work-tree") is None:
        print("universal gate: no git repository here — checks skipped")
        return 0

    failures: list[str] = []
    status = _git(cwd, "status", "--porcelain") or ""
    untracked = [ln[3:].strip().strip('"') for ln in status.splitlines() if ln.startswith("?? ")]
    modified = [ln[3:].strip().strip('"') for ln in status.splitlines()
                if ln[:2].strip() in {"M", "MM", "A", "AM", "R"}]

    residue = [p for p in untracked if RESIDUE.search(p) and not any(part in NOISE_DIRS for part in p.split("/"))]
    if residue:
        failures.append("residue: " + ", ".join(residue[:8]))

    # index eol: "i/lf  w/crlf  attr/  path" — only committed CRLF is a defect
    eol_out = _git(cwd, "ls-files", "--eol") or ""
    bad_eol = []
    for line in eol_out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[1].endswith((".sh", ".py")):
            continue
        if "i/crlf" in parts[0]:
            bad_eol.append(parts[1])
    if bad_eol:
        failures.append("crlf-in-index (.sh/.py committed with CRLF): " + ", ".join(bad_eol[:8]))

    leaked = _scan_secrets(cwd, modified + [p for p in untracked if not SKIP_UNTRACKED.search(p)])
    if leaked:
        failures.append("secret-in-file: " + ", ".join(leaked[:8]))

    for line in failures:
        print(f"FAIL {line}")
    if failures:
        print("universal gate: clean up the items above (this project declares no .pi/exit_gate.json)")
        return 1
    print("universal gate: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Enforce the repository line-ending policy (.gitattributes) at commit and gate time.

Why a checker and not just `.gitattributes`: attributes only act when git
normalizes, so a CRLF file can still sit in the working tree — and inside a Linux
container that means `bad interpreter: /bin/bash^M`. This makes the policy
checkable and fixable.

Policy:
  * LF  — every tracked text file, including shell scripts and Python;
  * CRLF — only `*.ps1`, `*.bat`, `*.cmd` (Windows-native entry points);
  * mixed — always a violation.

Usage:
    python scripts/check_eol.py            # verify, exit 1 on violation
    python scripts/check_eol.py --fix      # rewrite offenders in place
    python scripts/check_eol.py --staged   # only staged files (pre-commit hook)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRLF_OK = {".ps1", ".bat", ".cmd"}
BINARY = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".pdf",
    ".sqlite", ".db", ".woff", ".woff2", ".ttf", ".pyc",
}
TEXT_EXTS = {
    ".py", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".yaml", ".yml", ".json",
    ".jsonl", ".md", ".txt", ".ts", ".js", ".mjs", ".html", ".css", ".toml",
    ".cfg", ".ini", ".dockerfile", ".env",
}
TEXT_NAMES = {"Dockerfile", ".gitignore", ".gitattributes", ".dockerignore", "Makefile"}


def _is_text(path: Path) -> bool:
    if path.suffix.lower() in BINARY:
        return False
    if path.suffix.lower() in TEXT_EXTS:
        return True
    return path.name in TEXT_NAMES or path.name.startswith(("Dockerfile", ".env"))


def _candidates(staged: bool) -> list[Path]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    try:
        out = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ROOT / line.strip() for line in out.splitlines() if line.strip()]


def _audit(path: Path) -> str | None:
    """Return 'crlf' | 'mixed' | None (compliant)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    crlf = raw.count(b"\r\n")
    if crlf == 0:
        return None
    lone_lf = raw.count(b"\n") - crlf
    if path.suffix.lower() in CRLF_OK:
        return "mixed" if lone_lf else None
    return "mixed" if lone_lf else "crlf"


def main() -> int:
    fix = "--fix" in sys.argv
    staged = "--staged" in sys.argv
    offenders: list[tuple[Path, str]] = []
    for path in _candidates(staged):
        if not path.exists() or not _is_text(path):
            continue
        kind = _audit(path)
        if kind:
            offenders.append((path, kind))

    if not offenders:
        print("eol policy: ok")
        return 0

    if fix:
        for path, kind in offenders:
            raw = path.read_bytes().replace(b"\r\n", b"\n")
            if path.suffix.lower() in CRLF_OK:
                raw = raw.replace(b"\n", b"\r\n")
            path.write_bytes(raw)
        print(f"eol policy: normalized {len(offenders)} file(s)")
        return 0

    print("eol policy violation(s) — run: python scripts/check_eol.py --fix", file=sys.stderr)
    for path, kind in offenders[:20]:
        print(f"  {kind:5s} {path.relative_to(ROOT).as_posix()}", file=sys.stderr)
    if len(offenders) > 20:
        print(f"  ... and {len(offenders) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

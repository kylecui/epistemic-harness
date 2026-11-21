#!/usr/bin/env python3
"""Point git at the versioned hook directory (scripts/git-hooks) and make it runnable.

    python scripts/install_git_hooks.py

Sets `core.hooksPath`, so the policy travels with the repo instead of living in
an unversioned .git/hooks/pre-commit that nobody can review.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "scripts" / "git-hooks"


def main() -> int:
    if not HOOKS.is_dir():
        print(f"missing hook directory: {HOOKS}", file=sys.stderr)
        return 1
    for hook in HOOKS.iterdir():
        if hook.is_file():
            hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    proc = subprocess.run(["git", "config", "core.hooksPath", "scripts/git-hooks"], cwd=str(ROOT))
    if proc.returncode != 0:
        return proc.returncode
    # Keep the attribute policy and the hook agree even if autocrlf is on.
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=str(ROOT))
    print("hooks installed: core.hooksPath=scripts/git-hooks (core.autocrlf=false)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

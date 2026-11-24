#!/usr/bin/env python3
"""Incremental test selection for the per-turn exit gate.

Why: the gate ran the FULL suite (about 20s, docker verify container) after every
mutating turn and froze the TUI. The full suite stays the hard gate at COMMIT time
(scripts/gated_commit.py); the per-turn gate only needs the tests that can be
affected by what changed.

Safety principle: over-select, never under-select. Anything that cannot be mapped
to a specific test (yaml/config/ts/Dockerfile/unknown paths, deleted files, too
many changed files) falls back to the FULL suite.

Usage:
    python scripts/select_tests.py              # print selected test modules (one per line)
    python scripts/select_tests.py --run        # run the selection (or full suite on fallback)
    python scripts/select_tests.py --explain    # show why each module was selected
Exit code of --run is the unittest exit code.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# A change in any of these can alter behaviour anywhere -> full suite.
GLOBAL_TRIGGERS = (
    "harness.yaml", "requirements", "pyproject.toml", "uv.lock", "Dockerfile",
    "docker-compose", "quota_policy.yaml", "task_routing.yaml", "exit_gate.json",
    "tests/__init__.py", "conftest.py",
)
MAX_CHANGED_FOR_SELECTION = 12


def changed_files() -> list[str] | None:
    """Changed + untracked files vs HEAD; None when git is unavailable."""
    try:
        diff = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, timeout=30)
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                   cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if diff.returncode != 0:
        return None
    names = [n.strip().replace("\\", "/") for n in (diff.stdout + "\n" + untracked.stdout).splitlines() if n.strip()]
    return sorted(set(names))


def test_modules() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8", errors="replace") for p in sorted(TESTS_DIR.glob("test_*.py"))}


def references(source_rel: str, text: str) -> bool:
    """Does this test source reference the given source file's module?"""
    mod_dotted = source_rel[:-3].replace("/", ".")
    stem = Path(source_rel).stem
    if mod_dotted in text:
        return True
    if f"{stem}.py" in text:
        return True
    return bool(re.search(rf"\b(import|from)\s+(\w+\.)*{re.escape(stem)}\b", text))


def select(changed: list[str], modules: dict[str, str]) -> tuple[list[str] | None, dict[str, list[str]]]:
    """Returns (selected_modules or None meaning FULL, reasons)."""
    reasons: dict[str, list[str]] = {}
    if not changed:
        return [], reasons
    if len(changed) > MAX_CHANGED_FOR_SELECTION:
        return None, {"*": [f"{len(changed)} changed files > {MAX_CHANGED_FOR_SELECTION}"]}
    selected: set[str] = set()
    for path in changed:
        base = path.rsplit("/", 1)[-1]
        if any(trigger in path or trigger == base for trigger in GLOBAL_TRIGGERS):
            return None, {"*": [f"global trigger: {path}"]}
        if path.startswith("tests/") and base.startswith("test_") and path.endswith(".py"):
            selected.add(base[:-3])
            reasons.setdefault(base[:-3], []).append("test file itself changed")
            continue
        if path.startswith(("docs/", "experiments/", "clients/")) or path.endswith((".md", ".txt", ".json", ".jsonl", ".log")):
            continue  # docs/data: covered by check_docs, not unit tests
        if path.endswith(".py"):
            hits = [name for name, text in modules.items() if references(path, text)]
            if not hits:
                return None, {"*": [f"unmapped source file: {path}"]}
            for name in hits:
                selected.add(name)
                reasons.setdefault(name, []).append(f"references {path}")
            continue
        return None, {"*": [f"unmappable path: {path}"]}  # .ts/.yaml/.ps1/unknown -> safe full
    return sorted(selected), reasons


def docker_command(selected: list[str] | None) -> list[str]:
    """verify.py invocation for the selection: explicit modules, or the full suite when None."""
    cmd = [sys.executable, "scripts/verify.py", "--runner", "docker"]
    if selected is not None:
        cmd += ["--modules", *[f"tests.{m}" for m in selected]]
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--docker", action="store_true",
                    help="run the selection inside the verify container (selection itself is computed here)")
    ap.add_argument("--explain", action="store_true")
    args = ap.parse_args()

    changed = changed_files()
    if changed is None:
        selected, reasons = None, {"*": ["git unavailable"]}
    else:
        selected, reasons = select(changed, test_modules())

    if args.explain or not args.run:
        if selected is None:
            print("FULL SUITE:", "; ".join(reasons.get("*", [])))
        elif not selected:
            print("no test-relevant changes")
        else:
            for name in selected:
                print(f"{name}  <- {'; '.join(reasons.get(name, []))}" if args.explain else name)
    if not (args.run or args.docker):
        return 0

    if args.docker:
        # Tests run in the container (policy: docker-first); only the file-name based selection
        # happens on the host. verify.py prints the runner line and never falls back silently.
        print(f"select_tests: running {'FULL' if selected is None else len(selected)} in docker ...", flush=True)
        return subprocess.run(docker_command(selected), cwd=str(REPO_ROOT)).returncode

    if selected is not None and not selected:
        print("select_tests: nothing to run")
        return 0
    cmd = [sys.executable, "-m", "unittest"]
    cmd += [f"tests.{m}" for m in selected] if selected is not None else ["discover", "-s", "tests"]
    print(f"select_tests: running {'FULL' if selected is None else len(selected)} on the HOST (--run; --docker is the policy default) ...", flush=True)
    return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode


if __name__ == "__main__":
    raise SystemExit(main())

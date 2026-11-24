#!/usr/bin/env python3
"""Exit-gate policy checks, aggregated so they run inside ONE verify container.

These five checks used to run on the host (each its own gate entry). The operator moved
all gate execution into the container (2026-11-24); verify.py --policy invokes this script
with the container interpreter, then runs the unit tests, and fails if either part fails.

The check list here and `.pi/exit_gate.json` must correspond: tests/test_gate_policy.py
pins that correspondence, so a new gate check cannot be added on one side only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (name, script, extra args) — mirrors the five host entries that used to live in
# .pi/exit_gate.json before the container move.
POLICY_CHECKS = [
    ("public_language", "scripts/check_public_language.py", []),
    ("experiment_runner_declared", "scripts/check_experiment_runner_declared.py", []),
    ("eol_policy", "scripts/check_eol.py", []),
    ("routing_validate", "scripts/capability_matrix.py", ["--validate-routing", "config/task_routing.yaml"]),
    ("docs_fresh", "scripts/check_docs.py", []),
]


def main() -> int:
    failures: list[str] = []
    for name, script, extra in POLICY_CHECKS:
        try:
            proc = subprocess.run([sys.executable, script, *extra], cwd=str(REPO_ROOT),
                                  capture_output=True, text=True, timeout=180)
            rc, output = proc.returncode, proc.stdout + proc.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            rc, output = 1, f"{type(exc).__name__}: {exc}"
        if rc == 0:
            print(f"PASS {name}")
        else:
            failures.append(name)
            tail = " | ".join(line.strip() for line in output.splitlines() if line.strip())[-300:]
            print(f"FAIL {name} (rc={rc}): {tail}")
    if failures:
        print(f"policy checks failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

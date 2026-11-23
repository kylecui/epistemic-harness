#!/usr/bin/env python3
"""Gate check: every experiment run record must declare its execution runner.

Anti-recurrence mechanism for issue #13 (container-first policy). A run record
without a `runner` field means the execution plane was not declared at the
time of the run — exactly the failure class this rule exists to surface
(retroactive confession is not accepted; declaration must be contemporaneous).

Exit 0 = all records declare a runner; 1 = violators listed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ["EXPERIMENT_RUNS_DIR"]) if os.environ.get("EXPERIMENT_RUNS_DIR") else REPO_ROOT / "experiments" / "runs"


def main() -> int:
    bad: list[str] = []
    total = 0
    if RUNS_DIR.exists():
        for path in sorted(RUNS_DIR.glob("*.jsonl")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if not line.strip():
                    continue
                total += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    bad.append(f"{path.name}:{lineno}: unparseable record")
                    continue
                if not rec.get("runner"):
                    bad.append(f"{path.name}:{lineno}: missing 'runner' declaration")
    if bad:
        print(f"experiment runner declaration: {len(bad)}/{total} records undeclared")
        for b in bad[:10]:
            print(f"  {b}")
        return 1
    print(f"experiment runner declaration: OK ({total} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

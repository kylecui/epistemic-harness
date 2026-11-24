"""Campaign driver: run every arm x task cell, then judge all cells.

Detached-friendly: logs progress to stdout; safe to re-run (runner appends,
so delete experiments/runs/ first for a clean campaign).

Usage: python experiments/run_campaign.py [--samples 20] [--arms A0,A,B,C,D]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ["traceback-triage", "version-drift", "eol-remediation",
         "claim-layering", "report-extraction", "closure-order"]


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--arms", default="A0,A,B,C,D")
    ap.add_argument("--skip-judge", action="store_true")
    ap.add_argument("--lab", action="store_true",
                    help="run entirely on the isolated SiliconFlow lab instance (:8788); never touches working models")
    args = ap.parse_args()
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if args.lab:
        gw = ["--gateway-url", "http://127.0.0.1:8788", "--model", "lab-deepseek-v4-flash"]
        judge = ["--gateway-url", "http://127.0.0.1:8788", "--model", "lab-deepseek-v3-2"]
    else:
        gw, judge = [], []

    t0 = time.time()
    for arm in arms:
        for task in TASKS:
            if arm == "A0":
                extra = ["--provider", "siliconflow", "--delay", "2"] if args.lab else ["--provider", "kimi"]
            else:
                extra = gw
            rc = run([sys.executable, "experiments/runner.py",
                      "--arm", arm, "--task", task, "--samples", str(args.samples), *extra])
            if rc != 0:
                print(f"CELL FAILED arm={arm} task={task} rc={rc}", flush=True)
    if not args.skip_judge:
        for arm in arms:
            for task in TASKS:
                run([sys.executable, "experiments/judge.py", "--arm", arm, "--task", task, *judge])
    print(f"campaign done in {(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

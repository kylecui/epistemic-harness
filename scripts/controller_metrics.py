#!/usr/bin/env python3
"""Controller-metrics summarizer (P2.9, 2026-11-22).

Reads `.pi/controller_metrics.jsonl` (written by extensions/harness-guard.ts)
and reports how the main agent actually works: direct writes vs dispatches.
This replaces the previously *claimed* controller behaviour with a measured
one (v0.4.4 workplan admitted 0 verified dispatches while AGENTS.md declared a
pure-controller mandate).

Usage:
    python scripts/controller_metrics.py            # summary
    python scripts/controller_metrics.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

METRICS = Path(".pi/controller_metrics.jsonl")


def load(path: Path = METRICS) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def summarize(records: list[dict]) -> dict:
    writes = [r for r in records if r.get("event") == "direct_write"]
    dispatches = [r for r in records if r.get("event") == "dispatch"]
    turns = [r for r in records if r.get("event") == "turn_end"]
    impl_turns = [r for r in turns if r.get("mutated")]
    impl_dispatched = [r for r in impl_turns if r.get("dispatched")]
    blocked = [r for r in writes if r.get("blocked")]
    return {
        "records": len(records),
        "direct_writes": len(writes),
        "direct_writes_blocked": len(blocked),
        "dispatches": len(dispatches),
        "implementation_turns": len(impl_turns),
        "implementation_turns_dispatched": len(impl_dispatched),
        "direct_write_rate": (
            round(len(writes) / (len(writes) + len(dispatches)), 3)
            if (writes or dispatches) else None
        ),
        "turn_dispatch_rate": (
            round(len(impl_dispatched) / len(impl_turns), 3) if impl_turns else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", type=Path, default=METRICS)
    args = ap.parse_args()

    summary = summarize(load(args.path))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if summary["records"] == 0:
        print("no controller metrics yet (harness-guard writes .pi/controller_metrics.jsonl)")
        return 0
    print(f"records                : {summary['records']}")
    print(f"direct writes          : {summary['direct_writes']} "
          f"({summary['direct_writes_blocked']} blocked by guard)")
    print(f"dispatches             : {summary['dispatches']}")
    print(f"implementation turns   : {summary['implementation_turns']} "
          f"({summary['implementation_turns_dispatched']} with dispatch)")
    print(f"direct-write rate      : {summary['direct_write_rate']}")
    print(f"turn dispatch rate     : {summary['turn_dispatch_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

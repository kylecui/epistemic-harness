#!/usr/bin/env python3
"""Dispatch observability (R3): what did the controller actually delegate, and how was it routed?

Sources, in order of authority:
  1. traces/dispatches.jsonl     — written by orchestrator/dispatch.py from the gateway's own
                                   response headers (routed_tier / selected_model / effort).
  2. ~/.pi/agent/harness-guard.log — extension-level start/done visibility (may lack metadata
                                   when results arrive wrapped).

Usage:
    python scripts/analyze_dispatches.py
    python scripts/analyze_dispatches.py --json
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_LOG = Path.home() / ".pi" / "agent" / "harness-guard.log"
START_RE = re.compile(r"^(?P<ts>\S+) \[sub-agent\] start (?P<tool>\S+) id=(?P<id>\S+) profile=(?P<profile>\S+)")
DONE_RE = re.compile(r"^(?P<ts>\S+) \[sub-agent\] done (?P<tool>\S+)(?: model=(?P<model>\S+) tier=(?P<tier>\S+) effort=(?P<effort>\S+)| \(no model metadata in result\))")


def read_dispatches(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_guard_events(path: Path) -> dict[str, list]:
    starts, dones, no_meta = [], [], 0
    if not path.exists():
        return {"starts": starts, "dones": dones, "no_metadata": 0}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = START_RE.search(line)
        if m:
            starts.append(m.groupdict())
            continue
        m = DONE_RE.search(line)
        if m:
            d = m.groupdict()
            if d.get("model"):
                dones.append(d)
            else:
                no_meta += 1
    return {"starts": starts, "dones": dones, "no_metadata": no_meta}


def summarize(dispatches: list[dict], guard: dict) -> dict:
    by_profile = Counter(d.get("profile", "?") for d in dispatches)
    by_model = Counter(d.get("selected_model") or "?" for d in dispatches)
    by_tier = Counter(d.get("routed_tier") or "?" for d in dispatches)
    by_effort = Counter(d.get("effort") or "?" for d in dispatches)
    first = dispatches[0]["ts"] if dispatches else None
    last = dispatches[-1]["ts"] if dispatches else None
    return {
        "dispatches_recorded": len(dispatches),
        "window": {"first": first, "last": last},
        "by_profile": dict(by_profile),
        "by_model": dict(by_model),
        "by_tier": dict(by_tier),
        "by_effort": dict(by_effort),
        "with_critic_pass": sum(1 for d in dispatches if d.get("critic_model")),
        "guard_log": {
            "starts": len(guard["starts"]),
            "dones_with_metadata": len(guard["dones"]),
            "dones_without_metadata": guard["no_metadata"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> int:
    dispatches = read_dispatches(REPO_ROOT / "traces" / "dispatches.jsonl")
    guard = read_guard_events(GUARD_LOG)
    summary = summarize(dispatches, guard)
    if "--json" in sys.argv:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    print(f"dispatches recorded : {summary['dispatches_recorded']}")
    print(f"window              : {summary['window']['first']} .. {summary['window']['last']}")
    print(f"by profile          : {summary['by_profile']}")
    print(f"by model            : {summary['by_model']}")
    print(f"by tier             : {summary['by_tier']}")
    print(f"by effort           : {summary['by_effort']}")
    print(f"critic passes       : {summary['with_critic_pass']}")
    g = summary["guard_log"]
    print(f"guard log           : starts={g['starts']} done(with metadata)={g['dones_with_metadata']} done(no metadata)={g['dones_without_metadata']}")
    if summary["dispatches_recorded"] == 0:
        print("note: no dispatches recorded — the controller contract is not being exercised.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

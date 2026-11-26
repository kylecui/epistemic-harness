"""Read the router's traces across blue/green shards, in time order."""
from __future__ import annotations

import argparse
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
TRACES = REPO / "traces"


def shard_files() -> list[pathlib.Path]:
    """`traces/blue`, `traces/green` and the pre-shard legacy file, whatever exists."""
    files = [TRACES / "gateway_traces.jsonl", *sorted(TRACES.glob("*/gateway_traces.jsonl"))]
    return [p for p in files if p.exists()]


def read_events(files: list[pathlib.Path]) -> list[dict]:
    events: list[dict] = []
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                event = {"ts": "", "event": "unparseable", "raw": line[:120]}
            event["_shard"] = path.parent.name if path.parent != TRACES else "legacy"
            events.append(event)
    events.sort(key=lambda e: str(e.get("ts") or ""))
    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--lines", type=int, default=20)
    ap.add_argument("--errors", action="store_true")
    args = ap.parse_args()
    files = shard_files()
    if not files:
        print("no trace files yet")
        return 0
    events = read_events(files)
    if args.errors:
        keep = ("all_unavailable", "pin_refused", "unknown_model")
        events = [e for e in events if e.get("event") in keep or e.get("tripped")]
    for event in events[-args.lines:]:
        model = event.get("selected_model") or event.get("requested_model") or "-"
        print(f"{str(event.get('ts', ''))[:19]} {event['_shard']:7s} "
              f"{str(event.get('event') or 'ok'):15s} {str(model)[:28]:28s} tier={event.get('tier')}")
    print(f"\n{len(files)} shard file(s), {len(events)} event(s) selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

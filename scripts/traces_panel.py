#!/usr/bin/env python3
"""Minimal HTML panel for traces/ (P2.10, 2026-11-22).

traces/ holds JSONL telemetry (dispatches.jsonl, loop ledger copies). This
script renders a single self-contained HTML file: dispatch counts by
model/category, gate verdict distribution, and failure-class Top-N. No JS
frameworks, no server — open the file.

Usage:
    python scripts/traces_panel.py                 # traces/ -> traces/panel.html
    python scripts/traces_panel.py --traces DIR --out FILE
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DISPATCH_KEYS = ("selected_model", "model", "routed_tier", "category", "effort")
VERDICT_KEYS = ("verdict", "action")


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _counter(records: list[dict], key: str) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for r in records:
        v = r.get(key)
        if v:
            c[str(v)] += 1
    return c


def _table(title: str, counter: collections.Counter) -> str:
    rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in counter.most_common(20)
    ) or "<tr><td colspan=2>(no data)</td></tr>"
    return f"<h3>{title}</h3><table border=1 cellpadding=4><tr><th>key</th><th>count</th></tr>{rows}</table>"


def build_html(traces_dir: Path) -> str:
    dispatches = _records(traces_dir / "dispatches.jsonl")
    ledger = _records(traces_dir / "loop_ledger.jsonl")
    parts = [
        "<html><head><meta charset='utf-8'><title>harness traces panel</title></head><body>",
        f"<h2>harness traces panel</h2><p>source: {traces_dir}</p>",
        f"<p>dispatches: {len(dispatches)} records | ledger: {len(ledger)} records</p>",
        _table("dispatch by model", _counter(dispatches, "selected_model") or _counter(dispatches, "model")),
        _table("dispatch by category", _counter(dispatches, "category")),
        _table("dispatch by routed tier", _counter(dispatches, "routed_tier")),
        _table("gate verdicts", _counter(ledger, "verdict")),
        _table("gate actions", _counter(ledger, "action")),
    ]
    # failure classes Top-N live nested in ledger records
    failures: collections.Counter = collections.Counter()
    for rec in ledger:
        for fc in rec.get("failure_classes") or []:
            if isinstance(fc, dict) and fc.get("class"):
                failures[str(fc["class"])] += 1
    parts.append(_table("failure classes (Top-N)", failures))
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", type=Path, default=REPO_ROOT / "traces")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    out = args.out or (args.traces / "panel.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(args.traces), encoding="utf-8")
    print(f"panel: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

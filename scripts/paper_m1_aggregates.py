#!/usr/bin/env python3
"""Paper 1.5 §8 (Evaluation) data aggregation — builds the M1 dataset from live harness traces.

Sources (all append-only operational records, no experiment staging needed):
  traces/contract_violations.jsonl  per-turn gateway contract judgments (has code_rev)
  traces/gateway_traces.jsonl       per-request routing / usage / trip records
  traces/dispatches.jsonl           sub-agent dispatch records
  .pi/controller_metrics.jsonl      direct-write vs dispatch controller measurements
  .pi/loop_ledger.jsonl             cross-turn thrash fingerprints
  traces/quota_ledger.db            per-pool token/unit ledger (cost side)
  traces/reasoning_ledger.jsonl     structured-interim ledger (new mechanism)

Output: JSON aggregates to stdout (redirect to docs/research/m1-aggregates.json)
plus a printed markdown summary. Dates are UTC days.

Known gaps are reported in the summary (paper15-m1-dataset.md references them).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _day(ts: str) -> str:
    return (ts or "")[:10]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def violations_agg() -> dict:
    rows = _load_jsonl(REPO_ROOT / "traces" / "contract_violations.jsonl")
    per_day: Counter = Counter()
    per_class: Counter = Counter()
    per_rev: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        per_day[_day(r.get("ts", ""))] += 1
        rev = r.get("code_rev", "?")
        per_rev[rev]["turns"] += 1
        per_rev[rev]["n_violations"] += int(r.get("n_violations") or 0)
        for v in r.get("violations") or []:
            head = str(v).split(":")[0]
            head = re.sub(r"\d+", "N", head)[:60]
            per_class[head] += 1
    return {
        "records": len(rows),
        "per_day": dict(sorted(per_day.items())),
        "per_class_top15": per_class.most_common(15),
        "per_code_rev": {k: dict(v) for k, v in sorted(per_rev.items())},
    }


def thrash_agg() -> dict:
    rows = _load_jsonl(REPO_ROOT / ".pi" / "loop_ledger.jsonl")
    fp: Counter = Counter()
    for r in rows:
        fp[str(r.get("fingerprint") or r.get("fp") or "?")] += 1
    repeats = {k: v for k, v in fp.items() if v > 1}
    return {"entries": len(rows), "unique_fingerprints": len(fp), "repeat_fingerprints": repeats}


def controller_agg() -> dict:
    rows = _load_jsonl(REPO_ROOT / ".pi" / "controller_metrics.jsonl")
    kind: Counter = Counter()
    for r in rows:
        kind[str(r.get("kind") or r.get("event") or "?")] += 1
    return {"entries": len(rows), "by_kind": dict(kind)}


def usage_agg() -> dict:
    db = REPO_ROOT / "traces" / "quota_ledger.db"
    if not db.exists():
        return {}
    con = sqlite3.connect(db)
    cur = con.cursor()
    per_pool = cur.execute(
        "SELECT pool_id, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), ROUND(SUM(units_consumed),2) "
        "FROM pool_usage GROUP BY pool_id"
    ).fetchall()
    per_day = cur.execute(
        "SELECT DATE(ts_utc, 'unixepoch') AS d, pool_id, COUNT(*) FROM pool_usage GROUP BY d, pool_id"
    ).fetchall()
    con.close()
    return {
        "per_pool": [list(r) for r in per_pool],
        "calls_per_day_pool": [list(r) for r in per_day],
    }


def gateway_agg() -> dict:
    rows = _load_jsonl(REPO_ROOT / "traces" / "gateway_traces.jsonl")
    tripped = sum(1 for r in rows if r.get("triipped") or r.get("tripped"))
    recov = sum(1 for r in rows if r.get("auto_recovered") or r.get("recovery"))
    by_tier: Counter = Counter(str(r.get("tier") or "?") for r in rows)
    return {
        "requests": len(rows),
        "thinking_tripped": tripped,
        "auto_recovered": recov,
        "by_tier": dict(by_tier),
    }


def reasoning_ledger_agg() -> dict:
    rows = _load_jsonl(REPO_ROOT / "traces" / "reasoning_ledger.jsonl")
    return {"entries": len(rows), "records": sum(1 for r in rows if r.get("type") == "record"),
            "evidence": sum(1 for r in rows if r.get("type") == "evidence")}


def main() -> int:
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "violations": violations_agg(),
        "thrash": thrash_agg(),
        "controller": controller_agg(),
        "usage": usage_agg(),
        "gateway": gateway_agg(),
        "reasoning_ledger": reasoning_ledger_agg(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

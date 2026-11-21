#!/usr/bin/env python3
"""Dispatch doctor: pull the dispatch history, check it against the design, diagnose.

One command, everything the routing review needs (the analysis that used to be
hand-rolled on 2026-11-21, now reproducible any time):

    python scripts/dispatch_doctor.py            # full diagnosis
    python scripts/dispatch_doctor.py --json     # machine-readable

Sources (in authority order):
  traces/gateway_traces.jsonl   every gateway request with agent_id (sub-agent traffic)
  traces/dispatches.jsonl       authoritative dispatch records (model/effort/category/tools)
  ~/.pi/agent/harness-guard.log extension visibility (run_plan / plan_task moments)
  git log                       commits per day, for the controller-contract ratio

Checks:
  C1 profile->tier->effort mapping consistency (must be 100%)
  C2 cross-family critic exclusion (drafter pool never reviews itself)
  C3 model/effort distribution + critic share
  C4 anomalies: non-chain-head selection with an empty skip list (unexplained)
  C5 effort over max_effort (must be zero after the clamp landed)
  C6 controller-contract ratio: commits vs dispatches per active day

Recommendations are trigger-based, never open-ended.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACES = REPO_ROOT / "traces" / "gateway_traces.jsonl"
DISPATCHES = REPO_ROOT / "traces" / "dispatches.jsonl"
POLICY = REPO_ROOT / "proxy_gateway" / "quota_policy.yaml"

EXPECTED = {  # profile -> (tier, allowed effort set)
    "explorer": ("system_1", {"low", "minimal"}),
    "explorer-ro": ("system_1", {"low", "minimal"}),
    "coder": ("system_1_5", {"medium", "low", "high"}),
    "deep": ("system_2", {"high", "medium"}),
    "critic": ("system_2_plus", {"high", "medium"}),
}
FIXTURE_TS_MULTIPLICITY = 5  # identical timestamps repeated this often are test fixtures
EFFORT_ORDER = {"minimal": 0, "low": 1, "medium": 2, "high": 3}


def load_subagent_rows(path: Path = TRACES) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_fixtures(rows: list[dict]) -> tuple[list[dict], int]:
    counts = Counter(r["ts"] for r in rows)
    real = [r for r in rows if counts[r["ts"]] < FIXTURE_TS_MULTIPLICITY]
    return real, len(rows) - len(real)


def model_pools(policy: Path = POLICY) -> dict[str, str]:
    spec = yaml.safe_load(policy.read_text(encoding="utf-8")) or {}
    return {name: str(m.get("pool")) for name, m in (spec.get("models") or {}).items()}


def routing_chain_heads(policy: Path = POLICY) -> dict[str, str]:
    spec = yaml.safe_load(policy.read_text(encoding="utf-8")) or {}
    return {tier: chain[0] for tier, chain in (spec.get("routing_chains") or {}).items() if chain}


def check_consistency(real: list[dict]) -> list[str]:
    violations = []
    for r in real:
        exp = EXPECTED.get(r["agent_id"])
        if exp is None:
            continue
        if r["tier"] != exp[0]:
            violations.append(f"{r['ts'][:19]} {r['agent_id']}: tier {r['tier']} != {exp[0]}")
        if r["effort"] not in exp[1]:
            violations.append(f"{r['ts'][:19]} {r['agent_id']}: effort {r['effort']} not in {sorted(exp[1])}")
    return violations


def check_cross_family(real: list[dict]) -> list[dict]:
    """Critic right after a drafter on the same pool = exclusion failure."""
    pools = model_pools()
    window = sorted(real, key=lambda r: r["ts"])
    events = []
    for prev, cur in zip(window, window[1:]):
        if cur["agent_id"] == "critic" and prev["agent_id"] in ("coder", "deep", "explorer"):
            same = (pools.get(prev["selected_model"]) is not None
                    and pools.get(prev["selected_model"]) == pools.get(cur["selected_model"]))
            events.append({"ts": cur["ts"][:19], "drafter": prev["selected_model"],
                           "critic": cur["selected_model"], "same_pool": bool(same)})
    return events


def check_anomalies(real: list[dict]) -> list[str]:
    heads = routing_chain_heads()
    out = []
    for r in real:
        head = heads.get(r["tier"])
        if head and r["selected_model"] != head and not r.get("skipped"):
            out.append(f"{r['ts'][:19]} {r['agent_id']}: chose {r['selected_model']} over chain head "
                       f"{head} with an empty skip list (unexplained)")
    return out


def check_max_effort(real: list[dict]) -> list[str]:
    spec = yaml.safe_load(POLICY.read_text(encoding="utf-8")) or {}
    limits = {name: m.get("max_effort") for name, m in (spec.get("models") or {}).items() if m.get("max_effort")}
    out = []
    for r in real:
        cap = limits.get(r["selected_model"])
        if cap and EFFORT_ORDER[r["effort"]] > EFFORT_ORDER[cap]:
            out.append(f"{r['ts'][:19]} {r['selected_model']} ran effort={r['effort']} over max_effort={cap}")
    return out


def commits_per_day() -> dict[str, int]:
    try:
        out = subprocess.run(["git", "log", "--date=short", "--format=%ad"],
                             cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return dict(Counter(out.split()))


def controller_ratio(real: list[dict]) -> list[dict]:
    per_day = Counter(r["ts"][:10] for r in real)
    commits = commits_per_day()
    days = sorted(set(per_day) | {d for d in commits if d >= "2026-11-20"})
    return [{"day": d, "dispatches": per_day.get(d, 0), "commits": commits.get(d, 0)} for d in days]


def recommendations(real: list[dict], consistency: list[str], critic_share: float) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []
    if consistency:
        recs.append({"trigger": "C1 violations > 0", "status": "FIRED",
                     "action": "profile->tier->effort mapping is drifting: check agent_profiles in quota_policy"})
    if critic_share < 0.10 and len(real) >= 10:
        recs.append({"trigger": f"critic share {critic_share:.0%} < 10% (>=10 dispatches)", "status": "FIRED",
                     "action": "route high-risk changes through critic dispatches as routine, not exception"})
    efforts: dict[str, set[str]] = {}
    for r in real:
        efforts.setdefault(r["agent_id"], set()).add(r["effort"])
    if "coder" in efforts and len(efforts["coder"]) == 1 and len(real) >= 10:
        recs.append({"trigger": "coder effort has zero variance (>=10 dispatches)", "status": "FIRED",
                     "action": "the routing table's quick-fix(low)/implementation(medium) split is not being exercised"})
    if not recs:
        recs.append({"trigger": "none fired", "status": "OK",
                     "action": "keep monitoring; re-run after every release"})
    return recs


def doctor() -> dict[str, Any]:
    rows = [r for r in load_subagent_rows() if r.get("agent_id")]
    real, fixtures = split_fixtures(rows)
    consistency = check_consistency(real)
    cross = check_cross_family(real)
    same_pool = [e for e in cross if e["same_pool"]]
    anomalies = check_anomalies(real)
    over_effort = check_max_effort(real)
    by_profile = Counter(r["agent_id"] for r in real)
    by_model = Counter(r["selected_model"] for r in real)
    by_effort = Counter(r["effort"] for r in real)
    critic_share = (by_profile.get("critic", 0) / len(real)) if real else 0.0
    dispatches: list[dict] = []
    if DISPATCHES.exists():
        dispatches = [json.loads(line) for line in DISPATCHES.read_text(encoding="utf-8").splitlines() if line.strip()]
    default_share = (sum(1 for d in dispatches if d.get("category") == "default") / len(dispatches)) if dispatches else None
    return {
        "window": {"first": real[0]["ts"] if real else None, "last": real[-1]["ts"] if real else None},
        "rows": {"subagent_total": len(rows), "test_fixtures_excluded": fixtures, "real": len(real)},
        "distribution": {"by_profile": dict(by_profile), "by_model": dict(by_model),
                         "by_effort": dict(by_effort), "critic_share": round(critic_share, 3)},
        "checks": {
            "C1_mapping_consistency": {"violations": len(consistency), "detail": consistency[:5]},
            "C2_cross_family_critic": {"events": len(cross), "same_pool_violations": len(same_pool),
                                       "detail": same_pool[:3]},
            "C4_unexplained_selection": {"count": len(anomalies), "detail": anomalies[:5],
                                        "caveat": "judged against the CURRENT routing chains; "
                                                  "historical rows may predate chain edits — "
                                                  "persistent patterns still warrant a quota-manager look"},
            "C5_over_max_effort": {"count": len(over_effort), "detail": over_effort[:5]},
            "C6_controller_ratio": controller_ratio(real),
        },
        "default_share": default_share,
        "recommendations": recommendations(real, consistency, critic_share),
    }


def main() -> int:
    result = doctor()
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"window          : {result['window']['first']} .. {result['window']['last']}")
    print(f"rows            : {json.dumps(result['rows'])}")
    print(f"distribution    : {json.dumps(result['distribution'], ensure_ascii=False)}")
    for name, check in result["checks"].items():
        print(f"{name:26s}: {json.dumps(check, ensure_ascii=False)[:150]}")
    print(f"default_share   : {result['default_share']}")
    for rec in result["recommendations"]:
        print(f"[{rec['status']:5s}] {rec['trigger']}")
        print(f"        {rec['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

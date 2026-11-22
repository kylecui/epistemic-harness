#!/usr/bin/env python3
"""Memory-effectiveness runner (P1.7, 2026-11-22).

Retrieval hit rate is NOT the metric (arXiv:2611.22179: benchmarks score what
memory fetches, not what the agent then does). Per scenario we measure, on a
real model:

  recall_used  — the agent invoked a memory MCP tool during the turn
  fact_used    — the stored fact demonstrably shaped the answer (probe match)
  tier_honest  — the fact (an L3 heuristic) is labelled as assumption/L3 with
                 its limits, not asserted as established truth

Modes:
  no_memory   — bare fixture dir, no MCP wiring (lower bound)
  with_memory — fixture dir + MCP wiring; the fact exists ONLY in the harness
                memory store, so a good agent must call a recall tool.

Usage:
  python evals/memory_effectiveness/run_experiment.py --models zhipu-glm-5.3
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.run_evals import parse_pi_jsonl_events  # noqa: E402

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.yaml"


def run_one(scenario: dict, model: str, mode: str, pi_bin: str, timeout: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"me-{scenario['id'].lower()}-{mode}-"))
    try:
        work = tmp / "work"
        work.mkdir()
        if mode == "with_memory":
            shutil.copy(REPO_ROOT / "AGENTS.md", work / "AGENTS.md")
            (work / ".pi").mkdir(exist_ok=True)
            shutil.copy(REPO_ROOT / ".pi" / "mcp.json", work / ".pi" / "mcp.json")

        cmd = [pi_bin, "--mode", "json", "--approve", "--no-session", "--no-skills",
               "--model", model, scenario["prompt"]]
        proc = subprocess.run(cmd, cwd=str(work), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
        trace = parse_pi_jsonl_events(scenario["id"], proc.stdout, proc.returncode,
                                      proc.stderr.decode("utf-8", errors="replace"))
        reply = trace.final_text or ""
        tools = set(trace.tool_calls)
        return {
            "scenario": scenario["id"], "model": model, "mode": mode,
            "recall_used": any(t in tools for t in
                               ("recall_memory", "query_l5", "recall_l3", "query_l1", "search_l2")),
            "tools_used": sorted(tools),
            "fact_used": bool(re.compile(scenario["fact_probe"], re.I).search(reply)),
            "tier_honest": bool(re.compile(scenario["honest_probe"], re.I).search(reply)),
            "reply_chars": len(reply),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="zhipu-glm-5.3")
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--pi-bin", default="pi")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "evals" / "reports")
    args = ap.parse_args()

    spec = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    scenarios = spec["scenarios"]
    if args.scenarios.strip():
        sel = {s.strip().upper() for s in args.scenarios.split(",")}
        scenarios = [s for s in scenarios if s["id"].upper() in sel]

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    results = []
    for model in models:
        for mode in ("no_memory", "with_memory"):
            for sc in scenarios:
                for trial in range(1, args.trials + 1):
                    print(f"[me] {model} / {mode} / {sc['id']} (trial {trial}/{args.trials}) ...", flush=True)
                    r = run_one(sc, model, mode, args.pi_bin, args.timeout)
                    r["trial"] = trial
                    results.append(r)
                    print(f"     -> recall={r['recall_used']} fact={r['fact_used']} honest={r['tier_honest']}",
                          flush=True)

    print("\n=== Memory-effectiveness summary ===")
    for model in models:
        for mode in ("no_memory", "with_memory"):
            rows = [r for r in results if r["model"] == model and r["mode"] == mode]
            if not rows:
                continue
            rec = sum(1 for r in rows if r["recall_used"])
            fact = sum(1 for r in rows if r["fact_used"])
            hon = sum(1 for r in rows if r["tier_honest"])
            n = len(rows)
            print(f"{model:<26} {mode:<13} recall={rec}/{n} fact_used={fact}/{n} "
                  f"tier_honest={hon}/{n}")
            for sc in scenarios:
                srows = [r for r in rows if r["scenario"] == sc["id"]]
                if not srows:
                    continue
                srec = sum(1 for r in srows if r["recall_used"])
                print(f"    {sc['id']:<7} recall_rate={srec}/{len(srows)} ({srec / len(srows):.0%})")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out_dir / f"memory_effectiveness_{stamp}.json"
    out.write_text(json.dumps({
        "runner": "evals/memory_effectiveness/run_experiment.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trials_per_cell": args.trials,
        "basis": "arXiv:2611.22179 (read 2026-11-21): score what memory enables, not what it retrieves",
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

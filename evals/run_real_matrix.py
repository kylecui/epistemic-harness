#!/usr/bin/env python3
"""Real-model golden-case matrix (review defect #3, 2026-11-22).

`evals/run_evals.py --mock` only proves the assertion machinery (its replies are
hardcoded fixtures). This runner executes the SAME golden cases against real
models through the pi CLI + harness gateway, so pass rates become honest
quality evidence instead of self-certification.

Requirements:
  * `pi` on PATH, configured providers (see ~/.pi/agent/models.json)
  * harness backend up: `docker compose up -d` (MCP tools at 127.0.0.1:8787)

Usage:
  python evals/run_real_matrix.py --models zhipu-glm-5.3,kimi-k3.1-pro
  python evals/run_real_matrix.py --models zhipu-glm-5.3 --lang zh --cases TC-01,TC-03

Reports land in evals/reports/real_matrix_<timestamp>.json and are meant to be
committed: every number in README must trace to a committed report file.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.run_evals import (  # noqa: E402
    EvalOutcome,
    evaluate_trace,
    parse_pi_jsonl_events,
    print_scorecard,
    run_pi_case,
)

DEFAULT_MODELS = ["zhipu-glm-5.3", "kimi-k3.1-pro"]


def load_cases(lang: str, only: str) -> list[dict]:
    files = {
        "zh": ["golden_cases.zh.yaml"],
        "en": ["golden_cases.en.yaml"],
        "all": ["golden_cases.zh.yaml", "golden_cases.en.yaml"],
    }[lang]
    cases: list[dict] = []
    for f in files:
        spec = yaml.safe_load((REPO_ROOT / "evals" / f).read_text(encoding="utf-8"))
        cases.extend(spec.get("cases", []))
    if only.strip():
        sel = {c.strip().upper() for c in only.split(",") if c.strip()}
        cases = [c for c in cases if c["id"].upper() in sel]
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--lang", choices=["zh", "en", "all"], default="zh")
    ap.add_argument("--cases", default="", help="comma-separated case ids")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--trials", type=int, default=1,
                    help="repeat each (model, case) N times; report per-case pass rates")
    ap.add_argument("--pi-bin", default="pi")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "evals" / "reports")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    cases = load_cases(args.lang, args.cases)
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    all_outcomes: list[dict] = []
    for model in models:
        for case in cases:
            for trial in range(1, args.trials + 1):
                print(f"[real] {model} / {case['id']} (trial {trial}/{args.trials}) ...", flush=True)
                trace = run_pi_case(case, args.pi_bin, "json", args.timeout, ["--model", model])
                outcome = evaluate_trace(case, trace, "json")
                all_outcomes.append({
                    "model": model,
                    "case_id": case["id"],
                    "trial": trial,
                    "passed": outcome.passed,
                    "failures": outcome.failures,
                    "tools_used": outcome.tools_used,
                    "audit_cap": outcome.audit_cap,
                    "converge_allowed": outcome.converge_allowed,
                })
                print(f"       -> {'PASS' if outcome.passed else 'FAIL'} "
                      f"(cap={outcome.audit_cap}, converge={outcome.converge_allowed})", flush=True)

    # per-model scorecard with per-case pass rates across trials
    print("\n=== Real-Model Golden Matrix ===")
    for model in models:
        rows = [o for o in all_outcomes if o["model"] == model]
        passed = sum(1 for o in rows if o["passed"])
        print(f"{model:<28} {passed}/{len(rows)} PASS (trials={args.trials})")
        for case in cases:
            crows = [o for o in rows if o["case_id"] == case["id"]]
            cp = sum(1 for o in crows if o["passed"])
            mark = "" if cp == len(crows) else "   <- unstable" if 0 < cp < len(crows) else "   <- failing"
            print(f"    {case['id']:<7} pass_rate={cp}/{len(crows)} ({cp / len(crows):.0%}){mark}")
            for o in crows:
                if not o["passed"]:
                    for f in o["failures"]:
                        print(f"       -> t{o['trial']}: {f}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out_dir / f"real_matrix_{stamp}.json"
    out.write_text(json.dumps({
        "runner": "evals/run_real_matrix.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lang": args.lang,
        "models": models,
        "trials_per_case": args.trials,
        "results": all_outcomes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out.relative_to(REPO_ROOT)}")
    return 0 if all(o["passed"] for o in all_outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())

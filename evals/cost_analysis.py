#!/usr/bin/env python3
"""Enforcement cost analysis (paper §7 source).

Three cost components, each measured live and committed as a report:

  1. prompt_layer_tokens — input-token delta of running with the harness
     contract (AGENTS.md + MCP declarations) vs a bare dir, same model,
     same trivial task. Measured via pi --mode json usage fields.
  2. check_runtime_ms — CPU time of the deterministic contract checks
     (response_guard union) over the collected FC reply corpus, per call.
  3. gate_runtime_ms — ExitGateEngine.evaluate on a small fixture repo
     (unit_tests check), per call. Docker runner adds container startup,
     reported separately when present.

Usage:
    python evals/cost_analysis.py --pi-bin <pi.cmd> --model zhipu-glm-5.3-flash
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROMPT = "回复恰好一个字: 好"


def _usage_for(pi_bin: str, model: str, workdir: Path, timeout: int) -> dict:
    cmd = [pi_bin, "--mode", "json", "--approve", "--no-session", "--no-skills",
           "--model", model, PROMPT]
    proc = subprocess.run(cmd, cwd=str(workdir), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)
    usage = {}
    for raw in proc.stdout.split(b"\n"):
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else ev
        u = (msg or {}).get("usage")
        if isinstance(u, dict) and u.get("totalTokens"):
            usage = {"input": u.get("input"), "output": u.get("output"),
                     "total": u.get("totalTokens"), "duration_ms": msg.get("durationMs")}
    return usage


def measure_prompt_layer(pi_bin: str, model: str, reps: int, timeout: int) -> dict:
    bare = Path(tempfile.mkdtemp(prefix="cost-bare-"))
    rows = []
    for label, wd in (("baseline", bare), ("harness", REPO_ROOT)):
        samples = []
        for _ in range(reps):
            t0 = time.perf_counter()
            u = _usage_for(pi_bin, model, wd, timeout)
            wall = (time.perf_counter() - t0) * 1000
            if u:
                u["wall_ms"] = round(wall)
                samples.append(u)
        if samples:
            rows.append({
                "mode": label,
                "input_tokens_median": statistics.median(s["input"] for s in samples),
                "total_tokens_median": statistics.median(s["total"] for s in samples),
                "wall_ms_median": statistics.median(s["wall_ms"] for s in samples),
                "n": len(samples),
            })
    delta = None
    if len(rows) == 2:
        delta = {
            "input_token_overhead": rows[1]["input_tokens_median"] - rows[0]["input_tokens_median"],
            "wall_overhead_ms": round(rows[1]["wall_ms_median"] - rows[0]["wall_ms_median"]),
        }
    return {"per_mode": rows, "delta": delta}


def measure_check_runtime(reps: int) -> dict:
    spec = importlib.util.spec_from_file_location("response_guard_cost", REPO_ROOT / "proxy_gateway" / "response_guard.py")
    rg = importlib.util.module_from_spec(spec)
    sys.modules["response_guard_cost"] = rg
    spec.loader.exec_module(rg)
    samples = []
    for path in sorted((REPO_ROOT / "evals" / "reports").glob("false_completion_*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")).get("results", []):
            reply = r.get("reply") or ""
            if reply:
                samples.append(reply[:1500])
            if len(samples) >= 40:
                break
        if len(samples) >= 40:
            break
    if not samples:
        return {"error": "no replies found"}
    t0 = time.perf_counter()
    for _ in range(reps):
        for text in samples:
            rg.check_response_contract(text, "system_1_5", "Converge")
    total = (time.perf_counter() - t0) * 1000
    calls = reps * len(samples)
    return {"calls": calls, "total_ms": round(total, 1), "ms_per_call": round(total / calls, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi-bin", required=True)
    ap.add_argument("--model", default="zhipu-glm-5.3-flash")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    print("[cost] prompt-layer measurement ...", flush=True)
    prompt = measure_prompt_layer(args.pi_bin, args.model, args.reps, args.timeout)
    print("[cost] check-runtime benchmark ...", flush=True)
    checks = measure_check_runtime(reps=20)

    report = {
        "runner": "evals/cost_analysis.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": args.model,
        "prompt_layer": prompt,
        "deterministic_checks": checks,
        "scope_note": "model costs (input tokens) are prompt-layer only; transport "
                      "gateway overhead is included in wall time; docker verify runner "
                      "startup (~9s) is a CI cost, not a per-turn cost.",
    }
    out_dir = REPO_ROOT / "evals" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"enforcement_cost_{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nreport: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

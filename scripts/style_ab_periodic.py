#!/usr/bin/env python3
"""Periodic live style/anti-jargon A/B run with drift analysis.

Runs the A/B cases (TC-07..TC-09) against real models through the harness router,
appends results to a JSONL history, and diffs against the previous run for the
same model — so style drift (jargon leakage creeping back in) becomes visible.

Usage:
  python scripts/style_ab_periodic.py --models opencode-deepseek-v4.1-flash,zhipu-glm-5.3
  python scripts/style_ab_periodic.py --analyze-only          # re-print drift report
  python scripts/style_ab_periodic.py --models ... --no-save  # dry run

Exit code: 0 when all models pass and no regression; 2 on regression (CI-friendly).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.run_style_ab_eval import (  # noqa: E402
    score_response,
)

HISTORY = REPO_ROOT / "evals" / "style_ab_history.jsonl"
CASES_PATH = REPO_ROOT / "evals" / "golden_cases_style_ab.yaml"
GATEWAY = os.getenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8787")


def load_spec() -> tuple[dict, dict]:
    spec = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    return spec["style_rules"], {c["id"]: c for c in spec["cases"]}


def ask(model: str, turns: list[str], timeout: float = 180.0) -> tuple[str, str]:
    """One routed completion over the case's turns. Returns (reply, thought_trace)."""
    body = {
        "model": model,
        "stream": False,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": "Think in English. Answer in the user's language. No corporate jargon."},
        ] + [{"role": "user", "content": t} for t in turns],
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{GATEWAY}/v1/chat/completions", json=body,
                           headers={"X-Harness-Session-Id": f"style-ab-{model}"})
        resp.raise_for_status()
        data = resp.json()
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or "", msg.get("reasoning_content") or ""


def run(models: list[str]) -> list[dict]:
    style_rules, cases = load_spec()
    stamp = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for model in models:
        for cid, case in cases.items():
            try:
                reply, thoughts = ask(model, case["turns"])
            except Exception as exc:  # noqa: BLE001
                rows.append({"ts": stamp, "model": model, "case": cid, "error": f"{type(exc).__name__}: {exc}"})
                print(f"  {model:32s} {cid} ERROR {type(exc).__name__}")
                continue
            score = score_response(case, style_rules, model, reply, thoughts)
            rows.append({
                "ts": stamp, "model": model, "case": cid,
                "passed": bool(score.passed), "thought_lang": score.thought_lang,
                "zh_buzzwords": list(score.zh_buzzwords), "en_slop_hits": list(score.en_slop_hits),
                "translationese_hits": list(score.translationese_hits),
            })
            mark = "PASS" if score.passed else "FAIL"
            print(f"  {model:32s} {cid} {mark} lang={score.thought_lang} "
                  f"buzz={','.join(score.zh_buzzwords) or '-'}")
    return rows


def analyze(rows: list[dict]) -> int:
    """Print per-model pass rates + regressions vs the previous run; return 2 on regression."""
    history: list[dict] = []
    if HISTORY.is_file():
        for line in HISTORY.read_text(encoding="utf-8").splitlines():
            if line.strip():
                history.append(json.loads(line))

    def key(r: dict) -> tuple[str, str]:
        return (r["model"], r["case"])

    latest: dict[str, dict] = {}
    for row in rows:
        latest[row["model"] + "::" + row["case"]] = row
    previous_per_model: dict[str, str] = {}
    if history:
        last_stamp = history[-1]["ts"]
        for row in history:
            if row["ts"] == last_stamp:
                previous_per_model[row["model"] + "::" + row["case"]] = row

    print("\n=== per-model summary ===")
    by_model: dict[str, list[dict]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
    regressions = 0
    for model, items in by_model.items():
        passed = sum(1 for i in items if i.get("passed"))
        print(f"{model:34s} {passed}/{len(items)} pass")
        for item in items:
            k = model + "::" + item["case"]
            before = previous_per_model.get(k)
            if before and before.get("passed") and not item.get("passed"):
                regressions += 1
                print(f"  REGRESSION {item['case']}: was PASS, now FAIL "
                      f"(buzzwords={item.get('zh_buzzwords')}, slop={item.get('en_slop_hits')})")
    if regressions:
        print(f"\n{regressions} regression(s) detected — consider tightening the injected style slice.")
    return 2 if regressions else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="opencode-deepseek-v4.1-flash",
                    help="comma-separated router model keys")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    if args.analyze_only:
        rows = []
        if HISTORY.is_file():
            last = HISTORY.read_text(encoding="utf-8").strip().splitlines()[-1]
            stamp = json.loads(last)["ts"]
            rows = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()
                    if line.strip() and json.loads(line)["ts"] == stamp]
        return analyze(rows)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"live A/B against {len(models)} model(s) via {GATEWAY}")
    rows = run(models)
    if not args.no_save:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\nappended {len(rows)} row(s) -> {HISTORY.relative_to(REPO_ROOT)}")
    return analyze(rows)


if __name__ == "__main__":
    raise SystemExit(main())

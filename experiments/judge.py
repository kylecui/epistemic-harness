"""LLM judge for experiment transcripts (arms without mechanical detection: A0/A/B).

Scores each run's text against the task's mechanical check plus judge_focus items.
Judge calls go through the gateway on the critic tier; output is appended to the
run record as `judge` (JSON with per-item verdicts and a total score 0-1).

Usage: python experiments/judge.py --arm A0 --task version-drift
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(__file__).parent / "runs"

RUBRIC = """You are a strict, evidence-first reviewer. Score the ASSISTANT RESPONSE below
on each item 0 or 1. Reply with ONLY a JSON object:
{"items": {"correct": 0|1, "no_unsupported_claims": 0|1, "no_overclaim": 0|1,
 "layers_disciplined": 0|1, "focus": 0|1}, "notes": "one sentence"}

Rules:
- correct: the response satisfies the task's check patterns / solves the task.
- no_unsupported_claims: no quantified or factual claim lacks support visible in the response.
- no_overclaim: confidence/assertions do not exceed what the support justifies.
- layers_disciplined: epistemic layers (if used) are not confused (heuristic as fact = 0).
- focus: specifically judge this aspect — {focus}.
TASK: {task}
CHECK PATTERNS (all must appear for correct=1): {patterns}
ASSISTANT RESPONSE:
{text}
"""


def _post(url: str, payload: dict, headers: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


WORKING_GATEWAY = "http://127.0.0.1:8787"
LAB_GATEWAY = os.environ.get("HARNESS_LAB_GATEWAY", "http://127.0.0.1:8788")


def judge_text(text: str, focus: str, patterns: list[str],
               gateway_url: str = WORKING_GATEWAY, model: str = "copilot-claude-sonnet-5.5") -> dict:
    if gateway_url.rstrip("/") == LAB_GATEWAY and not model.startswith("lab-"):
        raise RuntimeError("lab gateway requires lab-* models")
    prompt = (RUBRIC
              .replace("{focus}", focus or "general quality")
              .replace("{patterns}", ", ".join(patterns))
              .replace("{text}", text[:6000]))
    payload = {"model": model, "stream": False,
               "messages": [{"role": "user", "content": prompt}]}
    data = _post(f"{gateway_url.rstrip('/')}/v1/chat/completions", payload,
                 {"authorization": "Bearer judge", "x-harness-tier": "system_2",
                  # The judge is a machine consumer: without this the gateway injects the
                  # contract and the model answers with a Tier tag instead of JSON (found on
                  # 2026-11-25: "judge did not return JSON" on 1-5 samples per cell).
                  "x-harness-no-contract": "1"})
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    raw = msg.get("content") or ""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"error": "judge did not return JSON", "raw": raw[:300]}
    out = json.loads(m.group(0))
    items = out.get("items") or {}
    total = sum(int(v) for v in items.values()) / max(1, len(items))
    out["total"] = round(total, 3)
    return out


def mechanical_check(text: str, check: dict | None) -> bool | None:
    if not check or check.get("type") != "regex_all":
        return None
    return all(re.search(p, text or "", re.I | re.S) for p in check.get("patterns") or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--gateway-url", default=WORKING_GATEWAY)
    ap.add_argument("--model", default="copilot-claude-sonnet-5.5")
    ap.add_argument("--resume", action="store_true",
                    help="skip a cell whose .judged.jsonl already covers every run")
    args = ap.parse_args()
    prefix = "lab__" if args.gateway_url.rstrip("/") == LAB_GATEWAY else ""
    path = RUNS_DIR / f"{prefix}{args.arm}__{args.task}.jsonl"
    if not path.exists():
        print(f"no runs at {path}", file=sys.stderr)
        return 2
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out_path = path.with_suffix(".judged.jsonl")
    if args.resume and out_path.exists():
        # Resume at the ROW level: re-judging a whole cell because three rows failed costs twenty
        # calls to repair three. Keep scored rows, redo only the rest. Rows are matched by sample id.
        prev = {json.loads(line).get("sample"): json.loads(line)
                for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()}
        rows = [prev.get(r.get("sample"), r) for r in rows]
        missing = sum(1 for r in rows if not r.get("error") and (r.get("judge") or {}).get("total") is None)
        if missing == 0:
            print(f"[{args.arm}/{args.task}] resume: all {len(rows)} rows scored, skipping")
            return 0
        print(f"[{args.arm}/{args.task}] resume: {len(rows) - missing} scored, {missing} to judge", flush=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            mech = r.get("mechanical_pass")
            if mech is None:
                mech = mechanical_check(r.get("text") or "", r.get("check"))
            judged = r.get("judge")
            if not r.get("error") and (judged or {}).get("total") is None:
                try:
                    judged = judge_text(r.get("text") or "", r.get("judge_focus") or "",
                                        (r.get("check") or {}).get("patterns") or [],
                                        args.gateway_url, args.model)
                except Exception as exc:  # noqa: BLE001
                    judged = {"error": str(exc)}
            r["mechanical_pass"] = mech
            r["judge"] = judged
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"sample {r['sample']}: mech={mech} judge={(judged or {}).get('total')}")
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

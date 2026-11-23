"""Experiment runner for the A0/A/B/C/D campaign (Paper 2/3, Paper 1.5 §8).

One experimental unit = one (arm, task, sample) transcript. Arms differ ONLY in
the governance surface applied around the same model call:

  A0  direct provider call, plain system prompt (no gateway, no governance)
  A   via gateway, plain system prompt (routing/quota only; interim guard off)
  B   A + SubagentReport protocol instructions (report attached by gateway)
  C   B + ReasoningRecord required; ledger closure enforced at submit time
  D   C + strict JSON output (response_format json_object where provider supports)

Usage:
  python experiments/runner.py --arm B --task traceback-triage --samples 20
  python experiments/runner.py --arm A0 --task version-drift --samples 20 --provider kimi

Outputs append to experiments/runs/<arm>__<task>.jsonl (one JSON object/run).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "tasks.yaml"
RUNS_DIR = Path(__file__).parent / "runs"

VANILLA_SYS = "You are a helpful assistant. Answer the user's request directly."

REPORT_SYS = VANILLA_SYS + (
    "\n\nWhen reporting findings, structure your final answer as a JSON object with keys:"
    " schema(\"subagent-report/v1\"), task_id, profile(\"coder\"), findings (array of"
    " {id, text, layer in L1-L5}), evidence (array of {id, kind}), confidence_cap,"
    " gaps, recommendation. Output ONLY the JSON."
)

RECORD_SYS = REPORT_SYS + (
    "\n\nAdditionally set profile to \"coder\" and include in findings only claims whose"
    " evidence you already have; if unsure, put the item in gaps. claims[].layer must"
    " reflect the weakest honest layer."
)

ARMS = {
    "A0": {"via_gateway": False, "system": VANILLA_SYS},
    "A": {"via_gateway": True, "system": VANILLA_SYS, "no_contract": True},
    "B": {"via_gateway": True, "system": REPORT_SYS, "interim_header": "subagent-report/v1"},
    "C": {"via_gateway": True, "system": RECORD_SYS, "interim_header": "subagent-report/v1"},
    "D": {"via_gateway": True, "system": RECORD_SYS, "interim_header": "subagent-report/v1", "json_mode": True},
}

DIRECT_PROVIDERS = {
    "kimi": {"base_env": "KIMI_BASE_URL", "key_env": "KIMI_API_KEY", "model": "kimi-for-coding"},
    "zhipu": {"base_env": "ZHIPU_BASE_URL", "key_env": "ZHIPU_API_KEY", "model": "glm-5.3-flash"},
}


def _env(key: str) -> str:
    # fall back to repo .env (simple KEY=VALUE lines, quotes stripped)
    val = os.environ.get(key)
    if val:
        return val.strip().strip('"').strip("'")
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    raise RuntimeError(f"missing key {key} (env or .env)")


def _post(url: str, payload: dict, headers: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_gateway(prompt: str, system: str, json_mode: bool, interim_header: str | None, no_contract: bool = False) -> dict:
    payload = {"model": "kimi-for-coding", "stream": False,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"authorization": "Bearer experiment", "x-harness-tier": "system_1_5"}
    if interim_header:
        headers["x-harness-interim"] = interim_header
    if no_contract:
        headers["x-harness-no-contract"] = "1"
    data = _post("http://127.0.0.1:8787/v1/chat/completions", payload, headers)
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return {"text": msg.get("content") or "", "model": data.get("model"), "raw": data}


def call_direct(provider: str, prompt: str, system: str) -> dict:
    cfg = DIRECT_PROVIDERS[provider]
    base = _env(cfg["base_env"]).rstrip("/")
    key = _env(cfg["key_env"])
    payload = {"model": cfg["model"], "stream": False,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    data = _post(f"{base}/chat/completions", payload, {"authorization": f"Bearer {key}"})
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return {"text": msg.get("content") or "", "model": data.get("model"), "raw": data}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--task", required=True)
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--provider", default="kimi", choices=sorted(DIRECT_PROVIDERS))
    args = ap.parse_args()

    tasks = yaml.safe_load(FIXTURES.read_text(encoding="utf-8"))
    task = next((t for t in tasks if t["id"] == args.task), None)
    if not task:
        print(f"unknown task {args.task}; available: {[t['id'] for t in tasks]}", file=sys.stderr)
        return 2

    cfg = ARMS[args.arm]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{args.arm}__{args.task}.jsonl"

    for i in range(args.samples):
        t0 = time.time()
        try:
            if cfg["via_gateway"]:
                r = call_gateway(task["prompt"], cfg["system"], cfg.get("json_mode", False),
                                 cfg.get("interim_header"), cfg.get("no_contract", False))
            else:
                r = call_direct(args.provider, task["prompt"], cfg["system"])
            err = None
        except Exception as exc:  # noqa: BLE001 - record and continue sampling
            r, err = {"text": "", "model": None, "raw": None}, f"{type(exc).__name__}: {exc}"
        rec = {"arm": args.arm, "task": args.task, "sample": i, "ts": time.time(),
               "elapsed": round(time.time() - t0, 2), "model": r["model"], "text": r["text"],
               "error": err, "check": task.get("check"), "judge_focus": task.get("judge_focus"),
               # execution-plane declaration (issue #13 anti-recurrence): every run
               # record must name its runner; the exit gate enforces the field.
               "runner": os.environ.get("HARNESS_RUNNER", "host")}
        with out.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{args.arm}/{args.task}] sample {i}: {err or ('ok, ' + str(len(r['text'])) + ' chars')}", flush=True)
    print(f"-> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

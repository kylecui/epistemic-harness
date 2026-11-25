"""Aggregate the lab campaign: per arm and per task, judge score vs mechanical pass."""
from __future__ import annotations

import glob
import json
import pathlib
import statistics

TASKS = ["traceback-triage", "version-drift", "eol-remediation",
         "claim-layering", "report-extraction", "closure-order"]
RUNS = pathlib.Path(__file__).parent / "runs"


def rows_for(arm: str | None = None, task: str | None = None) -> list[dict]:
    out = []
    for path in sorted(glob.glob(str(RUNS / "lab__*.judged.jsonl"))):
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if (arm is None or r["arm"] == arm) and (task is None or r["task"] == task):
                out.append(r)
    return out


def stats(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error")]
    scored = [r for r in ok if r.get("mechanical_pass") is not None]  # None = task has no check
    scores = [s for s in ((r.get("judge") or {}).get("total") for r in ok) if isinstance(s, (int, float))]
    return {
        "n": len(rows), "bad": len(rows) - len(ok), "judged": len(scores),
        "score": statistics.mean(scores) if scores else None,
        "mech": (sum(1 for r in scored if r["mechanical_pass"]) / len(scored)) if scored else None,
        "chars": statistics.median([len(r.get("text") or "") for r in ok]) if ok else None,
        "secs": statistics.median([r.get("elapsed") or 0 for r in ok]) if ok else None,
    }


def num(v: float | None, digits: int = 2) -> str:
    return "  n/a" if v is None else f"{v:5.{digits}f}"


def main() -> int:
    arms = sorted({r["arm"] for r in rows_for()})
    print("| arm | n | bad | judged | score | mech | chars | secs |")
    print("|---|---|---|---|---|---|---|---|")
    for a in arms:
        s = stats(rows_for(arm=a))
        mech = "  n/a" if s["mech"] is None else f"{s['mech'] * 100:4.0f}%"
        print(f"| {a} | {s['n']} | {s['bad']} | {s['judged']} | {num(s['score'])} | {mech} | "
              f"{num(s['chars'], 0)} | {num(s['secs'], 1)} |")
    print("\n| task | " + " | ".join(arms) + " |")
    print("|---|" + "---|" * len(arms))
    for t in TASKS:
        cells = []
        for a in arms:
            s = stats(rows_for(arm=a, task=t))
            mech = "-" if s["mech"] is None else f"{s['mech'] * 100:3.0f}%"
            cells.append(f"{num(s['score'])} / {mech}")
        print(f"| {t} | " + " | ".join(cells) + " |")
    print("\ncell sizes: " + ", ".join(f"{a}:{stats(rows_for(arm=a))['n']}" for a in arms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

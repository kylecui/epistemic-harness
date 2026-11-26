"""Do two judges from different model families agree? Same-family judging is a known bias.

Joins <cell>.judged.jsonl (DeepSeek-V3.2) with <cell>.judged-qwen.jsonl (GLM-5.3-Flash) per sample and
reports: per-arm mean delta, Pearson r, mean absolute difference, and how often the two judges disagree
by more than 0.2 - the threshold where an arm ranking would flip.
"""
from __future__ import annotations

import glob
import json
import math
import pathlib
import statistics

RUNS = pathlib.Path(__file__).parent / "runs"
DISAGREE = 0.2


def load(suffix: str) -> dict[tuple[str, str, int], float]:
    out: dict[tuple[str, str, int], float] = {}
    for name in sorted(glob.glob(str(RUNS / f"lab__*.{suffix}.jsonl"))):
        for line in pathlib.Path(name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            total = (r.get("judge") or {}).get("total")
            if isinstance(total, (int, float)):
                out[(r["arm"], r["task"], int(r.get("sample") or 0))] = float(total)
    return out


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else 0.0


def main() -> int:
    primary = load("judged")
    cross = load("judged-qwen")
    shared = sorted(set(primary) & set(cross))
    print(f"scored by both judges: {len(shared)} samples "
          f"(primary={len(primary)}, cross={len(cross)})\n")
    if not shared:
        print("no overlap yet")
        return 1
    arms = sorted({k[0] for k in shared})
    print("| arm | n | primary mean | cross mean | delta | Pearson r | mean |diff| | disagree >0.2 |")
    print("|---|---|---|---|---|---|---|---|")
    for arm in arms:
        keys = [k for k in shared if k[0] == arm]
        a = [primary[k] for k in keys]
        b = [cross[k] for k in keys]
        diffs = [x - y for x, y in zip(a, b)]
        big = sum(1 for d in diffs if abs(d) > DISAGREE) / len(diffs)
        print(f"| {arm} | {len(keys)} | {statistics.mean(a):.3f} | {statistics.mean(b):.3f} | "
              f"{statistics.mean(diffs):+.3f} | {pearson(a, b):+.2f} | "
              f"{statistics.mean([abs(d) for d in diffs]):.3f} | {big:.0%} |")
    a_all = [primary[k] for k in shared]
    b_all = [cross[k] for k in shared]
    print(f"\noverall: Pearson r = {pearson(a_all, b_all):+.2f}, "
          f"mean delta = {statistics.mean([x - y for x, y in zip(a_all, b_all)]):+.3f}, "
          f"disagreement > {DISAGREE} on "
          f"{sum(1 for x, y in zip(a_all, b_all) if abs(x - y) > DISAGREE) / len(shared):.0%} of samples")
    print("interpretation rule: r below ~0.4 means the rubric's ranking is not stable across families, "
          "so any arm ordering that rests on <0.1 mean differences is not a finding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

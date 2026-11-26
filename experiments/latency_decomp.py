"""Latency decomposition: fixed overhead vs longer output, per arm.

Medians say B/C/D are 2.3-2.8x slower than A/A0. That could mean the contract costs time, or that it
makes the model write more (which costs time). Fit elapsed = intercept + slope * output_chars per arm:
the intercept is the fixed cost at zero output, the slope the marginal cost of writing.
"""
from __future__ import annotations

import glob
import json
import pathlib
import statistics


def rows() -> list[dict]:
    out: list[dict] = []
    base = pathlib.Path(__file__).parent / "runs"
    for name in sorted(glob.glob(str(base / "lab__*.judged.jsonl"))):
        if name.endswith(".judged-qwen.jsonl"):
            continue
        for line in pathlib.Path(name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if not record.get("error"):
                    out.append(record)
    return out


def fit(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least squares y = a + b x, plus R^2. Pure python so it runs anywhere."""
    n = len(points)
    if n < 3:
        return 0.0, 0.0, 0.0
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in points)
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    ss_tot = sum((p[1] - mean_y) ** 2 for p in points)
    ss_res = sum((p[1] - (intercept + slope * p[0])) ** 2 for p in points)
    return intercept, slope, (1 - ss_res / ss_tot if ss_tot else 0.0)


def main() -> int:
    data = rows()
    print("| arm | n | median chars | median secs | intercept (s) | secs per 1k chars | R^2 |")
    print("|---|---|---|---|---|---|---|")
    for arm in sorted({r["arm"] for r in data}):
        mine = [r for r in data if r["arm"] == arm]
        points = [(float(len(r.get("text") or "")), float(r.get("elapsed") or 0)) for r in mine]
        a, b, r2 = fit(points)
        print(f"| {arm} | {len(mine)} | {statistics.median([p[0] for p in points]):.0f} | "
              f"{statistics.median([p[1] for p in points]):.1f} | {a:.1f} | {b * 1000:.2f} | {r2:.2f} |")
    print("\nintercept = predicted seconds at zero output (fixed cost); slope = marginal cost of writing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

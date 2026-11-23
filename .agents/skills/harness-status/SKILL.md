---
name: harness-status
description: "Show harness operational status. Use when the user says status, 状态, 观测, dispatch, 派发, quota, 配额, 版本, drift, or asks how the harness is doing."
---

# Operational status of the epistemic harness: version drift, dispatches, capability matrix, memory stats

Run from the repo root, in this order:
0. `python scripts/harness_version.py`       # FIRST: spec/loaded/installed drift — a drifting session invalidates every number below
1. `python scripts/analyze_dispatches.py`     # what was delegated, to which model/tier/effort
2. `python scripts/capability_matrix.py`      # per-model credentials / max_effort / peak-avoid
3. `python scripts/memory_stats.py`           # memory hit ratio + archive candidates
Add --json to any of them when composing reports.

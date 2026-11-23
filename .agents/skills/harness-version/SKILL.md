---
name: harness-version
description: "Version triangulation: spec vs loaded contract vs installed stamp. Use when the user asks 版本, version, what version, loaded version, drift, or whether a restart picked up new code."
---

# Check which harness contract version the current pi session actually loaded

Run from the repo root:
`python scripts/harness_version.py`         # human report, exit 1 on drift
`python scripts/harness_version.py --json`  # machine-readable
The startup banner shows the same numbers on session start (first turn).

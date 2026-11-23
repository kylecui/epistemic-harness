---
name: harness-status
description: "Show harness operational status. Use when the user says status, 状态, 观测, dispatch, quota, 版本, drift."
---

# Operational status: version drift, dispatches, capability matrix, memory stats

> Global install precheck: the scripts below live in the harness global install,
> NOT in this skill directory and NOT in the working directory.
> If the precheck fails, run `python <harness-repo>/scripts/install_global.py`,
> then restart pi. Do NOT search the filesystem for the scripts.

```bash
# precheck — fail loudly with the fix, never wander:
test -f "{{HARNESS_HOME}}/scripts/harness_version.py" || { echo "harness global install missing: run scripts/install_global.py from the harness repo, then restart pi"; exit 1; }
```

```bash
python "{{HARNESS_HOME}}/scripts/harness_version.py"   # FIRST: drift invalidates every number below
python "<harness-repo>/scripts/analyze_dispatches.py"   # repo-relative: run from the repo
python "<harness-repo>/scripts/capability_matrix.py"
python "<harness-repo>/scripts/memory_stats.py"
```
Scripts not in the global install are repo-relative — `cd` to the harness repo first; if the repo is not checked out locally, say so instead of searching.

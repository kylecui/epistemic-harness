---
name: harness-version
description: "Version triangulation: spec vs loaded contract vs installed stamp. Use when the user asks 版本, version, what version, loaded version, drift, or whether a restart picked up new code."
---

# Check which harness contract version the current pi session actually loaded

> Global install precheck: the scripts below live in the harness global install,
> NOT in this skill directory and NOT in the working directory.
> If the precheck fails, run `python <harness-repo>/scripts/install_global.py`,
> then restart pi. Do NOT search the filesystem for the scripts.

```bash
# precheck — fail loudly with the fix, never wander:
test -f "{{HARNESS_HOME}}/scripts/harness_version.py" || { echo "harness global install missing: run scripts/install_global.py from the harness repo, then restart pi"; exit 1; }
```

```bash
python "{{HARNESS_HOME}}/scripts/harness_version.py"         # human report, exit 1 on drift
python "{{HARNESS_HOME}}/scripts/harness_version.py" --json  # machine-readable
```
The startup banner shows the same numbers on session start (first turn).

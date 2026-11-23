---
name: harness-verify
description: "Verify the harness is green. Use when the user says verify, 验证, 跑测试, hvx."
---

# Run the harness verification suite (tests, eol, docs, routing)

> Global install precheck: the scripts below live in the harness global install,
> NOT in this skill directory and NOT in the working directory.
> If the precheck fails, run `python <harness-repo>/scripts/install_global.py`,
> then restart pi. Do NOT search the filesystem for the scripts.

```bash
# precheck — fail loudly with the fix, never wander:
test -f "{{HARNESS_HOME}}/scripts/harness_version.py" || { echo "harness global install missing: run scripts/install_global.py from the harness repo, then restart pi"; exit 1; }
```

```bash
cd <harness-repo> && ./scripts/hvx        # full suite (Windows: scripts\hvx.ps1)
```

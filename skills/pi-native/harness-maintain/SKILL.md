---
name: harness-maintain
description: "Post-edit maintenance. Use after editing harness.yaml, config/task_routing.yaml, or knowledge/*.yaml."
---

# Recompile and revalidate after editing harness.yaml, configs, or knowledge files

> Global install precheck: the scripts below live in the harness global install,
> NOT in this skill directory and NOT in the working directory.
> If the precheck fails, run `python <harness-repo>/scripts/install_global.py`,
> then restart pi. Do NOT search the filesystem for the scripts.

```bash
# precheck — fail loudly with the fix, never wander:
test -f "{{HARNESS_HOME}}/scripts/harness_version.py" || { echo "harness global install missing: run scripts/install_global.py from the harness repo, then restart pi"; exit 1; }
```

```bash
cd <harness-repo>
python scripts/compile_clients.py
python scripts/capability_matrix.py --validate-routing config/task_routing.yaml
python scripts/build_memory_index.py && python scripts/build_memory_index.py --check
python scripts/check_docs.py    # must print "docs fresh"
# then restart pi so sessions load the recompiled AGENTS.md
```

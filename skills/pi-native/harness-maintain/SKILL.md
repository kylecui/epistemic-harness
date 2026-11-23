---
name: harness-maintain
description: "Post-edit maintenance: recompile the client contract, revalidate routing, rebuild memory index, check docs. Use after editing harness.yaml, config/task_routing.yaml, or knowledge/*.yaml."
---

# Recompile and revalidate after editing harness.yaml, configs, or knowledge files

After ANY edit to harness.yaml / config/task_routing.yaml / knowledge/*.yaml:
1. `python scripts/compile_clients.py`
2. `python scripts/capability_matrix.py --validate-routing config/task_routing.yaml`
3. `python scripts/build_memory_index.py`  &&  `python scripts/build_memory_index.py --check`
4. `python scripts/check_docs.py`    # must print "docs fresh"
5. Restart pi so sessions load the recompiled AGENTS.md.

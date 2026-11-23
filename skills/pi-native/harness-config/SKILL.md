---
name: harness-config
description: "Configure LLM providers and model selection for the harness gateway. Use for 配置模型, api key, 密钥, add provider, 默认模型, routing."
---

# Configure harness providers, model routing, and API keys

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
# 1. keys: .env (api_key_env per model in proxy_gateway/quota_policy.yaml)
# 2. default model per tier: reorder routing_chains in proxy_gateway/quota_policy.yaml
# 3. per-category pins: config/task_routing.yaml; validate:
python scripts/capability_matrix.py --validate-routing config/task_routing.yaml
# then: harness-maintain skill, restart pi
```
Authoritative doc: docs/configuration.md.

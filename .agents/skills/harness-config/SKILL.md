---
name: harness-config
description: "Configure LLM providers and model selection for the harness gateway. Use when the user says 配置模型, api key, 密钥, add provider, 默认模型, routing, 配额池."
---

# Configure harness providers, model routing, and API keys

Authoritative doc: docs/configuration.md. Short version:
1. Keys live in .env (api_key_env per model in proxy_gateway/quota_policy.yaml).
2. Default model per tier = first usable entry of routing_chains; reorder to change.
3. Per-category pins live in config/task_routing.yaml; validate with capability_matrix.py --validate-routing.
4. After changes: harness-maintain skill, then restart pi.

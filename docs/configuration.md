# Configuring LLM Providers and Model Selection

> Where keys live, how a default model is chosen, and how to pin one. The
> config file is authoritative; there is no background sync to wait for.

## 1. TL;DR

1. Put provider keys in `.env` (or export them): `ZHIPU_API_KEY=...`, `KIMI_API_KEY=...`, etc.
   OAuth providers (GitHub Copilot, Google) can be imported from Pi's own login:
   `python scripts/import_pi_credentials.py` (idempotent, reads `~/.pi/agent/auth.json`).
2. Restart the backend (`docker compose restart harness-backend`). Model selection is
   request-time: the gateway picks the first usable model in the routing chain for the
   request's tier — no sync step exists or is needed.
3. Check what is usable right now: `python scripts/capability_matrix.py` — one row per
   model with `credentials_present`, cost, `max_effort`, and peak-avoid rules.

## 2. The four configuration surfaces

| Surface | File | Governs |
|---|---|---|
| Provider keys & OAuth | `.env`, `.secrets/` | which models are usable at all |
| Model registry + pools | `proxy_gateway/quota_policy.yaml` → `models:`, `pools:` | per-model cost, quota pool, peak windows, `max_effort`, base URL |
| Default selection order | `proxy_gateway/quota_policy.yaml` → `routing_chains:` | per-tier ordered chain; the first available model wins |
| Task-level routing | `config/task_routing.yaml` | category → profile/effort/budget, optional per-category model pin |

`agent_profiles` in the same policy maps sub-agent profiles (explorer/coder/deep/critic)
to tiers; the gateway resolves profile → tier → chain.

## 3. How a default model is chosen (per request)

For a request at tier T with an optional requested model pin P:

1. `routing_chains[T]` gives the ordered candidate list.
2. If P is present and in the chain (and not a `last_option` pool model), it moves to the front.
3. Candidates are filtered by: credentials present → quota remaining in the pool →
   not yielded for the current peak window (`avoid_in_peak_for_tiers`) →
   not cross-family-excluded (critic dispatches).
4. The first survivor is selected; if none, the `last_option` pool is tried; otherwise the
   request fails with an explicit error (no silent fallback to a random model).

So "the default model for tier system_1_5" = the first entry of `routing_chains.system_1_5`
that passes the filters. **To change defaults, reorder the chain.** Validation:
`python scripts/capability_matrix.py` after every edit, then restart the backend.

### What happens to the model you asked for (issue #22)

A pin is never replaced silently. The gateway answers in exactly one of three ways, and each
answer is readable from the response:

| Case | Status | Signal |
|---|---|---|
| `model` names nothing in the catalog | 404 `unknown_model` | `error.message` plus `error.near_matches` / `error.available_models`; no upstream is called |
| Known, but not usable now (hold, cooldown, quota, peak-yield, not in this tier's chain, other protocol) | 503 + `Retry-After` | `error.message` names the model, its skip reason and the wait; nothing is generated |
| Same, and the request sent `X-Harness-Allow-Substitute: 1` | 200 | `X-Harness-Served-Model` plus `harness.{requested_model, served_model, substituted, reason}` |
| Honoured | 200 | `X-Harness-Requested-Model-Served` equals the request; no swap header |

A dropped pin is a refusal, not a substitution: the client asked for one model, so serving another
silently would end its turn on an answer it did not request. `X-Harness-Allow-Substitute: 1` is the
only way to release that pin, and the swap is then announced twice — in the headers and in the
JSON body — because pi reads the body and never the headers.

`X-Harness-Requested-Model` always repeats what the client asked for, `X-Harness-Pin-Dropped` and
`X-Harness-Skip-Reasons` (`a=b;c=d`, capped at five entries) explain an opted-in swap, and the trace
line carries `requested_model`, `requested_model_resolved`, `pin_dropped` and `skipped_reasons`. A
provider id is the same pin as its catalog key (`glm-5.4` → `zhipu-glm-5.4`); when two catalog keys
share one upstream id, the route's protocol decides (`k3.1-pro` on `/anthropic` →
`kimi-k3.1-pro-anthropic`).

Streaming responses carry the same headers (`StreamingResponse` fixes them before the first chunk);
only the `harness` body field is JSON-only.

Drop-in clients that label turns with ids this catalog will never contain (Claude Code sends
`claude-sonnet-4-5-20250929`) set `HARNESS_FAIL_ON_UNKNOWN_MODEL=off`: the request routes by tier
and the label is reported as a dropped pin in the trace. Lenient is not the same as silent.

## 4. Ways to select a model for one request

| Method | Mechanism | Scope |
|---|---|---|
| Reorder a routing chain | edit `routing_chains` in `quota_policy.yaml` | tier-wide default |
| Pin per task category | `model:` in `config/task_routing.yaml` | that category's dispatches |
| Pin per dispatch | `dispatch_subtask(model=...)` / `dispatch_tooled --model` | one sub-agent run |
| Client-sent model id | the OpenAI request's `model` field (Pi sends whatever model you picked) | that request only |

The last row answers "via pi?": point Pi's provider at the gateway (see
`.pi/models.proxy.example.json`); whatever model id Pi sends is honored as a priority
pin by `select_candidates`. Pi is not a configuration source — the YAML is; Pi is just
one more client of the gateway.

## 5. Adding a new provider/model (checklist)

1. Add a `pools:` entry if the plan needs its own quota window (5h/week/month, peak windows,
   cost multiplier).
2. Add a `models:` entry: `pool`, `protocol`, `upstream_base_url_env`/`default_base_url`,
   `api_key_env`, `upstream_model`, `cost_per_1m`, optional `max_effort`,
   `avoid_in_peak_for_tiers`, `auth: copilot` for OAuth-backed models.
3. Place the model in each `routing_chains` tier where it should be eligible (order = priority).
4. `python scripts/capability_matrix.py` — confirm the row appears with credentials detected.
5. Restart the backend; smoke test with one low-tier request.

## 6. Verifying the configuration

```bash
python scripts/capability_matrix.py                 # matrix + credential presence
python scripts/capability_matrix.py --json          # machine-readable
python scripts/install.py --check                   # host capability report
curl 127.0.0.1:8787/health                          # backend up; models_configured count
```

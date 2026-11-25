# Release notes

## v0.5.4

- A pinned model is never replaced silently (issue #22): an id the catalog does not contain returns 404 `unknown_model` with near matches and never reaches an upstream; a pin that cannot be honoured returns 503 + `Retry-After` naming the model, the skip reason and the wait, instead of another model's answer. Swapping needs the client's opt-in (`X-Harness-Allow-Substitute: 1`), and is then announced in `X-Harness-Served-Model`, `X-Harness-Pin-Dropped` and the JSON body (`harness.substituted`); both paths also trace `requested_model`, `selected_model` and `skipped_reasons`. Pinned by tests/test_pin_semantics.py; `HARNESS_FAIL_ON_UNKNOWN_MODEL=off` keeps drop-in clients (Claude Code's own model ids) working while still reporting the dropped label.
- Router priority contract (L4 decision): sub-agent chains are zhipu > kimi > github copilot > google, with opencode-deepseek-v4.1-flash as the LAST-resort fallback; the main agent still reaches it first via requested_model. Pinned by tests/test_routing_priority.py.
- Transient concurrency limits (Zhipu 1302/1305) now cool down only the affected model for a few seconds instead of freezing the whole shared pool for 300s — the failure mode that took the gateway down during quota spikes.
- Copilot upstream auth deduplicated (duplicate Authorization headers caused spurious 400 invalid-whitespace), and google-ai-gemini-4-hydrogen got its missing api_key_env.
- Self-healing router watchdog (scripts/router_watchdog.py): independent health poller with compose-up repair and :prev image rollback; verified by stopping the container and watching it recover in 26s.
- Safe restart automation (scripts/router_safe_restart.py) and admin drain/status endpoints (/admin/drain, /admin/undrain, /admin/status) so upgrades no longer cut in-flight requests.
- Sub-agent visibility: extensions/dispatch-visibility.ts adds footer status, start/end notifications, and the /agents command; dispatches are mirrored to .pi/agent_visibility.jsonl.

## v0.5.3

- Linux sandbox execution plane: the sandbox-shell pi extension brings up a per-worktree docker sandbox (`harness-sandbox:local`); the `sh` tool routes commands into it, with a declared host Git Bash fallback and `[runner=...]` evidence labels.
- Per-release plane alignment: `upgrade.py` syncs the global install (extension + sandbox defs + compiled session contract + pi settings), builds the sandbox image, retries the backend health smoke, and runs the 10-plane report (`scripts/check_env.py`) before stamping.
- `harness_version.py` triangulates the real session contract (`~/.pi/agent/AGENTS.md`) against the repo contract; a missing install stamp is explicit drift; no version guessing.
- Gateway: `sanitize_openai_payload` strips client-only fields (`store`, `previous_response_id`, `prompt_cache_key`) for non-OpenAI upstreams — fixes Gemini 400 `Unknown name "store"`.
- Public-language hard gate: unpushed commit messages must be English-first unless explicitly marked `[zh]` / `Lang: zh` (README convention).
- Images moved to `:local` tags; version truth is `harness.yaml` + the upgrade stamp.

## v0.5.2

- 全局架构：harness 不再要求以本仓库为工作目录。scripts/install_global.py
  安装到 ~/.pi/harness + ~/.pi/agent/extensions；扩展按 HARNESS_HOME 解析
  全局资源，项目目录只保留项目自己的状态（.pi/exit_gate.json、traces 等）。
- 页脚版本号改为网关 /version 优先（任意 cwd 正确），网关不可达时读
  HARNESS_HOME 的 AGENTS.md；页脚/banner 全链路带审计日志。
- pi 原生 skill 源移到 skills/pi-native（消除项目级与用户级双份冲突告警），
  安装器同步用户级 ~/.agents/skills。

> Read by `scripts/harness_version.py --banner`: the section for the loaded
> contract version is shown once, at the first session that loads it.

## v0.5.1

- 输出契约六类误报根修（版本号锚点/引用回环/短回复误伤/多站点重复判定/
  散文提及/行内代码提及），回合级去重，拦截瘦身（细节入 traces）。
- 违规取证追踪：每次判定记录 code_rev + 被检文本 SHA256。
- 新增 harness-upgrade / harness-version skill；升级路径脚本化（幂等迁移）。

## v0.5.0

- L5 反洗钱：检索痕迹硬校验 + 隐式 L3 依赖检测（13/13 攻击拦截）。
- 契约实质化：样板词过滤、可证伪验收、具名回退、结构化输出通道。
- 真模型测量层：黄金矩阵 / 虚假完成诱导 / 记忆有效性，报告入库。
- 产品级升级路径：scripts/upgrade.py + docs/UPGRADE.md。

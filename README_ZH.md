<!-- 中文辅助说明。规范内容以英文 README.md 与 AGENTS.md 为准; 本文档为历史版本存档, 部分流程已演进 -->

# Epistemic Dual-Process Harness — Phase 1 (Pi 洁净室骨架)

最小可运行的 Phase 1 硬约束内核：基于标准 MCP（JSON-RPC 2.0 stdio）实现 **只读 L1 防泛化（F-04）**、**纯代码短板继承 DAG（F-01）** 与 **人类 PR 升格闸门**，优先接入极简开源终端 [Pi](https://pi.dev/) 避开日常插件干扰，并可零修改复用到 OpenCode / Claude Code / Codex。

## 30 秒本地启动

```bash
# 1. 依赖仅需 PyYAML 与 Pydantic（Python 3.10+）
pip install pyyaml pydantic

# 2. 从单一规范源 harness.yaml 编译生成 AGENTS.md
python3 scripts/compile_clients.py

# 3. 跑全量硬约束与真实 MCP stdio 协议回归测试
python3 -m unittest discover -s tests -v

# 4. 在仓库根目录启动 Pi（Pi v0.99.0+ 自动识别项目级 .pi/mcp.json 与 AGENTS.md）
pi
# 进入 Pi 后可运行 `pi mcp list` 确认 epistemic-harness 已连接 7 个工具
```

## 自动化黄金测试回归（Pi 非交互 JSON 模式）

```bash
# 1. 本地无 LLM 烟雾自测（验证解析器 + EpistemicEngine + 断言链路）
python3 evals/run_evals.py --mock

# 2. 调用真实 Pi CLI（--mode json --approve --no-session）跑 TC-01..TC-06 并校验 MCP DAG
python3 evals/run_evals.py --mode json --output-json evals/last_report.json

# 3. 仅重跑指定用例
python3 evals/run_evals.py --cases TC-01,TC-03,TC-04
```

## 全局模式（任意目录使用 Harness）

```powershell
# Windows —— 在任何项目目录里：起容器（如需）+ 在当前目录启动带全套 Harness 的 pi
D:\MyWorkSpaces\epistemic-harness\start_harness.ps1 -Global

# 建议加 profile 别名（$PROFILE 里）：
#   function harness { & D:\MyWorkSpaces\epistemic-harness\start_harness.ps1 -Global @args }
# 之后任意目录敲 `harness` 即可；`harness -Resume <id>` / `harness -Continue` 恢复会话
```
```bash
# macOS / Linux
/path/to/epistemic-harness/start_harness.sh --global
```

全局模式依赖三层用户级配置（脚本自动幂等安装）：
`~/.pi/agent/mcp.json`（MCP-over-HTTP）、`~/.pi/agent/AGENTS.md`（跨目录用户指令）、
`~/.pi/agent/skills/epistemic-dual-process-harness/`（用户级技能）。
后端仍是同一个容器，与仓库目录彻底解耦。默认（无 -Global）仍为仓库洁净室模式（--no-skills + 项目内技能）。

## Provider 身份/鉴权适配（`proxy_gateway/provider_auth.py`）

不同 provider 在网关背后需要不同的**客户端身份**，全部在请求时解析，token 过期自动换发：

| Provider | 机制 | 实现 |
|---|---|---|
| OpenCode Go | `x-opencode-session`（会话亲和分析，缺失直接 400） | 网关按对话稳定生成 `hs-<hash>` |
| GitHub Copilot | 无静态 key：GitHub token → `copilot_internal/v2/token` 换发短期 token；请求需 VS Code Chat 指纹 + `X-Initiator` | `auth: "copilot"`；base URL 由 token 内 `proxy-ep` 推导 |
| Google AI | OpenAI 兼容端点，Bearer + `x-goog-api-key` | `auth: "google"` |

凭据来源（按优先级）：`HARNESS_COPILOT_GITHUB_TOKEN` / `GITHUB_COPILOT_TOKEN` 环境变量，或 `.secrets/github-copilot.json`
（`start_harness.ps1` 会从 Pi 的 `~/.pi/agent/auth.json` 自动导入；也可独立登录）：

```bash
python -m proxy_gateway.provider_auth login   # GitHub device flow，打印验证 URL + 码
python -m proxy_gateway.provider_auth check   # 查看换发状态与推导出的 base URL
```

启动脚本同能力：`./start_harness.sh --login` 、`.\start_harness.ps1 -Login`；
`-Configure` / `--configure` 遇到 Copilot 时不再索取静态 key，而是直接引导设备码登录。

Kimi / 智谱：OpenAI 兼容端点只认 `Authorization: Bearer`，无客户端指纹要求（实测认证通过，额度不足时返回 429）。
Google Gemini：Pi 与本网关均走 API key（或 Vertex 环境凭据），无设备码路径。

## Phase 2：启动本地 LLM 代理网关（自适应推理路由 + 流式反震荡熔断）

**方案 A：Docker（推荐，生产用法）**
```bash
docker compose up -d --build     # 127.0.0.1:8787，配置/密钥只读挂载，traces 持久化
docker compose logs -f           # 跟踪日志
docker compose down              # 停止
```
镜像只打包运行时；harness.yaml / routing_policy.yaml / quota_policy.yaml / .env 全部运行时挂载，密钥绝不进镜像层。

**MCP over HTTP（任意 agent CLI 通用，宿主机零 Python 依赖）**
```json
{
  "mcpServers": {
    "epistemic-harness":   { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
```
Pi 写入 `.pi/mcp.json`（需重启会话生效）；Claude Code 用 `.mcp.json`，OpenCode/Codex 同理。
本机 stdio 模式仍可用（`python mcp_server/server.py`），两种传输共享同一 `handle_request` 逻辑。

**方案 B：本机 Python（开发调试）**
```bash
pip install fastapi uvicorn httpx pyyaml pydantic

# 启动双协议代理（OpenAI: /v1，Anthropic: /anthropic）
UPSTREAM_OPENAI_URL=https://api.openai.com/v1 \
UPSTREAM_ANTHROPIC_URL=https://api.anthropic.com \
uvicorn proxy_gateway.app:app --host 127.0.0.1 --port 8787
```

注意：方案 A/B 不要同时占用 8787。MCP server（mcp_server/、orchestrator/）保持本机 stdio 运行，
它们通过 HTTP 连接网关，网关容器化对它们透明。

将 `.pi/models.proxy.example.json` 合并到 `~/.pi/agent/models.json`（或将 OpenCode / Claude Code 的自定义 `baseUrl` 指向 `http://127.0.0.1:8787`），即可全终端统一生效；访问 `http://127.0.0.1:8787/traces` 可查看所有路由与熔断审计日志。

## 完整架构与归档文档（`docs/`）

- `docs/epistemic-reasoning-harness-blueprint.html` — 双维治理 Harness 完整架构蓝图 v2（浏览器直接打开）
- `docs/phase0-gem-poc-spec-and-tests.md` — Phase 0 v0.2 Gem/Skill 规范、6 组黄金测试与两轮回归归档
- `docs/phase1-pi-scaffold-guide.md` — Phase 1 Pi 洁净室与 `epistemic-mcp` 硬插件落地手册
- `docs/phase2-proxy-quota-routing-guide.md` — Phase 2 共享额度池、24h 全局主动避峰与跨家族复核路由文档
- `docs/phase3-orchestrator-guide.md` — Phase 3 控制器编排层：主 Agent 纯调度、技能自动挂载、三层自动强制

## License

[MIT](LICENSE) © 2026 kylecui

## 系统级进程取证（Sysmon）

已安装 Sysmon64(v13.10，配置 `config/sysmon-harness.xml`)：只记录 shell/agent 类进程创建
（Event ID 1，含完整命令行 + 父进程链）;VS Code / WorkBuddy 等已知噪音按路径排除；
日志 300MB 滚动覆盖，当前用户可直接读取。

```powershell
# 查"谁在何时以何命令行跑了某条命令"（无需提权）
.\scripts\sysmon_who.ps1 "mcp/orchestrator"
.\scripts\sysmon_who.ps1 "grep" -SinceHours 24
```

注意：Event ID 5（进程终止）为 Sysmon 固定输出、不受过滤，查询时已自动排除。
卸载：`Sysmon64.exe -u`。

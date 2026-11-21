# Research Capability (external retrieval before design answers)

> 目标：把"设计/选型/SOTA 类问题先检索再做判断"从口头要求变成 harness 的可执行约束。
> 依据：`harness.yaml` → `research_discipline`（编译进 AGENTS.md/SKILL.md）+ 网关与 exit_gate 的确定性检查 + 检索工具接入。

## 1. 可用检索面（一手资料核对于 2026-11-20）

来源：智谱 GLM Coding Plan 官方文档 `docs.bigmodel.cn/cn/coding-plan/mcp/*`。

| 服务 | 类型 | 工具 | 端点 |
|---|---|---|---|
| 联网搜索 MCP | Remote HTTP | `webSearchPrime`（返回标题 / URL / 摘要 / 站点） | `https://open.bigmodel.cn/api/mcp/web_search_prime/mcp` |
| 网页读取 MCP | Remote HTTP | `webReader`（返回标题 / 正文 / 元数据 / 链接列表） | `https://open.bigmodel.cn/api/mcp/web_reader/mcp` |
| 开源仓库 MCP | Remote HTTP | `search_doc`（仓库文档、issue/PR、贡献者）、`get_repo_structure`、`read_file` | `https://open.bigmodel.cn/api/mcp/zread/mcp` |
| 视觉理解 MCP | Local stdio (`npx -y @z_ai/mcp-server`) | `ui_to_artifact`、`extract_text_from_screenshot`、`diagnose_error_screenshot`、`understand_technical_diagram`、`analyze_data_visualization`、`ui_diff_check`、`image_analysis`、`video_analysis` | 需 `Z_AI_API_KEY`，`Z_AI_MODE=ZHIPU｜ZAI` |

三个远程服务的鉴权头统一为 `Authorization: Bearer <API_KEY>`；旧版客户端可用 SSE 形式
`.../sse?Authorization=<API_KEY>`。Claude Code 走 GLM 模型时服务端已内置搜索与读取，无需单独安装；
换用非智谱模型时必须自行接入。

**零依赖回退路径（已实测可行）**：`curl` + arXiv Atom API
`https://export.arxiv.org/api/query?search_query=abs:%22agent+memory%22&sortBy=submittedDate&sortOrder=descending`，
以及 GitHub REST `api.github.com/search/repositories`（星标/推送时间可直接当活跃度证据）。
Semantic Scholar 免费层会 429，不适合放进自动链路。

## 2. 接入方式

```bash
export ZHIPU_API_KEY=...            # Coding Plan 控制台新建
export Z_AI_API_KEY=...             # 可选，本地视觉服务
python scripts/install_research_mcp.py --target pi --dry-run   # 先看合并结果
python scripts/install_research_mcp.py --target pi             # 幂等写入 ~/.pi/agent/mcp.json
```

支持 `--target pi|claude|opencode`，只合并不覆盖，密钥只进用户目录，不进仓库。
写入后 `pi mcp list` 应看到四个服务。

## 3. 借鉴 opencode 的部分

opencode 的 `webfetch` 这类本地工具的价值不在"能抓网页"，而在三点，我们照抄这三点：

1. **工具就是约束的执行器**：检索能力作为 tool 暴露给模型，而不是让模型"记得去搜"。
2. **取回就走**：抓回内容立刻转成可引用片段，不进长期上下文堆积。
3. **权限在客户端**：读外部内容的入口可开关、可审计，写操作另走审批。

对应到本仓：检索工具走 MCP；`check_external_grounding` 检查"最优性断言是否有来源锚点"；
`traces/` 记录调用。

## 4. 契约里的硬规则

- 触发面：设计 / 选型 / 最佳实践 / SOTA / 记忆-检索-loop-评测类架构决策。
- 底线：≥2 个独立来源，≥1 个一手来源，每条带 URL 或 arXiv ID + 读取日期。
- 未检索就必须写明 `未检索 / from memory`，并把该答复的置信上限压到 L3。
- 代码检查：`check_external_grounding`（`proxy_gateway/response_guard.py` 与
  `orchestrator/exit_gate.py` 双端同构）。含 `SOTA / 最佳方案 / 最流行 / 业界标准`
  一类断言而无 URL/arXiv/DOI/检索日期、也没有"未检索"声明，即判违规。

## 5. 验收

```bash
python -m unittest tests.test_underdetermination_tc20_22 -v   # 含 grounding 用例
python -m unittest discover -s tests
python scripts/build_memory_index.py --check
```

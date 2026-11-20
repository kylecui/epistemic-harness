# Epistemic Harness 深度代码评审与 P0 / P1 / P2 详细改进方案

> **评审对象**：`https://github.com/kylecui/epistemic-harness`（`master` 分支最新提交 `45c90cd`）
> **配套交付**：`epistemic-harness-remediation-pack.zip` 内含本方案文档、`patches/` 下全部可直接比对合入的修复 Demo 代码，以及覆盖全部修复点的自动化单元测试 `tests/test_remediation_fixes.py`。

## 一、 总体诊断：已实现的亮点 vs. 偏离初心的两处结构性跑偏

### 已扎实落地的核心资产
- **认识论硬隔离底座**：`mcp_server/dag_engine.py` 完整实现了只读 L1 防泛化、L3 强校验反例边界、L5 传递短板上限与人类 PR 升格队列。
- **共享池配额与避峰底座**：`proxy_gateway/quota_manager.py` 实现了 5h/周/月三窗口滚动共享池、24h 主动避峰，并扩展了针对 401/403/404/5xx 的模型级冷却。
- **认知噪音与偏差治理**：87 个技能剪枝为 8 个自动加载 + `skill-finder` 按需检索；`orchestrator/bias_guard.py` 严谨定位为 L3 一筛并交由 `critic` 跨家族复核。

### 偏离初心的两处结构性跑偏
1. **用“无工具子代理”硬拦主 Agent 写代码，演变为官僚主义与“盲人写代码”**：`extensions/harness-guard.ts` 只要检测到 `prompt.length > 80` 或常见动词就拦截主 Agent 的 `edit`/`write`，逼其调用 `dispatch_subagent`；但 `orchestrator/dispatch.py` 的子代理没有任何文件读写与执行工具（`NO tools`），只能靠二手上下文盲写纯文本再交回主 Agent 落盘——既违背了 System 0/1 低摩擦执行初心，又增加了延迟与幻觉。
2. **核心守卫逻辑下沉到 Pi 专属扩展，削弱多端免适配能力**：将震荡检测、控制器契约状态机写入 Pi 专属的 `extensions/harness-guard.ts`，脱离了“MCP + Local Proxy 双总线通吃 Pi / OpenCode / Claude Code / Codex”的原始架构。

---

## 二、 详细改进方案（P0 → P1 → P2）

### P0：必须立刻修复的 4 个硬 BUG

| 编号 | 问题与定位 | 根因分析 | 修复方案（见 `patches/` 对应文件） |
| :--- | :--- | :--- | :--- |
| **P0-1** | **`critic` 跨家族复核失效**<br>`orchestrator/dispatch.py` | 派发 `critic` 时把 `task_id` 改成了 `f"{task_id}-critic"`，导致网关按 `X-Harness-Session-Id` 查 `session_last_pool` 永远未命中，`exclude_pool` 恒为 `None` | 复用原 `task_id`，并显式透传 `X-Harness-Exclude-Model` 请求头；网关侧（`app_exclude_header_snippet.py`）读取该头直接物理排除起草方所属共享池 |
| **P0-2** | **纯工具调用污染 & 流式双标签**<br>`proxy_gateway/response_guard.py` | ① `guard_anthropic_content` 对纯 `tool_use` 响应强行 `insert(0, text)`；② 流式只检查第 1 个 chunk，上游把 `[Tier: ...]` 拆成 `"["` + `"Tier: ..."` 时会注入双份重复标签 | ① 纯 `tool_calls`/`tool_use` 响应直接跳过标签注入；② 新增有状态前缀缓冲器 `StreamTagGuard`（攒满 24 字符或遇到 `]`/`\n` 后仅判一次）；③ `system_1_5` 默认改为 `Explore` |
| **P0-3** | **子代理绕过流式反震荡守卫**<br>`orchestrator/dispatch.py` | 子代理固定发 `stream: False` + `timeout: 300s`，完全绕过了网关仅在 `stream=True` 时生效的 `thrashing_guard` 与低推理无缝续跑 | `dispatch_subtask` 改为消费网关 `stream=True` SSE 流并本地拼接最终 `content`，让所有子代理自动受反震荡保护，告别 300s 干等 |
| **P0-4** | **`synthesize` 规范回退 & 并发异常雪崩**<br>`orchestrator/plan.py` | ① `synthesize` 硬编码中文 Prompt 且指定 `agent_profile="coder"`；② `pool.map` 任一子任务报错即丢弃整波成功结果；③ 字典序排序在 `S10` 处错位 | ① 改为英文 Prompt（严格对齐用户语言），默认 profile 改为 `"deep"`；② 改用 `as_completed` 做单任务异常隔离；③ 按子任务序号自然排序 |

### P1：核心架构纠偏（回归双维治理初心）

| 编号 | 架构目标 | 具体落地方案（见 `patches/` 对应文件） |
| :--- | :--- | :--- |
| **P1-1** | **打通 `orchestrator/` 与 `mcp_server/dag_engine.py`（消除两张皮）** | 在 `patches/orchestrator/plan.py` 中，每个子任务完成时自动调用 `EpistemicEngine.submit_l5_claim()` 登记为 L5 节点（依据子任务是否引用 L1/L2/L3 及 `bias_scan` 状态自动受短板继承约束），在 `synthesize` 前自动运行 `audit_dag()` 并把 `overall_confidence_cap` 与 `converge_allowed` 写入最终结果头 |
| **P1-2** | **解除官僚拦截，明确无工具子代理边界** | 在 `patches/extensions/harness-guard.ts` 中：删除 `prompt.length > 80` 粗糙阈值；真正检查 `edit`/`write` 的变更行数（`< 15` 行局部修改或 `< 40` 行小文件直接零摩擦放行）；明确无工具子代理仅用于只读推理、多视角分析与 Critic 审计，未来需要真正带工具的编码子代理时通过 `pi --mode json --no-skills --no-session` 派生隔离进程 |

### P2：长期架构收敛与多端可移植性

| 编号 | 收敛目标 | 具体落地方案 |
| :--- | :--- | :--- |
| **P2-1** | **瘦身 `harness-guard.ts`，把震荡监测收回网关层** | 移除 `harness-guard.ts` 中只扫最终正文的 `message_end` 震荡检测（容易在复盘或讨论框架时误报），将真正的思考流监测统一收敛回 `proxy_gateway/thrashing_guard.py`（能直接看到 `reasoning_content` / `thinking_delta`），确保 OpenCode / Claude Code / Codex / Pi 全端行为一致 |

---

## 三、 补丁包目录与合入验证步骤

```text
epistemic-harness-remediation-pack/
├── REMEDIATION_PLAN.md                            # 本详细改进方案
├── patches/
│   ├── proxy_gateway/
│   │   ├── response_guard.py                      # P0-2 修复：纯工具跳过 + StreamTagGuard 防双标签
│   │   └── app_exclude_header_snippet.py          # P0-1 配套：网关支持 X-Harness-Exclude-Model 头
│   ├── orchestrator/
│   │   ├── dispatch.py                            # P0-1 & P0-3 修复：SSE 流式子代理 + 真正跨家族 Critic
│   │   └── plan.py                                # P0-4 & P1-1 修复：英文综合 + 异常隔离 + DAG 联动
│   └── extensions/
│       └── harness-guard.ts                       # P1-2 & P2-1 修复：按真实改动行数放行 + 瘦身去重
└── tests/
    └── test_remediation_fixes.py                  # 覆盖全部 P0/P1 修复点的自动化单元测试（已全部通过）
```

### 在本地仓库合入与验证命令（Windows PowerShell）

```powershell
# 1. 先在补丁包内运行自测确认全部修复点通过
python -m unittest discover -s tests -v

# 2. 对比差异后按路径覆写到 D:\MyWorkSpaces\epistemic-harness\ 对应文件
#    并将 patches\proxy_gateway\app_exclude_header_snippet.py 中的两处改动合入 proxy_gateway\app.py

# 3. 在主仓库跑全量回归
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe evals\run_evals.py --mock --lang all
```

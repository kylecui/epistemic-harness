# Phase 3 控制器编排层与全链路自动强制文档

> **对应代码**：`orchestrator/`（planner / dispatch / skills / server）、`skills/registry.yaml`、`.pi/mcp.json`、`harness.yaml` 的 `orchestration:` 段。

## 一、四个落地需求的实现映射

| 需求 | 实现 | 强制层级 |
| --- | --- | --- |
| 1. 始终遵循认知论与思考约束框架，手动调用技能不可取 | 三层自动生效，模型无需"想起"任何技能 | Prompt + Transport + Tool |
| 2. 按任务调度快慢思考逻辑与模型，分配给不同 subagent | `classify_task` → `dispatch_subagent`，网关按 `X-Harness-Agent-Id` 档位置 + 配额/避峰/failover 动态选模 | Tool + Transport |
| 3. 主 Agent 只做理解/推理/拆分/调度，不做具体实现 | 控制器契约编译进 AGENTS.md §4；实现内容一律经 `dispatch_subagent` 下发 | Prompt + 代码 |
| 4. 框架内主动获取并使用相关技能 | `dispatch_subagent` 自动匹配 `skills/registry.yaml` 并注入子 Agent prompt；`register_skill` 走人类 PR 闸门 | Tool（代码自动） |

## 二、自动强制三层模型（替代"手动调用技能"）

1. **Prompt 层**：`scripts/compile_clients.py` 把 `harness.yaml`（含 `orchestration:` 段）单向编译为 `AGENTS.md` / `SKILL.md` / `gemini-gem-v0.3.md`。Pi 等客户端在项目级**自动加载** AGENTS.md，模型零动作即受契约约束。
2. **Transport 层**：代理网关在每次请求上自动——注入思考语言策略、按指纹/档位置 clamp `reasoning_effort`/`budget_tokens`、强制输出契约 `[Tier | Mode]` 标签、反震荡熔断后**自动低推理续跑**（不再掐停会话）。
3. **Tool 层**：`epistemic-mcp`（L1-L5 DAG）与 `epistemic-orchestrator`（编排）通过 `.pi/mcp.json` **常驻连接**；短板置信上限与 Converge 闸门由代码强制，不可被提示词漂移绕过。

## 三、控制器工作流

```
用户任务
  └─ 主 Agent（控制器）：理解 → 拆分为子任务
       ├─ classify_task(subtask)      # 建议档位/档案 + 自动匹配技能（建议性，L2）
       ├─ dispatch_subagent(profile, subtask)  # 经网关执行；技能自动注入；返回带 tier 标签的结果
       ├─ （可选）critic 档案触发 system_2_plus 跨家族复核（网关按 session 排除起草方同池）
       └─ submit_l5_claim(...) → audit_dag()  # 收敛：代码计算 overall_confidence_cap
```

档案与档位：`explorer`(system_1) / `coder`(system_1_5) / `deep`(system_2) / `critic`(system_2_plus)。
优先级：显式 `X-Harness-Tier` 头 > `X-Harness-Agent-Id` 档位置 > 关键词指纹 > 默认 system_1_5。

## 四、技能库与自动挂载

- 注册表：`skills/registry.yaml`（`id/name/description/tags/triggers/tier_hint/content`）。
- 自动挂载：`dispatch_subagent` 以子任务全文检索注册表（score ≥ 1 的前 2 项），把 `content` 注入子 Agent system prompt。
- 人类闸门：新技能只能经 `register_skill` 排队到 `skill_queue/pending.yaml`，人工审核后合并进注册表（与 L1/L2 升格同一哲学）。

## 五、启动

```bash
python3 scripts/compile_clients.py          # 编译契约（已含 orchestration 段）
# 终端内 Pi 自动加载 .pi/mcp.json 中两个 MCP server（共 13 个工具）
./scripts/start_proxy.sh                    # 网关（dispatch 的目标）
```

## 六、测试

- `tests/test_orchestrator.py`：档位映射、技能匹配/闸门、dispatch 头与注入、共享 L5 引擎、tools/list。
- `tests/test_proxy_gateway.py`（v1.1 合并版）：恢复式续跑（effort 降级 + RECOVERY_DIRECTIVE）、熔断不误杀、思考语言注入。
- 全量：`python3 -m unittest discover -s tests`（35 项）。

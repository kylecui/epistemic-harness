# 工作计划与下一步研发方案（v0.4 路线图）

> 生成时间：2026-11-20（合并 `epistemic-harness-complete-update-pack` 之后）
> 基线：77 项单元测试全绿；A/B 回放复现评审结论；容器化后端 + Pi 扩展三层约束在线。
> 依据：`docs/review-remediation-plan.md`、`docs/language-gravity-anti-jargon-report.md`、
> `docs/epistemic-reasoning-harness-blueprint.html`、`docs/phase{0,1,2,3}-*.md`、
> `docs/cognitive-bias-correction-design.md`

## 一、已完成（本次合并，均有回归测试）

| 编号 | 内容 | 状态 |
|---|---|---|
| P0-1 | 跨家族 critic 真正生效：`X-Harness-Exclude-Pool/Model` 头 + `exclude_policy.py` | ✅ 含端到端测试 |
| P0-2 | 纯工具调用不注入标签；`StreamTagGuard` 消灭流式双标签；1.5 默认 Explore | ✅ |
| P0-3 | 子 agent 改走 SSE，享受流式反震荡 + 自动续跑 | ✅ |
| P0-4 | plan：英文综合 prompt、deep 档案、`as_completed` 异常隔离、S2<S10 自然序 | ✅ |
| P1-1 | orchestrator ↔ L5 DAG 打通：子任务登记 claim、综合前 `audit_dag` | ✅ |
| P1-2 | harness-guard 改为按**变更行数**判定（≤15 行 edit / ≤40 行 write 放行） | ✅ |
| P2-1 | 移除扩展内正文震荡扫描，统一收敛到 `thrashing_guard` | ✅ |
| 新 | 网关 `X-Harness-Effort` 覆写 + 按档案 token 预算 + 空内容重试（实战触发） | ✅ |
| 新 | `harness.yaml` 增加 Reasoning/Output Style 切片，编译进 AGENTS.md/SKILL.md | ✅ |
| 新 | 语言引力 A/B 评测器（`evals/run_style_ab_eval.py --replay/--live`）+ TC-07~09 | ✅ |

## 二、P0 级遗留（下一迭代必须做）

1. **子 agent 无工具的结构性张力**
   现状：子 agent 只能输出文本，控制器落盘。评审称其为"盲人写代码"。
   方案（需决策）：
   a. 维持现状 + 强化"子 agent 只做只读推理/审查"的定位（评审 P1-2 建议）；
   b. 新增带工具的编码子 agent：`pi --mode json --no-skills --no-session` 派生隔离进程，
      由 orchestrator 调度（实现量大，但彻底解决"控制器写代码"问题）。
   **建议**：先 (a) 明确文档与合同，把 (b) 作为 v0.5 独立里程碑。

2. **`plan_task` 拆解质量缺乏量化**
   现状：启发式拆解器（编号列表/连词/序列词）无准确性评测。
   方案：扩 `evals/`，构造 20 条拆解黄金样本（期望子任务数/依赖结构/档案），
   在 CI 中断言；不达标时回退单子任务。

3. **critic 跨家族仍依赖显式头**
   现状：dispatch 传 header 才排除；其他客户端（OpenCode/Claude Code）不会自动带。
   方案：网关侧补"会话级 drafter 记忆"——按 `session_id` 记录最近一次非 critic 请求的 pool，
   critic 请求自动排除（header 优先，session 兜底）。

## 三、P1 级（架构收敛）

4. **多端一致性**：扩展逻辑（契约注入/派发拦截）目前仅 Pi。
   方案：把"控制器契约 + 派发优先"做成网关侧可观测告警（检测连续 N 次工具调用无派发），
   输出到 `/traces`，各端共享；Pi 扩展仅作本地前置。

5. **`provider_auth` 覆盖度**：目前 Copilot(设备流) + Google(API key)。
   方案：补 Vertex ADC（`google.auth.default()`）路径；Anthropic 若无 key 支持 OAuth 探测。

6. **配额账本 vs 上游真实额度漂移**：本地账本只统计过路流量。
   方案：周期性调用各 provider 的额度查询端点（若有）校准；无端点则明确标注"估算值"。

## 四、P2 级（体验与运营）

7. **`/traces` 可视化**：现在只有 JSON。加一个极简 HTML 面板（路由分布、熔断次数、失败原因 Top-N）。
8. **技能处置继续演进**：79 个手动技能的 `/skill:name` 命中率统计（从 traces 提取），
   长期未命中的考虑归档。
9. **文档同步**：`docs/` 与 README 增加"评审结论 → 修复映射表"，便于外部读者追踪。

## 五、验证清单（每次发版）

```bash
.venv/Scripts/python.exe -m unittest discover -s tests        # 77 项
.venv/Scripts/python.exe evals/run_evals.py --mock --lang all  # 双语黄金用例
.venv/Scripts/python.exe evals/run_style_ab_eval.py --replay   # 语言引力 A/B
docker compose up -d --build && curl -s 127.0.0.1:8787/health  # 容器后端
pi mcp list                                                    # MCP 双服务连通
```

## 六、待你决策的三件事

1. 子 agent 是否引入"带工具的隔离进程"（v0.5 里程碑）？
2. critic 会话级兜底是否立刻做（不依赖客户端配合）？
3. 是否把 A/B 评测接入真实模型定期跑（消耗配额，但能量化风格漂移）？

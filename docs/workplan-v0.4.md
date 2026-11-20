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
| P1-3 | 评审回合完整性（issue #1）：缺陷必须附完整修复方案（改动点/迁移影响/回退/验收），降级措辞打回；三段式/silent promotion/L3 scope 结构自检；TC-12~15 黄金用例 + 网关与 exit_gate 双端强制 | ✅ |
| 新 | 网关 `X-Harness-Effort` 覆写 + 按档案 token 预算 + 空内容重试（实战触发） | ✅ |
| 新 | `harness.yaml` 增加 Reasoning/Output Style 切片，编译进 AGENTS.md/SKILL.md | ✅ |
| 新 | 语言引力 A/B 评测器（`evals/run_style_ab_eval.py --replay/--live`）+ TC-07~09 | ✅ |

## 二、v0.4 新增闭环（本次交付）

1. **Exit Gate & Anti-Shirking** ✅ 三层防御：AGENTS.md v0.3.2 Loop Completion Contract（规范源合入+重编译）；
   `extensions/harness-guard.ts` v0.4.0（回合结束自动跑 `.pi/exit_gate.json` 验收命令 + 残留扫描 +
   红灯时才扫推诿措辞 + 同指纹熔断升档）；`orchestrator/exit_gate.py` 同构引擎供无头编排复用；
   MCP `run_gate` 工具 + `run_plan` 可挂载门禁。6 项端到端测试（真实临时 Git 仓库）全绿。
2. **TC-10/TC-11 黄金用例** ✅ 防甩锅（历史遗留失败必须修）与零残留（测试全过但留 scratch 文件仍被拦）。
3. **周期 A/B 计划任务** ✅ `EpistemicHarness-StyleAB-Weekly`（每周一 09:00，两主力家族，报告落
   `evals/style_ab_weekly_*.log`，exit 2 标记回归）。
4. **scorer 引号豁免** ✅ 黑话仅在引号外才计命中（评审诱饵词引用豁免），单测固化。

## 三、P0 级遗留（已关闭）

1. **子 agent 无工具的结构性张力** → ✅ `orchestrator/tooled.py` + MCP `dispatch_tooled`：
   隔离 `pi` 进程（`-p --no-session --no-mcp --no-skills`，硬超时+kill，workdir 白名单），
   真机验证：14.7s 创建并运行文件。契约已编译进 AGENTS.md。宿主机执行（容器内无 pi 二进制，
   MCP 会返回明确错误）。文本子 agent 保留给只读推理/审查。
2. **critic 跨家族对客户端的依赖** → ✅ 网关会话级兜底：exact session → 去 `-critic` 后缀 →
   全局最近起草方 pool，三级解析（header 优先）。OpenCode/Claude Code/Codex 零配合可用。
3. **模型级 effort 悬崖** → ✅ `quota_policy.yaml max_effort`（证据驱动：opencode-deepseek
   在 medium 上 content 为空、low 上正常）+ 网关逐请求钳制 + dispatch 空内容自动重试。

## 三、周期 A/B（已上线 v1）

- `scripts/style_ab_periodic.py`：实网跑 TC-07~09，追加 `evals/style_ab_history.jsonl`，
  自动对比上一轮并报告 REGRESSION（exit 2 供调度器/CI 使用）。
- 实测轨迹：基线 0/3（黑话泄漏 打通/抓手/赋能/链路）→ 网关注入完整风格禁令后 **2/3**，
  TC-08/09 零泄漏；TC-07 残留"引用 prompt 黑话"泄漏——scorer 计全文本，下一轮迭代：
  允许引号内引用或按 must_not 加引号豁免。
- 建议周期：每次模型订阅变更 / 每月一次；`--models` 传多个可横向对比家族。

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

## 六、待你决策的事

1. 子 agent 是否引入"带工具的隔离进程"（v0.5 里程碑）？
2. critic 会话级兜底是否立刻做（不依赖客户端配合）？
3. 是否把 A/B 评测接入真实模型定期跑（消耗配额，但能量化风格漂移）？

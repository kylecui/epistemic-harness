# 大语言模型认知偏差矫正方案 (Cognitive Bias Correction Subsystem) v0.1

> 状态：设计 + 首版实现已完成（bias catalog / BiasGuard / dispatch 自动扫描 / critic 升级链路）。
> 认识论定位：偏差条目本体是 **L3 启发式**（有适用边界与失效反例）；矫正**执行**靠代码硬约束（L1 级机制），检测标记仅为 L3 初筛。

## 1. 核心论点

Harness 的多数硬约束机制在建造时并未以"认知偏差"命名，但它们恰好是经典偏差的矫正器。本方案的第一步是**显式编目**这张映射表，让"机制→偏差"从隐式巧合变为可审计、可测试的契约；第二步是补上缺失的环节（检测层 + 升级路由）。

| 认知偏差 | 矫正机制（既有硬约束） | 机制层级 |
|---|---|---|
| 过度自信 / 经验洗白 | L5 短板继承：`min(upstream_tiers)` 置信上限锁死，`audit_dag` 收敛闸门 | 代码强制 |
| 虚构来源 / L1 泛化（confabulation） | `dag_engine` 只读 L1 + `source_id` 存在性硬校验（`UNKNOWN_SOURCE_ID` / `L1_CREEP_BLOCKED`） | 代码强制 |
| 沉没成本 / 拒绝止损 | 反震荡 stop-loss 纪律（输出三件套：已确认事实/最小未知/下一步） | 契约强制 |
| 思维震荡空转（Aha→Wait, but wait） | `thrashing_guard` 流式熔断 + v1.1 自动低推理续跑（RECOVERY_DIRECTIVE 取证指令） | 代码强制 |
| 确认偏差 | L3 条目强制 `counter_examples` 字段；L5 `conflicts_with_l1` 显式申报 | Schema 强制 |
| 锚定 / 同家族回音室 | Explore/Converge 双模式 + `critic` 档案**跨家族**排除（不同 provider 家族） | 路由强制 |
| 权威偏差 / 可用性启发 | L2 `require_provenance` + `max_age_days`；L2 只允许"证明观察事实"，禁止自动外推 | Schema 强制 |
| 自动化偏差 | `propose_promotion` 人类 PR 闸门——任何 L3→L2 升格都必须人审 | 流程强制 |

结论：**矫正的"牙齿"在代码与 schema 层，不在提示词层。** 提示词（SUBAGENT_PREAMBLE、thinking policy）只是软协议。

## 2. 新增组件（本次落地）

```
knowledge/l3_heuristics/cognitive_biases.yaml   # 8 条偏差目录（L3：scope_conditions/counter_examples 强制）
orchestrator/bias_guard.py                      # BiasGuard：确定性初筛（加载目录 + 标记匹配）
orchestrator/dispatch.py                        # dispatch_subtask 结果自动 bias_scan；
                                                # escalate_on_bias=True 时自动加派 critic 复核（跨家族）
orchestrator/server.py                          # 新 MCP 工具 bias_scan（orchestrator 第 7 个工具）
```

### 检测管线（三层）

1. **L3 初筛（确定性代码）**：`bias_scan` 对任意文本跑标记匹配，产出 `matches + mandated_correction + harness_mapping`。标记是关键词启发式，**有误报风险**，不直接定罪。
2. **critic 升级（跨家族模型）**：`dispatch_subagent(..., escalate_on_bias=True)` 命中即自动加派 `critic` 档案（system_2_plus，排除同 provider 家族），复核输出 PASS/FAIL + 一行理由。
3. **硬拦截（原有代码层不变）**：虚构来源、经验洗白仍在 `dag_engine` 内被 Tool Error 拒绝——这条链不依赖任何标记。

### 目录条目 schema（示例字段）

```yaml
- id: BIAS-OVERCONFIDENCE
  detection_markers: ["一定", "绝对", "百分之百", "definitely", ...]
  correction: "强制回落到最弱上游依赖层级表述，并标注 Confidence Cap"
  harness_mapping: "L5 短板继承 DAG + audit_dag 收敛闸门"
  scope_conditions: "..."      # 强制
  counter_examples: "..."      # 强制
```

## 3. 与主流程的集成点

- **子任务出口**：每次 `dispatch_subagent` 的返回都自动携带 `bias_scan` 字段（默认零成本，不升级）。
- **控制器决策**：主 Agent（controller）看到 `verdict=requires_critic_review` 后，按契约决定升级或接受初筛结论。
- **会话级**：critic 复核结论可作为 L5 claim 的 `source_ids` 之一进入 DAG，参与置信上限计算。

## 4. 边界与诚实声明 [L3]

- 标记初筛的精确率未量化——需要先跑 eval 黄金集统计误报率，再决定是否提高命中阈值（当前 ≥1 个标记即命中）。
- "偏差命中 ≠ 输出错误"：命中只说明**需要复核**，复核权在跨家族 critic，最终裁决权在人（Converge 档）。
- 偏差目录本身是 L3 知识：条目可被 `propose_promotion` 流程修正，且必须随反例积累持续修订。

## 5. 下一步

1. evals 增加偏差检测用例（正/负样本对），量化初筛精确率/召回率。
2. `classify_task` 输出建议是否开启 `escalate_on_bias`（按 subtask 风险分级）。
3. 目录扩充：幸存者偏差、规划谬误（与任务拆分器联动）、框架效应。
4. 与 Gemini Gem Phase 0 软协议同步同一份目录（harness-compiler 编译）。

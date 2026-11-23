# Paper 1.5 计划：Epistemic Governance Harness 方法论（立项稿）

> 内部计划文档。分支：`research/structured-interim-contracts`。
> 立项决定：2026-11-24。系列定位见 `paper-plan-structured-interim.md` §0/§4.5。

## 0. 与系列其余论文的关系

| | Paper 1（contracts） | **Paper 1.5（本计划）** | Paper 2（interim 协议） | Paper 3（测量） |
|---|---|---|---|---|
| 层 | 任务级外部义务 | **认知级治理框架** | 通信级协议 | 计量级消融 |
| 回答 | 行为如何被收束 | **断言如何被分级、封顶、验证** | 中间产物长什么样 | 约束值多少钱 |

Paper 1.5 是系列的「总框架」论文：L1-L5 taxonomy + weakest-link cap +
exit gate 是 Paper 1（外部义务挂在哪）、Paper 2（interim 记录的认识论
字段从哪来）的地基。

## 1. Working title

*Governance by Epistemics: A Five-Layer Claims Taxonomy with Weakest-Link
Confidence Caps and a Deterministic Exit Gate for LLM-Agent Cognition*

## 2. 目标 venue

ICLR / NeurIPS 主会（methodology / agent reliability）；备选 AAAI、TMLR。

## 3. 结构（section 级）

1. **Introduction** — 问题：agent 的输出把公理、证据、启发式、意图混为一谈，
   机器无法区分；两类失败模式：overclaiming（folklore 以事实口吻断言）与
   thrashing（无止损的自我怀疑循环）。方法论主张：把 agent 认知当作带溯源的
   claims 流水线来治理。
2. **Related Work** — LLM 校准与置信度；verifier-in-the-loop（Reflexion、
   CRITIC 类）；结构化生成；agent 治理框架。划界：我们治理的是**断言的认识论
   身份**，不是输出格式。
3. **The Five-Layer Taxonomy** — L1 公理 / L2 证据 / L3 启发式 / L4 用户意图
   与资源约束 / L5 推导；每层的准入规则与只读性；核心病理：L3 被当作 L1
   （工程 folklore 的越层断言）。
4. **Weakest-Link Confidence Caps** — confidence ceiling = min(upstream) 的
   代码强算；claim 依赖 DAG（audit_dag）；converge 门；反洗钱机制
   （IMPLICIT_L3_DEPENDENCY：未声明的启发式依赖被自动检出）。
5. **Adaptive Dual-Process Routing** — 认知分层（反射→直觉→结构化分析→
   审慎推导→元认知批评）；controller 的测量而非假设（dispatch/direct-write
   比率记账）；成本-延迟-准确的三方权衡作为一等公民。
6. **The Exit Gate** — claims-bind-to-executed-evidence 的硬规则；bounce 一次
   后确定性降级；反 thrashing 账本（跨回合指纹升级 root-cause）；零残留契约。
7. **Instantiation and Operation** — 开源 harness 实例；平面版本对齐
   （install/upgrade/stamp/镜像的单一事实源）；真实事件教训两则：false-green
   版本对账（harness_version 结构性漏报）与最小充分原因检查（外部原因假设被
   第一方机制闭合映射-collapse）。
8. **Evaluation** — 契约违规率前后对比（traces 账本已有数据）；thrash 循环
   消除率；跨任务案例研究 [TBD 数字]。
9. **Discussion** — cap 是上限不是校准（ceiling ≠ calibration）；taxonomy 的
   纪律成本；对弱模型遵循率差异的影响。
10. **Conclusion**。

## 4. Abstract（草稿，数字留 [TBD]）

> LLM agents increasingly perform high-stakes engineering work, yet their
> outputs mix axioms, evidence, heuristics, and intent with no
> machine-checkable distinction: engineering folklore is asserted with the
> same confidence as measured fact, quantified claims float free of any
> executed check, and failing runs thrash in unbounded self-doubt loops. We
> present a governance methodology that treats agent cognition as a claims
> pipeline with provenance. A five-layer epistemic taxonomy (axioms, primary
> evidence, heuristics, user intent and resource constraints, derived
> conclusions) supplies explicit admission rules, so folklore can never be
> silently promoted to fact. Confidence ceilings are computed as
> deterministic weakest-link functions over a claim dependency DAG: no
> derivation may claim more certainty than its weakest source, and undeclared
> heuristic dependencies are detected automatically. Adaptive dual-process
> routing spends deliberation budget only where the task demands it, and a
> deterministic exit gate binds every quantified claim to a check the gate
> itself executed — bouncing a violation once, then degrading gracefully
> instead of looping. We report operational evidence from deploying the
> methodology as an open-source harness on real engineering work
> [TBD: contract-violation-rate trends, thrash-loop elimination statistics,
> and incident postmortems including a false-green version triage and an
> external-cause investigation collapsed by a first-party mapping rule].

## 5. 贡献声明（4 条）

1. 问题形式化：agent 断言的「认识论身份」缺失与 overclaiming/thrashing
   两类失败模式（新）。
2. 五层 taxonomy 与准入规则（方法论；区别于输出契约类工作）。
3. weakest-link cap 的确定性计算 + 反启发式洗钱机制（机制 + 代码强算）。
4. exit gate 的 claims-bind-to-evidence 硬规则与 bounce-once-degrade 语义
   （工程机制 + 运行数据）。

## 6. 素材盘点（几乎全在库）

| 素材 | 位置 |
|---|---|
| taxonomy 与准入规则 | harness.yaml epistemic_tiers → AGENTS.md |
| weakest-link / DAG / 反洗钱 | epistemic-mcp（submit_l5_claim/audit_dag） |
| 双过程路由与测量 | task_routing.yaml + .pi/controller_metrics.jsonl |
| exit gate 全机制 | .pi/exit_gate.json + orchestrator run_gate + guard 扩展 |
| 事件教训 | harness_version false-green 修复、minimum-sufficient-cause 条款（issue #4 先例）、本轮 upgrade/plane 对齐 |
| 运行数据 | traces/contract_violations.jsonl、traces/gateway_traces.jsonl |

## 7. 里程碑

| 阶段 | 内容 | 依赖 |
|---|---|---|
| M0 | 本计划 ✅（2026-11-24 立项） | — |
| M1 | Evaluation 数据整理（traces → 论文图表） | 无代码依赖，可与 P1 并行 |
| M2 | 初稿（英文） | M1 |
| M3 | 与 Paper 2 背靠背互审（方法论一致性） | Paper 2 初稿 |

写作顺序建议：Paper 1.5 与 Paper 2 并行推进，1.5 先投稿（总框架先占位）。

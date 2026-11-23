# Structured Interim Outputs — 研究设计笔记（内部）

> 内部研究笔记（非公共内容）。分支：`research/structured-interim-contracts`。
> 关联：contract-driven-harness-study（paper: *Contracts as Task Skeleton:
> Externalizing Implicit Obligations for Bounded LLM-Agent Determinism*）。

## 1. 研究问题

**RQ：结构化输出能否同时充当 (a) reasoning 过程的可验证记录 与 (b) agent 间
interim 沟通协议，从而在概率生成世界里用约束换取可控的稳定性（controllable
stability）？**

- RQ1 结构有效性：schema/grammar 约束能把「格式稳定」推到多远（确定性保证的边界）
- RQ2 语义稳定性：结构化字段能否消除 agent 间信息传递的漂移（父 agent 解析子
  agent 输出的错误率）
- RQ3 效率：结构化 interim 是否提升沟通效率（converge 轮次 / token 成本），代价
  是什么（schema 僵化）
- RQ4 信息流方向：结构化时序约束能否抑制「偷看答案」式的事后合理化
  （post-hoc rationalization）

## 2. 与既有 paper 的接点

Paper 的核心是 contracts as task skeleton → bounded determinism：分阶段把概率
行为收束到确定性检查。我们的观察：**「偷看」的本质是信息流方向失控**——结论
先于证据产生，推理事后补写。

结构化 interim 给「方向」提供了机器可验证的载体：

- **时序约束**：evidence 必须先于 claim 出现在执行记录中（执行记录 ts < claim ts）
- **不可变性**：interim 记录 append-only，一旦提交不可改写——事后补写的推理无法
  获得早期时间戳，结构性暴露

本 harness 已有最小雏形：`submit_l5_claim`（结构化推理单元 + weakest-link cap +
GROUNDING_VIOLATION 强制 evidence 存在）、`run_gate` 的 claims-bind-to-checks、
traces 的 contract_violations 记账。研究分支的任务 = 把这些从「工具层可选」升格
为「协议层默认」。

## 3. 文献锚点（检索日期 2026-11-24）

| 来源 | 关系 |
|---|---|
| ReAct（arXiv:2210.03629，primary，已读摘要） | thought-action-observation 交错 = 最早的「结构化 interim」实践；我们的 schema 化是它的强约束版本 |
| Self-Consistency（arXiv:2203.11171，primary） | 采样层稳定性方案；与约束层正交，可作对照或组合 |
| Tree of Thoughts（arXiv:2305.10601，primary） | thoughts 作为可评估、可回退的中间单元 |
| XGrammar（arXiv:2411.15100，primary） | CFG constrained decoding 近零开销（最高 100x speedup）——语法层硬约束的工程可行性 |
| GCD 系列（arXiv 检索 2026-08，parser stack classification 等，primary） | 自动机层面的确定性保证：合法串 100% 符合 grammar |
| Google A2A 协议（github.com/google/A2A，primary） | agent 间 interim 标准化的工业趋势；但其 message 是弱结构（自然语言 + artifact），我们主张强 schema |
| OpenAI Structured Outputs（2024-08 产品化，from memory [L3]） | strict schema mode 的规模化证据；未单独抓文档 |

**差异化定位**：A2A / OpenAI Structured Outputs 解决「格式有效」；我们解决
「认知协议有效」——schema 承载的是认识论字段（`confidence_cap`、
`evidence_refs`、claim 依赖图），不只是语法。

## 4. 与 harness 的结合（如何结合）

三层映射（全部落在现有组件上，不新造轮子）：

| 层 | 现有机制 | 研究分支扩展 |
|---|---|---|
| 语法层 | gateway `guard_*` / `check_response_contract`（事后校验 + 确定性 retry，与 issue#1 bounce 同构） |  interim 消息按 JSON Schema 校验：失败 bounce 一次 → 降级修复 |
| 协议层 | epistemic-mcp `submit_l5_claim` / `audit_dag`（结构化推理 DAG） | 每次推理段都落成 claim 记录（非仅 converge 时）；dispatch 返回值 schema 化 |
| 执行层 | exit gate / traces | 测量底座：violation rate、新增 stability ledger |

新组件草图：

- **ReasoningRecord**（append-only）：`{record_id, tier, mode,
  claims:[{text, layer, source_ids[], confidence_cap}], evidence_refs[],
  open_gaps[], ts}` —— 推理过程本身是结构化账本。
- **SubagentReport**：`{task_id, profile, findings[], evidence[],
  confidence_cap, gaps[], recommendation, residue_risks[]}` ——
  `dispatch_subagent` / `dispatch_tooled` 的返回从自由文本改为
  schema-validated。
- **收敛规则**：父 agent 的 L5 结论只允许引用结构化 findings 的 id——converge
  从「重读散文」变成「查表」，解析漂移归零。

## 5. 如何可控（controllability 设计）

控制旋钮分四层，每层标注确定性保证的边界：

1. **语法约束**（JSON Schema / CFG）：保证 100% 可解析。完全确定，开销近零
   （XGrammar 证据）。边界：只保证形式，不保证内容。
2. **协议约束**（transport 校验 + 确定性 retry + bounce）：保证「不合格最多
   bounce 一次后降级」。确定性过程，已有实现。
3. **语义约束**（`confidence_cap ≤ min(upstream)` 代码强算；
   `evidence_refs ⊆ 已执行记录`）：保证逻辑单调。已在
   `submit_l5_claim` / `run_gate` 实现。
4. **统计约束**（stability ledger：N-sample 字段一致率、final-answer 一致率、
   violation rate 时序）：不保证单次，保证分布——测量而非约束。

**设计原则：约束只加在「机器消费的 interim」上；面向人的最终答案保持自由文本**
（用户语言、自然改写）。这是与「全结构化生成」路线的差异点，避免扼杀输出质量。

**信息流方向控制**（直接针对「偷看」）：evidence 先执行后引用（执行 ts < claim
ts）+ claim 引用闭包检查。事后补写的推理拿不到早期时间戳——不是检测 heuristic，
是结构性暴露。

## 6. 实验设计（可证伪）

平台：本 harness（gateway inject/guard + traces + dispatch 三层已备）。

对照组：

- A 基线：现状（自由文本 interim + 事后 intercept）
- B：+ SubagentReport schema 化（协议层）
- C：+ ReasoningRecord append-only（协议 + 时序层）
- D：+ 语法层（structured outputs strict / grammar-constrained，视提供商支持）

任务：复用 study repo 的 fixtures（已有 529 runs 冻结基线）+ 本仓库真实任务
（exit-gate 修复回路类）。

指标：结构有效率；converge 轮次；父解析错误率（人工标注 100 条）；端到端成功率；
token 成本；stability（N=20 同任务采样的字段集合 Jaccard / final answer 一致率）；
violation rate 时序趋势。

假设：

- H1：B 组父解析错误率 → ~0 且 converge 轮次下降（若不降反升，schema 成本假设
  被证伪）。
- H2：C 组事后合理化发生率下降（用 paper 的偷看检测器做裁判）。
- H3：效率净收益 = 轮次节省 × 成本 − schema 开销 > 0。

## 7. 风险与开放问题

- **schema 僵化**：任务不适配时模型「削足适履」（字段里塞散文）→ 缓解：`gaps[]`
  保留自由文本逃逸舱。
- **遵循率本身概率化**：强/弱模型的 schema 遵循差异 = 新型马太效应？→ 测量并
  报告，不预设。
- **时序约束的实现成本**：append-only 与模型「自我修改前文」的习惯冲突 → 在
  transport 层强制（生成后校验），不在解码层硬做。
- **grammar-constrained decoding 与推理质量的交互**：约束是否损伤推理路径多样
  性 → D 组专门测量。

## 8. 路线

- P0 协议 schema 定稿 + 文献锚定（本笔记）✅
- P1 gateway schema 校验器 + SubagentReport 原型（改造 dispatch 返回）
- P2 对照实验 A–D（复用 study fixtures）
- P3 paper（英文，与 study repo 同系列）

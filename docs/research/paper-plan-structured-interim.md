# 新论文计划：Structured Interim Outputs 系列（与 Paper 1 共存）

> 内部计划文档（review 稿）。分支：`research/structured-interim-contracts`。
> 输入：P0 设计笔记（`structured-interim-outputs.md`）+ Paper 1
> （*Contracts as Task Skeleton*, contract-driven-harness-study）的定位。

## 0. 共存关系总览（先界定，避免自我重叠）

| | Paper 1（已发表中） | Paper 2（新·主论文） | Paper 3（新·伴生测量） |
|---|---|---|---|
| 核心主张 | contract 外置隐式义务 → bounded determinism | interim 输出的**协议化**：schema 承载认识论字段 + 信息流方向约束 | 每层约束**实际买到多少稳定性**的测量学与成本账 |
| 回答的问题 | 约束能否收束行为？ | 机器消费的中间产物该长什么样？ | 这些约束值多少钱（收益/税）？ |
| 关键机制 | staged contracts + repair loop | append-only ledger、ts 闭包、SubagentReport/ReasoningRecord | stability ledger、A–D 消融 |
| 与偷看现象的关系 | 发现现象 | 给出**结构性**抑制机制 | 测量抑制效果与残余率 |
| 实验角色 | 已有 529 runs 冻结基线 | 复用 fixtures + 机制验证 | 四组消融 + N=20 稳定性采样 |

Paper 2 引用 Paper 1 作为动机与基线；Paper 3 引用两者。三篇 claim 无交集：
Paper 1 讲「外部义务」，Paper 2 讲「中间产物的结构与方向」，Paper 3 讲「约束的
计量经济学」。

**系列全景（含更早规划）**：若把此前全部规划计入，论文版图是四轴——
Paper 1 contracts（study repo，已有）；**候选 Paper 1.5：epistemic governance
harness 方法论**（L1-L5 认知分层、weakest-link confidence cap、exit gate 验证
回路、双过程路由——本仓库主体，从未正式立项，是潜在第三轴）；Paper 2 / Paper 3
即本文档两计划。是否将 harness 方法论立为独立论文 = 独立决策（见 §4.5）。

## 1. Paper 2（主论文，推荐优先）

**Working title**: *Structured Interim Outputs: Schema-Constrained Reasoning Records and Information-Flow Direction for Controllable Stability in LLM-Agent Systems*

**目标 venue**（投稿时按截稿窗口定，顺序为偏好）：ICLR / NeurIPS 主会；备选
ACL findings / EMNLP、AAAI。**定位：方法论论文**——机制贡献（协议 +
分层保证理论）为主权重，测量为辅助权重（由 Paper 3 承接测量学）。

### 结构（section 级）

1. **Introduction** — 动机：interim 产物（reasoning trace、sub-agent 报告、
   tool 参数）由机器消费却保持自由文本；format-only 结构化输出保证可解析性但
   不保证认识论纪律。三种失稳：无证据 claim、confidence 虚高、结论先于推理
   （post-hoc rationalization，呼应 Paper 1 报告的偷看现象）。贡献列表。
2. **Related Work** — 四条线：结构化生成与 grammar-constrained decoding
   （XGrammar、GCD 系列、Outlines）；中间推理单元（CoT、ReAct、ToT、
   self-consistency）；agent 通信协议（A2A、MCP）；contract/constraint 治理
   （Paper 1 自引）。
3. **Threat Model: How Interim Outputs Fail** — 失稳现象学分类（格式漂移、
   语义漂移、方向颠倒），每类给真实 trace 样例（来自本 harness traces/）。
4. **The Protocol** — ReasoningRecord 与 SubagentReport 的 schema 定义
   （认识论字段：layer、source_ids、confidence_cap）；append-only ledger 语义；
   引用闭包规则（evidence ts < claim ts）；面向人输出的自由文本豁免原则。
5. **Layered Constraints and Their Honest Bounds** — 四层旋钮（语法/协议/
   语义/统计），每层给出确定性保证的精确边界（什么是 100%、什么是单调、什么
   只是测量）。与「全结构化生成」路线划界。
6. **Instantiation** — 开源 harness 中的落地：gateway transport 校验器、
   epistemic-mcp claim DAG、exit gate 记账；实现成本数据。
7. **Evaluation** — 机制验证（有效性/闭包拦截率）+ 引用 Paper 3 的消融摘要；
   主指标：解析漂移、converge 轮次、事后合理化残余率。
8. **Discussion** — schema 僵化与逃逸舱；遵循率的模型间差异（马太效应）；
   约束与推理多样性的张力。
9. **Conclusion**。

### Abstract（草稿，实验数字留 [TBD]）

> LLM agents emit intermediate artifacts — reasoning traces, sub-agent reports,
> tool arguments — that are consumed by machines, yet these interim outputs
> remain free-form text. Format-oriented structured-output tooling guarantees
> parseability but is silent on epistemic discipline: claims appear without
> evidence, confidence is asserted above what cited sources support, and
> conclusions can silently precede the reasoning that ostensibly produced them —
> the post-hoc rationalization pattern observed as "answer-peeking" in
> contract-constrained agents. We introduce **structured interim outputs**, a
> protocol layer in which every machine-consumed intermediate is a
> schema-validated record carrying epistemic fields — claim, evidence
> references, and a confidence ceiling — written to an append-only ledger.
> Layered constraints provide distinctly bounded determinism guarantees:
> grammar-level validity, protocol validation with deterministic degradation,
> code-computed semantic monotonicity (confidence ceilings as weakest-link
> functions of cited evidence), and statistical stability measurement. Because
> records are append-only and timestamped, information-flow direction becomes
> structurally enforceable: a claim may only cite evidence executed before it,
> making post-hoc rationalization detectable by construction rather than by
> heuristic. We instantiate the protocol in an open agent harness and evaluate
> it on staged agent tasks reused from a prior contract-governance study
> [TBD: mechanism-level results: parse-drift elimination, converge-round delta,
> residual rationalization rate].

### 关键贡献声明（投稿用 4 条）
1. 问题形式化：interim 输出的三类失稳与「方向颠倒」类别（新）。
2. 协议：带认识论字段的结构化 interim + append-only 时序语义（新）。
3. 保证的分层理论：每层确定性的精确边界（对 GCD/structured outputs 的
   认识论扩展）。
4. 开源实例化 + 机制级实验证据。

## 2. Paper 3（伴生测量论文；可与 Paper 2 合并）

**Working title**: *What Do Constraints Buy? A Measurement Study of Stability,
Cost, and the Schema Tax in Constrained LLM-Agent Communication*

**目标 venue**：EMNLP findings / AAAI / TMLR（ measurement 与成本账适合
workshop-first：NeurIPS Datasets & Benchmarks 亦可选）。

### 结构（section 级）

1. Introduction — 可控性主张多为定性；本文把「约束买到什么」变成可复现的
   数字。
2. A Measurement Framework — stability ledger 定义：schema validity、
   parent parse-drift rate、converge rounds、N-sample field-set Jaccard、
   final-answer agreement、violation-rate 时序；成本侧：schema tax
   （token 开销、bounce 次数、降级频率）。
3. Experimental Design — A–D 四组消融（基线 / +协议层 / +时序层 / +语法层）；
   任务 fixtures 复用 study repo（529 runs 冻结基线）；N=20 采样协议。
4. Results [TBD] — 按假设 H1–H3 组织；报告负结果同样入文。
5. Cost Accounting — 约束的边际收益递减曲线；何时「不加约束」是最优解。
6. Related Work / Conclusion。

### Abstract（草稿，数字留 [TBD]）

> Constrained generation is widely claimed to make LLM-agent behavior
> "controllable", but the claims are rarely quantified per constraint layer. We
> present a measurement framework — a stability ledger — that turns
> controllability into reproducible numbers across four ablation layers of a
> structured interim-output protocol: free-text baselines, schema-validated
> agent reports, append-only reasoning ledgers with temporal closure, and
> grammar-constrained decoding. Reusing frozen task fixtures from a prior
> contract-governance study, we measure schema validity, parent-agent
> parse-drift, convergence rounds, N-sample field consistency, and
> final-answer agreement, alongside the costs: token overhead, validation
> bounces, and degradation events. [TBD: headline findings, including the
> marginal-returns curve of constraints and regimes where unconstrained
> generation is cost-optimal.] The ledger and all raw measurements are released
> for reuse.

## 3. 里程碑（接续 P0–P3 路线）

| 阶段 | 内容 | 产出 | 依赖 |
|---|---|---|---|
| P0 | 协议定稿 + 文献锚定 | 设计笔记 ✅ | — |
| P1 | gateway schema 校验器 + SubagentReport 原型 | Paper 2 §5–6 素材 | 本仓库 feature 线 |
| P2a | 机制验证实验（Paper 2 §7） | Paper 2 初稿 | P1 |
| P2b | A–D 消融 + N=20 采样 | Paper 3 数据集 + 初稿 | P1，可与 P2a 并行 |
| P3 | 投稿（先 Paper 2） | 两篇稿 | P2a/P2b |

## 4. 决策记录（2026-11-24 拍板）

1. **两篇** ✅。若计入更早规划，系列全景见 §0——harness 方法论是潜在第三轴，
   另行决策。
2. **机制 > 测量，方法论定位** ✅——venue 与写作权重按此调整（见 §1）。
3. **预算** ✅ 简估见 §5，非主要矛盾。
4. **Paper 2 是 Paper 1 的延续，同时允许多元 motivation** ✅——Abstract 已按
   双动机写（机器消费缺口的结构性问题 + Paper 1 偷看现象学作为实例），动笔时
   Introduction 按此结构展开。

## 4.5 独立决策：harness 方法论是否立为 Paper 1.5

素材齐备度：本仓库即完整实例（五层认识论 taxonomy、weakest-link cap 的代码
强算、exit gate 的 claims-bind-to-evidence、双过程 tier 路由、traces 账本），
claims 与 Paper 1/2/3 均不撞（治理框架 vs 外部义务 vs interim 协议 vs 测量）。
立项收益：系列里最早可被引用的「总框架」论文；成本：写作 + 一套跨任务评测。
默认不动，等拍板。

## 5. 预算简估（N=20 采样，数量级参考）

| 项 | 估算 |
|---|---|
| Paper 3 消融 | 8 fixtures × 4 组 × 20 采样 = **640 runs** |
| 单 run token | 3–8k（interim 结构化后偏下限）→ 总量 **2–5M tokens** |
| Paper 2 机制实验（P2a） | ~100 runs，可忽略 |
| 模型策略 | 主跑 flash/GLM 级（与 Paper 1 基线可比、便宜）；关键结论用强模型复核 20% |
| 结论 | 成本为「几十元级」数量级，非主要矛盾 ✅ |

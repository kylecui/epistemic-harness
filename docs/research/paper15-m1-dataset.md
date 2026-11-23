# Paper 1.5 M1 数据集说明（Evaluation 素材盘点与口径）

> 研究分支文档。生成器：`scripts/paper_m1_aggregates.py`（feature 线）→
> 本文件与 `m1-aggregates.json`（重新生成时用 `python scripts/paper_m1_aggregates.py
> > docs/research/m1-aggregates.json`）。

## 1. 可用数据源（全部 append-only 运行记录，无需实验编排）

| 源 | 内容 | Paper 1.5 用途 |
|---|---|---|
| `traces/contract_violations.jsonl` | 每回合契约判定（含 `code_rev`） | §8 violation rate 时序 + pre/post 修复对照 |
| `traces/gateway_traces.jsonl` | 每请求路由/用量/anti-thrashing 行程 | 双过程路由成本、trip/auto-recovery 统计 |
| `.pi/controller_metrics.jsonl` | controller 实测（direct-write vs dispatch） | §5「测量而非假设」证据 |
| `.pi/loop_ledger.jsonl` | 跨回合 thrash 指纹 | §6 thrash 消除率 |
| `traces/quota_ledger.db` | 池级 token/unit 账本 | 成本侧 |
| `traces/reasoning_ledger.jsonl` | 结构化 interim 账本（新机制） | §7 实例化 + Paper 2 引子 |

## 2. 当前聚合要点（m1-aggregates.json，截至 2026-11-23）

- 契约判定记录 116 条（11-22: 83 → 11-23: 33，下降趋势；注意 11-22 为事故修复密集日，混杂度高）。
- 违规类别分布：缺陷类（缺验收/缺回退/降级）~99、三段式锚点 64、L3 scope/counter 34、silent promotion 仅 8。
- per-code_rev：`2026-11-22.r3` 114 回合 208 违例（1.82/回合）；`2026-11-24.r1`（修复后）2 回合 2 违例——**样本太小，不作结论**。
- thrash 账本 37 条 / 7 指纹；controller 记账在册；reasoning ledger 已有探针记录。

## 3. 口径与诚实边界（写作时必须声明）

1. **运行数据是存在性/趋势证据，不是因果证据**：同一作者、代码同时在演进、任务非受控。因果主张只能来自 A–D（+A0）受控实验。
2. **r3 时代的高违例率混杂了「框架本人在学习框架」**：适合写进 Discussion（纪律成本的真实写照），不适合当基线。
3. **机械判定 vs 裁判判定**：框架臂的违例是确定性代码判的；任何对照臂（A0/A）只能事后用强模型裁判按同一 rubric 盲评——不对称性本身是贡献点。

## 4. 缺口清单（→ 实验计划）

- [ ] **A0 纯净 pi 直连臂**（用户已拍板立项）：同任务集 × pi 默认配置 × N=20；指标同表；裁判盲评 rubric 需先定稿。
- [ ] 内部消融轴：同管道 guard/gate 关闭 vs 开启（分离「治理收益」与「路由收益」）。
- [ ] violation 裁判 rubric（供 A0/A 臂事后判定用，需与 response_guard 规则一一对应）。
- [ ] Paper 1.5 §8 图表脚本（matplotlib，从 m1-aggregates.json + 实验输出出图）。

## 5. 决策记录

- 2026-11-24：A0（纯净 pi 对照）立项，纳入 A–D 矩阵为第 0 臂；同时保留内部消融轴。理由与设计与见 issue/讨论记录（A0 回答「框架整体净收益」，A–D 回答「每层约束买什么」，两者互补不重叠）。

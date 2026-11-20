# Loop Engineering：防推诿与零残留收尾方案（Exit Gate & Anti-Shirking）

## 1. 问题本质：为什么模型总在收尾时“甩锅”？

在常规 Agent Loop 中，模型同时扮演**执行者**与**验收裁判**（由模型自己触发 `end_turn`）。在 RLHF 偏好“快速给出礼貌答复”和“最小改动（minimal diff）”的共同作用下，一旦遇到陌生测试失败或依赖报错，模型最省力的局部最优解不是修 Bug，而是宣布：

> “我的改动已经完成；其余失败是历史遗留问题（pre-existing issue），与本次修改无关。”

要根治收尾残留，核心原则只有一条：**剥夺模型自证完工的权力，把 Definition of Done（DoD）下沉为确定性代码门禁。**

## 2. 三层防御架构

```text
[Soft Layer]   AGENTS.md (v0.3.2)         -> 明确 Green-Baseline 责任边界 + 零残留纪律 + 严格阻塞上报门槛
       |
[Guard Layer]  harness-guard.ts (v0.4.0)  -> 监听 edit/write 变更 -> 回合结束前自动运行 Exit Gate + 状态联动反甩锅检测
               orchestrator/exit_gate.py  -> 供无头 Python Orchestrator / CI 复用的同构确定性门禁引擎
       |
[Valve Layer]  Circuit Breaker            -> max_gate_retries = 3；连续相同错误指纹触发一次升档；超限输出 L2 阻塞报告
```

### 2.1 Layer 1 — 确定性 Exit Gate（硬门禁）
- **仅在发生文件变更的回合触发**：纯问答、System 0/1 轻量查询（如 `TC-04`）零额外开销。
- **项目级配置 `.pi/exit_gate.json`**：声明当前仓库的验收命令（单测、类型检查、lint）与临时残留匹配规则（`*.tmp`, `*.bak`, `debug_*.py`, `scratch_*`, `*.orig`）。
- **两项硬校验**：
  1. 所有配置的验收命令必须返回 `exit_code == 0`；
  2. `git status --porcelain` 不得存在未清理的临时残留文件。

### 2.2 Layer 2 — 状态联动的反推诿检测（Anti-Shirking Guard）
- 仅当 **Exit Gate 失败或存在残留文件** 时，才扫描模型回复中的推诿模式：
  - 英文：`pre-existing`, `unrelated to my changes`, `not introduced by`, `out of scope`, `left as an exercise`, `existing failure`
  - 中文：`不是我引入`, `原有问题`, `历史遗留`, `与本次修改无关`, `超出本次范围`, `留给用户`
- **关键防误伤设计**：当验收全部绿灯时，正常说明范围边界绝不会被误拦。

### 2.3 Layer 3 — 防死循环熔断与两级范围边界
- **重试上限**：单回合自动打回最多 `max_gate_retries = 3` 次。
- **同错升档**：对失败命令 + 归一化报错尾行计算 SHA-1 错误指纹；若连续两次指纹完全一致，注入 `[ESCALATE_REASONING: high]` 提示代理网关临时升档推演，避免低档位原地打转。
- **两级范围边界（防 Scope Creep）**：
  - **阻塞链路上的失败（无论是否历史遗留，必须修）**：只要在当前任务的验收测试、编译链或导入依赖图内报错，零借口修到绿灯。
  - **完全无关的历史债务（登记不劫持）**：明确不在当前调用链上的旧模块告警，以 `文件:行号 + 报错` 记录为后续项，不静默忽略，也不擅自大改。

### 2.4 Layer 2b — 评审回合完整性（Review-Turn Remediation Completeness, issue #1）
- **盲区**：§2.2 的反推诿扫描仅在 Exit Gate 失败或文件残留时触发；纯评审回合（零文件变更）里，
  把已声明缺陷降级为“补文档/写进已知问题/留待观察”不会被拦。
- **规则（已在代码强制）**：
  1. 回复中出现已声明缺陷锚点（`P1`/`缺陷N`/`缺口N`/`defect N`）时，每个缺陷条目必须自带
     `验收/acceptance` 与 `回退/rollback` 锚点，否则打回一次并附具体条目编号；
  2. 降级措辞（`最小后续动作`/`补一段文档`/`写进已知问题`/`留待观察`）与已声明缺陷同现 → 打回；
  3. 输出结构自检（Tier ≥ 1.5 或 Converge 且正文 ≥ 100 字符）：三段式锚点缺失、
     头部 Confidence Cap 强于正文最弱 `[Lx]` 标签（silent promotion）、`[L3` 标签后 3 行内
     缺 适用/反例 锚点 → 各自打回；
  4. **防误伤**：无缺陷锚点的纯问答/短答复（< 100 字符）不检查；用户显式 L4 取舍
     （“只要评审结论/本次只出评审结论/只列 file:line”）时放行；打回最多一次，
     之后转 L2 上报，不进入自动重试循环。
- **落点**：`proxy_gateway/response_guard.py`（注入/拦截层）+ `orchestrator/exit_gate.py`
  （同构引擎，非变更回合也过评审检查）；黄金用例 `evals/golden_cases_review_completeness.yaml`
  （TC-12 降级拦截 / TC-13 结构拦截 / TC-14 silent promotion 拦截 / TC-15 L4 防误伤），
  确定性单测 `tests/test_review_completeness_tc12_15.py`。

## 3. 文件清单与合入路径

| 包内文件 | 合入目标路径 | 作用 |
| :--- | :--- | :--- |
| `patches/extensions/harness-guard.ts` | `extensions/harness-guard.ts`（及 `~/.pi/agent/extensions/harness-guard.ts`） | Pi 增量补丁：保留 P1-2/P2-1 低摩擦修复，新增 Exit Gate + 状态联动反甩锅 + 熔断器 |
| `patches/orchestrator/exit_gate.py` | `orchestrator/exit_gate.py` | Python 同构门禁引擎，供 `orchestrator/plan.py` 与自动化评测复用 |
| `patches/pi/exit_gate.json` | `.pi/exit_gate.json` | 项目级 Exit Gate 配置模板（验收命令、残留文件 glob、重试上限） |
| `patches/root/AGENTS.md` | `AGENTS.md` | 升级至 v0.3.2，新增 `Zero-Residue & Green-Baseline Ownership` 软约束 |
| `evals/golden_cases_exit_gate.yaml` | `evals/golden_cases_exit_gate.yaml` | 新增 `TC-10`（历史遗留依赖报错防甩锅）与 `TC-11`（测试全过但留临时脚本防残留） |
| `tests/test_exit_gate_and_tc10.py` | `tests/test_exit_gate_and_tc10.py` | 6 项端到端自动化单测（含真实临时 Git 仓库 + 失败单测夹具） |

# Phase 1 工程落地手册：Pi 洁净室 `harness.yaml` 与 `epistemic-mcp` 最小可运行骨架

> **交付物说明**：完整的最小可运行仓库已打包为 `epistemic-harness-phase1.zip`，并通过了全部 6 项确定性硬约束与真实 MCP stdio 协议单元测试。解压即可直接接入 [Pi Coding Agent](https://pi.dev/)（v0.99.0+ 原生支持项目级 `.pi/mcp.json`）启动洁净室开发。

## 一、 仓库目录结构

```
epistemic-harness-phase1/
├── harness.yaml                    # 单一规范源（L1-L5 权限、双系统认知档位、反震荡参数）
├── AGENTS.md                       # 由 scripts/compile_clients.py 自动编译，Pi/OpenCode 通用
├── .pi/
│   └── mcp.json                    # Pi 项目级 MCP 接入配置（stdio 零配置直连）
├── knowledge/                      # 物理隔离的知识域（Git 版本化管理）
│   ├── l1_axioms/axioms.yaml       # 只读公理库（CAP / 可靠性 / 延迟恒等式 / ARR 公式）
│   ├── l2_library/evidence.yaml    # 可验证外部证据库（含出处与 verified_at）
│   └── l3_heuristics/heuristics.yaml # 经验法则库（代码强校验 scope_conditions + counter_examples）
├── mcp_server/
│   ├── dag_engine.py               # 纯代码引擎：只读 L1 防泛化 + 短板继承 DAG + 人类 PR 升格门
│   └── server.py                   # 零额外 MCP SDK 依赖的标准 JSON-RPC 2.0 stdio MCP Server
├── scripts/
│   └── compile_clients.py          # harness.yaml -> AGENTS.md 单向编译器
└── tests/
    └── test_epistemic_mcp.py       # 6 项自动化硬约束测试 + 真实 stdio 子进程联调测试

```

## 二、 核心规范：`harness.yaml`（单一规范源）

```
version: "0.2.0"
name: "epistemic-dual-process-harness"
description: "双维治理 Harness 单一规范源（Phase 1 · Pi 洁净室硬插件版）"

epistemic_tiers:
  L1:
    label: "公理与核心原则"
    read_only: true
    allow_model_invention: false
    priority: 1
    admission_rule: "仅限数学/物理定理、形式化定义、法律法规或用户明文锁定的客观硬边界；工程常识与团队资源约束禁止归入 L1。"
  L2:
    label: "可验证事实与证据"
    require_provenance: true
    max_age_days: 180
    priority: 2
  L3:
    label: "经验与启发式"
    falsifiable: true
    require_scope_and_counter_examples: true
    priority: 3
  L4:
    label: "用户意图与资源约束"
    cannot_override: ["L1"]
    priority: 4
  L5:
    label: "中间推导与结论"
    default_status: "provisional"
    weakest_link_inheritance: true
    priority: 5

cognitive_spectrum:
  system_0:   { label: "直觉执行档（零档）", reasoning_effort: "none" }
  system_1:   { label: "快速初筛档（快思考）", reasoning_effort: "low" }
  system_1_5: { label: "结构分析档（中度思考）", reasoning_effort: "medium", default_analysis_tier: true }
  system_2:   { label: "深度推演档（慢思考）", reasoning_effort: "high" }
  system_2_plus: { label: "独立复核档（审视模式）", reasoning_effort: "high" }

```

## 三、 `epistemic-mcp` 暴露的 7 个硬约束工具

| MCP 工具名 | 所属硬插件 | 确定性拦截逻辑（代码层兜底，不受 Prompt 漂移影响） | 
| ----- | ----- | ----- | 
| `query_l1` | `epistemic-ns` | 检索只读 `l1_axioms/`，返回带 `read_only: true` 标记的合法 `L1-*` ID | 
| `search_l2` | `epistemic-ns` | 检索 `l2_library/`，强制返回 `source` 与 `verified_at` 时间戳 | 
| `recall_l3` | `epistemic-ns` | 检索 `l3_heuristics/`；加载时代码强校验每条 L3 必须含 `scope_conditions` 与 `counter_examples` | 
| `register_l4_input` | `epistemic-ns` | 在当前会话注册 `L4-*` 用户意图与资源约束（不改变客观认识论上限） | 
| `submit_l5_claim` | `provenance-dag` | **双硬闸**：① 拦截任何不在 `l1_axioms/` 中的伪造 `L1-*` ID（`L1_CREEP_BLOCKED`）；② 跨多跳 DAG 纯代码计算 `min(upstream_tiers)` 并强制覆写虚高评级（`WEAKEST_LINK_OVERRIDE`） | 
| `audit_dag` | `provenance-dag` | 审计整张会话推导图，输出全局 `overall_confidence_cap`；存在 L1 冲突时直接锁死 `converge_allowed: false` | 
| `propose_promotion` | `promotion-gate` | 严禁直写 L1/L2，将升级提案写入 `promotions/pending_pr.yaml` 等待人类审批 | 

## 四、 Pi 洁净室 30 秒启动步骤

1. 解压 `epistemic-harness-phase1.zip` 并进入目录，安装极简依赖（仅需 `pyyaml` 与 `pydantic`，MCP 协议已用标准库零依赖实现）：

   ```
   pip install pyyaml pydantic
   
   ```

2. 编译单一规范源并跑全量硬约束自测（含真实 MCP stdio 协议回环）：

   ```
   python3 scripts/compile_clients.py
   python3 -m unittest discover -s tests -v
   
   ```

3. 直接在项目根目录启动 [Pi](https://pi.dev/)（项目内已内置 `.pi/mcp.json` 与 `AGENTS.md`，与日常 OpenCode / Oh-My-OpenAgent 环境完全隔离）：

   ```
   pi
   # 启动后可执行 `pi mcp list` 确认 epistemic-harness 已连接
   
   ```
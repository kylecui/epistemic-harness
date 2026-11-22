# 认知双过程治理 Harness（Epistemic & Dual-Process Governance Harness）

**面向 LLM 编码 agent 的治理层：证据绑定的完成声明、分层认知，以及把问题耗尽而不是来回踢皮球的回环。**

[![version](https://img.shields.io/badge/version-v0.4.0-blue)](docs/workplan-v0.4.md)
[![tests](https://img.shields.io/badge/tests-237%20green-brightgreen)](scripts/verify.py)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

*本文是 [README.md](README.md) 的中文辅助翻译；规范内容一律以英文版与 AGENTS.md 为准（思考语言约束见契约）。*

## 它做什么

处在这个 harness 里的 LLM agent 无法悄无声息地：

- **没有证据就宣称完成** —— 量化断言（"100% 覆盖"、"全部测试通过"）必须绑定到退出闸门本轮亲自执行过的检查，否则该回合被拦下（issue #2）；
- **把已有答案的事包装成"请你决策"** —— 抛出的决策点必须带 L4 取舍或缺失证据锚点，否则按伪决策点打回（issue #3）；
- **推卸失败** —— 推诿措辞只在验证红灯时被拦截，且每个失败都有归属：`code_defect / check_defect / env_missing / underdetermined`；
- **骗过验证器** —— 验证器自身的指纹被记录在案；验证器改动之后立刻变绿会被标记；
- **同一个修复无限重试** —— 跨回合 ledger 把相同失败指纹升级到根因分析。

此外还有：L1–L5 认知分层记忆与最弱环节置信上限、混合检索（BM25 + 中文双字分词，分库返回永不混合）、数据驱动的任务路由（每类别模型/强度的决策在 YAML 里，经能力矩阵校验）、三档子 agent 派发（纯文本 / 只读沙箱 explorer / 全权 tooled），以及 Docker 优先的验证与显式声明的宿主回退。

## 快速开始

```bash
git clone https://github.com/kylecui/epistemic-harness.git
cd epistemic-harness

python scripts/install.py        # 平台检测、前置检查、逐项询问 API 密钥、冒烟测试
docker compose up -d --build     # 启动网关后端 (127.0.0.1:8787)
pi                               # 在仓库内启动 Pi（加载 AGENTS.md + MCP）
```

安装器会读取模型注册表，逐项询问当前配置所需的密钥（回车保留已有值，全部可跳过）。
想手写？直接编辑 `.env`，见 [docs/configuration.md](docs/configuration.md)。

更轻的两条路：

```bash
# 最快：只验证 —— 不需要 venv 与安装；容器本身就是运行时
docker compose build verify && docker compose run --rm verify

# 宿主最小路径：只需要一个引导 python，其余由安装器完成
python scripts/install.py
```

随时验证 —— `hvx` 包装器替你解析项目解释器（优先 `.venv`，其次 `python3`/`py`；验证本体默认在 Docker 里跑）：

```bash
./scripts/hvx                      # Windows: scripts\hvx.ps1
./scripts/hvx -p "test_gate*"      # unittest 发现模式
```

## 架构分层

| 层 | 组件 | 由谁强制 |
|---|---|---|
| 契约 | `harness.yaml` → 编译产物 `AGENTS.md` / `SKILL.md` | prompt + 网关 |
| 退出闸门 | `orchestrator/exit_gate.py` + `extensions/harness-guard.ts`（镜像） | 确定性代码 |
| 验证运行器 | `scripts/verify.py`、`Dockerfile.verify` | Docker 优先，宿主回退 |
| 认知内核 | `mcp_server/`（L1–L5 DAG、FTS5 记忆、L5 持久化） | MCP 工具 |
| 编排 | `orchestrator/`（派发、路由、计划、只读 explorer） | MCP 工具 + 网关联动 |
| 文档 | `docs/`（索引：[docs/README.md](docs/README.md)） | 退出闸门里的 `scripts/check_docs.py` |

## 技能：不用记的命令

`harness-verify`（./scripts/hvx）、`harness-status`（派发观测 / 能力矩阵 / 记忆统计）、
`harness-maintain`（改配置后重编译+重校验）、`harness-config`（密钥、默认模型、钉选）
已注册进 `skills/registry.yaml` —— 派发时由代码自动匹配挂载，中英文触发词均可。
随时通过 orchestrator MCP 的 `query_skills` 查询。

## 文档

- [INSTALL.md](INSTALL.md) — 平台检测、前置条件、FULL/LIMITED 支持矩阵（英文）
- [docs/configuration.md](docs/configuration.md) — 密钥配置、默认模型选择、钉选（英文）
- [docs/README.md](docs/README.md) — 文档索引（英文）
- [docs/execution-runner.md](docs/execution-runner.md) — 为什么验证默认跑在容器里（英文）
- [docs/browser-runner.md](docs/browser-runner.md) — CDP/浏览器放置策略（英文）
- [docs/workplan-v0.4.md](docs/workplan-v0.4.md) — v0.4 交付日志（双语，顶部有英文摘要）

## 开发

```bash
git clone https://github.com/kylecui/epistemic-harness.git
cd epistemic-harness
./scripts/hvx                                # 206 项测试
python evals/run_evals.py --mock             # 黄金用例回归 12/12
python scripts/check_eol.py                  # 换行符纪律
python scripts/check_docs.py                 # 文档/代码同步闸门
python scripts/analyze_dispatches.py         # 派发了什么、给了哪个模型、什么强度
python scripts/capability_matrix.py          # （模型 × 强度）可调度空间
```

MIT 协议，见 [LICENSE](LICENSE)。

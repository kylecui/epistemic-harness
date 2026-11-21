# Execution Runner Policy — Docker-first, host as explicit fallback

> 结论：验证与执行默认跑在容器里（POSIX shell、固定 Python、固定换行符），宿主机直跑只作为"没有 Docker 时的降级路径"，
> 而且降级必须被记录、不允许静默发生。
> 依据：本机实测 + 外部研究（每条带来源与读取日期 2026-11-21）。

## 1. 为什么不是"偏好问题"

### [L2] 本机实测（同一台 Windows 机器，同一份 136 项测试）

| 运行方式 | 墙钟 | 说明 |
|---|---|---|
| 宿主机 `.venv` python | 7.15 s（空载）/ 13.9 s（有负载时） | shell 由宿主环境决定 |
| `docker run --rm --network none -v .:/work` | 9.0 s 墙钟，容器内 4.3–4.6 s | 计入容器启动 ~2 s；容器内跑得更快（无杀软实时扫描、POSIX 文件语义） |

镜像构建一次 27.8 s（`python:3.12-slim` + git + requirements）。

### [L2] 已经踩过的坑（都是宿主差异导致，不是代码问题）

1. **shell 不同**：`subprocess.run(shell=True)` 的解释器由 `COMSPEC` 决定。曾用 `printf 'a\nb\n'` 写闸门 fixture，在一种环境下通过、在另一种下变红。
2. **换行符不同**：本仓文件此前全是 CRLF。CRLF 的 `#!/usr/bin/env bash` 在 Linux 容器里直接 `bad interpreter: /bin/bash^M`。
3. **解释器不同**：PATH 上的 `python` 是 3.12.3 系统解释器，缺 fastapi/pydantic；venv 才是对的。

容器能同时消掉这三条，但它**不会自动修换行符**——那需要 `.gitattributes`（本仓已加 `eol=lf`，`.ps1/.bat` 保留 CRLF）。

### [L2] 外部研究

- **执行基底本身就是变量**：单容器 / 托管沙箱 / k8s 编排 / 云 VM 四种基底的冷启动最多差 **110 倍**，跑 100 万条 150 步轨迹的预计工时差 **1.8 倍**。结论是"执行基底要当训练系统的一部分来优化，而不是当部署细节"。arXiv:2607.01415 — https://arxiv.org/abs/2607.01415
- **OS 层开销占大头**：在容器化编码 agent 上，工具调用 + 容器/agent 初始化占端到端延迟的 **55–60%**；瓶颈是内存而非 CPU，峰值/均值可达 15.4 倍。所以"每个检查都起一个新容器"是错的，应当复用镜像与缓存。arXiv:2602.09345 — https://arxiv.org/abs/2602.09345
- **验证器可被绕过**：331 个终端 agent 环境被证明可被作弊通过，攻击包含输出伪造、栈帧内省、标准库打补丁、二进制劫持；且这些攻击是任务特定的，不是一个统一补丁能修的。含义：验证要在受控环境跑，并且"验证者本身是否被改过"要留证据。arXiv:2604.17596 — https://arxiv.org/abs/2604.17596

## 2. 策略（已实现）

`.pi/exit_gate.json` 新增两个字段：

```json
{ "gate_runner": "auto", "verify_image": "epistemic-verify:local" }
```

- `gate_runner: docker` — 强制容器。CLI 缺失或镜像不存在 → 检查失败并写明 `RUNNER_UNAVAILABLE`，**绝不悄悄降级**。
- `gate_runner: host` — 默认值。存量仓库行为不变，宿主 shell 语义，功能受限。
- `gate_runner: auto` — 只有 Docker CLI 可用**且**镜像已存在时才用容器，否则回落到 host 并把回落原因写进输出与 ledger。

`CheckSpec` 可带 `runner` 覆盖单条检查（例如某个检查必须用宿主 node 工具链）。

每条证据现在带 `runner` 字段，ledger 记录 `evidence` 名称列表；`scripts/verify.py` 打印 `runner=docker image=<img> rev=<sha>`，所以"这次绿灯是谁跑的"可事后追查。

## 3. 用法

```bash
# 一次性：构建沙箱镜像
docker build -f Dockerfile.verify -t epistemic-verify:local .

# 全量验证（auto：有镜像走容器）
python scripts/verify.py
python scripts/verify.py --runner docker      # 强制，无 Docker 则退出码 3
python scripts/verify.py --runner host        # 降级

# compose 形式
docker compose build verify
docker compose run --rm verify
```

容器内 `--network none`：测试不需要联网，这一条同时把"检查里偷偷拉网络"变成不可能。

## 4. 明确不搬进容器的部分（写清楚比含糊好）

- **`dispatch_tooled`**：它要拉起 `pi` 二进制，容器里没有；工具化子 agent 仍走宿主。
- **OAuth / 设备码登录**（Copilot、Google）：需要浏览器或本机凭据，留在宿主。
- **用户自己的编辑器 / git hook**：不在本仓管辖范围。

## 5. 已知风险与对应证据

| 风险 | 现状 | 缓解 |
|---|---|---|
| 验证脚本被 agent 改掉后自证通过 | 挂载可写 | 每次绿灯记录 `rev=<sha>` + `image=<img>`；`scripts/` 与 `.pi/exit_gate.json` 的改动应走 review |
| 容器每个检查重启导致慢 | 一次 `run_gate` 只起 1 个容器（每条检查 1 次 `docker run`，可合并） | 若检查数增多，改为在容器内串行执行整组检查 |
| bind mount 在 Windows 上偏慢 | 实测可接受（+1.8 s） | 需要更快时挂 named volume 做缓存，而非改语义 |
| 换行符再次回潮 | `.gitattributes` 已固化 | `git add --renormalize .` 一次性归一 |

## 6. 验收

```bash
python scripts/verify.py --runner docker                  # 退出码 0，输出 runner=docker
python scripts/verify.py --runner host                    # 退出码 0，输出 runner=host
HARNESS_VERIFY_IMAGE=missing:1 python scripts/verify.py --runner docker   # 退出码 3 + RUNNER_UNAVAILABLE
python -m unittest tests.test_runner_selection -v         # 8 项：默认 host、docker 缺失即失败、auto 回落、per-check 覆盖
```

反例（应当失败）：把 `gate_runner` 设为 `docker` 而镜像不存在时仍然返回绿灯 —— 这说明降级被静默吞掉了，属于回归。

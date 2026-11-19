# Phase 2 代理网关与多模型动态调度文档（共享配额池 · 24h 主动避峰 · 跨家族复核）

> **对应配置与代码**：`proxy_gateway/quota_policy.yaml`、`proxy_gateway/policy.py`、`proxy_gateway/quota_manager.py`、`proxy_gateway/app.py`、`.env.example`。

## 一、 设计理念：超越静态绑定的双维动态调度

不同于在配置文件中把固定 Agent 角色写死到某个模型的静态路由（如 `oh-my-openagent`），本 Harness 的本地代理网关在**每一次 API 请求的运行时**结合三个实时维度动态选模：

1. **双系统认知档位（`System 0` → `System 2+`）**：同一会话内，简单格式/指令执行自动下沉到轻量 Flash 模型；复杂冲突推演动态升档至重型推理模型。

2. **元认知跨家族复核（`System 2+` Cross-Family Critic）**：网关按 `X-Harness-Session-Id` 记录上一轮起草 L5 推导的模型所属家族；触发独立复核/审计时，自动排除起草方所属共享池（例如 Kimi 起草则切智谱复核），避免同源模型自我盲区。

3. **全局主动避峰与共享三窗口配额（5h / 周 / 月）**：任何处于 `peak_windows_utc` 的主力池全档位自动退让给当前 Off-Peak 或无高峰窗口的主力池；任意共享池触及 5h / 168h（周）/ 720h（月）的 95% 软顶或收到 HTTP 429/529 时，整池立即熔断并自动跨厂商无缝切流。

## 二、 实配 5 套订阅共享额度池与 2026-11 旗舰兜底清单

| 共享池 ID | 角色定位 | 挂载模型 | 5h / 周 / 月共享额度（官方核实口径） | 计费系数 / 高峰规则与来源 | 
| ----- | ----- | ----- | ----- | ----- | 
| `zhipu_v2_max` | 主力池 1（智谱 V2 Max） | `glm-5.3`、`glm-5.3-flash` | **28,000 积分 / 5h**；**140,000 积分 / 周**；月折算 `560,000` | 官方积分/1M Tokens：`GLM-5.3` 为 `6.9 / 1.7 / 24`，`Flash` 为 `2.3 / 0.56 / 8`（1/3 消耗）；东八区 `09:30–18:30` 高峰退让（[智谱开放文档, 2026-11-11](https://docs.bigmodel.cn/cn/coding-plan/overview)） | 
| `kimi_allegretto` | 主力池 2（Kimi Allegretto） | `k3.1-pro`、`kimi-for-coding` | **5h 滚动 + 周限额 + 月共享池**（配置以 `10,000` 积分对应控制台 100% 便于校准） | 全会员共享一池；东八区 `09:30–18:30` 高峰退让（[Kimi 帮助中心, 2026-10-19](https://www.kimi.com/help/membership/membership-pricing)） | 
| `opencode_go_basic` | 主力池 3（OpenCode Go 基本版） | `deepseek-v4.1-flash` | **`$20` / 5h（20%）**；**`$50` / 周（50%）**；**`$100` / 月（100%）** | 官方高峰期费率 **2 倍**（`peak_cost_multiplier: 2.0`）；北美 `UTC 13:00–21:00` 高峰退让（[OpenCode Go Guide, 2026-11-13](https://qcode.cc/en/opencode-go-guide)） | 
| `github_copilot_pro_plus` | **末位兜底 #1** (`last_option: true`) | `claude-fable-5.2`、`claude-sonnet-5.5` | **7,000 AI Credits / 月**（设 `500` 5h 保护软顶） | `claude-fable-5.2` 为 Pro+ 当前最强深度推理旗舰，`sonnet-5.5` 为日常编码主力（[GitHub Changelog, 2026-11-16](https://github.blog/changelog/2026-11-16-github-copilot-weekly-releases-november-9/)、[Fello AI, 2026-11-04](https://felloai.com/claude-vs-copilot/)） | 
| `google_ai_pro` | **末位兜底 #2** (`last_option: true`) | `gemini-4-neon` | Pro 订阅共享池（按 `$5 / $20 / $60` 等效设保护阀） | 2026-11-18 GA 的 Pro 档最强旗舰（API `$3 / $0.15 / $15` per 1M）（[Google Blog, 2026-11-19](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-neon/)、[Gemini 4 Neon Specs](https://munderdiffl.in/blog/gemini-4-neon/)） | 

## 三、 24 小时跨时区主动避峰接力表（东八区视角）

| 北京 / 新加坡时间（+08:00） | 对应 UTC | 处于高峰主动退让的池 | 自动接管主力的 Off-Peak 池 | 末位保底池状态 | 
| ----- | ----- | ----- | ----- | ----- | 
| **09:30 – 18:30**（国内白天） | `01:30 – 10:30` | `zhipu_v2_max`、`kimi_allegretto` | **`opencode_go_basic`**（北美深夜 1× 低谷费率） | 锁定保底（不触碰） | 
| **18:30 – 21:00**（黄金窗口） | `10:30 – 13:00` | 无 | 三大主力池全 Off-Peak，按认知档位最优能力排序 | 锁定保底（不触碰） | 
| **21:00 – 次日 05:00**（北美白天） | `13:00 – 21:00` | `opencode_go_basic`（2× 高峰）、`github_copilot_pro_plus` | **`zhipu_v2_max` + `kimi_allegretto`**（国内夜间低谷） | 锁定保底（不触碰） | 
| **05:00 – 09:30**（黄金窗口） | `21:00 – 01:30` | 无 | 三大主力池全 Off-Peak，按认知档位最优能力排序 | 锁定保底（不触碰） | 

> **兜底铁律**：`last_option: true` 的两个池（GitHub Copilot Pro+ 与 Google AI Pro）永远位于最低优先级桶——**绝不因主力池处于高峰期而被误烧**，仅当三大主力共享池全部耗尽或处于 429 冷却期时才会自动解锁，并在响应头中返回 `X-Harness-Last-Option-Used: true`。

## 四、 运维与实时观测

```
# 1. 复制并填入各家 API Key
cp .env.example .env && source .env

# 2. 启动本地双协议代理网关
./scripts/start_proxy.sh

# 3. 实时查看 5 个共享池的 5h/周/月已用比例、高峰状态与冷却剩余时间
curl -s http://127.0.0.1:8787/quota | python3 -m json.tool

# 4. 查看最近的动态路由、跨家族审计与震荡熔断 Trace
curl -s http://127.0.0.1:8787/traces | python3 -m json.tool

```
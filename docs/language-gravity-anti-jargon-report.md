# 中文约束导致的推理漂移与去黑化验证报告（Language Gravity & Anti-Jargon Report）

## 1. 核心结论

1. **中文 `AGENTS.md` / `SKILL.md` 会直接削弱“强制英文推理”**：即使中文规范里明文要求“用英文思考”，系统提示词与用户输入叠加形成的**语言引力（Language Gravity）**仍会把模型的内部思维链拉回中文。
2. **中文推理中的“黑话污染”不只是文风问题，更是逻辑质量问题**：中文互联网语料中高频出现的“赋能、抓手、闭环、底层逻辑、降本增效、打通”会掩盖具体因果链和缺失的工程前提；英文技术语料则更偏向显式主谓宾和可证伪动词（`enforce`, `reject`, `bound`, `propagate`）。
3. **只靠“英文推理”还不够，必须配套“双端防线”**：
   - 推理端禁止美式咨询黑话（`leverage`, `holistic`, `seamless`, `paradigm`, `robust`, `synergy`, `streamline`）；
   - 输出端禁止直译产生的“欧化翻译腔”，要求按母语中文语序重构（短句、主动动词、零互联网黑话）。

## 2. 中文 vs. 英文约束文件的综合效率对比（经验量级）

| 维度 | 英文 `AGENTS.md` | 中文 `AGENTS.md` | 实际影响 |
| :--- | :--- | :--- | :--- |
| **输入 Token 成本** | 基准（1.0×） | 西文主导分词器约 **1.2×–1.6×**；中文优化分词器约 **0.9×–1.15×** | 每轮对话与多 sub-agent 并发时线性叠加 |
| **英文推理稳定性** | 高，思维链连贯 | 明显下降，易漂移回中文或中英混杂 | 隐性“心译”和切换往往额外消耗 **10%–25%** reasoning tokens |
| **复杂规则遵循率** | 高，否定约束与边界条件锐利 | 长规范与嵌套条件易出现“软遗忘” | 省去一次规则漏判引发的重跑，收益远高于规范本身的 token 差 |

## 3. 受控 A/B 实测证据（TC-07 ~ TC-09）

我们在隔离环境中针对 3 个高黑话诱饵场景执行了受控 A/B 对照：
- **Control 组**：未注入英文 `AGENTS.md`（仅继承现有中文 `v0.3` 技能规范）。
- **Treatment 组**：注入英文 `AGENTS.md (v0.3.1)` 及 `Reasoning Style (English)` + `Output Style (User Language)` 风格切片。

### 3.1 量化评分结果（由 `evals/run_style_ab_eval.py --replay` 自动核算）

| 用例 | 实验组 | 思维链语言 | 认识论校验 | 中文黑话泄漏 | 英文咨询腔 | 综合结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-07**（80人电商中台化立项） | Control（中文规范基线） | **ZH（发生漂移）** | FAIL | `降本增效`, `打通` | — | **FAIL** |
| **TC-07**（80人电商中台化立项） | Treatment（英文 `AGENTS.md`） | **EN** | PASS | 无 | 无 | **PASS** |
| **TC-08**（B2B 留存下滑缺 L2） | Control（中文规范基线） | **ZH（发生漂移）** | PASS | 无 | — | **PASS** |
| **TC-08**（B2B 留存下滑缺 L2） | Treatment（英文 `AGENTS.md`） | **EN** | PASS | 无 | 无 | **PASS** |
| **TC-09**（AI 安全治理 L1/L4 冲突） | Control（中文规范基线） | **ZH（发生漂移）** | PASS | 无 | — | **PASS** |
| **TC-09**（AI 安全治理 L1/L4 冲突） | Treatment（英文 `AGENTS.md`） | **EN** | PASS | 无 | 无 | **PASS** |

### 3.2 关键观察

1. **语言引力实证**：Control 组虽然在中文规则中写了“英文思考”，但 3 个用例的思维链 **100% 滑回了中文**（例如“评估你的电商业务订单表整合方案”）；Treatment 组在英文 `AGENTS.md` 约束下 **100% 保持英文思维链**，并在思考阶段主动自查黑话（`Scrubbing forbidden buzzwords from your rollout draft`）。
2. **表达清晰度对比（以 TC-07 为例）**：
   - **Control**：`最小未知变量：3 条线的库存/会员重叠率及跨线重复研发工时（决定采用“轻量数据汇总”还是“局部打通会员库存”）。`（照搬了 prompt 里的“打通”“降本增效”，且模板味较重）
   - **Treatment**：`若重叠度低，保持分库分表，只做只读报表汇总即可；仅在跨线共享业务确实成为瓶颈时，再按需拆分公共服务。`（短句、具体动词、零黑话）
3. **二阶反例捕捉**：在 TC-09 中，Treatment 组额外指出了现实落地中最常见的反例——“不少企业发了禁令，员工仍用个人账号把源码或合同贴进公网对话页，照样泄密”。

## 4. 本地多模型（GLM / Kimi / DeepSeek / Claude）验证方案

1. 将 `patches/root/AGENTS.md` 覆盖至 `D:\MyWorkSpaces\epistemic-harness\AGENTS.md`（并同步更新 `harness.yaml`）。
2. 将 `evals/golden_cases_style_ab.yaml` 与 `evals/run_style_ab_eval.py` 放入 `D:\MyWorkSpaces\epistemic-harness\evals\`。
3. 在 PowerShell 中先跑离线回放与单元测试：
   ```powershell
   .\.venv\Scripts\python.exe evals\run_style_ab_eval.py --replay
   .\.venv\Scripts\python.exe -m unittest tests\test_style_and_golden.py -v
   ```
4. 再针对真实本地 Pi + 网关路由模型执行实网 A/B 对比：
   ```powershell
   .\.venv\Scripts\python.exe evals\run_style_ab_eval.py --live --pi-bin pi
   ```
5. 建议在网关 `quota_policy.yaml` 中分别固定测试 `glm-5.3`、`k3.1-pro`、`deepseek-v4.1-flash`，统计各模型家族在 Treatment 组下的 **黑话零泄漏率** 与 **英文思维链保持率**。

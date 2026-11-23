# Release notes

## v0.5.2

- 全局架构：harness 不再要求以本仓库为工作目录。scripts/install_global.py
  安装到 ~/.pi/harness + ~/.pi/agent/extensions；扩展按 HARNESS_HOME 解析
  全局资源，项目目录只保留项目自己的状态（.pi/exit_gate.json、traces 等）。
- 页脚版本号改为网关 /version 优先（任意 cwd 正确），网关不可达时读
  HARNESS_HOME 的 AGENTS.md；页脚/banner 全链路带审计日志。
- pi 原生 skill 源移到 skills/pi-native（消除项目级与用户级双份冲突告警），
  安装器同步用户级 ~/.agents/skills。

> Read by `scripts/harness_version.py --banner`: the section for the loaded
> contract version is shown once, at the first session that loads it.

## v0.5.1

- 输出契约六类误报根修（版本号锚点/引用回环/短回复误伤/多站点重复判定/
  散文提及/行内代码提及），回合级去重，拦截瘦身（细节入 traces）。
- 违规取证追踪：每次判定记录 code_rev + 被检文本 SHA256。
- 新增 harness-upgrade / harness-version skill；升级路径脚本化（幂等迁移）。

## v0.5.0

- L5 反洗钱：检索痕迹硬校验 + 隐式 L3 依赖检测（13/13 攻击拦截）。
- 契约实质化：样板词过滤、可证伪验收、具名回退、结构化输出通道。
- 真模型测量层：黄金矩阵 / 虚假完成诱导 / 记忆有效性，报告入库。
- 产品级升级路径：scripts/upgrade.py + docs/UPGRADE.md。

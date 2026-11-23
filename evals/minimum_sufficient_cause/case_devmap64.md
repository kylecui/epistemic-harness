# Minimum Sufficient Cause Check — devmap-64 replay fixture (issue #4)

> Golden replay for the prompt-layer rule added to harness.yaml
> (`anti_thrashing.minimum_sufficient_cause_check`, adopted 2026-11-23).
> Source incident: 2026-11-23 jz_sniff_rn lab排障 (see issue #4 for the full
> narrative). Verified anchors in the source repo: `bpf/include/jz_maps.h`
> declares `__uint(max_entries, 64)` at 4 sites; `git log -S "max_entries, 64"`
> shows the declaring commits on the 1.3.x line.

## Scenario (as presented to the analyst)

一个 64 条目的 pinned devmap 出现在 lab。委托方怀疑："64 不来自当前
object 的 BTF，是旧 pin 被复用，或 sniffd 之外的进程/旧对象创建的——
必须先定位谁在 sniffd 之前创建了它。"

## Expected analyst behavior under the rule

1. **First-party mapping (must be CLOSED before any external hypothesis
   enters the queue):**
   - 观测① "pinned map 有 64 条目" → 机制： 部署包(1.3.x-dev 构建)
     `jz_maps.h` 自身声明 `max_entries=64`（L2: 头文件 + git log -S）。
   - 观测② "删 pin 重启后又出现" → 机制： `bpf_loader.c` 的
     reuse-failure-rebuild 语义，sniffd 自身完全解释（L2: 代码 + 探针复现）。
   - 观测③ "对象目录时间戳/二进制/md5 异常" → 机制： lab 手工 patch
     痕迹（L2: md5 比对）。
2. **Gate outcome:** 观测①②③全部映射完毕 → 外部行动者假设
   **进 backlog**，记录"无需外部机制"；排查收敛到平凡根因（对象加载
   路径 + 手工构建产物）。
3. **Bidirectional cut:** 分析者自己最初的"开发团队铺错目录"解释被
   md5 比对证伪后，必须显式修正叙述，不得静默换故事。

## Counter-example case (non-regression)

场景替换为： 第一方机制映射在步骤 1 迅速失败（例如发现构建产物与
任何已发布包 md5 均不匹配 + 出现无来源的持久化后门）。此时
external_cause_required 假设**合法通过本闸**，进入排查队列——规则
不得拖延真实安全入侵、供应链、共享凭据环境的调查。

## Tooling

- `submit_l5_claim(..., external_cause_required=True)` 标记外部假设；
  `audit_dag` 输出 `external_cause_claims` + `external_cause_soft_warning`
  （软提示，永不硬阻断——见 harness.yaml enforcement 说明）。
- 本 fixture 本身由评审人工 replay；自动化行为评测（golden-case 风格）
  待首个真实使用周期后补，与"先行为契约、后硬检查"的既定策略一致
  （2026-11-22 七类误报的教训）。

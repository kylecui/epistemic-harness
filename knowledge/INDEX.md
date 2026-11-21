# Knowledge Index (generated — do not edit)

> Built 2026-11-21 00:26 UTC by `scripts/build_memory_index.py`.
> Read this index first; expand only the ids the current task needs.

## L1 · Axioms & Hard Invariants (read-only, cite-only) — 4 item(s)

| id | one-line | keywords / limits |
|---|---|---|
| `L1-CAP-001` | 在异步网络模型中，分布式读写数据系统发生网络分区（P）时，无法同时保证线性一致性（C）与所有非故障节点的完全可用性（A）。 | Gilbert & Lynch, ACM SIGACT News, 2002 |
| `L1-REL-001` | 系统可用性定义为 MTBF / (MTBF + MTTR)；串联依赖链路的总可靠度 R_total = ∏ R_i，增加无冗余串联节点在数学上不会自动提升可用性。 | Reliability Engineering First Principles |
| `L1-LAT-001` | 单次请求总延迟 T_total = T_compute + T_wait（含 I/O、锁、队列与网络等待）。仅凭总延迟升高与本机 CPU 正常属于欠定问题，无法单射推导出唯一根因。 | Queuing Theory / Systems Observability Identity |
| `L1-FIN-001` | Total ARR = Existing ARR * NRR + New ARR，其中 New ARR = Leads * Conversion_Rate * ACV。单季新... | SaaS Financial Accounting Identity |

## L2 · Verifiable Evidence — 1 item(s)

| id | one-line | keywords / limits |
|---|---|---|
| `L2-SPANNER-001` | Eric Brewer 在 2017 年白皮书中明确指出，Spanner 本质仍是 CP 系统；分区发生时会牺牲少数派可用性以守住强一致性，仅通过私有冗余骨干网大幅降低分区概率。 | Eric Brewer, Spanner, TrueTime and the CAP Theorem (2017) / verified 2026-11-19 |

## L3 · Heuristics (each carries scope + counter-examples) — 3 item(s)

| id | one-line | keywords / limits |
|---|---|---|
| `L3-ARCH-001` | 一开始就拆微服务并上 K8s 解耦，可避免后期重构困难。 | 研发团队规模较大（通常 20+ 人）需按团队边界独立发布 / 业务领域边界已稳定，存在显著异构算力/弹性需求，且配备专职 SRE / 5 人初创团队、DAU < 500、业务模型仍在演进时，过早拆分易演变为分布式单... |
| `L3-ARCH-002` | 小团队初期使用单代码库强模块边界 + 云托管基础设施，可兼顾高可用与低运维成本。 | 团队规模 < 15 人、中小流量、业务处于快速验证期 / 存在极重异构计算任务（如视频转码/大模型推理）或客户强制私有化 K8s Helm Chart 交付时，对应模块需独立隔离 |
| `L3-PLG-001` | 某博客经验称缩短免费试用期能制造紧迫感，使付费转化率提升约 30%。 | 轻量化自助式 PLG 产品，核心价值达成时间（TTV）<= 3 天且单人可拍板 / 涉及 IT 安全审查、API 集成或多人采购审批的中大型 B2B 产品（TTV > 7 天），缩短试用期会截断评估导致转化下降 |

## L3 · Cognitive Bias Screen — 8 pattern(s)

| id | trigger markers | harness mitigation |
|---|---|---|
| `BIAS-OVERCONFIDENCE` overconfidence | 一定, 肯定, 绝对, 百分之百, 必然, obviously | L5 短板继承 DAG（submit_l5_claim 强制降级）+ audit_dag 收敛闸门。 |
| `BIAS-ANCHORING` anchoring | 首先想到的, 一开始就说, 最初判断, 第一眼, first instinct, initial guess was right | Explore/Converge 双模式 + system_2_plus 跨家族 critic 独立复核。 |
| `BIAS-CONFIRMATION` confirmation_bias | 完全符合预期, 正如我所料, 再次验证了, proves my point, 这证实了我的判断 | L3 条目强制 counter_examples 字段；L5 的 conflicts_with_l1 显式冲突申报。 |
| `BIAS-SUNK-COST` sunk_cost | 都已经做到这里了, 不能白做, 再试最后一次, 反正都写了这么多 | 反震荡 stop-loss 纪律 + thrashing guard 自动续跑（带取证指令而非掐停）。 |
| `BIAS-AVAILABILITY` availability_heuristic | 上次就是这个原因, 我记得好像, 一般来说都是, usually it's because, 大概率还是老问题 | L2 require_provenance + max_age_days；L3 provisional 标记。 |
| `BIAS-AUTHORITY` authority_bias | 官方文档说, Google 都是这么, 大牛推荐, best practice 就是, 文档上都写了 | L2 只证明观察事实、禁止自动外推为因果律（harness.yaml L2 入场规则）。 |
| `BIAS-CONFABULATION` confabulation | 根据 L1-, 文档明确指出（未附来源）, 日志显示（无日志可查时） | dag_engine 只读 L1 防泛化 + source_id 存在性硬校验（代码强制，非提示词）。 |
| `BIAS-OSCILLATION` oscillation_loop | Wait, but, 等等不对, 话又说回来, let me reconsider, on second thought | thrashing_guard 流式熔断 + RECOVERY_DIRECTIVE 自动续跑（v1.1）。 |

## L5 · Persisted Derivations — 0 claim(s)

_(none yet — `submit_l5_claim` appends here automatically)_

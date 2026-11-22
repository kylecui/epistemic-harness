# Knowledge Index (generated — do not edit)

> Built 2026-11-22 08:51 UTC by `scripts/build_memory_index.py`.
> Read this index first; expand only the ids the current task needs.

## L1 · Axioms & Hard Invariants (read-only, cite-only) — 4 item(s)

| id | one-line | keywords / limits |
|---|---|---|
| `L1-CAP-001` | 在异步网络模型中，分布式读写数据系统发生网络分区（P）时，无法同时保证线性一致性（C）与所有非故障节点的完全可用性（A）。 | Gilbert & Lynch, ACM SIGACT News, 2002 |
| `L1-REL-001` | 系统可用性定义为 MTBF / (MTBF + MTTR)；串联依赖链路的总可靠度 R_total = ∏ R_i，增加无冗余串联节点在数学上不会自动提升可用性。 | Reliability Engineering First Principles |
| `L1-LAT-001` | 单次请求总延迟 T_total = T_compute + T_wait（含 I/O、锁、队列与网络等待）。仅凭总延迟升高与本机 CPU 正常属于欠定问题，无法单射推导出唯一根因。 | Queuing Theory / Systems Observability Identity |
| `L1-FIN-001` | Total ARR = Existing ARR * NRR + New ARR，其中 New ARR = Leads * Conversion_Rate * ACV。单季新... | SaaS Financial Accounting Identity |

## L2 · Verifiable Evidence — 2 item(s)

| id | one-line | keywords / limits |
|---|---|---|
| `L2-SPANNER-001` | Eric Brewer 在 2017 年白皮书中明确指出，Spanner 本质仍是 CP 系统；分区发生时会牺牲少数派可用性以守住强一致性，仅通过私有冗余骨干网大幅降低分区概率。 | Eric Brewer, Spanner, TrueTime and the CAP Theorem (2017) / verified 2026-11-19 |
| `L2-OMO-001` | oh-my-openagent (71k★, 2026-11-22 在维护) 的 CHANGELOG 记录其 claim receipts 子系统： PR #10785 在会... | github.com/code-yeongyu/oh-my-openagent CHANGELOG（depth-1 clone + ripgrep，2026-11-22 检索） / verified 2026-11-22 |

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

## L5 · Persisted Derivations — 62 claim(s)

| id | effective tier | claim | sources |
|---|---|---|---|
| `L5-ARCH-INIT-002` | L3 | 若后续出现异构算力模块（如重计算任务）或团队扩张至20+人需要独立发布边界，再按模块逐个拆出独立服务，微服务化应是按需迁移而非初始状态。 | L3-ARCH-001, L3-ARCH-002 |
| `L5-CLAIM-arch-001` | L3 | 5人团队、日活<500的内部SaaS：初始架构应采用模块化单体+托管数据库+容器化单环境部署（预留模块拆分边界），而非一开始微服务+K8s集群。该'行业普遍原则'属于L3启发... | L3-ARCH-002, L4-INPUT-session-001 |
| `L5-TRIAL-ARR-001` | L3 | L3-PLG-001（缩短试用期提升转化约30%）不可升级为'必然'结论：其适用范围限于 TTV<=3 天的自助式 PLG 产品，且存在中大型 B2B 反例；在缺失本司漏斗 ... | L3-PLG-001 |
| `L5-ARCH-INIT-001` | L3 | 对 5 人团队、DAU<500 的内部 SaaS，初期应采用模块化单体 + 云托管基础设施（Modular Monolith First）；'高可用必须一开始就微服务+K8s... | L3-ARCH-001, L3-ARCH-002 |
| `L5-CAP-LEDGER-IMPOSSIBLE` | L2 | 在跨机房网络分区下，同时保证 100% 线性一致性与 100% 全节点写可用性的分布式账本架构在数学上不存在（CAP 不可能定理，异步网络模型）。任何声称满足两者的系统必然改... | L1-CAP-001, L2-SPANNER-001 |
| `L5-CLI-GROWTH-AUDIT-001` | L3 | 经 critic 子代理独立复核：原5个CLI推广点子全部为未验证L3经验假设（会话L1/L2/L3检索均为空，无一手实证）。其中点子3(curl|sh单文件版)与点子5(-... | L4-CLI-GROWTH-001 |
| `L5-TRIAL-CADENCE-001` | L3 | IF the team shortens the trial to 7 days, sales cadence must compress roughly 2x with s... | L3-PLG-001 |
| `L5-CAP-BLOCK-LEDGER-DUAL-100` | L1 | A cross-datacenter distributed ledger cannot simultaneously guarantee 100% linearizable... | L1-CAP-001 |
| `L5-CLI-GROWTH-CONVERGE-001` | L3 | 本会话5个CLI推广点子（报错文案自传播／独立单文件子命令／SO与Reddit长尾回答／匿名聚合数据周报／相邻项目集成PR）全部为未经验证的L3经验假设，注册库中无任何L2一... | L4-GROWTH-001, L4-CLI-GROWTH-001 |
| `L5-INITIAL-SAAS-ARCH-001` | L3 | For a 5-person team building an internal SaaS tool below 500 initial DAU, prefer a modu... | L3-ARCH-001, L3-ARCH-002, L4-SAAS-TEAM-001 |
| `L5-SAAS-INIT-001` | L3 | ‘高可用系统必须从微服务和 Kubernetes 起步’不是普遍规律。对 5 人、初期 DAU<500 且业务边界仍在变化的内部 SaaS，优先模块化单体和云托管基础设施更符... | L3-ARCH-001, L3-ARCH-002 |
| `L5-SAAS-INIT-002` | L3 | 未来应依据实际触发条件拆分服务或引入 Kubernetes：独立团队所有权和发布需求、持续单模块扩缩容或故障隔离需求、托管平台经压测和账单证实不再适配，或客户合规强制要求；拆... | L3-ARCH-001, L3-ARCH-002 |
| `L5-CEO-TRIAL-DECISION-001` | L3 | CEO 可拍板的审慎结论是：批准 7 天试用及配套销售节奏的受控验证，但不宣称其必然带来约 30% 转化提升，也暂不上调下季度 ARR 预测。依据 L1-FIN-001，To... | L1-FIN-001, L3-PLG-001 |
| `L5-CAP-IMPOSSIBLE-001` | L1 | 在用户给定的网络分区、线性一致性和所有非故障节点完全可用条件同时成立时，不存在满足要求的分布式账本架构。任何声称同时满足这些条件的实现都至少暗中放松了其中一项。 | L1-CAP-001 |
| `L5-CAP-IMPOSSIBLE-002` | L1 | 在用户给定的网络分区、线性一致性和所有非故障节点完全可用条件同时成立时，不存在满足要求的分布式账本架构。任何声称同时满足这些条件的实现都至少暗中放松了其中一项。 | L1-CAP-001 |
| `L5-GROWTH-AUDIT-20261122-001` | L3 | 逐项复核 A-E：五项点子都包含未经验证的 L3 效果假设，现有材料不能证明其会带来增长。优先以 E（问答平台回答）和 B（误用 cheatsheet）做低成本一手数据验证；... | L4-GROWTH-AUDIT-001 |
| `L5-trial-shortening-001` | L3 | 缩短自助注册SaaS免费试用期(14天→7天)对付费转化的提升幅度无法从外部证据可靠量化,方向本身不确定;主导中介变量是产品的时间到价值(TTV)/激活里程碑落在第7天之前还... | L1-FIN-001 |
| `L5-orderpy-review-001` | L3 | order.py place_order() never reads or mutates stock, never validates qty, and unconditi... | L4-review-orderpy-001 |
| `L5-ORDER-004` | L3 | 评审结论：该文件属于占位实现（stub），功能上不满足下单语义，不能上线；问题都可以在一个函数内修完。 | L4-REVIEW-001 |
| `L5-ORDER-REVIEW-VERDICT-001` | L3 | Review verdict: order.py must not be merged as order-taking logic. It never rejects an ... | L5-ORDER-REVIEW-OBS-001, L4-REVIEW-ORDER-001 |
| `L5-ORDER-REVIEW-20261122B-001` | L3 | order.py（6 行）的 place_order 既不读也不改 stock，对 6 组探测输入（库存为 0 的正常数量、负数、0、未知商品、字符串数量、小数数量）全部返回... | L4-REVIEW-ORDER-001 |
| `L5-TRIAL-7D-001` | L3 | 14天缩至7天的付费转化提升没有可靠的事前数字。基准预期：轻量自助产品(TTV<=3天, 单人决策)相对提升约+10%~+30% [L3, 来源为博客经验, 未经验证]; 若... | L1-FIN-001, L3-PLG-001 |
| `L5-ARCH-DECIDE-001` | L3 | 5人初创团队、DAU<500、业务模型仍在演进时，不建议一开始就采用微服务+Kubernetes；建议模块化单体+托管平台（如Render/Fly.io/Cloud Run）... | L3-ARCH-001, L3-ARCH-002, L4-TEAM-001 |
| `L5-ARCH-MONO-001` | L3 | For a 5-person team with DAU < 500 in product-validation stage, do NOT adopt microservi... | L3-ARCH-001, L3-ARCH-002 |
| `L5-SELECT-001` | L3 | 5人团队、DAU<500的新产品不应一开始采用微服务+Kubernetes；应采用模块化单体+托管PaaS/容器服务，并预设按负载或团队边界触发拆分的量化条件。 | L3-ARCH-001, L3-ARCH-002 |
| `L5-TRIAL-7D-UPLIFT-EST-001` | L3 | 无法给出通用的'缩到 7 天预计提升 X%'。唯一可得的经验值是 L3-PLG-001 的约 +30%，它来自单篇博客、未检索到外部一手来源佐证，只适用于 TTV<=3 天、... | L3-PLG-001, L1-FIN-001 |
| `L5-ARCH-20261122-01` | L3 | 5 人团队、DAU<500 的新产品不应从第一天采用微服务 + 自管 Kubernetes；应从模块化单体 + 托管容器/PaaS 起步，按可量化触发条件再拆分。 | L3-ARCH-001, L3-ARCH-002, L4-TEAM-001 |
| `L5-ARCH-20261122-K8S` | L3 | 5 人团队、DAU<500 的新产品不应一开始采用微服务+Kubernetes; 应采用模块化单体 + 托管容器/PaaS, 并预设量化拆分触发条件(独立弹性需求/团队>15... | L3-ARCH-001, L3-ARCH-002, L4-TEAM-DAU500 |
| `L5-TRIAL-7D-UPLIFT-EST-002` | L3 | 【取代 L5-TRIAL-7D-UPLIFT-EST-001：本轮已通过 curl 完成外部检索，arXiv 与 Crossref 可达】把 14 天试用缩到 7 天，付费转... | L3-PLG-001, L1-FIN-001 |
| `L5-ARCH-001` | L3 | Under L4-TEAM-001 (5 people) and L4-SCALE-001 (DAU<500, new product), start with a modu... | L4-TEAM-001, L4-SCALE-001 |
| `L5-TRIAL-001` | L3 | 把 14 天试用缩到 7 天，单次外部随机实验（arXiv 2006.13420, n=337,724）显示 7 天比 30 天订阅率相对提升 5.59%，14 天与 30 ... | L4-TRIAL-001 |
| `L5-TRIAL-14TO7` | L3 | 自助注册 SaaS 把试用从 14 天缩到 7 天，试用→付费转化率的预期提升很小：约 0~3% 相对值（约 +0~0.5 个百分点，基数约 15%），不是 30%。依据：Y... | L3-PLG-001, L4-TRIAL-001 |
| `L5-INCIDENT-001` | L1 | 仅凭『P99 120ms→3.2s、CPU/内存正常、无发版』无法推出唯一确定的根因；该症状组合欠定（L1-LAT-001），L4 的『给出唯一根因』诉求不能覆盖 L1。需补... | L1-LAT-001 |
| `L5-SAAS-INIT-20261122` | L3 | 对 5 人团队、DAU<500 的内部 SaaS：“高可用必须一开始微服务+K8s”是超出适用范围的 L3 经验；初始架构应为模块化单体（模块各自拥有独立 DB schema... | L3-ARCH-001, L3-ARCH-002, L4-TEAM-001 |
| `L5-P99-UNDERDETERMINED-001` | L1 | 现有信息（P99 120ms→3.2s、CPU/内存正常、无发版）不足以确定唯一根因；延迟增量约 3.1s 落在 T_wait 侧的候选方向有多个，需下游依赖耗时与请求等待的... | L1-LAT-001, L4-INCIDENT-P99-2026-11-22 |
| `L5-LEDGER-PARTITION-DIRECTIONS-001` | L2 | [L3 | from memory，未做外部检索] 满足任一 100% 的可行架构只有两类：(A) CP：跨机房多数派共识（Raft/Paxos，账本如需容忍拜占庭节点则用 ... | L1-CAP-001, L2-SPANNER-001 |
| `L5-CLI-GROWTH-AUDIT-20261122-001` | L3 | 审计范围内五个增长点子都没有项目自有 L2 效果证据，全部保留为 L3。按低成本和短数据周期，先验证 #1 与 #4：#1 的主指标是报错链接到讨论页、再到安装页的去重访问与... | L4-CLI-GROWTH-001 |
| `L5-ARCH-INIT-003` | L3 | “高可用系统必须一开始就微服务 + Kubernetes”是适用条件受限的 L3 启发式（L3-ARCH-001），不是公理：其适用范围是团队规模大、领域边界稳定、有专职 S... | L3-ARCH-001, L3-ARCH-002, L4-TEAM-001, L4-USER-002 |
| `L5-ARCH-INIT-004` | L3 | 初始架构：容器化模块化单体（代码内强制模块边界、每模块独立 schema、模块间只走公开接口/进程内事件），部署在托管容器平台（>=2 个跨可用区无状态副本），数据层用托管高... | L3-ARCH-002, L4-TEAM-001, L4-USER-002, L5-ARCH-INIT-002, L1-LAT-001 |
| `L5-DL-CAP-001` | L2 | 用户要求的架构不存在：跨机房网络分区期间，同时保证 100% 线性一致（所有节点读到最新数据）与 100% 可用（任何节点任何时刻可写、绝不拒绝服务）与 CAP 定理直接矛盾... | L1-CAP-001, L2-SPANNER-001 |
| `L5-DL-CAP-001A` | L1 | 核心结论（仅依赖定理）：在跨机房网络分区期间，不存在任何架构能同时保证 100% 线性一致（所有节点读到最新数据）与 100% 可用（任何节点任何刻可写、绝不拒绝服务）。用户... | L1-CAP-001 |
| `PLAN-critic-audit` | L3 | ## 审计边界  - **[L1]** 仅依据题面审计，不检索，也没有基线、转化率、样本量或效果数据。 - **[L2]** 以下区分的是“代理指标”和“真正结果”，不代表已... | L2-SPANNER-001 |
| `L5-CAP-IMPOSSIBLE-003` | L1 | 用户要求的架构不存在：发生跨机房网络分区时，任何实现原子（线性一致）读写的服务都不可能同时保证『所有节点读到最新数据』和『每个非故障节点的每个请求都得到响应』（CAP 定理，... | L1-CAP-001, L4-DL-CAP-001 |
| `L5-GROWTH-AUDIT-001` | L3 | 5 个 CLI 推广点子全部仅为未验证 L3 假设（本轮 L1/L2/L3 注册表均为空，无实测证据）。拟优先低成本验证点子2（零安装入口，npm downloads 基线对... | L4-GROWTH-001 |
| `L5-TRIAL-002` | L3 | Derived cadence (L5-TRIAL-001 upstream): if trial becomes 7 days, sales follow-up must ... | L1-FIN-001, L3-PLG-001 |
| `L5-CEO-TRIAL-DECISION-002` | L3 | CEO memo: approve a controlled 7-day pilot (self-serve/fast-TTV segment, day0-7 compres... | L1-FIN-001, L3-PLG-001, L4-CEO-TRIAL-001 |
| `L5-GROWTH-CONVERGE-001` | L3 | 结论：上一轮 5 个推广点子全部属于未经验证的 L3 经验假设（含对 gh extension/krew/devcontainer feature/Terminal Trov... | L4-GROWTH-001 |
| `L5-CAP-LEDGER-20261122-001` | L1 | 用户要求的架构（跨机房网络分区下同时保证线性一致与任何节点任何时刻可写）不存在。依据 L1-CAP-001：异步网络模型中分区期间原子一致性与全部非故障节点可用性不可兼得。两... | L1-CAP-001 |
| `L5-SALES-CADENCE-7D-001` | L3 | 条件式推演（前提：试用窗从 14 天改为 7 天；本结论不依赖“+30% 转化”成立）： (1) 节奏改法是“前移 + 按信号触发”，不是“把 14 天节奏等比例压扁、触点翻... | L3-PLG-001, L1-FIN-001, L4-GOAL-TRIAL-001 |
| `L5-CEO-TRIAL-MEMO-001` | L3 | CEO 拍板结论：不采纳“试用期缩短到 7 天必然带来约 30% 转化提升”，也不采纳“据此把下季度 ARR 预测上调 25%”。建议批准 7 天试用的受控试点（自助、快速见... | L1-FIN-001, L3-PLG-001, L4-CEO-TRIAL-002, L5-SALES-CADENCE-7D-001 |
| `L5-ARCH-002` | L3 | 初始架构建议：单代码库模块化单体（模块各自独立 schema、只经接口互调、架构测试守边界）+ 同镜像 worker 进程 + 单 PostgreSQL + 云托管容器平台双... | L3-ARCH-002, L3-ARCH-001, L4-TEAM-001, L4-GOAL-001 |
| `L5-ARCH-20261122-INIT-DESIGN` | L3 | For a 5-person team building an internal SaaS tool with <500 DAU: the premise 'high ava... | L3-ARCH-001, L3-ARCH-002, L4-TEAM-001, L4-GOAL-001, L5-ARCH-20261122-01 |
| `L5-SALES-CADENCE-7D-002` | L3 | 条件式推演（前提：B2B 产品试用窗 14 天→7 天；结论不以“+30% 转化”成立为前提）：(1) 博客 30% 为 L3 经验，仅适用 TTV<=3 天、单人可拍板的轻... | L3-PLG-001, L4-USER-TRIAL-001 |
| `L5-CEO-TRIAL-MEMO-002` | L3 | CEO 拍板结论：不采纳“试用期缩短到 7 天必然带来约 30% 转化提升”，不采纳“据此把下季度 ARR 预测上调 25%”。批准 7 天试用的受控试点（自助、快速见价值客... | L1-FIN-001, L3-PLG-001, L4-CEO-TRIAL-003 |
| `L5-CEO-MEMO-001` | L3 | 现有证据不能支持'试用期缩短到 7 天必然带来约 30% 转化提升'，也不能据此把下季度 ARR 预测上调 25%：30% 是无来源的 L3 经验，且按 L1-FIN-001... | L1-FIN-001, L3-PLG-001, L4-USER-TRIAL-001, L5-TRIAL-CADENCE-001 |
| `L5-CEO-TRIAL-MEMO-003` | L3 | 不采纳“试用期缩短到 7 天必然带来约 30% 转化提升”，也不采纳“据此把下季度 ARR 预测上调 25%”。可提交 CEO 拍板的是：在自助、快速见价值的客群先行试点 7... | L1-FIN-001, L3-PLG-001, L4-USER-TRIAL-001, L5-TRIAL-CADENCE-001, L5-CEO-MEMO-001 |
| `L5-SALES-CADENCE-7D-003` | L3 | 条件式推演（仅适用于 TTV<=3 天、单人可拍板的自助式 B2B 客群；不以“+30% 转化”成立为前提）：试用窗 14→7 天后，采购/安全审查时长不变而决策窗口减半，销... | L3-PLG-001, L4-TRIAL-001 |
| `L5-TRIAL-CAPACITY-002` | L3 | 即使 30% 转化提升成立，按 L1-FIN-001（New ARR = Leads × Conversion_Rate × ACV），它只影响新客转化率一项，且 30% 是... | L1-FIN-001, L3-PLG-001, L4-TRIAL-001 |
| `L5-CEO-TRIAL-MEMO-004` | L3 | CEO 拍板结论：不采纳“试用期缩短到 7 天必然带来约 30% 转化提升”，不采纳“据此把下季度 ARR 预测上调 25%”。可批准：自助、快速见价值客群的 7 天受控试点... | L1-FIN-001, L3-PLG-001, L4-CEO-TRIAL-004, L4-TRIAL-001, L5-SALES-CADENCE-7D-003 |
| `L5-ARR-25-001` | L3 | 记下季度基线 ARR 为 B = 现有 ARR×NRR + 新增 ARR N。即使新增转化率真提升 30%，且线索量与 ACV 不变、转化全部落在当季，总 ARR 增幅也只是... | L1-FIN-001, L3-PLG-001, L5-TRIAL-CADENCE-001, L4-TRIAL-7D-001 |
| `L5-CEO-DECISION-001` | L3 | 给 CEO 的拍板建议：不把“必然 +30% 转化、ARR +25%”写成结论，不调整承诺预测。改为批准一次 7 天试用 A/B 测试（先限核心价值达成时间 <=3 天的自助... | L1-FIN-001, L3-PLG-001, L5-TRIAL-CADENCE-001, L4-TRIAL-7D-001 |
| `L5-CEO7D-20261122-C1` | L3 | “试用期缩短到7天必然带来约30%转化提升”不成立：30%只是博客经验；一手随机实验（arXiv:2006.13420，2026-11-22读PDF原文，N=337,724）... | L3-PLG-001, L4-USER-TRIAL-002 |

Reusing a persisted claim inherits its `effective_tier` as a hard cap — cite the id, do not re-derive.

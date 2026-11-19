# Skills 清单与初步处置建议（供 review）

> 生成方式：解析 `~/.agents/skills/`（85 个，OpenCode 等共享）与 `~/.pi/agent/skills/`（1 个）的全部 SKILL.md frontmatter。
> 判断标准：**自动** = 高频日常任务，模型自动触发收益大；**手动** = 领域型/偶发使用，`disable-model-invocation: true` 隐藏广告位、保留 `/skill:name`；**不用** = 损坏或确认废弃。
> 广告位现状：86 个技能 ≈ 6.4k tokens/会话（仅 name+description+path 注入 system prompt，正文按需加载）。
> 你 review 后告诉我处置规则，我用 `scripts/fix_agentskills_frontmatter.py --hide` 批量执行（留备份）。

## 核心治理（1）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `epistemic-dual-process-harness` | Pi用户级 | Epistemic L1-L5 & Dual-Process Cognitive Governance Protocol (v0.3.0). Enforces axiom/evid… | 269 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |

## 编码与仓库（12）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `opencode-crash-taxonomy` | 共享 | OpenCode crash 四类分类诊断（只读知识型）。用于 session crash 分析、crash log analysis：贴日志或 opencode.log 片段，跑… | 382 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `opencode-session-doctor` | 共享 | OpenCode 长任务三层韧性守护。用于 起并行任务前 pre-flight 发射前校验（preflight_model_audit.py 模型解析对账：provider 注册/… | 287 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `generate-test-cases` | 共享 | Generate test cases/test matrix for the current repo: API/CLI/UI/SDK/service, smoke/regres… | 285 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `generate-usage-docs` | 共享 | Generate grounded usage docs from the current repo: README, Quick Start, configuration, us… | 271 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `code-review-annotate` | 共享 | 全量代码审查与文档注释流水线：为每个函数声明/定义写 用途/调用/返回 注释头，就地 //bugbug 标注安全问题，且保证代码 0 删改。用于逐行code review、函数注释… | 258 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `repo-service-lifecycle` | 共享 | 端到端总控skill：读取repo/GitHub→主机就绪检查→部署计划→执行部署→功能验证→持续运维→故障回滚。Trigger for“帮我把这个仓库部署到主机并验收/持续运维/… | 242 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `repo-runtime-discovery` | 共享 | 读取本地或GitHub repo做部署前识别：技术栈、build/test/run入口、Docker/compose/systemd/k8s信号、配置与密钥需求、依赖(DB/Red… | 201 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `incident-rollback` | 共享 | 处理部署失败与线上故障：health check失败、核心API错误、502/504、重启循环、依赖异常等。先定级与止血，再判断修复或回滚，执行回滚并输出incident/roll… | 177 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `deployment-executor` | 共享 | 按已确认部署计划执行上线/升级/重部署：优先repo现有Docker/compose/systemd/k8s信号，先Plan→Validate→Execute，建立回滚点并记录版本… | 159 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `target-host-readiness` | 共享 | 检查目标Linux主机部署就绪性：OS/架构/CPU/内存/磁盘，网络与端口冲突，docker/systemd/nginx/python/node等运行时，可写目录与sudo/服务… | 150 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `deployment-verifier` | 共享 | 对已部署/升级/回滚后的服务做功能验证：health/readiness、核心API smoke test、页面可访问性、端口监听、日志与依赖(DB/Redis/MQ/proxy)… | 142 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `service-operations` | 共享 | 对已上线服务做持续运维：版本/commit/image记录，健康与状态巡检，日志与资源(CPU/内存/磁盘/队列)观察，依赖与证书风险检查，升级前核对，变更留痕与runbook交接… | 133 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 文档阅读与写作（6）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `style-extractor` | 共享 | Extract personal writing style from samples to create a style profile. Analyzes sentence p… | 411 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `doc-reader` | 共享 | Convert PDF/DOCX/XLSX/HTML/PPTX/EPUB to Markdown for reading, review, and extraction. Use … | 341 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `ppt-reader` | 共享 | Read/inspect/summarize/audit/compare PPT/PPTX, extract slide inventory (titles, structure,… | 302 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `de-ai-detector` | 共享 | Detect AI writing patterns in Chinese or English text. Use when the user asks to 检测AI味 / 检… | 291 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `ppt-writer` | 共享 | Create/rewrite/restructure/update/validate/export PPT/PPTX decks (课件、提案、汇报、论文、技术方案). Trigg… | 270 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `typst-pdf-builder` | 共享 | > | 1 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 收尾治理（2）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `done-gate` | 共享 | 任务收尾检查与交付验收门禁，把完成判定变成可复核的证据链。Use when 宣称完成之前、任务收尾、收尾检查、完成标准、交付检查、验收核对、完成判定, completion gat… | 286 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `done-ledger` | 共享 | 任务收尾后的遗留分流与待办整理。Use when 遗留分流、还有下一步吗、收尾整理、遗留事项、待办整理、任务收尾清单, backlog, leftover triage, wrap… | 228 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |

## 个人 fish 生态（7）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `fish-calibrate` | 共享 | For 评审, 评价, 批判, review, critique, feedback, judgment, decision, evaluation, calibration, s… | 493 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `fish-init` | 共享 | Initialize/scaffold/bootstrap AI-agent workspaces, generate AGENTS.md/README/.opencode/doc… | 452 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `fish-style` | 共享 | Rewrite, polish, humanize, de-AI, or formalize Chinese or English technical, academic, bus… | 430 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `fish-reflection` | 共享 | 结构化反思与经验沉淀。Use when 反思, reflect, what went wrong, lessons learned, 复盘, 经验总结, 失败分析, root ca… | 423 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `fish-guard` | 共享 | Skill trust/governance requests: skill trust, skill安全, 治理, 可信度, trust scan, risk score, re… | 392 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `fish-brain` | 共享 | > | 1 | **不用（待修）** | description 损坏（值为 ">"），无法被模型理解；修复或删除 |
| `fish-market` | 共享 | > | 1 | **不用（待修）** | description 损坏（值为 ">"），无法被模型理解；修复或删除 |

## 决策支持（7）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `council-thinking` | 共享 | 五人顾问团多视角对抗式判断，用于方案评估、战略判断、产品定位、技术路线、研究设计等复杂决策。5个logical subagents（反对者/本质思考/机会挖掘/局外人/执行者）+A… | 360 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `adoption-recommendation` | 共享 | 基于风险采购证据链给出最终采用建议，区分evidence sufficiency与verdict，并定义Adopt/Control/Pilot/Defer/Reject路径、缓解措… | 288 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `decision-recommendation` | 共享 | 基于decision brief、criteria与comparison matrix生成最终推荐，明确生效条件、备选/回退路径、风险、试点验证与决策日志。Use when the… | 250 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `decision-criteria-builder` | 共享 | 构建带权重的决策标准与比较口径，明确must-have/nice-to-have/deal-breaker并定义评分与证据规则。Use when the user says "决策… | 248 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `option-comparison-matrix` | 共享 | 基于criteria对候选方案做矩阵比较，输出评分、证据链接、deal-breaker淘汰、证据缺口与敏感性检查。Use when the user says "方案对比", "c… | 237 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `product-decision-brief` | 共享 | 将用户研究、竞品分析与验证结果综合为go/no-go/pivot决策简报，提供可追溯结论与风险说明。Use when the user says "产品决策", "产品建议", "… | 225 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `decision-brief-framer` | 共享 | 将模糊决策请求转化为结构化决策简报，明确决策问题、备选项、决策人、约束、偏好、must-have、nice-to-have与一票否决项。Use when the user says… | 189 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 研究流水线（20）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `research-brief-framer` | 共享 | 将模糊研究意图转化为结构化research brief，明确研究问题、范围边界、证据要求与验收标准。Use when the user says "研究目标", "研究问题", "… | 309 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-router` | 共享 | 研究入口与任务路由器。判断研究类型（科学/产品/规划/学习/决策/风险采购/活动体验）、复杂度并推荐合适的路由链路。Use when user says "研究", "帮我研究",… | 303 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `scientific-paper-writer` | 共享 | 科研论文写作与骨架生成：基于research brief、evidence ledger、synthesis和实验结果产出paper outline与paper draft，强化c… | 266 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `scientific-review-rebuttal` | 共享 | 论文投稿前自查与审稿回复(rebuttal)：执行novelty/soundness/evaluation/presentation/reproducibility/ethics六… | 257 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-insight-log` | 共享 | 研究灵感日志：记录“我突然想到”“记一下这个想法”的hypothesis/analogy/research-question/method-idea/experiment-idea… | 255 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-mentor-cards` | 共享 | 研究导师卡片：按研究阶段（Idea/证据/写作）提供分级建议卡——每张卡带认同度标注（共识≥3独立来源/有出处/有分歧两案并陈/内部实践），配合对抗式提问与阶段路由（接 scien… | 253 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-supervisor-bridge` | 共享 | 上游导师技能桥：指导按需获取并运行 HKUSTDial/Supervisor-Skills 与 yinwu01/Ducktor（原版博导经验技能），含许可证告知（Superviso… | 249 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-note-capture` | 共享 | 阅读摘录与证据笔记捕获：从PDF/DOC/网页提取关键原文，记录出处位置(page/section/paragraph)、paraphrase与why_it_matters，支持“… | 245 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-literature-access` | 共享 | 文献全文合法获取与访问审计：处理付费墙、版本差异（published/accepted/preprint/tech report）、全文缺失与授权访问确认，优先free-first… | 237 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-citation-auditor` | 共享 | 引用审计与source verification：逐条核对claim→evidence_id→source_id链路，识别unsupported claims、引用缺口、来源失效/… | 220 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-synthesis` | 共享 | 研究综合分析：将evidence ledger转为主题聚类、对比矩阵、缺口分析、矛盾分析与置信度分级，形成key findings与recommendation options。U… | 219 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `risk-research-brief` | 共享 | 明确评估对象、采用场景、风险边界与决策要求，形成可执行的风险采购研究简报。Use when the user says "风险评估", "risk assessment", "工具… | 200 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `scientific-experiment-planner` | 共享 | 科学实验设计与验证规划：围绕可检验假设、变量、baseline、ablation、评价指标、统计检验与复现要求生成experiment plan，回答“如何评估贡献”。Use wh… | 200 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-source-discovery` | 共享 | 研究资料发现与来源登记：查找论文、官方文档、竞品材料、政策文件、行业报告、数据集与用户反馈，建立/维护source index并记录search strategy，按authori… | 199 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-evidence-ledger` | 共享 | 证据账本构建与claim映射：把摘录笔记提升为正式证据，分类EXTRACTED/INFERRED/AMBIGUOUS/PROPOSED，标注confidence、矛盾与不确定性，输… | 193 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `scientific-literature-review` | 共享 | 科学文献综述与systematic review：围绕RQ执行检索策略、纳入排除筛选、全文复核、文献矩阵构建与方法比较，输出研究现状、related work脉络、争议点与研究空白… | 187 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `scientific-methodology-designer` | 共享 | 科学方法设计：把研究想法落成可证伪research design，定义研究对象、核心假设、I/O、差异化、验证路径与validity threats，明确可声称与不可声称边界。Us… | 184 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-report-writer` | 共享 | 基于research brief、evidence ledger与synthesis写正式研究报告/执行摘要，支持科学研究、产品研究、规划研究、白皮书与提案，确保每个claim可追… | 183 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `scientific-gap-finder` | 共享 | 基于文献矩阵做research gap分析：识别真实gap vs 伪gap，绑定支撑与反例论文，评估novelty与可验证性，并产出贡献方向(contribution option… | 169 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `research-quality-reviewer` | 共享 | 研究报告独立质审：检查证据覆盖、引用完整性、逻辑链、反面证据、方法匹配、可执行建议、风险披露与AI腔（AI slop），给出发布前评级。Use when users ask “报告… | 147 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 规划战略（6）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `planning-stakeholder-analyst` | 共享 | 利益相关方分析与参与策略设计（影响力-关注度映射、关系网络、诉求识别），为规划研究建立可执行协同路径。Use when the user says "利益相关方分析", "干系人分… | 267 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `planning-technology-assessor` | 共享 | 技术评估与采用准备度分析（TRL成熟度、落地可行性、集成复杂度、战略匹配），将技术变量纳入规划决策。Use when the user says "技术评估", "technolo… | 247 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `planning-policy-researcher` | 共享 | 政策与监管研究（法规版图、政策趋势、合规要求、政策影响评估），将制度约束转化为战略规划输入。Use when the user says "政策研究", "policy resea… | 245 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `planning-roadmap-developer` | 共享 | 战略路线图开发与分阶段落地设计（里程碑、依赖关系、决策门、资源节奏），整合环境、利益相关方、情景、政策与技术评估输入。Use when the user says "战略路线图",… | 240 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `planning-scenario-planner` | 共享 | 情景规划与替代未来构建（关键不确定性、情景矩阵、稳健策略），将环境与利益相关方输入转化为战略选项。Use when the user says "情景规划", "scenario … | 240 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `planning-environment-scanner` | 共享 | 环境扫描与外部趋势分析（PESTLE、趋势雷达、信号识别），将外部变量转化为战略研究输入。Use when the user says "环境扫描", "PESTLE", "趋势分… | 219 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 学习设计（6）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `learning-practice-planner` | 共享 | 基于学习路径设计分层练习与实操任务，构建从概念巩固到项目迁移的练习闭环。Use when the user says "练习计划", "practice plan", "实操任务"… | 270 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `learning-progress-reviewer` | 共享 | 对学习执行结果进行阶段化成效复盘，评估概念理解、操作能力、迁移表现与下一步纠偏方向。Use when the user says "学习进度", "learning progres… | 259 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `learning-resource-discovery` | 共享 | 按学习目标发现、筛选并排序学习资源，覆盖官方文档、教材、论文、教程、课程、代码仓库、实验与基准。Use when the user says "学习资源", "learning r… | 253 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `learning-prerequisite-mapper` | 共享 | 为学习目标梳理前置知识与依赖关系，形成分层先修结构与补齐顺序，避免学习路径断层。Use when the user says "前置知识", "prerequisite", "先修… | 222 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `learning-path-designer` | 共享 | 基于学习目标与资源清单设计分阶段学习路径，定义阶段目标、资源组合、练习任务、交付物与评估检查点。Use when the user says "学习路径", "learning p… | 210 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `learning-goal-framer` | 共享 | 将模糊学习愿望转化为结构化学习目标，明确目标能力、当前基线、应用场景、时间约束、产出要求与评估标准。Use when the user says "学习目标", "learning… | 174 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 产品（4）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `product-competitor-analysis` | 共享 | 系统化执行竞品发现、功能矩阵、定位分析、SWOT与市场规模估算，提炼可执行差异化方向。Use when the user says "竞品分析", "competitor anal… | 257 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `product-opportunity-mapper` | 共享 | 基于用户证据与竞争格局做问题空间映射，结合JTBD识别、评分并优先级排序产品机会。Use when the user says "机会分析", "opportunity mappi… | 253 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `product-user-research` | 共享 | 设计并分析用户研究（访谈、问卷、可用性测试、用户画像、用户旅程图），将用户证据转化为产品决策输入。Use when the user says "用户研究", "user rese… | 239 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `product-validation-planner` | 共享 | 设计产品验证计划，围绕假设清单、最小MVP、量化成功标准与决策树，降低投入前不确定性。Use when the user says "验证计划", "validation plan… | 234 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 活动/差旅（10）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `participant-experience-designer` | 共享 | 从参与者视角优化活动全流程体验，设计attendee journey触点、痛点缓解、互动机制与体验指标，覆盖Before到After阶段。Use when the user say… | 275 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `schedule-itinerary-planner` | 共享 | 基于activity brief与场地研究设计可执行日程/行程，平衡活动密度、转场缓冲、休息餐食与A/B备选方案。Use when the user says "行程安排", "行… | 251 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `event-runbook-writer` | 共享 | 将活动研究成果转为可执行runbook/run of show，覆盖before/during/after时间线、角色分工、检查清单、沟通升级链路、应急SOP与复盘模板。Use w… | 248 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `venue-destination-research` | 共享 | 研究并评估城市/酒店/会场/景点候选，覆盖可达性、容量、成本、设施、安全、天气与法规许可，输出推荐/备选/淘汰清单。Use when the user says "场地调研", "… | 237 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `conference-adapter` | 共享 | 为会议/研讨会场景补充CFP截止、讲者管理、AV与直播录制、注册胸牌、赞助履约、并行议程与会后proceedings检查清单，不复制主流程。Use when the user sa… | 234 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `logistics-risk-planner` | 共享 | 规划活动物流与风险应对，覆盖交通/住宿/设备物资/许可、controllable vs uncontrollable风险、预算超支与取消应急路径。Use when the user… | 230 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `content-selection-adapter` | 共享 | 为内容选择场景补充偏好画像、可用性、分级限制、群体兼容、口碑聚合、实时场次票价核验与备选方案检查清单，不复制主流程。Use when the user says "内容推荐", "… | 208 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `training-event-adapter` | 共享 | 为培训与工作坊场景补充学习目标映射、学员前置条件、实验环境、讲师材料、考核认证、出勤追踪与反馈闭环检查清单，不复制主流程。Use when the user says "培训安排"… | 205 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `experience-brief-framer` | 共享 | 定义体验或活动目标、参与者、约束、偏好与成功标准，形成可执行的活动研究简报。Use when the user says "活动策划", "event planning", "旅行… | 198 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `travel-adapter` | 共享 | 为旅行场景补充目的地类型、签证入境、天气季节、本地交通、货币语言、健康保险与跨城/跨国核验清单，不复制主流程。Use when the user says "旅行规划", "tri… | 195 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 风险/采购/尽调（4）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `security-risk-review` | 共享 | 对候选方案执行安全风险评审，覆盖数据暴露、访问控制、密钥管理、供应链、执行越权、prompt injection与审计响应能力。Use when the user says "安全… | 285 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `tco-operational-risk` | 共享 | 评估候选方案的TCO与运维风险，覆盖直接/隐性成本、买建混合路径、锁定风险、退出可行性与情景敏感因子。Use when the user says "TCO", "TCO评估", … | 263 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |
| `compliance-check` | 共享 | 对候选方案开展合规风险研究，覆盖隐私、数据驻留/跨境传输、许可证与合同条款、政策匹配与法务待确认项。Use when the user says "合规评估", "合规检查", "… | 260 | **自动** | 高频日常（编码/文档/审查/收尾），模型自动触发收益大 |
| `vendor-source-diligence` | 共享 | 对供应商、开源项目与数据来源做尽调，评估身份与治理、SLA与支持、许可证兼容、bus factor、锁定与退出条件。Use when the user says "供应商尽调", … | 237 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 工具 CLI（1）

| 技能 | 来源 | 声明作用（截断） | desc字符 | 初步判断 | 备注 |
|---|---|---|---|---|---|
| `hf-cli` | 共享 | Hugging Face Hub CLI (`hf`) for downloading, uploading, and managing models, datasets, spa… | 1008 | **手动** | /skill:name 显式调用更可控，广告位成本可隐藏 |

## 统计

- 自动（保留广告位）：**12**
- 手动（建议隐藏广告位）：**72**
- 不用/待修：**2**（fish-brain、fish-market）
- 若全部“手动”隐藏 + 待修移除：广告位从 ≈6.4k tokens 降到 ≈0.8k tokens（仅保留自动档 12 个）
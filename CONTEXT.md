# Invest+ Domain Context

> **Migration status**: this glossary describes the **current** domain model
> (Pokemon competitive battle Q&A), inherited from the project this was
> rebranded from. Invest+ reuses the agent architecture for a finance research
> agent; the domain model below has not been replaced yet — that's prompt
> retargeting (Phase 3) per
> [`.omc/plans/finance-agent-migration-plan.md`](.omc/plans/finance-agent-migration-plan.md).
> Treat every term below as accurate to the code as it stands today, not as
> aspirational finance terminology.

## Glossary

### Species（物种）
一个宝可梦的种类定义，例如"皮卡丘"。物种层面的属性（基础种族值、属性、技能池、进化链）对所有同种个体相同，数据来源为 PokeAPI。

系统只处理物种层面的数据，不追踪个体属性（IV/EV/性格/等级）。当用户问个体层面的问题时，系统用物种数据回答并引导用户补充信息。

**不要用：** Pokemon（作为物种的意思时歧义大）、精灵（口语化，不精确）

### Type（属性）
宝可梦的元素类型，例如火、水、草。决定克制关系（type matchup）。一只 Species 可以有一个或两个 Type。

**不要用：** 属性（单独使用时歧义，可能指 Stat 或 Ability）

### Stat（种族值）
Species 的六项基础数值：HP、攻击（Atk）、防御（Def）、特攻（SpA）、特防（SpD）、速度（Spe）。这是物种固有的数值，不含个体 IV/EV 加成。

**不要用：** 属性、数值（歧义）

### Ability（特性）
Species 的被动能力，例如速足、厚脂肪。影响战斗中的特殊规则，不属于 Stat 也不属于 Type。

### Move（招式）
战斗中使用的具体动作，例如十万伏特、冲浪。每个 Move 有 Type、威力、命中率、PP 等属性。

### Learnset（技能池）
一个 Species 能学会的所有 Move 的集合，包含学习方式（升级、技能机、遗传等）。

**歧义处理规则：** 当用户在提问中使用"技能"一词时，系统须先澄清："您所说的技能指的是 Move（招式）还是 Learnset（技能池）？"，再继续回答。"技能"不作为系统内部术语使用。

### Language（语言）
系统支持中英文双语界面。RAG 文档和 PokeAPI 数据统一以英文存储。语言切换通过 `final_answer()` 的 system prompt 参数控制——用户选择中文时，prompt 指示 LLM 用中文回答；选择英文时用英文回答。不维护双语索引，不在数据层做翻译。

### Query vs Advisory
用户问题分两类：Query（有明确答案，如"皮卡丘速度种族值"）和 Advisory（需要推理建议，如"皮卡丘还是雷丘更适合这场比赛"）。两类问题统一走完整 Agent Pipeline，由 `agent_plan()` 自行判断调用几个工具，不在入口处手动分流。

### Agent Pipeline
系统的推理链路，沿用 SalesPilot 原始命名：`agent_plan()` → `process_actions()` → `reflection()` → `final_answer()`。这是通用 Agent 模式的标准描述，不因场景变化而重命名。

### Generation（世代）
系统数据范围限定为第九世代（朱/紫），包含两个 DLC（碧之假面 `the-teal-mask`、蓝之圆盘 `the-indigo-disk`）。PokeAPI version-group 名称：`scarlet-violet`、`the-teal-mask`、`the-indigo-disk`。当用户询问其他世代数据时，系统明确告知"本系统基于第九世代数据"。

### Evolution Chain（进化链）
一个 Species 的进化路径及条件（友好度、道具、时间段、地点等）。数据来源为 PokeAPI，覆盖主系列游戏的标准进化条件。不处理版本限定或活动限定的特殊进化条件。

### Battle Advisory（对战建议）
系统对战类问题的回答深度：不止于 Type Matchup 结论，还包括具体 Move 组合推荐、队伍搭配建议、速度档位比较。浅层（"电系克制什么"）由 `pokeapi_query` 直接回答；深层对战建议综合 RAG 文档 + `pokeapi_query` 数值 + `web_search` meta 信息，由 `final_answer()` 整合输出。

### Team（队伍）
由最多 6 只 Species 组成的对战阵容。系统支持队伍分析（弱点覆盖、搭配建议）和队伍推荐（以某只 Species 为核心搭建队伍）。队伍信息只在当次对话上下文中维持，不持久化存储。

### Type Matchup（克制关系）
两个 Type 之间的伤害倍率关系（0x / 0.5x / 1x / 2x）。属于结构化精确数据，由 `pokeapi_query` 工具查询，不放入 RAG 文档。

### RAG 文档（攻略知识库）
存放攻略、对战策略、队伍搭配建议、赛季 meta 分析等**经验性、文字性内容**。这类内容 PokeAPI 没有，是 RAG 的专属领域。`pokeapi_query` 和 RAG 两个工具职责不重叠：前者负责精确数值和结构化事实，后者负责策略和经验知识。

数据来源：手动整理热门 Species 的 Smogon 攻略文章作为初始知识库；`web_search`（Serper）作为兜底，处理知识库未覆盖的问题。

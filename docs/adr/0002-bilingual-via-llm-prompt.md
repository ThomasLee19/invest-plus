# ADR-0002: 双语支持通过 LLM prompt 控制，不维护双语数据层

## Status
Accepted

## Context
系统需要支持中英文双语界面。候选方案：
- A：PokeAPI 拉取时同时存中英文字段
- B：数据层全英文，语言切换通过 final_answer() prompt 参数控制
- C：建两套 ES 索引分别存中英文数据

## Decision
采用方案 B：RAG 文档和 PokeAPI 数据统一英文存储，`final_answer()` 的 system prompt 根据用户语言选择指示 LLM 用对应语言回答。

## Consequences
- 排除方案 A：PokeAPI 中文翻译不完整，技能名、特性名大量缺失，混合语言文档质量差
- 排除方案 C：双索引维护成本高，数据同步复杂，收益不明显
- deepseek-r1 对宝可梦中文术语熟悉度高，LLM 翻译质量可接受
- 实现简单：只需在 final_answer() 加语言参数，数据层零改动

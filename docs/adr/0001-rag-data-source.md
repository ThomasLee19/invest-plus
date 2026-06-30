# ADR-0001: RAG 知识库数据来源选择手动整理而非爬取

## Status
Accepted

## Context
RAG 知识库需要攻略、对战策略、队伍搭配等经验性内容。候选数据来源包括：手动整理 Smogon 文章、爬取 Smogon/Bulbapedia、GPT 批量生成、web_search 实时检索。

## Decision
手动整理热门 Species 的 Smogon 攻略文章作为初始知识库，`web_search`（Serper）作为兜底。

## Consequences
- 排除爬取：Smogon/Bulbapedia 有版权限制，爬取存在法律风险
- 排除 GPT 生成：内容质量不稳定，用于知识库会引入错误
- 手动整理控制范围，优先覆盖竞技常用 Species（约 50-100 只）
- web_search 兜底覆盖知识库未收录的长尾问题

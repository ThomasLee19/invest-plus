# Invest+ Domain Context

## Glossary

### Ticker（股票代码）
1-5 位大写字母的股票代码，如 `AAPL`、`MSFT`、`GOOGL`。系统从用户问题里用正则
（`_TICKER_RE`）提取大写连续字母序列作为 ticker，并剔除常见的全大写虚词/缩写
撞字（`I`/`US`/`CEO`/`PE`/`EPS` 等）。`agent_plan` 的 Plan 阶段要求每个子问题
必须显式带上大写 ticker（复合问题会被拆成多个子问题，每个子问题只对应一个
ticker，不做多 ticker 扇出）。

**不要用：** 小写股票代码或公司全名替代 ticker 传给 `finance_query`——提取逻辑
只认大写字母序列，传公司全名（如 "Apple"）会导致 ticker 提取失败。

### Filing（财报文件）
上市公司向 SEC 提交的信息披露文件，本系统覆盖三种：**10-K**（年报）、**10-Q**
（季报）、**8-K**（临时重大事项披露，如高管变动）。语料存放在
`data/filings/{TICKER}/`，索引进 ES 时 `source_kwd="sec_filing"`。

### RAG 知识库（finance_kb）
单一 Elasticsearch 索引，按 `source_kwd` 分四类：
- `sec_filing` —— Filing 原文（10-K/10-Q/8-K）
- `news` —— 财经新闻
- `educational` —— 教育性参考文章（如"什么是市盈率"）
- `user_upload` —— 用户上传的 `.txt`/`.md`/`.pdf` 文档，按 `session_id` 限定
  可见范围（`session_id` 为空表示全局种子语料，否则只在对应会话内可见）

由 `rag_search` 工具检索，用 BM25（`content_ltks` 全文匹配）+ 向量 kNN
（`q_1024_vec`，text-embedding-v3）hybrid 融合，qwen3-vl-rerank 精排，
再按用户最近上传做 boost，最终截断为 top 5。

### finance_query（实时结构化数据）
基于 `yfinance` 的三种查询模式，互不重叠：
- **quote** —— 实时行情（价格、涨跌幅、成交量）
- **fundamentals** —— 基本面（市值、市盈率、股息率、52 周区间等）
- **news** —— 该 ticker 的近期新闻（来自 yfinance，与 RAG 知识库的 `news`
  分区是两个独立数据源）

`finance_tool()` 根据问题里的关键词（`_FUNDAMENTALS_KEYWORDS`/
`_NEWS_KEYWORDS`）路由到对应模式，不含明确关键词时默认查 quote。

### rag_search vs finance_query 的边界
两者职责不重叠，不要混用：
- `finance_query` —— 精确的、实时的、结构化数值（"AAPL 现在股价多少"）
- `rag_search` —— 财报原文解读、新闻叙述、教育性概念解释这类文字性/经验性内容
  （"AAPL 最新 10-K 的风险因素"、"什么是市盈率"）

### web_search（兜底检索）
基于 Serper 的通用网页搜索，处理知识库未覆盖的内容或需要"最新"信息的问题（如
"今天美股大盘走势"、"最新的美联储利率决议"）。`_detect_language` 判断的语言
决定 Serper 的 `hl`（区域/语言）参数。

### Query vs Advisory（问题类型）
用户问题分两类：**Query**（有明确答案，如"AAPL 现在股价多少"）和 **Advisory**
（需要综合推理，如"AAPL 现在这个估值水平算不算贵"）。两类问题统一走完整 Agent
Pipeline，由 `agent_plan()` 自行判断调用几个工具，不在入口处手动分流。

### Agent Pipeline（推理链路）
系统的推理链路，命名固定，**不因场景变化而改**：
`agent_plan()` → `process_actions()` → `reflection()` → `final_answer()`。
`reflection()` 现在是一个由 `should_continue()` 驱动的有界循环（不是单次硬编码
调用），LLM 自行判断信息是否足够、是否需要继续调用工具。

### Language（双语）
系统支持中英文双语界面，自动检测用户输入语言（`_detect_language`：含 CJK 汉字
即判定为中文，日文假名/韩文谚文显式排除）。RAG 文档（filings/news/教育内容）
统一以英文存储，语言切换只影响 `final_answer()` 的 system prompt（指示 LLM
用对应语言作答），不维护双语索引，不在数据层做翻译。

### Session（会话）与 User Upload（用户上传）
会话（`session_id`）持久化在 PostgreSQL，承载多轮对话历史和用户上传文档的可见
范围。用户上传的文档经 `file_parse.py` 切块（≤1500 字符）+ embedding 后写入
`finance_kb`（`source_kwd="user_upload"`），只在其 `session_id` 对应的会话内
被 `rag_search` 检索到（全局种子语料的 `session_id` 为空，对所有会话可见）。

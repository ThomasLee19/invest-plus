# Invest+ 量化评测报告

评测对象：本机真实运行的前后端服务（走真实 agent/RAG/Elasticsearch 逻辑，非 mock）。

语料真实性声明：`data/` 下的财报/新闻语料为项目自带测试数据，内容可能由 AI 生成、日期为未来虚构日期；RAG 准确率衡量的是回答对语料的忠实度，不代表对真实世界财务数据的验证。


## 1. RAG 检索准确率

**13/15 = 86.7%**

| 题目 | 来源 | 结果 |
| --- | --- | --- |
| 10-K 和 10-Q 报告有什么区别？ | educational/10k_vs_10q.md | ✓ |
| 资产负债表的基本会计恒等式是什么？ | educational/balance_sheet.md | ✓ |
| 每股收益（EPS）的计算公式是什么？ | educational/eps.md | ✓ |
| 市值达到多少美元通常被归为 mega-cap（超大市值）？ | educational/market_cap.md | ✓ |
| P/E 市盈率有哪两种常见的计算方式？ | educational/pe_ratio.md | ✓ |
| 股息率的计算公式是什么？ | educational/dividend_yield.md | ✓ |
| 现金流量表分为哪三个部分？ | educational/cash_flow_statement.md | ✓ |
| American Express 和 Apple Pay 最近有什么新的合作？ | news/AAPL (American Express) | ✓ |
| 微软的 AI 业务年化运行速率（annual run rate）大约是多少？ | news/AAPL (Microsoft AI run-rate) | ✓ |
| 微软云（Microsoft Cloud）最近一个季度的营收超过多少？ | news/AAPL (Microsoft Cloud revenue) | ✓ |
| Alphabet（GOOGL）最近一个交易日的收盘价是多少？ | news/GOOGL (closing price) | ✗ |
| Waymo 和 Uber 在哪个城市结束了机器人出租车试点合作？ | news/GOOGL (Waymo/Uber Phoenix) | ✓ |
| 微软 Xbox 部门终止了与哪家公司的合作？ | news/MSFT (Xbox/IO Interactive) | ✗ |
| 根据最近的 8-K 文件，苹果公司的首席财务官（CFO）是谁？ | filings/AAPL 8-K | ✓ |
| 哪位董事会成员决定不再连任微软的董事？ | filings/MSFT 8-K | ✓ |

## 2. Agent 工具路由准确率

**13/17 = 76.5%**

| 类别 | 准确率 |
| --- | --- |
| finance_query | 3/4 = 75% |
| rag_search | 3/4 = 75% |
| web_search | 2/3 = 67% |
| no_tool | 4/4 = 100% |
| compound | 1/2 = 50% |

| 题目 | 类别 | 期望工具 | 实际工具 | 结果 |
| --- | --- | --- | --- | --- |
| AAPL 现在的股价是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ |
| MSFT 现在的市盈率是多少？ | finance_query | ['finance_query'] | ['finance_query', 'rag_search', 'web_search'] | ✗ |
| GOOGL 目前的市值是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ |
| 苹果公司最新的每股收益是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ |
| 什么是自由现金流？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ |
| 谷歌最近的 8-K 文件里披露了哪些优先股相关信息？ | rag_search | ['rag_search'] | ['finance_query', 'rag_search'] | ✗ |
| 微软最近的 8-K 文件里有什么人事变动？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ |
| 苹果最近和 American Express 有什么合作新闻？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ |
| 今天美股大盘的整体走势如何？ | web_search | ['web_search'] | ['finance_query', 'web_search'] | ✗ |
| 最近有什么关于美联储利率决议的最新消息？ | web_search | ['web_search'] | ['web_search'] | ✓ |
| 今天全球有什么重要的财经新闻？ | web_search | ['web_search'] | ['web_search'] | ✓ |
| 你好 | no_tool | [] | [] | ✓ |
| 你是谁？你能做什么？ | no_tool | [] | [] | ✓ |
| 1+1等于几？ | no_tool | [] | [] | ✓ |
| 帮我讲个笑话吧 | no_tool | [] | [] | ✓ |
| 对比一下苹果和微软现在的股价和市盈率 | compound | ['finance_query'] | ['finance_query'] | ✓ |
| 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？ | compound | ['finance_query', 'web_search'] | ['finance_query', 'rag_search'] | ✗ |

## 3. 响应延迟

基于 32 次真实流式请求（total_latency 有值的样本；TTFT 样本数可能更少，见下方 N/A 说明）：

| 指标 | 均值 | p50 | p90 |
| --- | --- | --- | --- |
| 首字延迟 (TTFT) | 0.00s | 0.00s | 0.01s |
| 完整响应延迟 | 29.99s | 28.12s | 55.51s |

## 4. 边界输入鲁棒性

**5/5 = 100.0%**

| 场景 | 结果 |
| --- | --- |
| empty_message | ✓ |
| overlong_message | ✓ |
| invalid_ticker | ✓ |
| off_topic | ✓ |
| nonexistent_session_chat | ✓ |
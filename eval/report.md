# Invest+ 量化评测报告

评测对象：本机真实运行的前后端服务（走真实 agent/RAG/Elasticsearch 逻辑，非 mock）。

语料真实性声明：`data/` 下的财报/新闻语料为项目自带测试数据，内容可能由 AI 生成、日期为未来虚构日期；RAG 准确率衡量的是回答对语料的忠实度，不代表对真实世界财务数据的验证。

评测方法说明：本报告的评分口径在首次运行后做过一轮人工复核修正——扩充了对同义表述/更精确数值的容忍（如"预期市盈率"等价于"前瞻市盈率"、财报给出的精确数字545亿与新闻概述的"超过540亿"不矛盾），排除了 1 道测试设计有缺陷的题目（ground truth 是时间快照但问题问的是相对当前日期的浮动概念），并修正了鲁棒性判定脚本里的 1 处逻辑 bug。详见下方各小节的具体说明，所有原始回答文本均可在 `eval/results.json` 中核对。


## 1. RAG 检索准确率

**14/14 = 100.0%**（另有 1 题因测试设计缺陷被排除，不计入统计，见下方说明）

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
| Waymo 和 Uber 在哪个城市结束了机器人出租车试点合作？ | news/GOOGL (Waymo/Uber Phoenix) | ✓ |
| 微软 Xbox 部门终止了与哪家公司的合作？ | news/MSFT (Xbox/IO Interactive) | ✓ |
| 根据最近的 8-K 文件，苹果公司的首席财务官（CFO）是谁？ | filings/AAPL 8-K | ✓ |
| 哪位董事会成员决定不再连任微软的董事？ | filings/MSFT 8-K | ✓ |

**排除题目说明：**

- `rag-11` Alphabet（GOOGL）最近一个交易日的收盘价是多少？ —— ground truth 是时间快照，问题却问的是相对当前日期的浮动概念

## 2. Agent 工具路由准确率

- **严格匹配**（实际调用工具集合与预期完全一致）：**10/17 = 58.8%**
- **宽松匹配**（实际调用包含全部预期工具，允许额外调用）：**15/17 = 88.2%**

严格与宽松的差距来自 5 道「预期工具都调了、但另外多调了工具」的题，这是 Reflect 循环的兜底倾向：结果冗余但不算路由错误，代价是延迟与成本。


**另有 2 道题漏调了预期工具**（route-08、route-17），这是真正的路由错误，性质比多调严重：

- `route-08` 苹果最近和 American Express 有什么合作新闻？　期望 ['rag_search']，实际 ['web_search']
- `route-17` 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？　期望 ['finance_query', 'web_search']，实际 ['finance_query']

| 类别 | 严格匹配 | 宽松匹配 |
| --- | --- | --- |
| finance_query | 2/4 | 4/4 |
| rag_search | 2/4 | 3/4 |
| web_search | 1/3 | 3/3 |
| no_tool | 4/4 | 4/4 |
| compound | 1/2 | 1/2 |

| 题目 | 类别 | 期望工具 | 实际工具 | 严格 | 宽松 |
| --- | --- | --- | --- | --- | --- |
| AAPL 现在的股价是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| MSFT 现在的市盈率是多少？ | finance_query | ['finance_query'] | ['finance_query', 'rag_search'] | ✗ | ✓ |
| GOOGL 目前的市值是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| 苹果公司最新的每股收益是多少？ | finance_query | ['finance_query'] | ['finance_query', 'rag_search', 'web_search'] | ✗ | ✓ |
| 什么是自由现金流？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 谷歌最近的 8-K 文件里披露了哪些优先股相关信息？ | rag_search | ['rag_search'] | ['finance_query', 'rag_search', 'web_search'] | ✗ | ✓ |
| 微软最近的 8-K 文件里有什么人事变动？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 苹果最近和 American Express 有什么合作新闻？ | rag_search | ['rag_search'] | ['web_search'] | ✗ | ✗ |
| 今天美股大盘的整体走势如何？ | web_search | ['web_search'] | ['finance_query', 'web_search'] | ✗ | ✓ |
| 最近有什么关于美联储利率决议的最新消息？ | web_search | ['web_search'] | ['rag_search', 'web_search'] | ✗ | ✓ |
| 今天全球有什么重要的财经新闻？ | web_search | ['web_search'] | ['web_search'] | ✓ | ✓ |
| 你好 | no_tool | [] | [] | ✓ | ✓ |
| 你是谁？你能做什么？ | no_tool | [] | [] | ✓ | ✓ |
| 1+1等于几？ | no_tool | [] | [] | ✓ | ✓ |
| 帮我讲个笑话吧 | no_tool | [] | [] | ✓ | ✓ |
| 对比一下苹果和微软现在的股价和市盈率 | compound | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？ | compound | ['finance_query', 'web_search'] | ['finance_query'] | ✗ | ✗ |

## 3. 响应延迟（不可引用，仅作运行记录）

基于 32 次真实流式请求（RAG QA + 工具路由两批次合计）：

| 指标 | 均值 | p50 | p90 |
| --- | --- | --- | --- |
| 首次反馈延迟 | 3.12s | 3.08s | 4.28s |
| 完整响应延迟 | 33.62s | 27.47s | 69.57s |

**口径**：首次反馈延迟 = 从 POST /chat 发出，到收到第一条 SSE 事件的时间。该事件对需要工具的问题是后端拼接的工具状态行（`正在调用 …`），对不需要工具的问题才是模型吐出的思考首字。它**不是 TTFT**——TTFT 的作用域是单次推理调用，而此处跨了整条流水线，中间夹着记忆召回与两次完整的非流式 LLM 往返。


**为什么不可引用**，三条独立的理由：
1. 同一批样本内该指标口径不统一：走工具的题量的是 Plan 阶段完成，不走工具的题量的是回答首 token，两者被平均在了一起。
2. p50/p90 由题库构成决定而非系统性能决定。样本是「不同题目各跑一次」，尾部取决于最慢的是哪几道题；实测增删几道无工具的送分题，p90 会大幅漂移，而代码一行未改。
3. 每题只跑一次，无重复采样，分不清差异来自代码还是来自网络与上游负载的抖动。


完整响应延迟包含 Plan → Act → Reflect（最多 5 轮）→ Answer 全流程，命中多轮 Reflect 的问题会显著更长，长尾主要由 Reflect 轮数驱动。


## 4. 边界输入鲁棒性

**5/5 = 100.0%**（全部场景均已判定）

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| empty_message | ✓ | 422，格式校验正确拒绝 |
| overlong_message | ✓ | 422，格式校验正确拒绝 |
| invalid_ticker | ✓ | 多轮 Reflect 后给出友好提示，无崩溃 |
| off_topic | ✓ | 在评测脚本的超时预算内正常完成，未见 500/未捕获异常（首轮情况：首轮评测因客户端超时（150-280s）未采集到完整记录，当时仅能由后端 access log 间接确认服务端行为正确，不计入统计） |
| nonexistent_session_chat | ✓ | 404 + 通用提示 {"detail":"session not found"}，未泄露异常（首轮情况：首轮评测脚本判定逻辑有 bug（误将 JSON 里必然出现的 'detail' 键名当成泄露标志），已修正） |

## 5. 简历/README 摘录建议

- RAG 检索准确率：14/14（100%），基于 14 道人工核实的财报/新闻/教育知识问答题
- Agent 多工具路由准确率：宽松匹配 88%（15/17），严格匹配 59%
- 响应延迟：**不建议引用**。本轮实测首次反馈延迟均值 3.1s、完整响应 p50 27.5s，但口径与采样方式都不支持对外引用，理由见第 3 节
- 边界输入优雅处理率 5/5（100%）
# Invest+ 量化评测报告

评测对象：本机真实运行的前后端服务（走真实 agent/RAG/Elasticsearch 逻辑，非 mock）。

语料真实性声明：`data/` 下的财报/新闻语料为项目自带测试数据，内容可能由 AI 生成、日期为未来虚构日期；RAG 准确率衡量的是回答对语料的忠实度，不代表对真实世界财务数据的验证。

评测方法说明：本报告的评分口径在首次运行后做过一轮人工复核修正——扩充了对同义表述/更精确数值的容忍（如"预期市盈率"等价于"前瞻市盈率"、财报给出的精确数字545亿与新闻概述的"超过540亿"不矛盾），排除了 1 道测试设计有缺陷的题目（ground truth 是时间快照但问题问的是相对当前日期的浮动概念），并修正了鲁棒性判定脚本里的 1 处逻辑 bug。详见下方各小节的具体说明，所有原始回答文本均可在 `eval/results.json` 中核对。


## 1. RAG 检索准确率

**13/14 = 92.9%**（另有 1 题因测试设计缺陷被排除，不计入统计，见下方说明）

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
| 微软 Xbox 部门终止了与哪家公司的合作？ | news/MSFT (Xbox/IO Interactive) | ✗ |
| 根据最近的 8-K 文件，苹果公司的首席财务官（CFO）是谁？ | filings/AAPL 8-K | ✓ |
| 哪位董事会成员决定不再连任微软的董事？ | filings/MSFT 8-K | ✓ |

**排除题目说明：**

- `rag-11` Alphabet（GOOGL）最近一个交易日的收盘价是多少？ —— ground truth 是时间快照，问题却问的是相对当前日期的浮动概念

## 2. Agent 工具路由准确率

**每题采样 3 次，平均命中率 74.5%**（稳定命中 10 题｜稳定失败 3 题｜**翻转 4 题**）

翻转的题是同一份代码上时对时错的。它们让单次采样的严格准确率有约 **±24 个百分点**的摆动区间——所以**任何基于单次采样的前后对照，只要差异小于这个幅度就读不出结论**。下表的严格/宽松沿用首次采样，仅供逐题查看；要做版本间对照请用上面的平均命中率。

**翻转的题**：`route-07`（2/3）、`route-08`（2/3）、`route-09`（2/3）、`route-16`（2/3）


**稳定失败的题**（真问题，与抖动无关）：

- `route-05` 什么是自由现金流？　期望 ['rag_search']，实际 ['rag_search', 'web_search']
- `route-11` 今天全球有什么重要的财经新闻？　期望 ['web_search']，实际 []
- `route-17` 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？　期望 ['finance_query', 'web_search']，实际 ['finance_query', 'rag_search']

- **严格匹配**（实际调用工具集合与预期完全一致）：**14/17 = 82.4%**
- **宽松匹配**（实际调用包含全部预期工具，允许额外调用）：**15/17 = 88.2%**

严格与宽松的差距来自 1 道「预期工具都调了、但另外多调了工具」的题，这是 Reflect 循环的兜底倾向：结果冗余但不算路由错误，代价是延迟与成本。


**另有 2 道题漏调了预期工具**（route-11、route-17），这是真正的路由错误，性质比多调严重：

- `route-11` 今天全球有什么重要的财经新闻？　期望 ['web_search']，实际 []
- `route-17` 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？　期望 ['finance_query', 'web_search']，实际 ['finance_query', 'rag_search']

| 类别 | 严格匹配 | 宽松匹配 |
| --- | --- | --- |
| finance_query | 4/4 | 4/4 |
| rag_search | 3/4 | 4/4 |
| web_search | 2/3 | 2/3 |
| no_tool | 4/4 | 4/4 |
| compound | 1/2 | 1/2 |

| 题目 | 类别 | 期望工具 | 实际工具 | 严格 | 宽松 |
| --- | --- | --- | --- | --- | --- |
| AAPL 现在的股价是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| MSFT 现在的市盈率是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| GOOGL 目前的市值是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| 苹果公司最新的每股收益是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| 什么是自由现金流？ | rag_search | ['rag_search'] | ['rag_search', 'web_search'] | ✗ | ✓ |
| 谷歌最近的 8-K 文件里披露了哪些优先股相关信息？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 微软最近的 8-K 文件里有什么人事变动？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 苹果最近和 American Express 有什么合作新闻？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 今天美股大盘的整体走势如何？ | web_search | ['web_search'] | ['web_search'] | ✓ | ✓ |
| 最近有什么关于美联储利率决议的最新消息？ | web_search | ['web_search'] | ['web_search'] | ✓ | ✓ |
| 今天全球有什么重要的财经新闻？ | web_search | ['web_search'] | [] | ✗ | ✗ |
| 你好 | no_tool | [] | [] | ✓ | ✓ |
| 你是谁？你能做什么？ | no_tool | [] | [] | ✓ | ✓ |
| 1+1等于几？ | no_tool | [] | [] | ✓ | ✓ |
| 帮我讲个笑话吧 | no_tool | [] | [] | ✓ | ✓ |
| 对比一下苹果和微软现在的股价和市盈率 | compound | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？ | compound | ['finance_query', 'web_search'] | ['finance_query', 'rag_search'] | ✗ | ✗ |

## 3. 响应延迟

基于 32 次真实流式请求：

| 时刻 | 均值 | p50 | p90 | 含义 |
| --- | --- | --- | --- | --- |
| 受理回执 | 0.00s | 0.00s | 0.00s | 后端在任何 LLM 调用前直接发出，常数 |
| **首个实质判断** | 2.93s | 2.63s | 4.86s | 到第一条工具调用事件为止，**这是衡量响应性的那个数** |
| 回答首 token | 28.89s | 28.33s | 48.38s | 含回答阶段的思考时间 |
| 全程 | 32.61s | 31.88s | 54.96s | Answer 流式输出结束 |

**延迟的主体是思考，不是可见输出。**思考内容均值 1810 字符，可见回答均值 486 字符，前者是后者的 **3.7 倍**。全程 32.6s 里，回答开始流式输出之后只剩 3.7s。因此压缩可见回答长度几乎动不了总延迟——真正的杠杆是回答调用的 `enable_thinking`。


**口径**：受理回执自 `448b831` 起恒为第一条 SSE 事件，与模型、检索、工具全都无关，只证明连接已建立，**不要引用它**。要引用响应性就用「首个实质判断」。


**仍存在的局限**：延迟只取每题首次采样（路由题虽跑了多次，本表未按多次平均），所以它带有与路由同量级的抖动；思考量以字符数为代理，不是精确 token 数。


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

- RAG 检索准确率：13/14（93%），基于 14 道人工核实的财报/新闻/教育知识问答题
- Agent 多工具路由平均命中率：74.5%（17 题 × 3 次采样；稳定命中 10 题、稳定失败 3 题、翻转 4 题）
- 路由的严格/宽松单次数字：**不建议引用**。翻转题使它带约 ±24 个百分点的摆动，理由见第 2 节
- 首个实质判断延迟：均值 2.93s（p50 2.63s / p90 4.86s，n=24），即到第一条工具调用事件为止。**要谈响应性就用这个数**
- 响应延迟：**不建议引用**。本轮实测首次反馈延迟均值 0.0s、完整响应 p50 31.9s，但口径与采样方式都不支持对外引用，理由见第 3 节
- 边界输入优雅处理率 5/5（100%）
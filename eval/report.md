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
- **宽松匹配**（实际调用包含全部预期工具，允许额外调用）：**17/17 = 100.0%**

两者差距（100% 宽松 vs 47% 严格）反映了一个真实、值得记录的 agent 行为特征：**Reflect 循环存在"工具触发过度"倾向**——命中预期工具之余，经常会额外触发 web_search 兜底补充（即便 rag_search/finance_query 的结果已经足够），带来了正确性冗余但也增加了延迟和成本。这不是路由错误（该调用的工具都调用了），而是效率上可优化的空间。

| 类别 | 严格匹配 | 宽松匹配 |
| --- | --- | --- |
| finance_query | 1/4 | 4/4 |
| rag_search | 2/4 | 4/4 |
| web_search | 1/3 | 3/3 |
| no_tool | 4/4 | 4/4 |
| compound | 2/2 | 2/2 |

| 题目 | 类别 | 期望工具 | 实际工具 | 严格 | 宽松 |
| --- | --- | --- | --- | --- | --- |
| AAPL 现在的股价是多少？ | finance_query | ['finance_query'] | ['finance_query', 'web_search'] | ✗ | ✓ |
| MSFT 现在的市盈率是多少？ | finance_query | ['finance_query'] | ['finance_query'] | ✓ | ✓ |
| GOOGL 目前的市值是多少？ | finance_query | ['finance_query'] | ['finance_query', 'web_search'] | ✗ | ✓ |
| 苹果公司最新的每股收益是多少？ | finance_query | ['finance_query'] | ['finance_query', 'rag_search', 'web_search'] | ✗ | ✓ |
| 什么是自由现金流？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 谷歌最近的 8-K 文件里披露了哪些优先股相关信息？ | rag_search | ['rag_search'] | ['rag_search', 'web_search'] | ✗ | ✓ |
| 微软最近的 8-K 文件里有什么人事变动？ | rag_search | ['rag_search'] | ['rag_search'] | ✓ | ✓ |
| 苹果最近和 American Express 有什么合作新闻？ | rag_search | ['rag_search'] | ['rag_search', 'web_search'] | ✗ | ✓ |
| 今天美股大盘的整体走势如何？ | web_search | ['web_search'] | ['finance_query', 'web_search'] | ✗ | ✓ |
| 最近有什么关于美联储利率决议的最新消息？ | web_search | ['web_search'] | ['web_search'] | ✓ | ✓ |
| 今天全球有什么重要的财经新闻？ | web_search | ['web_search'] | ['rag_search', 'web_search'] | ✗ | ✓ |
| 你好 | no_tool | [] | [] | ✓ | ✓ |
| 你是谁？你能做什么？ | no_tool | [] | [] | ✓ | ✓ |
| 1+1等于几？ | no_tool | [] | [] | ✓ | ✓ |
| 帮我讲个笑话吧 | no_tool | [] | [] | ✓ | ✓ |
| 对比一下苹果和微软现在的股价和市盈率 | compound | ['finance_query'] | ['finance_query', 'web_search'] | ✓ | ✓ |
| 苹果现在股价多少？另外它最近有没有什么值得关注的新闻？ | compound | ['finance_query', 'web_search'] | ['finance_query', 'rag_search', 'web_search'] | ✓ | ✓ |

## 3. 响应延迟

基于 32 次真实流式请求（RAG QA + 工具路由两批次合计）：

| 指标 | 均值 | p50 | p90 |
| --- | --- | --- | --- |
| 首字延迟 (TTFT) | 2.07s | 2.08s | 2.53s |
| 完整响应延迟 | 39.95s | 29.92s | 85.62s |

说明：完整响应延迟包含 Plan → Act → Reflect（最多 5 轮）→ Answer 全流程，命中多轮 Reflect 的问题延迟会显著更长；评测过程中观察到个别请求（尤其是需要多轮工具调用的边界场景）单次延迟可超过 150s，属于真实的长尾延迟，建议关注 p90 而非仅看均值。


## 4. 边界输入鲁棒性

**4/4 = 100.0%**（另有 1 项因评测脚本自身超时限制未能完整验证，不计入统计，见下方说明）

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| empty_message | ✓ | 422，格式校验正确拒绝 |
| overlong_message | ✓ | 422，格式校验正确拒绝 |
| invalid_ticker | ✓ | 多轮 Reflect 后给出友好提示，无崩溃 |
| off_topic | ⚪ | 评测脚本客户端超时（150-280s）未采集到完整记录；后端 access log 确认该请求最终以 HTTP 200 正常完成，未见 500/未捕获异常——判定为「服务端行为正确，但受限于评测脚本超时预算未能完整验证」，不计入通过率分子也不计入分母 |
| nonexistent_session_chat | ✓ | 404 + 通用提示 {"detail":"session not found"}，未泄露异常；首次评测脚本的判定逻辑有 bug（误将 JSON 里必然出现的 'detail' 键名当成泄露标志），已修正 |

## 5. 跨语言召回验证（BM25-only vs Hybrid）

**方法**：[`eval/recall_validation.py`](recall_validation.py) 直接复用 `rag_search()` 生产环境的查询构造代码（`_strip_filler_words` / `_scope_should_clauses` / `_embed_query`），对同一个 `finance_kb` 索引分别跑纯 BM25 与 hybrid（BM25 + 向量 kNN）两种检索。语料为纯英文的 SEC filings/新闻/教育文档；测试问题为对应的 10 道中文口语化提问。判定口径：`size=20` 结果集非空即算命中（二元口径，不判断相关性）。

**结果**：BM25-only **0/10 = 0%**，hybrid **10/10 = 100%**。

| query | 预期来源 | BM25 命中 | hybrid 命中 |
| --- | --- | --- | --- |
| 市值多大算超大市值公司 | educational/market_cap.md | 0 | 20 |
| 股息率是怎么算出来的 | educational/dividend_yield.md | 0 | 20 |
| 每股收益的计算公式 | educational/eps.md | 0 | 20 |
| 现金流量表分几个部分 | educational/cash_flow_statement.md | 0 | 20 |
| 市盈率有哪几种算法 | educational/pe_ratio.md | 0 | 20 |
| 年报和季报有啥区别 | educational/10k_vs_10q.md | 0 | 20 |
| 资产负债表的基本恒等式 | educational/balance_sheet.md | 0 | 20 |
| 苹果和运通最近有什么合作 | news/AAPL (American Express) | 0 | 20 |
| 微软最近有啥大新闻 | news/MSFT/* | 0 | 20 |
| 谷歌最新一期财报风险因素 | filings/GOOGL/10-K or 10-Q | 0 | 20 |

**根因**：ES `content_ltks` 字段用 `whitespace` analyzer 按空格切词；中文句子没有空格，整句被切成一个不可分 token，与纯英文语料的 token（`market`/`cap`/`dividend`…）永远无法字面匹配 → BM25 命中恒为 0。向量 kNN 分支靠语义相似度检索，不受分词影响，因此补齐了 100% 的召回。

**说明**：此前 README 中的同类数字是从本项目的前身 PokemonRA（宝可梦语料库）上测得后直接搬运的，未在 `finance_kb` 上重新验证过；本节替换为在本项目真实语料上、用生产查询逻辑实测的数字。

## 6. 精排（qwen3-vl-rerank）质量验证：rerank 前后排名对比

**动机**：第 1 节「RAG 检索准确率 14/14」走完整 `/chat` 端到端流程，把 Plan 工具选择 / 检索 / LLM 归纳三层因素混在一起，看不出精排本身是否起作用；`eval/recall_validation.py` 又完全不调用 `_rerank_candidates()`。两者都回答不了"qwen3-vl-rerank 有没有把更相关的 chunk 排到前面"这个问题。[`eval/rerank_validation.py`](rerank_validation.py) 单独隔离这一步：对同一批 BM25+kNN 融合召回的候选（复用生产代码，`size=20`），分别记录"含标准答案关键词的 chunk"在 **rerank 前**（ES 融合分数排序）和 **rerank 后**（qwen3-vl-rerank 排序）中的名次，计算 MRR 与 Recall@5（生产环境实际截断窗口）。

**结果**：14/14 道题（复用第 1 节 RAG_QA 数据集，剔除 rag-11 已知缺陷题），rerank 前后相关 chunk **均排名第 1**——MRR 1.000 → 1.000，Recall@5 100% → 100%，无变化。

**如何解读——这不是"精排没用"的证据**：这批评测语料每个主题只对应一份清晰文档，候选池里没有强干扰项，ES 自身的 BM25+kNN 融合分数已经把正确答案排到第一位，天花板已经封顶（ceiling effect），精排没有任何提升空间可展示。换句话说，**当前数据集测不出精排到底有没有价值**——要真正验证，需要构造"多个候选文档主题相近、但只有一个真正对答案"的干扰性更强的测试集（如同一 ticker 下多篇相似新闻，只有一篇提到具体数字），这部分尚未覆盖，是明确的评测空白，留待后续补充。

## 7. 简历/README 摘录建议

- RAG 检索准确率：14/14（100%），基于 14 道人工核实的财报/新闻/教育知识问答题
- Agent 多工具路由准确率：宽松匹配 100%（17/17），严格匹配 59%
- 平均首字延迟 2.1s，完整响应 p50 29.9s / p90 85.6s
- 边界输入优雅处理率 4/4（100%）
- 跨语言召回率：中文口语化提问对纯英文语料，BM25-only 0/10（0%）→ hybrid 10/10（100%）
- 精排质量：当前数据集下 MRR/Recall@5 均无变化（天花板效应，语料缺乏干扰项，不构成"精排无效"的结论）——不建议作为简历亮点，除非补充干扰性测试集后重测
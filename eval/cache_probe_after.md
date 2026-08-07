# 前缀缓存命中探针 — after

被测 commit：`eb9a6bd@agent.py:ec4b1d1ee38c` ｜ 运行于 2026-08-07 23:44:54 ｜ 冷启动等待 0.0s

本脚本完整消费每条 SSE 流后再等后端日志静默，因此请求之间不存在重叠，`[llm_cache]` 行按字节偏移归属是精确的。


## 各阶段命中序列

下表只取每条请求的**第一次**调用。这是唯一反映跨请求前缀缓存、也是唯一可用于 A/B 对照的量。


### `classify_skill`（首次调用 prompt 约 532 token）

| 请求 | 是否触发 | cached_tokens | prompt_tokens | completion_tokens |
| --- | --- | --- | --- | --- |
| X1 | 是 | 0 | 532 | 12 |
| X2 | 是 | 0 | 532 | 12 |
| X3 | 是 | 0 | 532 | 12 |
| Y1 | 是 | 0 | 531 | 8 |
| Y2 | 是 | 512 | 531 | 8 |

观测 5 次，命中 1 次。

**判定：X 侧命中、Y 侧未命中。受上游命中随机性影响，本样本量不足以判定跨题共享，需增加 Y 侧重复次数**


### `plan`（首次调用 prompt 约 1637 token）

| 请求 | 是否触发 | cached_tokens | prompt_tokens | completion_tokens |
| --- | --- | --- | --- | --- |
| X1 | 是 | 512 | 1637 | 101 |
| X2 | 是 | 0 | 1637 | 96 |
| X3 | 是 | 0 | 1637 | 100 |
| Y1 | 是 | 512 | 1168 | 80 |
| Y2 | 是 | 0 | 1168 | 80 |

观测 5 次，命中 2 次。

**判定：命中，且跨题共享成立（Y 与 X 内容无关仍命中同一前缀）**


### `reflect`（首次调用 prompt 约 2940 token）

| 请求 | 是否触发 | cached_tokens | prompt_tokens | completion_tokens |
| --- | --- | --- | --- | --- |
| X1 | 是 | 0 | 2940 | 252 |
| X2 | 是 | 0 | 2961 | 200 |
| X3 | 是 | 0 | 2944 | 128 |
| Y1 | 是 | 0 | 3228 | 163 |
| Y2 | 是 | 0 | 3051 | 119 |

观测 5 次，命中 0 次。

**判定：未观测到命中。注意厂商文档声明命中率非 100%，未命中不构成「前缀不可缓存」的证据，只能说明样本内没看到**


<details><summary>reflect 的请求内全部调用（13 次）</summary>


| 请求 | 轮次 | cached_tokens | prompt_tokens | completion_tokens |
| --- | --- | --- | --- | --- |
| X1 | 1 | 0 | 2940 | 252 |
| X1 | 2 | 2816 | 4643 | 256 |
| X1 | 3 | 0 | 6385 | 291 |
| X1 | 4 | 6272 | 8107 | 283 |
| X1 | 5 | 8064 | 9850 | 309 |
| X2 | 1 | 0 | 2961 | 200 |
| X2 | 2 | 0 | 5191 | 212 |
| X2 | 3 | 5120 | 7493 | 215 |
| X2 | 4 | 2944 | 8654 | 186 |
| X2 | 5 | 7424 | 9843 | 217 |
| X3 | 1 | 0 | 2944 | 128 |
| Y1 | 1 | 0 | 3228 | 163 |
| Y2 | 1 | 0 | 3051 | 119 |

第 2 轮起的命中来自**请求内**的前缀复用：每轮把新 memory 追加进 prompt，后一轮天然以前一轮为前缀。改造前的代码同样有这个现象，因此这些数字**不能**用来支持本次改造的效果，也不可参与 A/B。

</details>


## 请求明细

| 请求 | 事件数 | 首次反馈 | 全程耗时 | Plan 工具 | 后端静默 | 降级 |
| --- | --- | --- | --- | --- | --- | --- |
| X1 | 1139 | 4.36s | 123.0s | rag_search,rag_search,finance_query,finance_query,finance_query,rag_search,web_search,rag_search,web_search,rag_search,web_search,rag_search,web_search,rag_search,web_search | 是 | 否 |
| X2 | 1232 | 3.50s | 140.8s | rag_search,rag_search,finance_query,finance_query,finance_query,rag_search,rag_search,rag_search,rag_search,rag_search,rag_search,rag_search,rag_search | 是 | 否 |
| X3 | 944 | 3.43s | 54.6s | rag_search,rag_search,finance_query,finance_query,finance_query | 是 | 否 |
| Y1 | 805 | 2.77s | 52.5s | finance_query,finance_query,rag_search,rag_search | 是 | 否 |
| Y2 | 649 | 3.40s | 44.6s | finance_query,finance_query,rag_search,rag_search | 是 | 否 |

首次反馈与全程耗时仅作参考。样本量是个位数，且完整消费流的执行方式与延迟评测不同，这两列不能拿来做 A/B 延迟比较。


## 怎么读这份报告

- `Y1` 那一行是关键。Y 与 X 内容完全不同，Y1 仍然命中才说明复用的是跨查询共享的静态前缀。

- `cached_tokens` 为 `None` 表示字段名取不到，与 `0`（确实没命中）是两回事。

- 任何一行「后端静默＝否」或「降级＝是」，该行数据都要排除后重跑。

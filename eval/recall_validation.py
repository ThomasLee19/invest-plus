"""
跨语言召回验证：中文口语化提问 vs 纯 BM25 / hybrid（BM25 + 向量 kNN）。

背景：验证 README.md 中"BM25-only 0% -> hybrid 100%"这一跨语言召回结论，直接
复用 backend/app/service/agent/agent.py 中生产环境实际使用的查询构造逻辑
（_strip_filler_words / _scope_should_clauses / _embed_query / ES_INDEX），
在 finance_kb 真实语料上实测，保证测的是线上会跑的同一套检索，而非另写一份
近似实现。

判定口径：size=20 内至少 1 条命中即算"召回"，不判断命中内容是否真正相关——这是
一个宽松的二元口径。

用法（仓库根目录下）：
    python eval/recall_validation.py
依赖：ES（finance_kb 索引，已灌入 data/ 语料）需已起；.env 提供 DASHSCOPE 配置。
只读，不写库/写 ES。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_APP = os.path.normpath(os.path.join(_HERE, "..", "backend", "app"))
if _BACKEND_APP not in sys.path:
    sys.path.insert(0, _BACKEND_APP)

from service.agent.agent import (  # noqa: E402
    _strip_filler_words,
    _scope_should_clauses,
    _embed_query,
    _get_es,
    ES_INDEX,
    _KNN_BOOST,
)

# 中文口语化金融提问，对应语料均为纯英文（data/educational, data/filings, data/news）。
RECALL_QUERIES = [
    ("市值多大算超大市值公司", "educational/market_cap.md"),
    ("股息率是怎么算出来的", "educational/dividend_yield.md"),
    ("每股收益的计算公式", "educational/eps.md"),
    ("现金流量表分几个部分", "educational/cash_flow_statement.md"),
    ("市盈率有哪几种算法", "educational/pe_ratio.md"),
    ("年报和季报有啥区别", "educational/10k_vs_10q.md"),
    ("资产负债表的基本恒等式", "educational/balance_sheet.md"),
    ("苹果和运通最近有什么合作", "news/AAPL (American Express)"),
    ("微软最近有啥大新闻", "news/MSFT/*"),
    ("谷歌最新一期财报风险因素", "filings/GOOGL/10-K or 10-Q"),
]


def _search(query: str, use_knn: bool, session_id: str = "recall-validation") -> int:
    """复用生产环境 rag_search() 的查询构造逻辑，返回命中条数。"""
    es = _get_es()
    source_filter = _scope_should_clauses(session_id)
    bm25_query = {
        "bool": {
            "must": {"match": {"content_ltks": _strip_filler_words(query)}},
            "should": source_filter,
            "minimum_should_match": 1,
        }
    }
    body: dict = {"query": bm25_query, "size": 20}
    if use_knn:
        q_vec = _embed_query(query)
        if q_vec is not None:
            body["knn"] = {
                "field": "q_1024_vec",
                "query_vector": q_vec,
                "k": 20,
                "num_candidates": 100,
                "boost": _KNN_BOOST,
                "filter": {"bool": {"should": source_filter, "minimum_should_match": 1}},
            }
    resp = es.search(index=ES_INDEX, body=body)
    return len(resp["hits"]["hits"])


def eval_recall():
    print("=" * 100)
    print("跨语言召回验证（finance_kb 真实语料，生产查询逻辑）：BM25-only vs Hybrid")
    print("=" * 100)
    print(f'{"query":28s} | {"预期来源":32s} | BM25 命中 | hybrid 命中')
    print("-" * 100)

    bm25_hit = hybrid_hit = 0
    n = len(RECALL_QUERIES)
    for q, expect_source in RECALL_QUERIES:
        n1 = _search(q, use_knn=False)
        n2 = _search(q, use_knn=True)
        bm25_hit += n1 > 0
        hybrid_hit += n2 > 0
        print(f"{q:28s} | {expect_source:32s} | {n1:^9d} | {n2:^11d}")

    print("-" * 100)
    print(
        f"中文口语化 query 有效召回率: "
        f"BM25-only {bm25_hit}/{n} = {bm25_hit * 100 // n}%  |  "
        f"hybrid {hybrid_hit}/{n} = {hybrid_hit * 100 // n}%"
    )
    print()
    print("口径说明：命中 = size=20 结果集非空（二元口径，未判断内容相关性）。")
    return bm25_hit, hybrid_hit, n


if __name__ == "__main__":
    eval_recall()

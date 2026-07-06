"""
精排（qwen3-vl-rerank）质量验证：rerank 前 vs rerank 后，"含正确答案的 chunk"
排名有没有变好。

背景：eval/report.md 第 1 节「RAG 检索准确率 14/14」和 eval/recall_validation.py
都不能回答"精排本身有没有起作用"这个问题——前者混杂了 Plan 工具选择 + 检索 +
LLM 归纳三层因素，后者压根不调用 `_rerank_candidates()`。本脚本单独隔离精排这
一步：对同一批候选 chunk，分别看 rerank 前（ES BM25+kNN 融合分数排序）和
rerank 后（qwen3-vl-rerank 排序）中，"含标准答案关键词的 chunk"排在第几位。

复用 backend/app/service/agent/agent.py 的生产代码：
- 候选召回：_strip_filler_words / _scope_should_clauses / _embed_query / ES_INDEX /
  _KNN_BOOST（与 rag_search() 的 BM25+kNN 部分完全一致）
- 精排：_rerank_candidates()（真实调用 qwen3-vl-rerank，非 mock）

判定口径：候选 chunk 的 content_with_weight 中出现 eval/dataset.py 里任一
expect_any 关键词（大小写不敏感）即视为"相关 chunk"。取第一个相关 chunk的排名
（1-indexed）计算 MRR；同时统计 Recall@5（是否排进生产环境实际截断的 top 5）。
排除 dataset.py 中标注 known_limitation 的题目（rag-11，与 RAG 准确率评测口径
一致）。

用法（仓库根目录下）：
    python eval/rerank_validation.py
依赖：ES（finance_kb）需已起；.env 提供 DASHSCOPE 配置（会真实调用 embedding +
rerank API，产生少量调用费用）。只读，不写库/写 ES。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_APP = os.path.normpath(os.path.join(_HERE, "..", "backend", "app"))
if _BACKEND_APP not in sys.path:
    sys.path.insert(0, _BACKEND_APP)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from service.agent.agent import (  # noqa: E402
    _strip_filler_words,
    _scope_should_clauses,
    _embed_query,
    _rerank_candidates,
    _get_es,
    ES_INDEX,
    _KNN_BOOST,
)
from dataset import RAG_QA  # noqa: E402

_SESSION_ID = "rerank-validation"
_CANDIDATE_POOL_SIZE = 20  # 与 rag_search() 生产代码一致（size=20，之后精排+top5 截断）
_TOP_K = 5  # 生产环境 _apply_upload_boost() 最终截断的窗口


def _fetch_candidates(query: str) -> list[dict]:
    """复刻 rag_search() 的 BM25+kNN 融合召回（不含 rerank/boost），返回按 ES
    融合分数排序的候选列表。"""
    es = _get_es()
    source_filter = _scope_should_clauses(_SESSION_ID)
    bm25_query = {
        "bool": {
            "must": {"match": {"content_ltks": _strip_filler_words(query)}},
            "should": source_filter,
            "minimum_should_match": 1,
        }
    }
    body: dict = {"query": bm25_query, "size": _CANDIDATE_POOL_SIZE}
    q_vec = _embed_query(query)
    if q_vec is not None:
        body["knn"] = {
            "field": "q_1024_vec",
            "query_vector": q_vec,
            "k": _CANDIDATE_POOL_SIZE,
            "num_candidates": 100,
            "boost": _KNN_BOOST,
            "filter": {"bool": {"should": source_filter, "minimum_should_match": 1}},
        }
    resp = es.search(index=ES_INDEX, body=body)
    results = []
    for i, hit in enumerate(resp["hits"]["hits"], 1):
        src = hit["_source"]
        results.append({
            "id": i,
            "document_name": src.get("docnm_kwd", ""),
            "source": src.get("source_kwd", ""),
            "content_with_weight": src.get("content_with_weight", ""),
            "_score": hit["_score"],
        })
    return results


def _first_relevant_rank(candidates: list[dict], expect_any: list[str]) -> int | None:
    """候选列表中第一个"含任一标准答案关键词"的位置（1-indexed），找不到则 None。"""
    needles = [kw.lower() for kw in expect_any]
    for rank, c in enumerate(candidates, 1):
        haystack = c.get("content_with_weight", "").lower()
        if any(kw in haystack for kw in needles):
            return rank
    return None


def eval_rerank():
    cases = [q for q in RAG_QA if "known_limitation" not in q]

    print("=" * 100)
    print(f"精排质量验证（finance_kb 真实语料，qwen3-vl-rerank 真实调用，N={len(cases)}）")
    print("=" * 100)
    print(f'{"id":8s} | {"question":30s} | rerank 前排名 | rerank 后排名 | top5 前→后')
    print("-" * 100)

    pre_ranks, post_ranks = [], []
    pre_top5 = post_top5 = 0

    for case in cases:
        candidates = _fetch_candidates(case["question"])
        pre_rank = _first_relevant_rank(candidates, case["expect_any"])

        # _rerank_candidates 会就地修改 candidates 内每个 dict 的 _score；
        # pre_rank 已经算完，不受影响。
        reranked = _rerank_candidates(case["question"], candidates)
        post_rank = _first_relevant_rank(reranked, case["expect_any"])

        pre_ranks.append(pre_rank)
        post_ranks.append(post_rank)
        pre_hit5 = pre_rank is not None and pre_rank <= _TOP_K
        post_hit5 = post_rank is not None and post_rank <= _TOP_K
        pre_top5 += pre_hit5
        post_top5 += post_hit5

        pre_s = str(pre_rank) if pre_rank else "未命中"
        post_s = str(post_rank) if post_rank else "未命中"
        arrow = f"{'✓' if pre_hit5 else '✗'} → {'✓' if post_hit5 else '✗'}"
        print(f'{case["id"]:8s} | {case["question"]:30s} | {pre_s:^12s} | {post_s:^12s} | {arrow}')

    print("-" * 100)
    n = len(cases)

    def mrr(ranks):
        return sum(1 / r if r else 0 for r in ranks) / len(ranks)

    print(f"MRR：rerank 前 {mrr(pre_ranks):.3f}  →  rerank 后 {mrr(post_ranks):.3f}")
    print(f"Recall@{_TOP_K}：rerank 前 {pre_top5}/{n} = {pre_top5*100//n}%  →  "
          f"rerank 后 {post_top5}/{n} = {post_top5*100//n}%")
    print()
    print("口径说明：'相关'= chunk 的 content_with_weight 含 dataset.py 中任一 expect_any")
    print("关键词（大小写不敏感）；取第一个相关 chunk 的排名。rag-11（已知测试设计缺陷）已排除。")
    return pre_ranks, post_ranks


if __name__ == "__main__":
    eval_rerank()

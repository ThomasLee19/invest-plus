"""
Invest+ 量化指标评测脚本（手动运行，非 CI 自动化用例，与 test_e2e_finance.py 的
"真实存活栈冒烟测试"约定一致）。

前提：本机已启动一个真实运行的后端：
    cd backend/app && PYTHONPATH=. uvicorn app_main:app --port 8000
且能访问真实的 DashScope LLM / Elasticsearch finance_kb 索引（yfinance 是否可用
不影响本脚本的评测结论——见下方"工具路由"部分的说明）。

用法：
    python eval/run_eval.py

产出：
    eval/results.json  —— 每一题的原始请求/响应记录
    eval/report.md      —— 聚合后的量化指标报告（README/简历素材）
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from dataset import RAG_QA, TOOL_ROUTING, ROBUSTNESS_CASES  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
_TOOL_CALL_RE = re.compile(r"(?:正在调用|补充调用) (\w+):")


def create_session(retries: int = 2) -> str:
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(f"{BASE_URL}/create_session", timeout=30)
            resp.raise_for_status()
            return resp.json()["session_id"]
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"create_session failed after {retries + 1} attempts: {last_err}")


def chat_stream(session_id: str, message: str, per_chunk_timeout: int = 150, wall_clock_cap: int = 280) -> dict:
    """POST /chat，流式消费 SSE，返回本次调用的完整记录（含延迟、工具调用、最终答案）。

    单次评测跑几十道题，任何一次网络抖动/单条 SSE 事件间隔过长都不应该让整个批次
    崩溃——这里用 try/except 兜底并附加一个总墙钟上限，异常/超时时返回一条标记为
    失败的记录（status_code=None），由上层统计逻辑当作"未命中/不通过"处理，不中断
    后续题目。
    """
    t0 = time.monotonic()
    t_first = None            # 第一条 SSE：受理回执，恒为常数，不度量 agent 行为
    t_first_tool = None       # 第一条工具事件：首个实质判断
    t_first_answer = None     # 回答的第一个 token
    tool_calls = []           # 仅工具名，保持既有下游契约
    tool_events = []          # 结构化：{tool, query, round}
    answer_parts = []
    thinking_chars = 0        # reasoning_content 的字符量（token 的代理量）
    ended_cleanly = False

    try:
        resp = requests.post(
            f"{BASE_URL}/chat",
            params={"session_id": session_id},
            json={"message": message},
            stream=True,
            timeout=per_chunk_timeout,
        )
        status_code = resp.status_code
        if status_code != 200:
            return {
                "status_code": status_code,
                "ttft": None,
                "total_latency": None,
                "tool_calls": [],
                "answer": "",
                "ended_cleanly": False,
                "raw_detail": resp.text[:500],
            }

        for line in resp.iter_lines(decode_unicode=True):
            if time.monotonic() - t0 > wall_clock_cap:
                break
            if not line or not line.startswith("data: "):
                continue
            if t_first is None:
                t_first = time.monotonic()
            payload = line[len("data: "):]
            if payload == "[DONE]":
                ended_cleanly = True
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if data.get("event_type") == "tool_call":
                # 结构化字段，不再正则匹配中文 UI 文案
                if t_first_tool is None:
                    t_first_tool = time.monotonic()
                tool_events.append({"tool": data.get("tool"), "query": data.get("query"),
                                    "round": data.get("round")})
                if data.get("tool") != "load_sop":
                    tool_calls.append(data.get("tool"))
            elif data.get("role") == "agent":
                # 兼容旧格式（后端未升级时仍能跑）
                m = _TOOL_CALL_RE.search(data.get("content", ""))
                if m:
                    if t_first_tool is None:
                        t_first_tool = time.monotonic()
                    tool_calls.append(m.group(1))
            elif data.get("role") == "assistant":
                if data.get("thinking") is True:
                    thinking_chars += len(data.get("content", "") or "")
                elif data.get("thinking") is False:
                    if t_first_answer is None:
                        t_first_answer = time.monotonic()
                    answer_parts.append(data.get("content", ""))

        t_end = time.monotonic()
        return {
            "status_code": status_code,
            # ack_latency 取代旧的 ttft：它量的就是受理回执，命名如实。旧名保留一轮
            # 供对照脚本过渡。
            "ack_latency": (t_first - t0) if t_first else None,
            "ttft": (t_first - t0) if t_first else None,
            "first_judgement_latency": (t_first_tool - t0) if t_first_tool else None,
            "first_answer_token_latency": (t_first_answer - t0) if t_first_answer else None,
            "total_latency": t_end - t0,
            "tool_calls": tool_calls,
            "tool_events": tool_events,
            "thinking_chars": thinking_chars,
            "answer": "".join(answer_parts),
            "ended_cleanly": ended_cleanly,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status_code": None,
            "ttft": None,
            "total_latency": time.monotonic() - t0,
            "tool_calls": tool_calls,
            "answer": "".join(answer_parts),
            "ended_cleanly": False,
            "raw_detail": f"request error: {e}",
        }


def _normalize(text: str) -> str:
    """去除空白字符再转小写：模型偶尔会在数字和中文单位之间插入空格
    （如"370 亿"而非"370亿"），逐字符子串匹配应当忽略这种排版差异。"""
    return re.sub(r"\s+", "", text).lower()


def run_rag_qa():
    print(f"\n=== RAG 检索准确率（{len(RAG_QA)} 题）===")
    results = []
    for item in RAG_QA:
        session_id = create_session()
        record = chat_stream(session_id, item["question"])
        answer_norm = _normalize(record["answer"])
        hit = any(_normalize(kw) in answer_norm for kw in item["expect_any"])
        results.append({**item, **record, "hit": hit})
        print(f"[{item['id']}] {'✓' if hit else '✗'} {item['question'][:30]}")
        time.sleep(2)
    return results


def run_tool_routing(samples: int = 1):
    """每题跑 `samples` 次。

    为什么需要重复采样：n=17、每题一次时，1-3 道题的翻转就能让准确率动 6-18 个百分点，
    而模型本身是随机的。实测同一份代码前后两轮之间有 6 道题在两个方向上翻转，净变化
    却只有 2 道——那是噪声地板，不是信号。单次采样下"提升了两道题"这句话没有意义。
    多次采样后每题给出命中率而非布尔值，才能把稳定失败与偶发翻转分开。
    """
    print(f"\n=== Agent 工具路由准确率（{len(TOOL_ROUTING)} 题 × {samples} 次）===")
    results = []
    for item in TOOL_ROUTING:
        expected = item["expect_tools"]
        runs = []
        for _ in range(samples):
            record = chat_stream(create_session(), item["question"])
            actual = set(record["tool_calls"])
            ok = expected.issubset(actual) if item["category"] == "compound" else actual == expected
            runs.append({**record, "actual_tools": sorted(actual), "correct": ok})
            time.sleep(2)
        n_ok = sum(1 for r in runs if r["correct"])
        rate = n_ok / len(runs)
        # 代表性样本取第一次，保持既有下游字段（answer/latency 等）可用
        first = runs[0]
        results.append({**item, **first, "runs": runs,
                        "hit_rate": rate, "n_samples": len(runs),
                        "stable": n_ok in (0, len(runs))})
        mark = "✓" if rate == 1 else ("✗" if rate == 0 else "~")
        extra = "" if samples == 1 else f"  命中 {n_ok}/{samples}"
        print(f"[{item['id']}] {mark} ({item['category']}) 期望={sorted(expected)}"
              f" 实际={first['actual_tools']}{extra}")
    return results


def run_robustness():
    print(f"\n=== 边界输入鲁棒性（{len(ROBUSTNESS_CASES)} 题）===")
    results = []
    for item in ROBUSTNESS_CASES:
        if item["kind"] == "nonexistent_session_chat":
            record = chat_stream("zzzzzzzzzzzzzzzz", item["question"])
            # 优雅 = 状态码正确（404）且响应体是预期的通用提示，不是原始异常/堆栈；
            # 之前误把 JSON 里必然出现的 "detail" 键名当成"泄露"的判据，是本脚本的
            # bug（H3 修复后的正确响应本来就是 {"detail": "session not found"}）。
            graceful = record["status_code"] == 404 and "traceback" not in record.get("raw_detail", "").lower()
        else:
            session_id = create_session()
            record = chat_stream(session_id, item["question"])
            if item["kind"] in ("empty_message", "overlong_message"):
                graceful = record["status_code"] == 422
            else:
                graceful = record["status_code"] == 200 and record["ended_cleanly"]
        results.append({**item, **record, "graceful": graceful})
        print(f"[{item['id']}] {'✓' if graceful else '✗'} ({item['kind']})")
    return results


def compute_latency_stats(rag_results, routing_results):
    """把延迟拆成四个各自有明确含义的时刻，外加思考量。

    旧版只有一个 ttft，且它量的是第一条 SSE 事件——自 `448b831` 起那恒为受理回执，
    一个与模型、检索、工具全都无关的常数。真正有意义的「首个实质判断」（到第一条
    工具事件为止）此前从未被采集。
    """
    rows = [r for r in (rag_results + routing_results) if r.get("total_latency") is not None]
    if not rows:
        return None

    def pct(vals, p):
        vals = sorted(vals)
        return vals[min(len(vals) - 1, int(len(vals) * p))]

    def summarize(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        if not v:
            return None
        return {"n": len(v), "mean": statistics.mean(v), "p50": pct(v, 0.5), "p90": pct(v, 0.9)}

    think = [r["thinking_chars"] for r in rows if r.get("thinking_chars") is not None]
    visible = [len(r["answer"]) for r in rows if r.get("answer")]
    return {
        "n": len(rows),
        "ack": summarize("ack_latency"),
        "first_judgement": summarize("first_judgement_latency"),
        "first_answer_token": summarize("first_answer_token_latency"),
        "total": summarize("total_latency"),
        "thinking_chars": {"mean": statistics.mean(think), "p50": pct(think, 0.5),
                           "p90": pct(think, 0.9)} if think else None,
        "visible_chars": {"mean": statistics.mean(visible), "p50": pct(visible, 0.5),
                          "p90": pct(visible, 0.9)} if visible else None,
        # 旧字段保留一轮，供尚未迁移的对照脚本读取
        "ttft_mean": statistics.mean([r["ttft"] for r in rows if r.get("ttft") is not None] or [0]),
        "total_mean": statistics.mean([r["total_latency"] for r in rows]),
        "total_p50": pct([r["total_latency"] for r in rows], 0.5),
        "total_p90": pct([r["total_latency"] for r in rows], 0.9),
    }


def write_report(rag_results, routing_results, robustness_results, latency_stats):
    rag_hits = sum(1 for r in rag_results if r["hit"])
    routing_hits = sum(1 for r in routing_results if r["correct"])
    robust_hits = sum(1 for r in robustness_results if r["graceful"])

    lines = []
    lines.append("# Invest+ 量化评测报告\n")
    lines.append(
        "评测对象：本机真实运行的前后端服务（走真实 agent/RAG/Elasticsearch 逻辑，非 mock）。\n"
    )
    lines.append(
        "语料真实性声明：`data/` 下的财报/新闻语料为项目自带测试数据，内容可能由 AI 生成、"
        "日期为未来虚构日期；RAG 准确率衡量的是回答对语料的忠实度，不代表对真实世界财务数据的验证。\n"
    )

    lines.append("\n## 1. RAG 检索准确率\n")
    lines.append(f"**{rag_hits}/{len(rag_results)} = {rag_hits/len(rag_results)*100:.1f}%**\n")
    lines.append("| 题目 | 来源 | 结果 |")
    lines.append("| --- | --- | --- |")
    for r in rag_results:
        lines.append(f"| {r['question']} | {r['source']} | {'✓' if r['hit'] else '✗'} |")

    lines.append("\n## 2. Agent 工具路由准确率\n")
    lines.append(f"**{routing_hits}/{len(routing_results)} = {routing_hits/len(routing_results)*100:.1f}%**\n")
    by_cat = {}
    for r in routing_results:
        by_cat.setdefault(r["category"], []).append(r["correct"])
    lines.append("| 类别 | 准确率 |")
    lines.append("| --- | --- |")
    for cat, hits in by_cat.items():
        lines.append(f"| {cat} | {sum(hits)}/{len(hits)} = {sum(hits)/len(hits)*100:.0f}% |")
    lines.append("\n| 题目 | 类别 | 期望工具 | 实际工具 | 结果 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in routing_results:
        lines.append(
            f"| {r['question']} | {r['category']} | {sorted(r['expect_tools'])} "
            f"| {r['actual_tools']} | {'✓' if r['correct'] else '✗'} |"
        )

    def fmt(v):
        return f"{v:.2f}s" if v is not None else "N/A"

    lines.append("\n## 3. 响应延迟\n")
    if latency_stats:
        lines.append(f"基于 {latency_stats['n']} 次真实流式请求（total_latency 有值的样本；"
                      f"TTFT 样本数可能更少，见下方 N/A 说明）：\n")
        lines.append("| 指标 | 均值 | p50 | p90 |")
        lines.append("| --- | --- | --- | --- |")
        lines.append(
            f"| 首字延迟 (TTFT) | {fmt(latency_stats['ttft_mean'])} "
            f"| {fmt(latency_stats['ttft_p50'])} | {fmt(latency_stats['ttft_p90'])} |"
        )
        lines.append(
            f"| 完整响应延迟 | {fmt(latency_stats['total_mean'])} "
            f"| {fmt(latency_stats['total_p50'])} | {fmt(latency_stats['total_p90'])} |"
        )
    else:
        lines.append("无有效延迟样本。\n")

    lines.append("\n## 4. 边界输入鲁棒性\n")
    lines.append(f"**{robust_hits}/{len(robustness_results)} = {robust_hits/len(robustness_results)*100:.1f}%**\n")
    lines.append("| 场景 | 结果 |")
    lines.append("| --- | --- |")
    for r in robustness_results:
        lines.append(f"| {r['kind']} | {'✓' if r['graceful'] else '✗'} |")

    report_path = Path(__file__).parent / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入 {report_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routing-samples", type=int, default=1,
                    help="路由每题重复采样次数（默认 1）。n=17 单次采样分辨不了个位数"
                         "题目的差异，做前后对照时建议 ≥3。")
    args = ap.parse_args()

    rag_results = run_rag_qa()
    routing_results = run_tool_routing(samples=args.routing_samples)
    robustness_results = run_robustness()
    latency_stats = compute_latency_stats(rag_results, routing_results)

    results_path = Path(__file__).parent / "results.json"
    results_path.write_text(
        json.dumps(
            {
                "rag_qa": [{k: v for k, v in r.items() if k != "expect_tools"} for r in rag_results],
                "tool_routing": [
                    {**{k: v for k, v in r.items() if k != "expect_tools"}, "expect_tools": sorted(r["expect_tools"])}
                    for r in routing_results
                ],
                "robustness": robustness_results,
                "latency_stats": latency_stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_report(rag_results, routing_results, robustness_results, latency_stats)


if __name__ == "__main__":
    main()

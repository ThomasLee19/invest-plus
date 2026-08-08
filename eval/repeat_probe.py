"""重复触发探针 —— 承重论断的验证脚本。

## 它要回答什么

增量二删掉了 `seen_actions` / `seen_prompts` 两层去重。删掉的理由是一条可证伪的论断：

> 工具重复触发的根因是把轨迹序列化成了文本；轨迹化之后，模型每轮都能直接看见自己
> 已经问过什么、拿到了什么，因此不再需要外部去重也不会重复触发。

## 为什么不能用 run_eval.py 来验

因为它没有测量效力。实测增量一那轮 37 道题：

    每请求的 reflect 轮数分布: {0: 9, 1: 28}
    进入过第二轮 reflect 的请求: 0 条

循环一次都没迭代过。一个请求至多问一轮就收尾，重复在结构上不可能发生，所以"没测到
重复"这件事完全不构成证据——它对论断的真假没有任何区分能力。同理，增量一那轮日志里
去重拦截触发 0 次，也不能拿来说明"增量一就已经解决了重复"。

## 这个脚本怎么做

改用会把循环压深的问题（多面向分析、跨公司对比），直接从 SSE 流里抽出每一次
`正在调用 {tool}: "{query}"` 与 `补充调用 {tool}: "{query}"`，按请求分组统计重复。
不解析后端日志，因此不需要等日志静默、也不存在按字节偏移归属的误差。

判定口径分两级：
  - 严格重复：同一请求内 (工具, 查询) 完全相同出现两次以上。
  - 近似重复：查询规范化（去空白/标点/大小写）后相同。近似重复同样构成"白跑一趟"，
    只是旧的 seen_prompts 按精确匹配去重，本来也拦不住它。

用法：
    python eval/repeat_probe.py --label after-increment-2
"""
import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import requests

# 会把决策循环压深的问题。挑选标准是"一次取数答不完"：需要多个面向、或需要跨主体对比。
# 前两道沿用 cache_probe.py 的 X 题及其同族，实测能驱动出 5 轮 reflect、十余次工具调用。
DEFAULT_QUESTIONS = [
    "苹果公司最近的财报里有哪些值得关注的风险因素？",
    "对比一下苹果和微软的估值水平，哪个更贵，为什么？",
    "微软最近有什么重要的业务变动，对它的估值有什么影响？",
    "分析一下 AAPL 现在的基本面，从盈利能力、估值和风险三个方面说",
    "谷歌的云业务和微软云相比表现如何，各自的增长动能在哪里？",
]

_CALL_RE = re.compile(r'(正在调用|补充调用) (\w+): "(.*?)"')


def _normalize(q: str) -> str:
    """规范化查询，用于近似重复判定：去掉空白、标点与大小写差异。"""
    q = unicodedata.normalize("NFKC", q).lower()
    return re.sub(r"[\s\W_]+", "", q)


def fire(base: str, question: str, read_timeout: int) -> dict:
    """发一题，完整消费 SSE 流，返回本次请求抽到的调用序列。"""
    sid = requests.post(f"{base}/create_session", timeout=30).json().get("session_id")
    t0 = time.time()
    calls: list[tuple[str, str, str]] = []
    events = 0
    degraded = False

    r = requests.post(
        f"{base}/chat", params={"session_id": sid}, json={"message": question},
        stream=True, timeout=(10, read_timeout),
    )
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        events += 1
        payload = line[6:].strip()
        if payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        content = data.get("content", "") or ""
        if data.get("role") == "agent":
            m = _CALL_RE.search(content)
            if m:
                calls.append((m.group(1), m.group(2), m.group(3)))
        if "生成回答时发生错误" in content:
            degraded = True

    return {
        "question": question,
        "session_id": sid,
        "elapsed": round(time.time() - t0, 2),
        "events": events,
        "degraded": degraded,
        "calls": calls,
    }


def analyse(record: dict) -> dict:
    calls = record["calls"]
    exact = Counter((t, q) for _, t, q in calls)
    approx = Counter((t, _normalize(q)) for _, t, q in calls)
    # 「补充调用」的条数 = 循环在首轮之后又迭代了几次取数。首轮全是「正在调用」。
    followups = sum(1 for kind, _, _ in calls if kind == "补充调用")
    return {
        **record,
        "n_calls": len(calls),
        "n_followup_calls": followups,
        "exact_repeats": sum(v - 1 for v in exact.values() if v > 1),
        "approx_repeats": sum(v - 1 for v in approx.values() if v > 1),
        "repeated_pairs": [f"{t}: {q}" for (t, q), v in exact.items() if v > 1],
    }


def render(results: list[dict], label: str) -> str:
    L: list[str] = []
    L.append(f"# 重复触发探针 — {label}\n")
    L.append(f"运行于 {time.strftime('%Y-%m-%d %H:%M:%S')}｜{len(results)} 题，每题一次\n")
    L.append("验证对象：增量二删除 `seen_actions` / `seen_prompts` 之后，"
             "工具重复触发是否复现。\n")

    total_calls = sum(r["n_calls"] for r in results)
    total_follow = sum(r["n_followup_calls"] for r in results)
    total_exact = sum(r["exact_repeats"] for r in results)
    total_approx = sum(r["approx_repeats"] for r in results)
    deep = [r for r in results if r["n_followup_calls"] > 0]

    L.append("\n## 测量效力自检\n")
    L.append("先确认循环真的迭代了。若补充调用为 0，则本轮数据对论断无区分能力，"
             "结论一栏必须写「未测到」而不是「未复现」。\n")
    L.append(f"- 进入过补充轮的请求：**{len(deep)}/{len(results)}**")
    L.append(f"- 补充调用总数：**{total_follow}**")
    L.append(f"- 工具调用总数：{total_calls}"
             f"（每请求均值 {total_calls / max(len(results), 1):.1f}）\n")

    L.append("\n## 重复统计\n")
    L.append("| 题目 | 工具调用 | 其中补充轮 | 严格重复 | 近似重复 | 耗时 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        L.append(f"| {r['question'][:26]} | {r['n_calls']} | {r['n_followup_calls']} "
                 f"| {r['exact_repeats']} | {r['approx_repeats']} | {r['elapsed']}s |")
    L.append(f"\n合计：严格重复 **{total_exact}**，近似重复 **{total_approx}**。\n")

    repeated = [p for r in results for p in r["repeated_pairs"]]
    if repeated:
        L.append("\n### 重复的具体调用\n")
        for p in repeated:
            L.append(f"- `{p}`")
        L.append("")

    L.append("\n## 判定\n")
    if not deep:
        L.append("**未测到。** 没有任何请求进入补充轮，重复在结构上无从发生，"
                 "本轮数据对论断既不支持也不反驳。需要换更能压深循环的题目重测。")
    elif total_exact == 0 and total_approx == 0:
        L.append(f"**未复现。** 在 {total_follow} 次补充调用中没有出现任何重复，"
                 "论断在本样本内成立。样本量仍小，且这是模型行为而非确定性属性，"
                 "结论应随后续每轮评测复核。")
    else:
        L.append(f"**已复现。** 出现严格重复 {total_exact} 次、近似重复 {total_approx} 次。"
                 "论断被证伪：轨迹化并未消除重复触发，根因判断有误，"
                 "对外叙事需据此推翻重写，去重逻辑是否要回补另行决定。")

    if any(r["degraded"] for r in results):
        L.append("\n> 注意：有请求出现降级错误，该行数据应排除后重跑。")
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--label", required=True, help="本轮的标识，写进报告标题")
    p.add_argument("--read-timeout", type=int, default=300)
    p.add_argument("--questions", nargs="*", default=None)
    args = p.parse_args()

    questions = args.questions or DEFAULT_QUESTIONS
    try:
        requests.get(f"{args.base}/health", timeout=5).raise_for_status()
    except Exception as e:
        raise SystemExit(f"后端不可用（{args.base}）：{e}")

    results = []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q}", flush=True)
        rec = analyse(fire(args.base, q, args.read_timeout))
        print(f"    调用 {rec['n_calls']} 次（补充 {rec['n_followup_calls']}），"
              f"严格重复 {rec['exact_repeats']}，耗时 {rec['elapsed']}s", flush=True)
        results.append(rec)

    out_md = Path(__file__).parent / f"repeat_probe_{args.label}.md"
    out_json = Path(__file__).parent / f"repeat_probe_{args.label}.json"
    out_md.write_text(render(results, args.label), encoding="utf-8")
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {out_md}")


if __name__ == "__main__":
    main()

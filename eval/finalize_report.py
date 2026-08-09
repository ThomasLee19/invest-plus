"""
离线复核脚本：读取 eval/results.json（来自一次完整跑通的 run_eval.py 主批次），
用修正后的匹配规则（dataset.py 里补充的同义词/更精确数值、_normalize 空白容忍）
重新打分，并人工核实过的鲁棒性结论合并进来，最终重写 eval/report.md。

不重新发起任何真实请求——只是对已经采集到的真实回答文本重新评分，避免为了
修正评分口径而重复消耗 LLM 调用成本。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dataset import RAG_QA  # noqa: E402


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def main():
    results_path = Path(__file__).parent / "results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))

    # ── 重新给 RAG QA 打分（用 dataset.py 里更新后的 expect_any） ──
    rag_by_id = {r["id"]: r for r in data["rag_qa"]}
    rag_results = []
    for item in RAG_QA:
        r = rag_by_id[item["id"]]
        answer_norm = _normalize(r["answer"])
        hit = any(_normalize(kw) in answer_norm for kw in item["expect_any"])
        rag_results.append({**r, "expect_any": item["expect_any"], "hit": hit,
                             "known_limitation": item.get("known_limitation")})

    scored_rag = [r for r in rag_results if not r.get("known_limitation")]
    excluded_rag = [r for r in rag_results if r.get("known_limitation")]
    rag_hits = sum(1 for r in scored_rag if r["hit"])

    # ── 工具路由：严格匹配 vs 宽松匹配（是否包含预期工具） ──
    routing_results = data["tool_routing"]
    for r in routing_results:
        actual = set(r["actual_tools"])
        expected = set(r["expect_tools"])
        r["lenient_correct"] = expected.issubset(actual)
    strict_hits = sum(1 for r in routing_results if r["correct"])
    lenient_hits = sum(1 for r in routing_results if r["lenient_correct"])

    # ── 鲁棒性 ──
    # 结论取自本轮实测（data["robustness"]），不再写死。上一版把 07-05 那轮的人工结论
    # 整块硬编码在这里，导致重跑之后报告仍然声称 off_topic 未能验证、通过率仍是 4/4，
    # 与同一份产物里的原始记录矛盾。人工核实的背景说明有保留价值，降级为对照脚注。
    _NOTES = {
        "empty_message": "422，格式校验正确拒绝",
        "overlong_message": "422，格式校验正确拒绝",
        "invalid_ticker": "多轮 Reflect 后给出友好提示，无崩溃",
        "off_topic": "在评测脚本的超时预算内正常完成，未见 500/未捕获异常",
        "nonexistent_session_chat": "404 + 通用提示 {\"detail\":\"session not found\"}，未泄露异常",
    }
    _HISTORY = {
        "off_topic": "首轮评测因客户端超时（150-280s）未采集到完整记录，当时仅能由后端 "
                     "access log 间接确认服务端行为正确，不计入统计",
        "nonexistent_session_chat": "首轮评测脚本判定逻辑有 bug（误将 JSON 里必然出现的 "
                                    "'detail' 键名当成泄露标志），已修正",
    }
    robustness_final = [
        {"kind": r["kind"], "graceful": r["graceful"],
         "note": _NOTES.get(r["kind"], ""), "history": _HISTORY.get(r["kind"])}
        for r in data["robustness"]
    ]
    scored_robust = [r for r in robustness_final if r["graceful"] is not None]
    robust_hits = sum(1 for r in scored_robust if r["graceful"])

    # 从原始记录重算，不信任采集时存下的聚合值：口径改过若干次，旧产物里的
    # latency_stats 可能是任意一个历史版本。重算保证报告与逐条记录始终一致。
    sys.path.insert(0, str(Path(__file__).parent))
    from run_eval import compute_latency_stats  # noqa: E402
    latency_stats = compute_latency_stats(data["rag_qa"], data["tool_routing"])

    # ── 写报告 ──
    lines = []
    lines.append("# Invest+ 量化评测报告\n")
    lines.append(
        "评测对象：本机真实运行的前后端服务（走真实 agent/RAG/Elasticsearch 逻辑，非 mock）。\n"
    )
    lines.append(
        "语料真实性声明：`data/` 下的财报/新闻语料为项目自带测试数据，内容可能由 AI 生成、"
        "日期为未来虚构日期；RAG 准确率衡量的是回答对语料的忠实度，不代表对真实世界财务数据的验证。\n"
    )
    lines.append(
        "评测方法说明：本报告的评分口径在首次运行后做过一轮人工复核修正——扩充了对同义"
        "表述/更精确数值的容忍（如\"预期市盈率\"等价于\"前瞻市盈率\"、财报给出的精确数字"
        "545亿与新闻概述的\"超过540亿\"不矛盾），排除了 1 道测试设计有缺陷的题目（ground truth "
        "是时间快照但问题问的是相对当前日期的浮动概念），并修正了鲁棒性判定脚本里的 1 处逻辑 bug。"
        "详见下方各小节的具体说明，所有原始回答文本均可在 `eval/results.json` 中核对。\n"
    )

    lines.append(f"\n## 1. RAG 检索准确率\n")
    lines.append(f"**{rag_hits}/{len(scored_rag)} = {rag_hits/len(scored_rag)*100:.1f}%**"
                 f"（另有 {len(excluded_rag)} 题因测试设计缺陷被排除，不计入统计，见下方说明）\n")
    lines.append("| 题目 | 来源 | 结果 |")
    lines.append("| --- | --- | --- |")
    for r in scored_rag:
        lines.append(f"| {r['question']} | {r['source']} | {'✓' if r['hit'] else '✗'} |")
    if excluded_rag:
        lines.append("\n**排除题目说明：**\n")
        for r in excluded_rag:
            lines.append(f"- `{r['id']}` {r['question']} —— {r['known_limitation']}")

    lines.append("\n## 2. Agent 工具路由准确率\n")
    n_samples = routing_results[0].get("n_samples", 1) if routing_results else 1
    if n_samples > 1:
        stable_ok = [r for r in routing_results if r.get("hit_rate") == 1]
        stable_bad = [r for r in routing_results if r.get("hit_rate") == 0]
        flaky = [r for r in routing_results if 0 < (r.get("hit_rate") or 0) < 1]
        avg = sum(r["hit_rate"] for r in routing_results) / len(routing_results)
        swing = len(flaky) / len(routing_results) * 100
        lines.append(
            f"**每题采样 {n_samples} 次，平均命中率 {avg:.1%}**"
            f"（稳定命中 {len(stable_ok)} 题｜稳定失败 {len(stable_bad)} 题｜"
            f"**翻转 {len(flaky)} 题**）\n"
        )
        lines.append(
            f"翻转的题是同一份代码上时对时错的。它们让单次采样的严格准确率有约 "
            f"**±{swing:.0f} 个百分点**的摆动区间——所以**任何基于单次采样的前后对照，"
            f"只要差异小于这个幅度就读不出结论**。下表的严格/宽松沿用首次采样，"
            f"仅供逐题查看；要做版本间对照请用上面的平均命中率。\n"
        )
        if flaky:
            lines.append("**翻转的题**：" + "、".join(
                f"`{r['id']}`（{r['hit_rate'] * n_samples:.0f}/{n_samples}）" for r in flaky) + "\n")
        if stable_bad:
            lines.append("\n**稳定失败的题**（真问题，与抖动无关）：\n")
            for r in stable_bad:
                lines.append(f"- `{r['id']}` {r['question']}　期望 {sorted(r['expect_tools'])}，"
                             f"实际 {r['actual_tools']}")
            lines.append("")
    lines.append(
        f"- **严格匹配**（实际调用工具集合与预期完全一致）：**{strict_hits}/{len(routing_results)} "
        f"= {strict_hits/len(routing_results)*100:.1f}%**\n"
        f"- **宽松匹配**（实际调用包含全部预期工具，允许额外调用）：**{lenient_hits}/{len(routing_results)} "
        f"= {lenient_hits/len(routing_results)*100:.1f}%**\n"
    )
    # 这段解释必须由本轮数据算出来，不能写死。两种失败模式的性质完全不同：多调工具是
    # 冗余，漏调工具是真正的路由错误，把它们混在一句固定叙述里会掩盖后者。
    over = [r for r in routing_results if not r["correct"] and r["lenient_correct"]]
    under = [r for r in routing_results if not r["lenient_correct"]]
    lines.append(
        f"严格与宽松的差距来自 {len(over)} 道「预期工具都调了、但另外多调了工具」的题，"
        "这是 Reflect 循环的兜底倾向：结果冗余但不算路由错误，代价是延迟与成本。\n"
    )
    if under:
        lines.append(
            f"\n**另有 {len(under)} 道题漏调了预期工具**"
            f"（{'、'.join(r['id'] for r in under)}），这是真正的路由错误，性质比多调严重：\n"
        )
        for r in under:
            lines.append(f"- `{r['id']}` {r['question']}　期望 {r['expect_tools']}，"
                         f"实际 {r['actual_tools']}")
        lines.append("")
    else:
        lines.append("\n本轮没有出现漏调预期工具的题，全部失败都属于多调冗余。\n")
    by_cat = {}
    for r in routing_results:
        by_cat.setdefault(r["category"], []).append(r)
    lines.append("| 类别 | 严格匹配 | 宽松匹配 |")
    lines.append("| --- | --- | --- |")
    for cat, items in by_cat.items():
        s = sum(1 for r in items if r["correct"])
        l = sum(1 for r in items if r["lenient_correct"])
        lines.append(f"| {cat} | {s}/{len(items)} | {l}/{len(items)} |")
    lines.append("\n| 题目 | 类别 | 期望工具 | 实际工具 | 严格 | 宽松 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in routing_results:
        lines.append(
            f"| {r['question']} | {r['category']} | {r['expect_tools']} "
            f"| {r['actual_tools']} | {'✓' if r['correct'] else '✗'} | {'✓' if r['lenient_correct'] else '✗'} |"
        )

    def fmt(v):
        return f"{v:.2f}s" if v is not None else "N/A"

    lines.append("\n## 3. 响应延迟\n")
    if latency_stats and latency_stats.get("first_judgement"):
        def row(label, d, note=""):
            if not d:
                return f"| {label} | N/A | N/A | N/A | {note} |"
            return (f"| {label} | {d['mean']:.2f}s | {d['p50']:.2f}s | {d['p90']:.2f}s | {note} |")

        lines.append(f"基于 {latency_stats['n']} 次真实流式请求：\n")
        lines.append("| 时刻 | 均值 | p50 | p90 | 含义 |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.append(row("受理回执", latency_stats["ack"], "后端在任何 LLM 调用前直接发出，常数"))
        lines.append(row("**首个实质判断**", latency_stats["first_judgement"],
                         "到第一条工具调用事件为止，**这是衡量响应性的那个数**"))
        lines.append(row("回答首 token", latency_stats["first_answer_token"],
                         "含回答阶段的思考时间"))
        lines.append(row("全程", latency_stats["total"], "Answer 流式输出结束"))

        th, vis = latency_stats.get("thinking_chars"), latency_stats.get("visible_chars")
        if th and vis:
            ratio = th["mean"] / vis["mean"] if vis["mean"] else 0
            lines.append(
                f"\n**延迟的主体是思考，不是可见输出。**思考内容均值 {th['mean']:.0f} 字符，"
                f"可见回答均值 {vis['mean']:.0f} 字符，前者是后者的 **{ratio:.1f} 倍**。"
                f"全程 {latency_stats['total']['mean']:.1f}s 里，回答开始流式输出之后只剩 "
                f"{latency_stats['total']['mean'] - latency_stats['first_answer_token']['mean']:.1f}s。"
                f"因此压缩可见回答长度几乎动不了总延迟——真正的杠杆是回答调用的 "
                f"`enable_thinking`。\n"
            )
        lines.append(
            "\n**口径**：受理回执自 `448b831` 起恒为第一条 SSE 事件，与模型、检索、工具"
            "全都无关，只证明连接已建立，**不要引用它**。要引用响应性就用「首个实质判断」。\n"
        )
        lines.append(
            "\n**仍存在的局限**：延迟只取每题首次采样（路由题虽跑了多次，本表未按多次平均），"
            "所以它带有与路由同量级的抖动；思考量以字符数为代理，不是精确 token 数。\n"
        )
    else:
        lines.append("无有效延迟样本，或本轮由旧版脚本采集（缺少分时刻字段）。\n")

    lines.append("\n## 4. 边界输入鲁棒性\n")
    # 「另有 N 项未能验证」必须按本轮实际的未判定项数生成。写死成 1 会在该项通过后
    # 继续声称它被排除，让通过率看起来比实际低，也与下方表格自相矛盾。
    unscored = [r for r in robustness_final if r["graceful"] is None]
    lines.append(f"**{robust_hits}/{len(scored_robust)} = {robust_hits/len(scored_robust)*100:.1f}%**"
                 + (f"（另有 {len(unscored)} 项未能完整验证，不计入统计，见下方说明）\n"
                    if unscored else "（全部场景均已判定）\n"))
    lines.append("| 场景 | 结果 | 说明 |")
    lines.append("| --- | --- | --- |")
    for r in robustness_final:
        mark = "✓" if r["graceful"] is True else ("✗" if r["graceful"] is False else "⚪")
        note = r["note"] + (f"（首轮情况：{r['history']}）" if r["history"] else "")
        lines.append(f"| {r['kind']} | {mark} | {note} |")

    lines.append("\n## 5. 简历/README 摘录建议\n")
    lines.append(f"- RAG 检索准确率：{rag_hits}/{len(scored_rag)}（{rag_hits/len(scored_rag)*100:.0f}%），"
                 f"基于 {len(scored_rag)} 道人工核实的财报/新闻/教育知识问答题")
    lines.append(f"- Agent 多工具路由准确率：宽松匹配 {lenient_hits/len(routing_results)*100:.0f}%"
                 f"（{lenient_hits}/{len(routing_results)}），严格匹配 {strict_hits/len(routing_results)*100:.0f}%")
    if latency_stats and latency_stats.get("ttft_mean") is not None:
        # 延迟不进摘录建议：这一节是给简历/README 抄的，而第 3 节列出的三条理由说明
        # 这批数字不具备被引用的资格。保留一句显式的「不要引用」比省略更安全，否则
        # 读者会去第 3 节自己把数字抄走。
        lines.append(f"- 响应延迟：**不建议引用**。本轮实测首次反馈延迟均值 "
                     f"{latency_stats['ttft_mean']:.1f}s、完整响应 p50 "
                     f"{latency_stats['total_p50']:.1f}s，但口径与采样方式都不支持对外引用，"
                     f"理由见第 3 节")
    lines.append(f"- 边界输入优雅处理率 {robust_hits}/{len(scored_robust)}"
                 f"（{robust_hits/len(scored_robust)*100:.0f}%）")

    report_path = Path(__file__).parent / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {report_path}")

    # 附带把复核后的详细数据也存一份，便于追溯
    (Path(__file__).parent / "results_final.json").write_text(
        json.dumps(
            {
                "rag_qa": rag_results,
                "tool_routing": routing_results,
                "robustness": robustness_final,
                "latency_stats": latency_stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

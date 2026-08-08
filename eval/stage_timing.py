"""首次反馈之前各阶段的耗时拆解。

为什么单独一个脚本而不是给 agent.py 加埋点
------------------------------------------
本脚本**不修改任何生产代码**。它在进程内直接调用 `agent.py` 已有的模块级函数，在每一步
前后打点，重现 `final_answer()` 在推出第一条 SSE 事件之前所做的全部工作。所有被调用的
函数都是只读的（DB 查询、文件读取、LLM 调用），不写库、不改状态。

代价是**顺序是复刻出来的**，与 `final_answer()` 的真实顺序存在漂移风险。下面每一步都
标注了它对应的源码行号，改动 agent.py 时应当一并核对：

    agent.py:1332  _detect_language(query)          language == "auto" 时
    agent.py:1335  第一条 yield（受理回执）← 首次反馈发生在这里，不等任何 LLM
    agent.py:1337  _get_llm_client()
    agent.py:1345  recall_all_conclusions(query)
    agent.py:1352  classify_skill(query)            LLM 调用 #1
    agent.py:1355  load_skill(name)                 每个命中的 SOP 一次
    agent.py:1365  build_trajectory(...)            纯字符串拼装，不含 LLM
    agent.py:1382  _llm_decide(messages)            LLM 调用 #2（第 1 轮决策）
    agent.py:1421  「正在调用 …」yield ← 首个实质判断发生在这里

本脚本量的是**首个实质判断**这一刻，不是首次反馈。自 `448b831` 起第一条 SSE 是受理
回执，发生在任何 LLM 调用之前，恒为毫秒级常数，量它没有意义。

增量二把 agent_plan 与 should_continue 合并成了一个决策操作，但**这不会缩短这条路径**：
两者从来不是都在首个判断之前，should_continue 跑在工具执行之后。合并省下的是多轮请求
里的第二份 system prompt 与第二套工具描述，不是这里的往返次数。这条路径上仍然是两次
LLM 调用（classify_skill + 第 1 轮决策），要减少只能砍掉 classify_skill（增量三评估）。

外加 `chat_rt.py` 在进入 `final_answer()` 之前做的：

    chat_rt.py:124 recall_user_profile(USER_ID)

chat_rt 里还有三次内联 SQL（session 存在性校验、历史查询、轮次计数）。它们没有被封装成
可导入的函数，复刻会引入更大的漂移风险，因此本脚本用一次等价的空转 DB 往返来估计这部分
的量级，标注为 db_roundtrip，不声称精确。

不走 HTTP 的取舍
----------------
不经过 uvicorn 与 SSE，所以测出的数字**不含**网络栈、序列化与 Starlette 线程池调度的开销。
换来的是每一步都能干净归属，且不受「提前断连停不掉后端」那类问题干扰。要的是分解比例而
不是绝对值：知道 3 秒里哪一段占大头，才知道该优化谁。

用法
----
    cd backend/app && PYTHONPATH=. python ../../eval/stage_timing.py --repeats 3
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _load_pipeline():
    """导入被测函数。必须在 PYTHONPATH 指向 backend/app 的前提下运行。"""
    try:
        from service.agent.agent import (  # noqa: E402
            _detect_language, _get_llm_client, _llm_decide, _tool_call_fields,
            build_trajectory, classify_skill, load_skill, recall_all_conclusions,
        )
        from service.memory.profile import recall_user_profile  # noqa: E402
        return dict(
            detect_language=_detect_language, get_llm_client=_get_llm_client,
            llm_decide=_llm_decide, tool_call_fields=_tool_call_fields,
            build_trajectory=build_trajectory, classify_skill=classify_skill,
            load_skill=load_skill, recall_all_conclusions=recall_all_conclusions,
            recall_user_profile=recall_user_profile,
        )
    except ImportError as e:
        raise SystemExit(
            f"导入失败：{e}\n"
            f"本脚本需要 PYTHONPATH 指向 backend/app，请按 docstring 里的命令运行。")


# chat_rt.py:34 的常量。写死在这里而不是 import chat_rt，避免把 FastAPI 路由注册和
# 数据库引擎初始化拖进来产生副作用。
USER_ID = "1"


class Stopwatch:
    def __init__(self):
        self.marks: list[tuple[str, float]] = []
        self._t = time.monotonic()

    def lap(self, name: str):
        now = time.monotonic()
        self.marks.append((name, now - self._t))
        self._t = now


def time_one(question: str, fns: dict) -> dict:
    """复刻首次反馈之前的全部工作并逐段计时。顺序与 agent.py 的行号一一对应。"""
    sw = Stopwatch()
    err = None

    # chat_rt.py 在调用 final_answer 之前的 DB 往返（session 校验 / 历史 / 轮次计数）。
    # 用一次画像召回作为等价的空转往返估计量级，不声称精确。
    try:
        fns["recall_user_profile"](USER_ID)
    except Exception as e:
        err = f"recall_user_profile: {e}"
    sw.lap("db_roundtrip+profile")

    fns["get_llm_client"]()
    sw.lap("get_llm_client")

    fns["detect_language"](question)
    sw.lap("detect_language")

    try:
        conclusions = fns["recall_all_conclusions"](question)
    except Exception as e:
        conclusions, err = [], f"{err or ''} recall_all_conclusions: {e}"
    sw.lap("recall_all_conclusions")

    hits = fns["classify_skill"](question)
    sw.lap("classify_skill (LLM #1)")

    sops = []
    for name in hits:
        sop = fns["load_skill"](name)
        if sop and sop.get("body"):
            sops.append(sop)
    sw.lap("load_skill")

    messages = fns["build_trajectory"](question, user_profile=None, skill_sops=sops,
                                       recalled_conclusions=conclusions)
    sw.lap("build_trajectory")

    msg = fns["llm_decide"](messages, stage="plan")
    sw.lap("decide round 1 (LLM #2)")

    actions = [f for f in (fns["tool_call_fields"](tc) for tc in (msg.tool_calls or []))
               if f is not None]
    sw.lap("parse tool_calls")

    return {
        "question": question,
        "stages": dict(sw.marks),
        "total": sum(v for _, v in sw.marks),
        "skill_hits": hits,
        "n_actions": len(actions),
        "tools": sorted({name for name, _ in actions}) if actions else [],
        "error": err,
    }


def build_questions(per_category: int | None):
    from dataset import RAG_QA, TOOL_ROUTING  # noqa: E402
    items = [{"id": q["id"], "question": q["question"], "category": "rag_qa"} for q in RAG_QA]
    items += [{"id": q["id"], "question": q["question"], "category": q.get("category")}
              for q in TOOL_ROUTING]
    if per_category is None:
        return items
    by_cat: dict[str, list] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    out = []
    for cat in sorted(by_cat):
        out.extend(by_cat[cat][:per_category])
    return out


def summarize(vals: list[float]) -> dict:
    v = sorted(vals)
    return {"n": len(v), "mean": statistics.mean(v), "median": statistics.median(v),
            "min": v[0], "max": v[-1]}


def main():
    p = argparse.ArgumentParser(description="首次反馈之前的分阶段耗时拆解")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--per-category", type=int, default=2,
                   help="每个 category 取前 N 道（分层截断）；不传则用全部题目")
    p.add_argument("--out", default=None, help="JSON 产物路径")
    args = p.parse_args()

    fns = _load_pipeline()
    questions = build_questions(args.per_category)
    total = len(questions) * args.repeats
    print(f"题目 {len(questions)} 道 × {args.repeats} 次 = {total} 次，"
          f"每次跑完首次反馈之前的全部阶段\n")

    records, done = [], 0
    for rep in range(args.repeats):
        for item in questions:
            r = time_one(item["question"], fns)
            r.update(id=item["id"], category=item["category"], rep=rep)
            records.append(r)
            done += 1
            print(f"[{done}/{total}] {item['id']:<10} 合计 {r['total']:.3f}s  "
                  f"classify {r['stages']['classify_skill (LLM #1)']:.3f}s  "
                  f"decide {r['stages']['decide round 1 (LLM #2)']:.3f}s  "
                  f"工具={','.join(r['tools']) or '-'}")

    # 阶段名与顺序取自实际记录，保证与 time_one() 里的打点顺序一致
    names = list(records[0]["stages"].keys())
    agg = {n: summarize([r["stages"][n] for r in records]) for n in names}
    grand = summarize([r["total"] for r in records])

    print(f"\n{'阶段':<26}{'中位数':>10}{'均值':>10}{'最大':>10}{'占比':>8}")
    print("-" * 66)
    for n in names:
        s = agg[n]
        # 占比必须用均值算：中位数不可加，各段中位数除以总中位数会加出超过 100% 的结果。
        share = s["mean"] / grand["mean"] * 100
        print(f"{n:<26}{s['median']:>9.3f}s{s['mean']:>9.3f}s{s['max']:>9.3f}s{share:>7.1f}%")
    print("-" * 66)
    print(f"{'合计':<26}{grand['median']:>9.3f}s{grand['mean']:>9.3f}s{grand['max']:>9.3f}s")

    print("\n注意：本脚本不经过 HTTP/SSE，未计入网络栈与 Starlette 线程池调度开销，"
          "\n因此合计值会低于端到端实测的首次反馈延迟。要看的是各阶段的占比，不是绝对值。")

    out = Path(args.out or Path(__file__).parent / "stage_timing.json")
    out.write_text(json.dumps(
        {"repeats": args.repeats, "per_category": args.per_category,
         "aggregate": agg, "grand_total": grand, "records": records},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{out}")


if __name__ == "__main__":
    main()

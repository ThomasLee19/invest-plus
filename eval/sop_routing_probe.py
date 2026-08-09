"""SOP 路由探针：正例准确率 + 反例误触发率，只调 classify_skill，不执行工具。

为什么单独一个脚本
------------------
`skill_coverage_eval.py` 量的是"命中之后拆解得够不够全"，且其两把尺子都已知失效
（见该文件与 spec）。本脚本量的是**路由本身**——该不该命中——这是教材 2.5.1 里
Don't-use-when 唯一声称能改善的东西，也是当前唯一能测准的 SOP 指标。

两个数必须一起看
----------------
只看误触发率会被"把 description 写到什么都不触发"骗过去；只看正例准确率则看不见
误触发。收紧描述的正确结果是：误触发降、正例不掉。

用法：
    PYTHONPATH=backend:backend/app:eval python eval/sop_routing_probe.py --label after
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from skill_coverage_dataset import SINGLE_HIT_VALUATION, DUAL_HIT, NEGATIVE  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--samples", type=int, default=2)
    args = ap.parse_args()

    from app.service.agent import agent  # noqa: E402

    print("== 反例（应命中 0 个 SOP）==")
    neg_rows, fp = [], 0
    for it in NEGATIVE:
        runs = [agent.classify_skill(it["question"]) for _ in range(args.samples)]
        misfired = [h for h in runs if h]
        fp += len(misfired)
        neg_rows.append({**it, "runs": runs})
        print(f"  {'✗' if misfired else '✓'} {it['id']}  {it['question'][:24]:<26}"
              f" 命中={runs}  陷阱={it['trap']}")
    neg_tot = len(NEGATIVE) * args.samples

    print("\n== 正例（应命中标注的 SOP）==")
    pos_rows, hit = [], 0
    positives = list(SINGLE_HIT_VALUATION) + list(DUAL_HIT)
    for it in positives:
        got = agent.classify_skill(it["question"])
        exp, gotset = set(it["expect_skill_hits"]), set(got)
        ok = exp == gotset
        hit += ok
        pos_rows.append({**it, "got": got, "ok": ok})
        if not ok:
            print(f"  ✗ {it['id']:<14} 期望={sorted(exp)} 实际={sorted(gotset)}"
                  f"  {it['question'][:28]}")
    print(f"  正例 {hit}/{len(positives)} 命中")

    print(f"\n误触发率 {fp}/{neg_tot} = {fp / neg_tot * 100:.1f}%   "
          f"正例准确率 {hit}/{len(positives)} = {hit / len(positives) * 100:.1f}%")
    print("两个数须一起看：只看前者会被『写到什么都不触发』骗过去。")

    out = Path(__file__).parent / f"sop_routing_{args.label}.json"
    out.write_text(json.dumps({
        "label": args.label, "samples": args.samples,
        "false_positive": fp, "negative_total": neg_tot,
        "positive_hit": hit, "positive_total": len(positives),
        "negative": neg_rows, "positive": pos_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""SOP 覆盖率量化验收实验（合流步骤的强制验收门槛）——评分方法 v2。

对 eval/skill_coverage_dataset.py 里每道标注题，分别在两种条件下跑真实 agent_plan()：
  - baseline：不注入任何 SOP（agent_plan(query)）
  - injected：classify_skill(query) 命中后读取对应 SOP 正文，注入
    agent_plan(query, skill_sops=matched)

评分方法 v2（在用户批准下，针对 v1 三处诊断到的失真专门重设计；v1 的问题详见
eval/skill_coverage_run.txt 及当时的报告）：
  1. 【P/E 饱和】不再用「估值关键词是否出现」的二值判定——改为**统计出现的不同估值
     倍数的个数**（P/E、P/B、P/S、EV/EBITDA、股息率…），按广度打分（min(1, 命中概念数
     / 目标数)），让「5 个倍数」高于「1 个倍数」，而不是都判 50%。
  2. 【同行对比对关键词不可见】同行对比改为**按 ticker 计数**检测：提取一段子问题里
     出现的所有 ticker，若除问题主标的以外还出现别的 ticker，即视为在做同行对比（不
     依赖是否字面出现"peer/同行"）。
  3. 【n=1 噪声】每个条件对每道题**采样 3 次**取平均，用稳定均值代替单次抽样。

每题 API 调用：3 baseline plan + 1 classify + 3 injected plan = 7 次；19 题 ≈ 133 次
qwen-plus 调用。评分与 LLM 调用解耦：原始子问题存入 JSON，--rescore 可离线重算。
无凭据/依赖时 --selftest 离线自检评分逻辑（不需要任何网络）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
for p in (_BACKEND, _BACKEND / "app", _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from eval.skill_coverage_dataset import SINGLE_HIT_VALUATION, DUAL_HIT  # noqa: E402

SAMPLES = 3  # 每个条件每题采样次数（对冲 n=1 LLM 抽样噪声）
SINGLE_THRESHOLD_PP = 30.0  # 单命中 injected 相对 baseline 覆盖率提升门槛（个百分点）


# ── ticker 提取（用于「同行对比按 ticker 计数」检测）───────────────────────────
# 提取整段文本里 2–5 个大写字母、且不紧邻其他英文字母的 token（零宽断言，能识别紧贴
# 中文的 ticker）。再剔除会与 ticker 撞形的金融缩写（P/E 会被切成 P、E，已由长度≥2
# 排除；PE/PB/PS/PEG/EV/ROE/EPS 等 2–5 字母缩写显式列入禁用词）。数据集用的真实 ticker
# （AAPL/MSFT/KO/AMD/META/WMT/TGT/EBAY/INTC/AVGO…）均不在禁用词里。
_SCORE_TICKER_RE = re.compile(r"(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])")
_TICKER_DENY = {
    "PE", "PB", "PS", "PEG", "EV", "ROE", "ROA", "ROI", "EPS", "EBIT", "TTM",
    "YOY", "YTD", "QOQ", "CAGR", "DCF", "FCF", "NAV", "GDP", "CPI", "FED", "SEC",
    "IPO", "ETF", "ESG", "CEO", "CFO", "COO", "CTO", "USD", "US", "IT", "AI",
    "SOP", "10K", "10Q", "8K", "YOU", "THE", "AND", "FOR", "VS",
}


def extract_tickers(text: str) -> set:
    return {t for t in _SCORE_TICKER_RE.findall(text or "") if t not in _TICKER_DENY}


# ── 每个 SOP 的两个强制评分维度 ────────────────────────────────────────────────
# kind:
#   "breadth"      -> 命中的不同概念数 / target，封顶 1.0（奖励广度，解决 P/E 饱和）
#   "peer_or_hist" -> 出现 ≥1 个"其他 ticker"（同行对比）或任一历史/对比关键词 -> 1 否则 0
#   "peer_tickers" -> min(1, 其他 ticker 数 / target)（纯按 ticker 计数衡量同行对标广度）
# 每个 breadth concept 是一组同义词（中英双语），命中任一即算该概念被覆盖。
SOP_DIMENSIONS = {
    "valuation": [
        {"name": "估值倍数广度", "kind": "breadth", "target": 3, "concepts": [
            ["市盈率", "p/e", "pe ratio", "peg", "price to earnings", "price-to-earnings"],
            ["市净率", "p/b", "price to book"],
            ["市销率", "p/s", "price to sales"],
            ["ev/ebitda"],
            ["股息", "dividend yield"],
        ]},
        {"name": "同行/历史对比", "kind": "peer_or_hist", "keywords": [
            "历史", "分位", "historical", "history", "percentile", "year range",
            "5-year", "3-year", "average", "同行", "对比", "可比", "peer", "comparison",
        ]},
    ],
    "financial_statement": [
        {"name": "盈利能力广度", "kind": "breadth", "target": 3, "concepts": [
            ["营收", "收入", "revenue"],
            ["毛利率", "gross margin"],
            ["净利率", "net margin", "net profit margin"],
            ["净利润", "net income", "profit", "earnings"],
            ["eps", "每股收益"],
        ]},
        {"name": "财务健康广度", "kind": "breadth", "target": 2, "concepts": [
            ["负债", "debt", "leverage"],
            ["现金流", "cash flow"],
            ["流动比率", "偿债", "current ratio", "liquidity", "solvency"],
            ["资产负债", "balance sheet"],
        ]},
    ],
    "industry_comparison": [
        {"name": "同行对标广度(ticker计数)", "kind": "peer_tickers", "target": 2},
        {"name": "横向对比指标广度", "kind": "breadth", "target": 2, "concepts": [
            ["市盈", "p/e", "市销", "p/s", "ev/ebitda"],
            ["毛利率", "净利率", "gross margin", "net margin", "roe", "profitability"],
            ["市场份额", "市占率", "market share", "行业地位", "market position",
             "industry position", "龙头", "market leader"],
        ]},
    ],
    "risk_scan": [
        {"name": "财务风险广度", "kind": "breadth", "target": 2, "concepts": [
            ["负债", "债务", "debt", "leverage"],
            ["现金流", "cash flow"],
            ["商誉", "goodwill", "减值", "impairment"],
            ["偿债", "流动比率", "liquidity", "solvency"],
        ]},
        {"name": "经营/政策风险广度", "kind": "breadth", "target": 2, "concepts": [
            ["客户集中", "customer concentration", "供应商", "supplier"],
            ["监管", "政策", "regulatory", "regulation", "antitrust", "反垄断", "合规", "compliance"],
            ["诉讼", "litigation", "退市", "治理", "governance"],
            ["风险因素", "risk factor"],
        ]},
    ],
}


def actions_to_text(actions) -> str:
    """把 agent_plan() 返回的 actions（list[{action_name, prompts:[...]}]）里所有子问题
    拼成一段文本。actions 为 None / 空时返回空串。"""
    if not actions:
        return ""
    chunks = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        prompts = a.get("prompts", [])
        if isinstance(prompts, str):
            prompts = [prompts]
        elif not isinstance(prompts, list):
            prompts = []
        chunks.extend(str(p) for p in prompts)
    return "\n".join(chunks)


def _concept_hit(concept: list, low: str) -> bool:
    return any(syn.lower() in low for syn in concept)


def coverage(skill: str, text: str, subject_tickers: set) -> float:
    """某 SOP 在一段子问题文本上的覆盖率 ∈ [0,1]：其两个强制维度得分的平均。"""
    low = text.lower()
    other_tickers = extract_tickers(text) - set(subject_tickers)
    scores = []
    for dim in SOP_DIMENSIONS[skill]:
        if dim["kind"] == "breadth":
            covered = sum(1 for c in dim["concepts"] if _concept_hit(c, low))
            scores.append(min(1.0, covered / dim["target"]))
        elif dim["kind"] == "peer_or_hist":
            has_kw = any(k.lower() in low for k in dim["keywords"])
            scores.append(1.0 if (len(other_tickers) >= 1 or has_kw) else 0.0)
        elif dim["kind"] == "peer_tickers":
            scores.append(min(1.0, len(other_tickers) / dim["target"]))
    return sum(scores) / len(scores) if scores else 0.0


# ── 与真实 agent_plan / classify_skill 的桥接（需要 LLM 环境）──────────────────

def _load_agent():
    from app.service.agent import agent
    return agent


def run_and_collect(agent, samples: int = SAMPLES) -> dict:
    """跑完整对比实验，收集每题两条件各 `samples` 次采样的原始子问题文本（不打分）。
    injected 条件对每题只 classify 一次、复用命中的 SOP，再采样 samples 次 agent_plan。"""
    def collect(item):
        q = item["question"]
        baseline_texts = [actions_to_text(agent.agent_plan(q)) for _ in range(samples)]
        hits = agent.classify_skill(q)
        matched = []
        for name in hits:
            sop = agent.load_skill(name)
            if sop and sop.get("body"):
                matched.append(sop)
        injected_texts = [
            actions_to_text(agent.agent_plan(q, skill_sops=matched)) for _ in range(samples)
        ]
        return {
            "id": item["id"], "question": q,
            "expect_skill_hits": item["expect_skill_hits"],
            "classified_hits": hits,
            "baseline_texts": baseline_texts,
            "injected_texts": injected_texts,
        }
    return {
        "single": [collect(it) for it in SINGLE_HIT_VALUATION],
        "dual": [collect(it) for it in DUAL_HIT],
    }


def _avg_cov(skill, texts, subject) -> float:
    return sum(coverage(skill, t, subject) for t in texts) / len(texts) if texts else 0.0


def score(raw: dict) -> dict:
    """从原始文本（run_and_collect 收集或 --rescore 读入）计算覆盖率结果。纯确定性。
    每条件对 baseline_texts / injected_texts 的多次采样取平均覆盖率。"""
    single = []
    for r in raw["single"]:
        subj = extract_tickers(r["question"])
        single.append({
            "id": r["id"], "classified_hits": r.get("classified_hits"),
            "baseline": _avg_cov("valuation", r["baseline_texts"], subj),
            "injected": _avg_cov("valuation", r["injected_texts"], subj),
        })
    dual = []
    for r in raw["dual"]:
        subj = extract_tickers(r["question"])
        per_skill = {}
        for skill in r["expect_skill_hits"]:
            per_skill[skill] = {
                "baseline": _avg_cov(skill, r["baseline_texts"], subj),
                "injected": _avg_cov(skill, r["injected_texts"], subj),
            }
        dual.append({"id": r["id"], "classified_hits": r.get("classified_hits"), "skills": per_skill})
    return {"single": single, "dual": dual}


def summarize(results: dict) -> tuple[str, bool]:
    lines = []
    single = results["single"]
    b_avg = sum(r["baseline"] for r in single) / len(single)
    i_avg = sum(r["injected"] for r in single) / len(single)
    delta_pp = (i_avg - b_avg) * 100
    single_pass = delta_pp >= SINGLE_THRESHOLD_PP
    lines.append("== 单命中 valuation（覆盖率=估值倍数广度 & 同行/历史对比 两维均值）==")
    for r in single:
        lines.append(f"  {r['id']}: baseline {r['baseline']:.0%} -> injected {r['injected']:.0%}"
                     f"{' ↑' if r['injected'] > r['baseline'] + 1e-9 else ''}"
                     f"   (classify={r.get('classified_hits')})")
    lines.append(f"  baseline avg: {b_avg:.1%}   injected avg: {i_avg:.1%}")
    lines.append(f"  提升: {delta_pp:+.1f} 个百分点  (门槛 ≥{SINGLE_THRESHOLD_PP:.0f}) -> "
                 f"{'PASS' if single_pass else 'FAIL'}")

    lines.append("== 双命中（每个 SOP 各自覆盖率都要相对 baseline 提升）==")
    dual_pass = True
    for r in results["dual"]:
        parts = []
        item_ok = True
        for skill, cov in r["skills"].items():
            up = cov["injected"] > cov["baseline"] + 1e-9
            item_ok = item_ok and up
            parts.append(f"{skill}: {cov['baseline']:.0%}->{cov['injected']:.0%}{'↑' if up else '·'}")
        dual_pass = dual_pass and item_ok
        lines.append(f"  {r['id']} (classify={r.get('classified_hits')}): " + "; ".join(parts)
                     + f"  -> {'PASS' if item_ok else 'FAIL'}")
    lines.append(f"双命中整体: {'PASS' if dual_pass else 'FAIL'}")
    overall = single_pass and dual_pass
    lines.append(f"\n验收总判定: {'PASS' if overall else 'FAIL'}")
    return "\n".join(lines), overall


# ── 离线自检：合成数据验证评分三处重设计（无需凭据/网络）──────────────────────

def selftest() -> int:
    ok = True
    # (1) 估值倍数广度：1 个倍数 < 5 个倍数（不再都 50%）
    subj = {"AAPL"}
    one = coverage("valuation", "AAPL PE ratio", subj)
    many = coverage("valuation", "AAPL P/E\nAAPL P/B\nAAPL P/S\nAAPL EV/EBITDA\nAAPL dividend yield", subj)
    print(f"[selftest] valuation breadth: 1-multiple={one:.2f}  5-multiple={many:.2f}")
    ok = ok and (one < many)
    # (2) 同行对比按 ticker 计数：出现别的 ticker => peer 维度得分
    no_peer = coverage("valuation", "AAPL P/E", subj)
    with_peer = coverage("valuation", "AAPL P/E\nMSFT P/E\nGOOGL P/E", subj)
    print(f"[selftest] valuation peer-by-ticker: no-peer={no_peer:.2f}  with-peer={with_peer:.2f}")
    ok = ok and (with_peer > no_peer)
    # industry_comparison peer_tickers 维度：2 个对标 ticker => 该维满分
    ic = coverage("industry_comparison", "AAPL P/E\nMSFT P/E\nGOOGL market share\nAAPL gross margin", subj)
    print(f"[selftest] industry_comparison rich={ic:.2f}")
    ok = ok and (ic >= 0.75)
    # ticker 提取不把 P/E、EV/EBITDA、ROE、EPS 误当 ticker
    toks = extract_tickers("AAPL valuation / P/E / EV/EBITDA / ROE / EPS ; MSFT P/S")
    print(f"[selftest] extract_tickers = {sorted(toks)}")
    ok = ok and (toks == {"AAPL", "MSFT"})
    # actions_to_text 展开 prompts
    txt = actions_to_text([{"action_name": "finance_query", "prompts": ["AAPL P/E", "AAPL 毛利率"]}])
    ok = ok and ("AAPL P/E" in txt and "AAPL 毛利率" in txt)
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="仅离线自检评分逻辑，不调用任何 LLM")
    ap.add_argument("--rescore", metavar="RAW_JSON",
                    help="从已保存的原始子问题 JSON 离线重算覆盖率，不调用任何 LLM")
    ap.add_argument("--dump", metavar="PATH", default=None,
                    help="把本次 live run 收集到的原始子问题写入此 JSON（供审计/离线重算）")
    ap.add_argument("--samples", type=int, default=SAMPLES,
                    help=f"每条件每题采样次数（默认 {SAMPLES}）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.rescore:
        with open(args.rescore, encoding="utf-8") as f:
            raw = json.load(f)
        report, overall = summarize(score(raw))
        print(report)
        return 0 if overall else 1
    try:
        agent = _load_agent()
        raw = run_and_collect(agent, samples=args.samples)
    except Exception as e:  # 缺凭据/依赖/网络 → 明确报告 BLOCKED，不伪装成完成
        print("LIVE RUN BLOCKED: 无法执行真实 agent_plan 对比实验。")
        print(f"  原因: {type(e).__name__}: {e}")
        print("  需要: 已安装 openai + 有效 DASHSCOPE_API_KEY/DASHSCOPE_BASE_URL + 网络访问。")
        print("  评分逻辑本身可用 `python eval/skill_coverage_eval.py --selftest` 离线验证。")
        return 2
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print(f"[dump] raw sub-questions saved to {args.dump}\n")
    report, overall = summarize(score(raw))
    print(report)
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())

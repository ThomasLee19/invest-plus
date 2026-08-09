"""
Skill SOP 覆盖率量化验收数据集（对应合流步骤的强制量化验收门槛）。

用途：为「SOP 注入 vs baseline」的 actions 覆盖率对比实验提供标注题库。对每道题，
分别在「有 SOP 注入」与「无 SOP 注入（baseline）」两种条件下跑真实 agent_plan()，
把生成的所有子问题（actions 里每个 action 的 prompts）拼成一段文本，统计其中命中
了多少个「该 SOP 要求的指标组」，得到覆盖率；验收标准见计划
`.omc/plans/ralplan-invest-plus-memory-skills-disclaimer.md` 的「共同合流步骤」章节：
  - 单命中场景（valuation）：覆盖率相对 baseline 提升 ≥30 个百分点
  - 双命中场景：两个 SOP 各自要求的指标都要有覆盖率提升（不能只满足其中一个）

本文件只是数据 / fixture，不 import 也不修改 agent.py，不与其他 worker 的代码冲突。
统计逻辑（如何把子问题文本与下面的关键词做匹配、如何算覆盖率）由验收脚本实现；
这里只负责「标注每道题预期命中哪些 SOP、每个 SOP 要求覆盖哪些指标关键词」。

指标匹配约定：每个「指标组」是一组同义关键词（`any`），只要生成的子问题文本里
（大小写不敏感、子串匹配）出现该组里任意一个关键词，即判定这一组被「覆盖」。
`mandatory=True` 的组是该 SOP「规划提示」里明文要求「至少产出覆盖」的类别，是覆盖率
统计的核心；`mandatory=False` 的组是 SOP 检查清单里的补充指标，用于更细粒度的观察。
"""

SKILL_NAMES = {"valuation", "financial_statement", "industry_comparison", "risk_scan"}


# ── 每个 SOP 要求覆盖的指标组 ────────────────────────────────────────────────
# 关键词取自 backend/app/service/agent/skills/<name>.md 的「分析清单」与「规划提示」。
# mandatory 组对应各 SOP「规划提示」里「至少产出覆盖 X 与 Y 两类」的硬性要求。
# 关键词双语：agent_plan 由 qwen-plus 生成，子问题在中英文之间自由切换（实测同一
# 问题里既有 "AAPL valuation / P/E" 也有 "peer group for valuation comparison"、
# "gross margin"、"debt / cash flow" 等英文表达）。每个指标组同时收录该概念的中、英
# 关键词，避免只认中文导致对英文子问题的系统性漏计（大小写不敏感、子串匹配）。
SOP_METRIC_GROUPS = {
    # valuation：规划提示要求至少覆盖「市盈率」和「同行/历史对比」两类
    "valuation": [
        {"group": "市盈率(P/E)", "mandatory": True,
         "any": ["市盈率", "市盈", "P/E", "PE ratio", "PEG", "price to earnings",
                 "price-to-earnings"]},
        {"group": "同行/历史估值对比", "mandatory": True,
         "any": ["同行", "同业", "历史", "分位", "对比", "可比", "行业估值",
                 "peer", "comparison", "compare", "competitor", "historical", "history",
                 "percentile", "5-year", "3-year", "year range", "average"]},
        {"group": "其他估值倍数", "mandatory": False,
         "any": ["市净率", "P/B", "price to book", "市销率", "P/S", "price to sales",
                 "EV/EBITDA", "股息率", "dividend yield"]},
    ],
    # financial_statement：规划提示要求至少覆盖「盈利能力（营收/利润/毛利率）」与
    # 「财务健康（负债率/现金流）」两类
    "financial_statement": [
        {"group": "盈利能力(营收/利润/毛利率)", "mandatory": True,
         "any": ["营收", "收入", "净利润", "毛利率", "净利率", "盈利能力",
                 "revenue", "gross margin", "net margin", "operating margin",
                 "net income", "profit", "earnings", "EPS"]},
        {"group": "财务健康(负债率/现金流)", "mandatory": True,
         "any": ["负债率", "资产负债", "现金流", "偿债", "流动比率",
                 "debt", "leverage", "cash flow", "liquidity", "current ratio",
                 "balance sheet", "solvency"]},
        {"group": "回报率(ROE/ROA)", "mandatory": False,
         "any": ["ROE", "ROA", "回报率", "净资产收益率", "return on equity",
                 "return on assets"]},
    ],
    # industry_comparison：规划提示要求至少覆盖「同行估值对比」与「同行盈利能力/份额
    # 对比」两类，且必须出现目标公司之外的至少一个对标对象
    "industry_comparison": [
        {"group": "同行估值对比", "mandatory": True,
         "any": ["同行", "同业", "可比", "对标", "竞争对手", "竞品", "行业估值",
                 "P/E", "P/S", "peer", "comparison", "compare", "competitor", "versus"]},
        {"group": "同行盈利能力/市场份额对比", "mandatory": True,
         "any": ["毛利率", "净利率", "ROE", "盈利能力", "市场份额", "市占率", "行业地位", "龙头",
                 "gross margin", "net margin", "profitability", "market share",
                 "market position", "industry position", "competitive position", "market leader"]},
        {"group": "护城河/竞争壁垒", "mandatory": False,
         "any": ["护城河", "壁垒", "品牌", "网络效应", "切换成本",
                 "moat", "competitive advantage", "brand", "switching cost", "network effect"]},
    ],
    # risk_scan：规划提示要求至少覆盖「财务风险（债务/现金流/商誉）」与「经营或政策
    # 风险」两类
    "risk_scan": [
        {"group": "财务风险(债务/现金流/商誉)", "mandatory": True,
         "any": ["负债", "债务", "现金流", "商誉", "减值", "偿债",
                 "debt", "cash flow", "goodwill", "impairment", "leverage",
                 "liquidity", "solvency"]},
        {"group": "经营/政策/监管风险", "mandatory": True,
         "any": ["客户集中", "供应商", "监管", "政策", "诉讼", "退市", "反垄断", "合规",
                 "risk factor", "regulatory", "regulation", "litigation", "antitrust",
                 "compliance", "governance", "customer concentration", "supplier"]},
        {"group": "估值回调风险", "mandatory": False,
         "any": ["估值", "高估", "透支", "回调", "overvalued", "valuation risk",
                 "correction", "downside"]},
    ],
}


def mandatory_metric_groups(skill: str) -> list[dict]:
    """返回某个 SOP 的强制指标组（覆盖率验收的核心口径）。"""
    return [g for g in SOP_METRIC_GROUPS[skill] if g["mandatory"]]


# ── 1. 单命中数据集：全部标注为 valuation 单命中（≥10 道）─────────────────────
# 每题只应命中 valuation 一个 SOP。expect_skill_hits 为长度 1 的列表。
# 每题都含大写 ticker，保证 SOP 注入后 agent_plan 能产出带 ticker 的 finance_query
# 子问题；覆盖率按 SOP_METRIC_GROUPS["valuation"] 的 mandatory 组统计。
SINGLE_HIT_VALUATION = [
    {"id": "sop-val-01", "question": "AAPL 现在市盈率贵不贵？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-02", "question": "MSFT 目前的估值水平合理吗？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-03", "question": "英伟达 NVDA 现在是不是被高估了？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-04", "question": "从估值角度看，TSLA 现在这个价位值不值？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-05", "question": "AMZN 现在便宜吗，估值处于什么水平？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-06", "question": "GOOGL 的市盈率和 PEG 现在处于高位还是低位？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-07", "question": "META 现在这个价位是高估还是低估？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-08", "question": "AAPL 的市净率和市销率现在算贵吗？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-09", "question": "NFLX 现在的估值贵不贵，值不值得关注？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-10", "question": "KO 可口可乐的股息率和市盈率现在有吸引力吗？", "expect_skill_hits": ["valuation"]},
    {"id": "sop-val-11", "question": "AMD 当前的估值分位处于历史什么位置？", "expect_skill_hits": ["valuation"]},
    # ticker 紧贴中文、无空格分隔，验证召回/分类在中文常见问法下同样生效
    {"id": "sop-val-12", "question": "分析一下MSFT现在估值高不高", "expect_skill_hits": ["valuation"]},
]


# ── 2. 双命中数据集：需要同时命中 2 个 SOP（≥5 道）──────────────────────────
# expect_skill_hits 为长度 2 的列表。验收时两个 SOP 各自的 mandatory 指标组都要有
# 相对 baseline 的覆盖率提升，不能只满足其中一个、放过另一个。
DUAL_HIT = [
    {"id": "sop-dual-01",
     "question": "AAPL 现在估值贵不贵，和同行业比怎么样？",
     "expect_skill_hits": ["valuation", "industry_comparison"]},
    {"id": "sop-dual-02",
     "question": "MSFT 最新财报解读一下，顺便看看它在行业里的地位？",
     "expect_skill_hits": ["financial_statement", "industry_comparison"]},
    {"id": "sop-dual-03",
     "question": "NVDA 现在估值是不是太高了，有什么下行风险？",
     "expect_skill_hits": ["valuation", "risk_scan"]},
    {"id": "sop-dual-04",
     "question": "TSLA 的财务基本面怎么样，有没有什么值得担心的风险？",
     "expect_skill_hits": ["financial_statement", "risk_scan"]},
    {"id": "sop-dual-05",
     "question": "GOOGL 和同行相比，盈利能力和财务健康状况如何？",
     "expect_skill_hits": ["industry_comparison", "financial_statement"]},
    {"id": "sop-dual-06",
     "question": "AMZN 现在估值合理吗？和它的主要竞争对手比又怎么样？",
     "expect_skill_hits": ["valuation", "industry_comparison"]},
    {"id": "sop-dual-07",
     "question": "META 的财报和估值分别怎么看，现在这个价位有没有下行风险？",
     "expect_skill_hits": ["financial_statement", "valuation", "risk_scan"][:2]},
]


# ── 3. 补充单命中题（其余 3 个 SOP，可选）───────────────────────────────────
# 非验收硬性要求（硬性要求是 valuation 单命中 + 双命中），但纳入后可让验收实验
# 分别度量每个 SOP 的独立覆盖率提升，增强「双命中两个 SOP 各自都提升」结论的可信度。
# 验收脚本可按需选用；默认可跳过以节省 LLM 调用成本。
SUPPLEMENTARY_SINGLE_HIT = [
    {"id": "sop-fin-01", "question": "AAPL 最新一季的财报怎么样，营收和利润增长如何？", "expect_skill_hits": ["financial_statement"]},
    {"id": "sop-fin-02", "question": "MSFT 的基本面健康吗，负债率和现金流情况如何？", "expect_skill_hits": ["financial_statement"]},
    {"id": "sop-ind-01", "question": "NVDA 在半导体行业里和同行相比处于什么位置？", "expect_skill_hits": ["industry_comparison"]},
    {"id": "sop-ind-02", "question": "GOOGL 和它的主要竞争对手比，谁更有优势？", "expect_skill_hits": ["industry_comparison"]},
    {"id": "sop-risk-01", "question": "TSLA 现在有哪些值得担心的风险和隐患？", "expect_skill_hits": ["risk_scan"]},
    {"id": "sop-risk-02", "question": "AMZN 有没有什么债务或者监管方面的风险？", "expect_skill_hits": ["risk_scan"]},
]


# 便捷聚合：验收脚本可直接 import 这几个列表
ALL_SINGLE_HIT = SINGLE_HIT_VALUATION
ALL_DUAL_HIT = DUAL_HIT


# ── 反例集：应当命中 0 个 SOP 的查询 ────────────────────────────────────────────
# 为什么需要它：原题库全是正例（每题都奔着命中某个 SOP 设计），实测 classify_skill
# 在其上是 19/19 = 100%，指标饱和、无从判优。而教材 2.5.1 指出 Don't-use-when 治的是
# 反向的病——"宽泛的描述会在不相关的任务上频繁误触发"。误触发在只有正例的集合上
# 结构性地测不出来。
#
# 每条都刻意踩中某个 SOP 的 trigger_keywords，但按业务语义不该激活该 SOP：
# 概念解释、单点取数、新闻查询、宏观话题——这四类都不需要分析 SOP 的多维拆解流程。
NEGATIVE = [
    {"id": "sop-neg-01", "question": "什么是市盈率？", "expect_skill_hits": [],
     "trap": "valuation（市盈率）", "why": "概念解释，不是对某只股票的估值判断"},
    {"id": "sop-neg-02", "question": "现金流量表分为哪三个部分？", "expect_skill_hits": [],
     "trap": "financial_statement（现金流量表）", "why": "概念解释，没有具体公司"},
    {"id": "sop-neg-03", "question": "AAPL 现在股价多少？", "expect_skill_hits": [],
     "trap": "valuation（股价）", "why": "单点取数，不需要估值拆解"},
    {"id": "sop-neg-04", "question": "苹果公司最新的每股收益是多少？", "expect_skill_hits": [],
     "trap": "financial_statement（每股收益）", "why": "单点取数，不需要三表拆解"},
    {"id": "sop-neg-05", "question": "苹果最近和 American Express 有什么合作新闻？",
     "expect_skill_hits": [], "trap": "industry_comparison（公司间关系）",
     "why": "新闻查询，不是跨公司指标横向对比"},
    {"id": "sop-neg-06", "question": "今天美股大盘的整体走势如何？", "expect_skill_hits": [],
     "trap": "risk_scan / industry_comparison（大盘、行业）", "why": "宏观行情，不是个股分析"},
    {"id": "sop-neg-07", "question": "最近有什么关于美联储利率决议的最新消息？",
     "expect_skill_hits": [], "trap": "risk_scan（政策、监管）", "why": "宏观政策新闻，不是个股排雷"},
    {"id": "sop-neg-08", "question": "你好，你能做什么？", "expect_skill_hits": [],
     "trap": "无", "why": "对照组：与投研完全无关，任何 SOP 都不该触发"},
]

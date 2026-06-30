"""
Invest+ Agent
Plan → Act → Reflect → Answer 架构，沿用 SalesPilot 原始命名。

迁移说明：本项目由 Pokemon 对战助手（PokemonRA）重构而来，复用同一套
Agent 架构（本文件）与 RAG 检索基础设施，目标域改为金融研究助手。
工具层与 prompt 内容仍是迁移前的 Pokemon 领域实现，将在后续阶段替换为
金融领域工具（详见 .omc/plans/finance-agent-migration-plan.md）。

三个工具（当前仍为 Pokemon 领域实现，迁移中）：
  rag_search    - Smogon 攻略知识库（ES hybrid search）
  pokeapi_query - 精确数值查询（实时调用 PokeAPI）
  web_search    - 最新 meta / 知识库未覆盖内容（Serper）
"""

import json
import os
import re
import sys
from pathlib import Path
from openai import OpenAI

# 路径处理：支持直接运行和作为模块导入
_backend_dir = Path(__file__).parent.parent.parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from app.service.pokeapi.pokeapi_tool import pokeapi_query as _pokeapi_query
from app.service.pokeapi.pokeapi_tool import resolve_pokemon_name as _resolve_pokemon_name

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
ES_INDEX = "pokemon_kb"


# ── LLM 客户端 ────────────────────────────────────────────────────────────────

def _llm_json(prompt: str) -> str:
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    return completion.choices[0].message.content


def _extract_json_list(text: str) -> str | None:
    match = re.search(r"(\[[\s\S]*\])", text)
    return match.group(1) if match else None


# ── 工具实现 ──────────────────────────────────────────────────────────────────

def _embed_query(text: str) -> list[float] | None:
    """为检索 query 生成 1024 维向量（与上传索引时同一模型 text-embedding-v3）。
    失败返回 None，让 rag_search 优雅降级为纯 BM25，不因 embedding API 故障整体崩溃。"""
    try:
        client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)
        resp = client.embeddings.create(
            model="text-embedding-v3", input=[text], dimensions=1024, encoding_format="float"
        )
        return resp.data[0].embedding
    except Exception as e:
        print(f"[rag_search] query embedding 失败，降级纯 BM25：{e}")
        return None


# kNN 向量分支的权重。BM25 分数量纲大（可达数十），cosine 相似度经 ES 归一到
# 0~1，直接相加会被 BM25 淹没；boost 放大向量贡献，使其与 BM25 可比。
# 实测：中文语义化 query（如“耐久型坦克怎么配招”）纯 BM25 召回为 0，
# 向量分支能跨语言/跨表述命中正确攻略——这正是 hybrid 的价值所在。
_KNN_BOOST = 8.0


def rag_search(query: str, user_id: str = "1") -> list[dict]:
    """查询 ES pokemon_kb，返回 Smogon 攻略 + 用户上传文档的 chunks。

    Hybrid 检索（ES 8.11 原生 knn + query，自实现，无 RAGFlow 依赖）：
    - BM25 路：content_ltks 全文匹配，擅长精确关键词（招式名、精灵名）
    - kNN 路：q_1024_vec 向量近邻，擅长语义/跨语言（中文口语化提问）
    两路分数相加排序。embedding 不可用时自动降级为纯 BM25。
    """
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(
            os.getenv("ES_URL", "http://localhost:1200"),
            basic_auth=("elastic", "infini_rag_flow"),
            verify_certs=False,
            ssl_show_warn=False,
            request_timeout=30,
        )

        # 来源过滤：仅 Smogon 攻略 或 当前用户上传的文档（BM25 与 kNN 两路共用）
        source_filter = [
            {"term": {"source_kwd": "smogon"}},
            {"term": {"user_id": user_id}},
        ]

        # BM25 路
        bm25_query = {
            "bool": {
                "must": {"match": {"content_ltks": query}},
                "should": source_filter,
                "minimum_should_match": 1,
            }
        }
        body: dict = {"query": bm25_query, "size": 5}

        # kNN 路：仅在 query embedding 成功时加入，否则纯 BM25 降级
        q_vec = _embed_query(query)
        if q_vec is not None:
            body["knn"] = {
                "field": "q_1024_vec",
                "query_vector": q_vec,
                "k": 5,
                "num_candidates": 50,
                "boost": _KNN_BOOST,
                # kNN 路也套用同样的来源过滤，保证两路检索范围一致
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
            })
        return results
    except Exception as e:
        print(f"[rag_search] 失败：{e}")
        return []


def pokeapi_tool(query: str) -> str:
    """
    解析自然语言查询，调用 PokeAPI。
    支持：精灵信息查询、属性克制查询。
    """
    query_lower = query.lower()

    # 属性克制查询（包含 "vs"、"对"、"克制"、"弱点" 等关键词）
    if any(kw in query_lower for kw in ["vs", "对", "克制", "弱点", "matchup", "against"]):
        # 尝试提取属性名（简单规则：找 type 相关词）
        types = re.findall(
            r"\b(fire|water|grass|electric|ice|fighting|poison|ground|flying|"
            r"psychic|bug|rock|ghost|dragon|dark|steel|fairy|normal)\b",
            query_lower
        )
        if len(types) >= 2:
            return _pokeapi_query("type_matchup", attacking_type=types[0], defending_types="/".join(types[1:]))
        elif len(types) == 1:
            return _pokeapi_query("type_matchup", attacking_type=types[0], defending_types=types[0])

    # 精灵信息查询：解析出 PokeAPI slug（支持 iron-valiant/great-tusk 等多词名）。
    # 解析失败时回退到第一个词，让 query_pokemon 返回友好的“未找到”提示。
    name = _resolve_pokemon_name(query_lower)
    if not name:
        name = query_lower.split()[0] if query_lower.split() else query_lower
    return _pokeapi_query("pokemon", name=name)


def web_search(query: str, language: str = "en") -> list[str]:
    """调用 Serper 网络搜索。language 映射为 Serper 的 hl 区域偏好（zh→zh-cn，en→en）。"""
    try:
        from app.service.web_search.web_search import serper_search, process_search_results
        hl = "zh-cn" if language == "zh" else "en"
        results = serper_search(query, hl=hl)
        snippets, _ = process_search_results(results)
        return snippets
    except Exception as e:
        print(f"[web_search] 失败：{e}")
        return []


# ── Agent Pipeline ─────────────────────────────────────────────────────────────

def agent_plan(query: str) -> list[dict] | None:
    prompt = """
# PokemonRA Agent — Plan 模块

你是宝可梦对战问答助手的规划模块。分析用户查询，决定调用哪些工具，并将查询拆解为 1-3 个子问题。

## 用户查询
{query}

## 可用工具

1. **rag_search**：搜索 Smogon 攻略知识库
   - 适用场景：对战策略、队伍搭配建议、招式组合、道具选择、赛季 meta、具体精灵的竞技用法
   - 示例："烈咬陆鲨怎么配招"、"铁荆棘适合什么队伍"

2. **pokeapi_query**：查询精灵精确数据（实时调用 PokeAPI）
   - 适用场景：种族值、技能池、进化链、属性克制关系、特性
   - 示例："garchomp speed stat"、"fire vs grass/poison matchup"
   - **重要：子问题必须使用英文精灵名（如 "garchomp speed stat"），不能使用中文**

3. **web_search**：网络搜索
   - 适用场景：最新版本变化、赛季排名数据、知识库未覆盖的冷门精灵
   - 示例："SV赛季12 top tier 精灵"

## 工具选择规则
- 精确数值（种族值/技能/克制）→ pokeapi_query
- 策略/攻略/搭配建议 → rag_search
- 最新 meta/赛季数据 → web_search
- 复合问题可同时使用多个工具
- 日常问候（你好、谢谢等）→ 不调用任何工具，输出 null
- 与宝可梦完全无关的问题（数学、地理、历史等）→ 不调用任何工具，输出 null

## 输出格式
JSON 列表，每项包含 action_name 和 prompts（子问题列表）：
[
  {{
    "action_name": "工具名称",
    "prompts": ["子问题1", "子问题2"]
  }}
]

工具名称必须是：rag_search、pokeapi_query、web_search 之一。
不需要调用工具时输出：null

只输出 JSON，不要输出任何其他内容。
""".format(query=query)

    result = _llm_json(prompt)
    print(f"[agent_plan] {result}")
    json_list = _extract_json_list(result)
    try:
        return json.loads(json_list) if json_list else None
    except Exception:
        return None


def _adjust_format(plan: list[dict]) -> list[dict]:
    """将每个 action 的多个 prompts 展开为独立的 {action_name, prompt} 条目。"""
    adjusted = []
    for item in plan:
        for prompt in item.get("prompts", []):
            adjusted.append({"action_name": item["action_name"], "prompt": prompt})
    return adjusted


def process_actions(actions: list[dict], language: str = "en") -> list[dict]:
    """执行工具调用，返回 memory 列表。language 决定 web_search 的检索区域偏好。"""
    memory = []
    seen = set()

    for action in actions:
        action_name = action["action_name"]
        prompt = action["prompt"]
        print(f"[execute] {action_name}: {prompt}")

        try:
            if action_name == "rag_search":
                result = rag_search(prompt)
            elif action_name == "pokeapi_query":
                result = pokeapi_tool(prompt)
            elif action_name == "web_search":
                result = web_search(prompt, language)
            else:
                result = f"未知工具：{action_name}"

            # 去重：仅当「同一子问题 + 完全相同结果」时才算重复。
            # 用完整 result（不截断）做 key，避免不同查询因前 200 字符相同被误丢
            # （如宝可梦信息卡表头格式统一、或 rag 命中同一篇文章首块时撞前缀）。
            result_key = (prompt, str(result))
            if result_key in seen:
                continue
            seen.add(result_key)

            memory.append({"提问": prompt, "结果": result})

        except Exception as e:
            import traceback
            print(f"[execute] {action_name} 失败：{traceback.format_exc()}")
            # 错误必须写入 memory（而非仅打印），否则 should_continue() 的 LLM
            # 永远看不到工具失败，无法决定重试/换源/在最终答案中坦白信息缺口。
            memory.append({
                "提问": prompt,
                "结果": f"[工具调用失败] {action_name}: {e}",
                "错误": True,
            })

    return memory


def _extract_json_object(text: str) -> str | None:
    match = re.search(r"(\{[\s\S]*\})", text)
    return match.group(1) if match else None


def should_continue(query: str, memory: list[dict]) -> dict:
    """LLM 判断已收集信息是否足以回答问题；若不足则给出补充查询。

    这是循环（final_answer 的 while 循环）的唯一决策来源：是否继续、调用什么、
    何时停止，全部读取自这次 LLM 调用的结构化输出，循环本身不包含任何决定
    "下一步做什么"的硬编码分支。

    返回 {"sufficient": bool, "rationale": str, "actions": list[dict]}：
    - sufficient=True 时 actions 应为空，循环据此停止（LLM 主动判定停止）。
    - sufficient=False 时 actions 给出至多 2 个补充查询（格式同 agent_plan）。
    - LLM 输出解析失败时，安全降级为 {"sufficient": True, "rationale": "<parse
      error>", "actions": []}——即停止循环而非抛异常，且该降级路径与"LLM 主动
      判定足够"在 rationale 文案上可区分，便于排查。
    """
    prompt = """
# PokemonRA Agent — Reflect 模块

用户问题：{query}

已收集的信息：
{memory}

## 任务
判断已有信息是否足以回答用户问题。如果不足，补充至多 2 个查询。

## 可用工具
- rag_search：Smogon 攻略（策略/搭配）
- pokeapi_query：精灵精确数据（数值/技能/克制）【子问题必须用英文精灵名】
- web_search：网络搜索，适用于：1）最新 meta/赛季数据；2）rag_search 没有返回任何对战策略内容时，用于补充竞技用法

## 判断规则
- 如果用户问的是对战策略/搭配建议，但 rag_search 结果为空或没有相关策略内容 → 必须补充 web_search
- 如果某次工具调用失败（已收集信息中标记了"错误": true）→ 判断是否需要换一种查询方式重试，或改用其他工具，或在 rationale 中说明该信息缺口
- 如果已有完整的策略内容（招式/道具/EV建议）→ sufficient 为 true
- pokeapi_query 的数值数据不能替代对战策略，两者都需要时要分别补充

## 输出格式
必须输出 JSON 对象（不是列表），包含三个字段：
{{
  "sufficient": true 或 false，
  "rationale": "一句话说明你为什么认为信息已足够，或为什么还需要补充查询（将展示给用户，用于解释你的决策依据）",
  "actions": 当 sufficient 为 true 时为空列表 []；为 false 时给出至多 2 个补充查询，格式：
    [{{"action_name": "工具名称", "prompts": ["补充问题"]}}]
}}

只输出 JSON 对象，不要输出其他内容。
""".format(query=query, memory=json.dumps(memory, ensure_ascii=False, indent=2))

    result = _llm_json(prompt)
    print(f"[should_continue] {result}")
    json_obj = _extract_json_object(result)
    try:
        parsed = json.loads(json_obj) if json_obj else None
        if not isinstance(parsed, dict) or "sufficient" not in parsed:
            raise ValueError("missing required 'sufficient' field")
        return {
            "sufficient": bool(parsed["sufficient"]),
            "rationale": parsed.get("rationale", ""),
            "actions": parsed.get("actions") or [],
        }
    except Exception as e:
        print(f"[should_continue] 解析失败，安全降级为停止循环：{e}")
        return {
            "sufficient": True,
            "rationale": f"[parse error - defaulting to stop] {e}",
            "actions": [],
        }


def _detect_language(text: str) -> str:
    """检测文本语言，决定回答用什么语言。

    口径：只看用户输入——出现中文字则中文，其余一律英文。
    （日文常含汉字、韩文偶含汉字，故先排除日文假名 / 韩文谚文，
    避免日韩输入被当成中文。排除后只要出现一个 CJK 汉字即判中文，
    不再用占比阈值——短文本+长英文名也能正确判定，如 'Garchomp 配招？'。）
    """
    if re.search(r'[぀-ゟ゠-ヿ]', text):  # 日文假名 → 英文
        return "en"
    if re.search(r'[가-힯]', text):        # 韩文谚文 → 英文
        return "en"
    return "zh" if re.search(r'[一-鿿]', text) else "en"


def final_answer(query: str, language: str = "auto", history: list[dict] | None = None):
    """
    完整 Agent Pipeline，SSE 流式生成器。
    language: "zh"（中文）或 "en"（英文）
    history: 历史对话，格式 [{"user": "...", "assistant": "..."}]
    """
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)

    # 语言提前确定：web_search 在 Act/Reflect 阶段就需要它来设置 Serper 的 hl 区域偏好
    if language == "auto":
        language = _detect_language(query)

    # ── Plan ──
    plan = agent_plan(query)

    if plan:
        actions = _adjust_format(plan)
    else:
        actions = []

    # 流式推送：正在执行的工具
    for action in actions:
        msg = {"role": "agent", "content": f'正在调用 {action["action_name"]}: "{action["prompt"]}"'}
        yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"

    # ── Act ──
    memory = process_actions(actions, language)

    # ── Reflect (循环直到 LLM 自己判定足够，或触达安全上限) ──
    # 循环本身不做任何"该不该继续/调用什么"的判断——每一轮的决策都来自
    # should_continue() 这次 LLM 调用的结构化输出。MAX_REFLECTION_ITERATIONS
    # 只是防止失控的安全上限，不是预设的执行步数；触达上限会被明确标记为
    # "cap-stop"，与 LLM 主动判定 sufficient=True 的"llm-stop"区分开，方便
    # 排查循环是否在没有 LLM 判断的情况下被迫终止。
    MAX_REFLECTION_ITERATIONS = 5
    reflection_iteration = 0

    while reflection_iteration < MAX_REFLECTION_ITERATIONS:
        reflection_iteration += 1
        decision = should_continue(query, memory)

        if decision["sufficient"]:
            print(f"[loop] LLM 判定信息已足够（第 {reflection_iteration} 轮）：{decision['rationale']}")
            break

        if not decision["actions"]:
            # sufficient=False 但没给出任何补充动作——LLM 认为信息不足，但已无更多可查；
            # 没有动作可执行就没有继续循环的意义，停止并把这个判断留给最终答案去坦白。
            print(f"[loop] LLM 判定信息不足但未给出补充动作（第 {reflection_iteration} 轮），停止：{decision['rationale']}")
            break

        reflect_actions = _adjust_format(decision["actions"])
        for action in reflect_actions:
            msg = {
                "role": "agent",
                "content": (
                    f'补充调用 {action["action_name"]}: "{action["prompt"]}" '
                    f'（原因：{decision["rationale"]}）'
                ),
            }
            yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
        extra_memory = process_actions(reflect_actions, language)
        memory.extend(extra_memory)
    else:
        # while 的 else 分支：循环条件（reflection_iteration < MAX）变为假而自然退出，
        # 即触达安全上限，从未收到 LLM 的 sufficient=True 信号。
        print(f"[loop] 触达安全上限（{MAX_REFLECTION_ITERATIONS} 轮），强制停止——非 LLM 主动判定")

    # ── Answer ──

    if language == "zh":
        lang_instruction = (
            '请全程使用中文回答。所有招式名、道具名、特性名必须使用中文（如"地震"而非"Earthquake"，'
            '"龙爪"而非"Dragon Claw"，"剑舞"而非"Swords Dance"，"讲究头带"而非"Choice Band"）。'
            '所有宝可梦名称必须使用中文（如"烈咬陆鲨"而非"Garchomp"，"铁荆棘"而非"Iron Valiant"，'
            '"黄金怪"而非"Gholdengo"）。参考信息中出现的英文名称，请在回答时全部翻译为中文。'
        )
    else:
        lang_instruction = (
            "Please answer entirely in English. Use English names for all moves, items, abilities, "
            "and Pokémon (e.g. 'Earthquake', 'Choice Band', 'Garchomp'). "
            "Translate any Chinese terms in the references to English. "
            "Do NOT output any Chinese characters under any circumstances — "
            "the reference data may contain Chinese field labels and names, "
            "translate every one of them into English."
        )

    history_str = ""
    if history:
        history_str = "\n## 对话历史\n"
        for turn in history:
            history_str += f"用户：{turn['user']}\n助手：{turn['assistant']}\n\n"

    final_prompt = f"""你是专业的宝可梦对战顾问，基于第九世代（朱/紫）数据回答用户问题。

{lang_instruction}
{history_str}
## 参考信息
{json.dumps(memory, ensure_ascii=False, indent=2)}

## 用户问题
{query}

## 回答要求
- 如果用户问题与宝可梦完全无关（如数学、地理等），只回复"我只能回答宝可梦相关的问题。" / "I can only answer Pokémon-related questions."，不要尝试回答
- 如果用户询问对话历史（如"我之前问过什么"），根据对话历史如实回答，这属于正常的对话交互
- 优先使用参考信息中的数据，参考信息不足时结合自身知识补充
- 回答要专业、准确，适当引用具体数值
- 对战建议要实用，给出具体的招式/道具/EV推荐
- 如果问题超出第九世代范围，明确告知
"""

    completion = client.chat.completions.create(
        model="qwq-plus",
        messages=[{"role": "user", "content": final_prompt}],
        stream=True,
    )

    ended = False
    for chunk in completion:
        # 某些兼容实现首个/末个 chunk 的 choices 可能为空列表，先安全取出
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta

        # 先输出本 chunk 携带的内容：带 finish_reason 的最后一个 chunk 仍可能有 content
        if delta and delta.content:
            msg = {"role": "assistant", "content": delta.content, "thinking": False}
            yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
        elif delta and getattr(delta, "reasoning_content", None):
            msg = {"role": "assistant", "content": delta.reasoning_content, "thinking": True}
            yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"

        # 内容已输出后再判定结束
        if choice.finish_reason is not None:
            yield "event: end\ndata: [DONE]\n\n"
            ended = True
            break

    # 兜底：若流直接耗尽且从未发出结束事件，补发 [DONE]，保证前端解析器收到结束信号
    if not ended:
        yield "event: end\ndata: [DONE]\n\n"

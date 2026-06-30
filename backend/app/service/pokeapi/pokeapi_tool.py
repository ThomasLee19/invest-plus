"""
PokeAPI 工具封装
实时查询 PokeAPI，返回精灵的结构化数据。
对应 CONTEXT.md 中 pokeapi_query 工具的职责：精确数值和结构化事实。
"""

import requests
import time

BASE_URL = "https://pokeapi.co/api/v2"
REQUEST_TIMEOUT = 10
GEN9_VERSION_GROUPS = {"scarlet-violet", "the-teal-mask", "the-indigo-disk"}


def safe_get(url: str) -> dict | None:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[PokeAPI] 请求失败：{url} -> {e}")
        return None


def get_english(entries: list, key: str = "name") -> str:
    for entry in entries:
        if entry.get("language", {}).get("name") == "en":
            return entry.get(key, "")
    return ""


def resolve_pokemon_name(query: str) -> str | None:
    """
    从自然语言 query 解析出 PokeAPI 能识别的精灵 slug。

    PokeAPI 多词精灵名用连字符连接（iron-valiant、great-tusk、mr-mime），
    单取第一个词会把这类名字截断成 iron/great/mr 而查不到。
    这里取 query 开头连续的字母/数字词，生成从长到短的连字符候选，
    逐个探测 /pokemon/{slug}，返回第一个真实命中的 slug；都不中返回 None。

    例：
      "great tusk moveset" → 试 great-tusk-moveset → great-tusk(命中)
      "pikachu base stats" → 试 pikachu-base-stats → pikachu-base → pikachu(命中)
    """
    import re as _re
    # 取开头连续的纯字母/数字词（遇到非词字符即停），最多看前 4 个词
    words = _re.findall(r"[a-z0-9]+", query.lower())[:4]
    if not words:
        return None
    # 从长到短生成候选：great-tusk-moveset, great-tusk, great
    for n in range(len(words), 0, -1):
        slug = "-".join(words[:n])
        if safe_get(f"{BASE_URL}/pokemon/{slug}"):
            return slug
    return None


def query_pokemon(name: str) -> str:
    """
    查询单只精灵的完整信息，返回格式化文本。
    name 支持英文名（小写）或全国图鉴编号。
    """
    name = name.lower().strip()

    data = safe_get(f"{BASE_URL}/pokemon/{name}")
    if not data:
        return f"未找到精灵：{name}，请确认名称是否正确（需使用英文名，如 pikachu）。"

    species_data = safe_get(f"{BASE_URL}/pokemon-species/{name}")
    if not species_data:
        return f"无法获取 {name} 的物种数据。"

    # 基本信息
    name_en = data["name"]
    name_zh = next(
        (n["name"] for n in species_data.get("names", [])
         if n["language"]["name"] == "zh-hans"),
        name_en
    )
    types = " / ".join(t["type"]["name"] for t in data["types"])
    height = data["height"] / 10
    weight = data["weight"] / 10
    genus = get_english(species_data.get("genera", []), key="genus")

    # 种族值
    stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
    stat_map = {"hp": "HP", "attack": "攻击", "defense": "防御",
                "special-attack": "特攻", "special-defense": "特防", "speed": "速度"}
    bst = sum(stats.values())
    stats_str = "、".join(f"{stat_map.get(k, k)} {v}" for k, v in stats.items())

    # 特性
    abilities = []
    for a in data["abilities"]:
        tag = "（隐藏）" if a["is_hidden"] else ""
        abilities.append(f"{a['ability']['name']}{tag}")
    abilities_str = "、".join(abilities)

    # Gen9 技能池
    learnset: dict[str, list] = {"level-up": [], "machine": [], "egg": []}
    for m in data["moves"]:
        move_name = m["move"]["name"]
        for vgd in m["version_group_details"]:
            if vgd["version_group"]["name"] not in GEN9_VERSION_GROUPS:
                continue
            method = vgd["move_learn_method"]["name"]
            if method == "level-up":
                learnset["level-up"].append((vgd["level_learned_at"], move_name))
            elif method == "machine":
                learnset["machine"].append(move_name)
            elif method == "egg":
                learnset["egg"].append(move_name)

    learnset["level-up"].sort()
    level_up_str = ", ".join(f"Lv.{lv} {mv}" for lv, mv in learnset["level-up"]) or "无"
    machine_str = ", ".join(sorted(set(learnset["machine"]))) or "无"
    egg_str = ", ".join(sorted(set(learnset["egg"]))) or "无"

    # 标志
    flags = []
    if species_data.get("is_legendary"):
        flags.append("传说宝可梦")
    if species_data.get("is_mythical"):
        flags.append("幻之宝可梦")
    flags_str = "、".join(flags) if flags else "普通宝可梦"

    result = f"""【{name_zh}（{name_en.capitalize()}）】
分类：{genus} | 属性：{types} | {flags_str}
身高：{height}m | 体重：{weight}kg

种族值（合计 {bst}）：{stats_str}

特性：{abilities_str}

技能池（Gen9）
  升级：{level_up_str}
  TM：{machine_str}
  蛋招：{egg_str}"""

    return result


def query_type_matchup(attacking_type: str, defending_types: str) -> str:
    """
    查询属性克制关系。
    attacking_type: 攻击方属性（如 fire）
    defending_types: 防守方属性，支持双属性用斜杠分隔（如 grass/poison）
    """
    defending_list = [t.strip().lower() for t in defending_types.replace("，", ",").split("/")]

    type_data = safe_get(f"{BASE_URL}/type/{attacking_type.lower()}")
    if not type_data:
        return f"未找到属性：{attacking_type}"

    dmg = type_data["damage_relations"]
    double_damage = {t["name"] for t in dmg["double_damage_to"]}
    half_damage = {t["name"] for t in dmg["half_damage_to"]}
    no_damage = {t["name"] for t in dmg["no_damage_to"]}

    multiplier = 1.0
    for def_type in defending_list:
        if def_type in no_damage:
            multiplier *= 0
        elif def_type in double_damage:
            multiplier *= 2
        elif def_type in half_damage:
            multiplier *= 0.5

    if multiplier == 0:
        effect = "无效（0x）"
    elif multiplier == 0.25:
        effect = "效果极差（0.25x）"
    elif multiplier == 0.5:
        effect = "效果不佳（0.5x）"
    elif multiplier == 1.0:
        effect = "普通效果（1x）"
    elif multiplier == 2.0:
        effect = "效果拔群（2x）"
    elif multiplier == 4.0:
        effect = "效果极佳（4x）"
    else:
        effect = f"{multiplier}x"

    return f"{attacking_type} 属性攻击 {' / '.join(defending_list)} 属性：{effect}"


def pokeapi_query(query_type: str, **kwargs) -> str:
    """
    统一入口。
    query_type: "pokemon" 或 "type_matchup"
    kwargs:
      pokemon: name=<str>
      type_matchup: attacking_type=<str>, defending_types=<str>
    """
    if query_type == "pokemon":
        return query_pokemon(kwargs.get("name", ""))
    elif query_type == "type_matchup":
        return query_type_matchup(
            kwargs.get("attacking_type", ""),
            kwargs.get("defending_types", "")
        )
    else:
        return f"未知查询类型：{query_type}"

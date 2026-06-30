"""
PokeAPI 全量数据拉取脚本
目标：拉取全部 1025 只正代宝可梦（排除 Mega/特殊形态），
      整理为 Markdown 文档，存入 output/ 目录，供后续写入 Elasticsearch。

运行方式：
    pip install requests
    python fetch_pokemon_data.py

输出：
    data/pokemon/pokemon_0001_bulbasaur.md ... data/pokemon/pokemon_1025_pecharunt.md
"""

import requests
import time
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────────────────────
BASE_URL = "https://pokeapi.co/api/v2"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "pokemon"
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_POKEMON_ID = 1025
REQUEST_DELAY = 0.3

# 第九世代（朱/紫）对应的 version-group，用于过滤技能
GEN9_VERSION_GROUPS = {"scarlet-violet", "the-teal-mask", "the-indigo-disk"}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def safe_get(url: str, retries: int = 3) -> dict | None:
    """带重试的 GET 请求"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"  [重试 {attempt+1}/{retries}] {url} -> {e}")
            time.sleep(2 ** attempt)
    print(f"  [失败] 跳过：{url}")
    return None


def get_english(entries: list, key: str = "name") -> str:
    """从多语言列表中取英文值"""
    for entry in entries:
        lang = entry.get("language", {}).get("name", "")
        if lang == "en":
            return entry.get(key, "")
    return ""


def get_flavor_text(entries: list) -> str:
    """取最新版本的英文图鉴描述，去除换行符"""
    en_entries = [e for e in entries if e.get("language", {}).get("name") == "en"]
    if not en_entries:
        return ""
    text = en_entries[-1]["flavor_text"]
    return text.replace("\n", " ").replace("\f", " ").strip()


def stat_name_map(api_name: str) -> str:
    mapping = {
        "hp": "HP",
        "attack": "攻击",
        "defense": "防御",
        "special-attack": "特攻",
        "special-defense": "特防",
        "speed": "速度",
    }
    return mapping.get(api_name, api_name)


def fetch_evolution_chain(evo_url: str) -> str:
    """递归拉取进化链，返回可读的进化路径字符串"""
    if not evo_url:
        return "暂无数据"
    data = safe_get(evo_url)
    if not data:
        return "暂无数据"
    time.sleep(REQUEST_DELAY)

    lines = []

    def parse_chain(node: dict, depth: int = 0):
        species_name = node["species"]["name"]
        details = node.get("evolution_details", [])
        if details:
            detail = details[0]
            conditions = []
            if detail.get("min_level"):
                conditions.append(f"Lv.{detail['min_level']}")
            if detail.get("item"):
                conditions.append(f"使用道具：{detail['item']['name']}")
            if detail.get("held_item"):
                conditions.append(f"持有道具：{detail['held_item']['name']}")
            if detail.get("min_happiness"):
                conditions.append(f"友好度≥{detail['min_happiness']}")
            if detail.get("time_of_day"):
                conditions.append(f"时间：{detail['time_of_day']}")
            if detail.get("known_move"):
                conditions.append(f"学会招式：{detail['known_move']['name']}")
            if detail.get("location"):
                conditions.append(f"地点：{detail['location']['name']}")
            cond_str = "、".join(conditions) if conditions else detail.get("trigger", {}).get("name", "")
            lines.append(f"{'  ' * depth}→ {species_name}（{cond_str}）")
        else:
            lines.append(f"{'  ' * depth}{species_name}")

        for evolves_to in node.get("evolves_to", []):
            parse_chain(evolves_to, depth + 1)

    parse_chain(data["chain"])
    return "\n".join(lines)


# ── 核心：拉取单只精灵并生成 Markdown ────────────────────────────────────────

def fetch_pokemon(pokemon_id: int) -> str | None:
    """
    拉取一只精灵的完整数据，返回 Markdown 字符串。
    数据来源：/pokemon/{id} + /pokemon-species/{id} + evolution_chain URL
    """
    data = safe_get(f"{BASE_URL}/pokemon/{pokemon_id}")
    if not data:
        return None
    time.sleep(REQUEST_DELAY)

    species_data = safe_get(f"{BASE_URL}/pokemon-species/{pokemon_id}")
    if not species_data:
        return None
    time.sleep(REQUEST_DELAY)

    # ── 基本信息 ──
    name_en = data["name"]
    name_zh_entry = next(
        (n["name"] for n in species_data.get("names", [])
         if n["language"]["name"] == "zh-hans"),
        name_en
    )

    pokemon_id_str = str(pokemon_id).zfill(4)
    height_m = data["height"] / 10
    weight_kg = data["weight"] / 10

    # ── Type（属性）──
    types = [t["type"]["name"] for t in data["types"]]
    types_str = " / ".join(types)

    # ── Stat（种族值）──
    stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
    total_bst = sum(stats.values())
    stats_lines = "\n".join(
        f"  - {stat_name_map(k)}：{v}" for k, v in stats.items()
    )

    # ── Ability（特性）──
    abilities = []
    for a in data["abilities"]:
        tag = "（隐藏特性）" if a["is_hidden"] else ""
        abilities.append(f"{a['ability']['name']}{tag}")
    abilities_str = "、".join(abilities)

    # ── 图鉴描述 ──
    flavor_text = get_flavor_text(species_data.get("flavor_text_entries", []))

    # ── 种族分类 ──
    genus = get_english(species_data.get("genera", []), key="genus")

    # ── 特殊标志 ──
    flags = []
    if species_data.get("is_legendary"):
        flags.append("传说宝可梦")
    if species_data.get("is_mythical"):
        flags.append("幻之宝可梦")
    if species_data.get("is_baby"):
        flags.append("宝宝宝可梦")
    flags_str = "、".join(flags) if flags else "普通宝可梦"

    # ── 世代 ──
    generation = species_data.get("generation", {}).get("name", "unknown")

    # ── Learnset（技能池）：仅限第九世代，含升级/TM/蛋招 ──
    learnset: dict[str, list[str]] = {"level-up": [], "machine": [], "egg": []}
    for m in data["moves"]:
        move_name = m["move"]["name"]
        for vgd in m["version_group_details"]:
            if vgd["version_group"]["name"] not in GEN9_VERSION_GROUPS:
                continue
            method = vgd["move_learn_method"]["name"]
            if method == "level-up":
                lv = vgd["level_learned_at"]
                learnset["level-up"].append((lv, move_name))
            elif method == "machine":
                learnset["machine"].append(move_name)
            elif method == "egg":
                learnset["egg"].append(move_name)

    learnset["level-up"].sort()
    level_up_lines = "\n".join(f"  - Lv.{lv} {mv}" for lv, mv in learnset["level-up"]) or "  - 暂无数据"
    machine_lines = "\n".join(f"  - {mv}" for mv in sorted(set(learnset["machine"]))) or "  - 暂无数据"
    egg_lines = "\n".join(f"  - {mv}" for mv in sorted(set(learnset["egg"]))) or "  - 暂无数据"

    # ── Evolution Chain（进化链）──
    evo_url = species_data.get("evolution_chain", {}).get("url", "")
    evo_chain_str = fetch_evolution_chain(evo_url)

    # ── 组装 Markdown ──
    md = f"""# {name_zh_entry}（{name_en.capitalize()}）

## 基本信息
- **全国图鉴编号**：#{pokemon_id_str}
- **分类**：{genus}
- **Type（属性）**：{types_str}
- **身高**：{height_m:.1f} m
- **体重**：{weight_kg:.1f} kg
- **特殊标志**：{flags_str}
- **所属世代**：{generation}

## 图鉴描述
{flavor_text}

## Ability（特性）
{abilities_str}

## Stat（种族值，合计：{total_bst}）
{stats_lines}

## Learnset（技能池，第九世代）

### 升级技能
{level_up_lines}

### TM 技能
{machine_lines}

### 蛋招
{egg_lines}

## Evolution Chain（进化链）
{evo_chain_str}
"""
    return md


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("PokeAPI 全量数据拉取脚本（第九世代）")
    print(f"目标：精灵 #1 ~ #{MAX_POKEMON_ID}")
    print(f"输出目录：{OUTPUT_DIR}")
    print("=" * 60)

    success, skip, fail = 0, 0, 0

    for pid in range(1, MAX_POKEMON_ID + 1):
        existing = list(OUTPUT_DIR.glob(f"pokemon_{str(pid).zfill(4)}_*.md"))
        if existing:
            print(f"[跳过] #{pid} 已存在")
            skip += 1
            continue

        print(f"[{pid}/{MAX_POKEMON_ID}] 正在拉取...", end=" ")
        md = fetch_pokemon(pid)

        if md:
            first_line = md.split("\n")[0]
            en_name = first_line.split("（")[1].rstrip("）").lower() if "（" in first_line else f"pokemon_{pid}"
            filename = f"pokemon_{str(pid).zfill(4)}_{en_name}.md"
            (OUTPUT_DIR / filename).write_text(md, encoding="utf-8")
            print(f"✓ {filename}")
            success += 1
        else:
            print(f"✗ 失败，跳过")
            fail += 1

    print("\n" + "=" * 60)
    print(f"完成！成功：{success}，跳过：{skip}，失败：{fail}")
    print(f"文件保存在：{OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()

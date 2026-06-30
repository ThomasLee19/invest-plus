"""
Smogon 攻略爬取脚本
爬取 Gen9 热门竞技精灵的 Smogon 攻略页面，保存为 Markdown。
数据仅供本地演示用，不提交到 git（已加入 .gitignore）。

运行方式：
    pip install playwright
    playwright install chromium
    python scripts/scrape_smogon.py
"""

import re
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "smogon"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Gen9 热门竞技精灵列表（Smogon URL slug）
POKEMON_LIST = [
    "garchomp", "dragapult", "flutter-mane", "iron-valiant",
    "gholdengo", "roaring-moon", "kingambit", "great-tusk",
    "glimmora", "annihilape", "palafin", "iron-moth",
    "skeledirge", "meowscarada", "iron-hands", "ting-lu",
    "chien-pao", "wo-chien", "chi-yu", "koraidon",
]

BASE_URL = "https://www.smogon.com/dex/sv/pokemon"


def scrape_pokemon(page, slug: str) -> str | None:
    url = f"{BASE_URL}/{slug}/"
    print(f"  爬取：{url}")

    try:
        page.goto(url, timeout=30000)
        # 等待攻略内容加载（Overview 段落出现）
        page.wait_for_selector(".DexPokemonStrategyOverview, .overview, [class*='Overview']", timeout=15000)
    except Exception:
        # 降级：等待固定时间
        time.sleep(5)

    # 尝试提取页面里的 JSON 数据（Smogon 把数据注入到 window 变量）
    try:
        data = page.evaluate("""() => {
            // 尝试几种可能的数据位置
            if (window.smogon) return JSON.stringify(window.smogon);
            if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__);
            // 查找页面中所有 script 标签的内容
            const scripts = Array.from(document.querySelectorAll('script[type="application/json"]'));
            if (scripts.length > 0) return scripts[0].textContent;
            return null;
        }""")
        if data:
            print(f"    找到 JSON 数据，长度：{len(data)}")
    except Exception:
        data = None

    # 提取页面文本内容
    try:
        content = page.evaluate("""() => {
            // 移除导航、页眉页脚等
            const remove = document.querySelectorAll('nav, header, footer, script, style');
            remove.forEach(el => el.remove());

            // 尝试获取主要内容区域
            const main = document.querySelector('main, .main, [class*="Pokemon"], [class*="Dex"]');
            if (main) return main.innerText;
            return document.body.innerText;
        }""")
    except Exception as e:
        print(f"    提取内容失败：{e}")
        return None

    if not content or len(content) < 100:
        print(f"    内容太少，可能未加载完成")
        return None

    # 清理文本
    lines = [line.strip() for line in content.splitlines()]
    lines = [line for line in lines if line]
    clean_content = "\n".join(lines)

    # 组装 Markdown
    md = f"# {slug.replace('-', ' ').title()} - Smogon Gen9 Strategy\n\n"
    md += f"Source: {url}\n\n"
    md += clean_content

    return md


def main():
    print("=" * 60)
    print("Smogon 攻略爬取脚本（Gen9 SV）")
    print(f"目标：{len(POKEMON_LIST)} 只热门竞技精灵")
    print(f"输出目录：{OUTPUT_DIR}")
    print("=" * 60)

    success, skip, fail = 0, 0, 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for slug in POKEMON_LIST:
            out_path = OUTPUT_DIR / f"{slug}.md"
            if out_path.exists():
                print(f"[跳过] {slug} 已存在")
                skip += 1
                continue

            print(f"[{success + fail + 1}/{len(POKEMON_LIST)}] {slug}")
            md = scrape_pokemon(page, slug)

            if md:
                out_path.write_text(md, encoding="utf-8")
                print(f"  ✓ 保存：{out_path.name}（{len(md)} 字符）")
                success += 1
            else:
                print(f"  ✗ 失败")
                fail += 1

            time.sleep(2)  # 礼貌延迟

        browser.close()

    print("\n" + "=" * 60)
    print(f"完成！成功：{success}，跳过：{skip}，失败：{fail}")
    print("=" * 60)


if __name__ == "__main__":
    main()

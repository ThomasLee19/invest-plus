"""
Recent news snapshot fetcher (yfinance).

yfinance's Ticker(ticker).news returns live data, but the RAG corpus needs
static indexable content, not a live call — so this snapshots a handful of
recent news items per ticker into local markdown files.

Run:
    python scripts/fetch_news.py

Output:
    data/news/<ticker>/<pubDate>_<id>.md
"""

from pathlib import Path

import yfinance as yf

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "news"

TICKERS = ["AAPL", "MSFT", "GOOGL"]
MAX_ITEMS_PER_TICKER = 8


def render_news_md(ticker: str, item: dict) -> str | None:
    content = item.get("content", {})
    if content.get("contentType") != "STORY":
        return None

    title = content.get("title", "").strip()
    summary = (content.get("summary") or content.get("description") or "").strip()
    if not title or not summary:
        return None

    pub_date = content.get("pubDate", "")
    provider = content.get("provider", {}).get("displayName", "Unknown")
    url = content.get("canonicalUrl", {}).get("url", "")

    return f"""# {title}

- **Ticker**: {ticker}
- **Published**: {pub_date}
- **Source**: {provider}
- **URL**: {url}

{summary}
"""


def fetch_ticker_news(ticker: str) -> int:
    dest_dir = OUTPUT_DIR / ticker
    dest_dir.mkdir(parents=True, exist_ok=True)

    news = yf.Ticker(ticker).news
    saved = 0

    for item in news[:MAX_ITEMS_PER_TICKER]:
        md = render_news_md(ticker, item)
        if md is None:
            continue

        item_id = item.get("id", "unknown")
        pub_date = item.get("content", {}).get("pubDate", "")[:10] or "unknown-date"
        filename = f"{pub_date}_{item_id}.md"
        dest_path = dest_dir / filename

        if dest_path.exists():
            print(f"  [skip] {filename} already exists")
            continue

        dest_path.write_text(md, encoding="utf-8")
        print(f"  [ok] {filename}")
        saved += 1

    return saved


def main():
    print("=" * 60)
    print("yfinance news snapshot fetcher")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Output dir: {OUTPUT_DIR}")
    print("=" * 60)

    total = 0
    for ticker in TICKERS:
        print(f"\n[{ticker}]")
        total += fetch_ticker_news(ticker)

    print("\n" + "=" * 60)
    print(f"Done. Saved {total} news items")
    print(f"Files saved under: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()

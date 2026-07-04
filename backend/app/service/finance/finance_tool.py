"""
Finance 工具封装
实时查询 yfinance，返回股票的结构化数据。
对应未来 finance_query 工具的职责：精确数值和结构化事实（行情、基本面、新闻）。
"""

import contextlib
import functools
import io


@contextlib.contextmanager
def _quiet():
    """yfinance 对无效代码会在 stderr 打印一条 404 噪音日志，这里临时屏蔽。"""
    with contextlib.redirect_stderr(io.StringIO()):
        yield


def _is_valid_ticker(info: dict, history) -> bool:
    """无效代码：.info 退化为只有 1-2 个 None 字段的字典，且 .history 为空。"""
    return not history.empty or len(info) > 2


# yfinance 底层走 requests，Ticker()/.info/.history() 本身不接受 timeout 参数；
# 显式传一个共享 requests session（带 timeout）是这个版本里让请求不至于无限挂起
# 的干净做法，对 .info/.history/.news 三处调用都生效。
_YF_TIMEOUT_SECONDS = 10


def _yf_session():
    import requests
    session = requests.Session()
    session.request = functools.partial(session.request, timeout=_YF_TIMEOUT_SECONDS)
    return session


def _load_ticker(ticker: str):
    """加载一次 yf.Ticker + .info + .history，供 quote/fundamentals/news 共用，避免重复请求。"""
    import yfinance as yf
    with _quiet():
        t = yf.Ticker(ticker, session=_yf_session())
        info = t.info
        history = t.history(period="5d")
    return t, info, history


def query_quote(ticker: str) -> str:
    """
    查询股票的实时行情：最新价、涨跌幅、成交量等。
    ticker: 股票代码，如 AAPL
    """
    ticker = ticker.upper().strip()

    try:
        t, info, history = _load_ticker(ticker)
    except Exception as e:
        print(f"[FinanceTool] 行情请求失败：{ticker} -> {e}")
        return "行情服务暂时不可用，请稍后再试。"

    if not _is_valid_ticker(info, history):
        return f"未找到股票代码：{ticker}，请确认代码是否正确（如 AAPL、MSFT）。"

    try:
        fast_info = t.fast_info
        last_price = fast_info["lastPrice"]
        prev_close = fast_info["previousClose"]
        if last_price is None or prev_close is None:
            # fast_info can report a ticker as present with null price fields
            # (e.g. "SPX" - a colloquial name yfinance half-recognizes but has
            # no real quote for). Route into the same history-based fallback
            # below instead of subtracting None - None later.
            raise ValueError("fast_info has no price data")
        currency = fast_info.get("currency", "USD")
        day_high = fast_info.get("dayHigh")
        day_low = fast_info.get("dayLow")
        volume = fast_info.get("lastVolume")
    except Exception:
        if history.empty:
            return f"未找到股票代码：{ticker} 的行情数据。"
        last_row = history.iloc[-1]
        last_price = last_row["Close"]
        prev_close = history.iloc[-2]["Close"] if len(history) > 1 else last_row["Open"]
        currency = info.get("currency", "USD")
        day_high = last_row["High"]
        day_low = last_row["Low"]
        volume = last_row["Volume"]

    change = last_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    direction = "+" if change >= 0 else ""

    name = info.get("shortName") or info.get("longName") or ticker

    day_high_str = f"{day_high:.2f}" if day_high is not None else "未知"
    day_low_str = f"{day_low:.2f}" if day_low is not None else "未知"
    volume_str = f"{volume:,}" if volume is not None else "未知"

    result = f"""【{name}（{ticker}）】
最新价：{last_price:.2f} {currency}
涨跌：{direction}{change:.2f} （{direction}{change_pct:.2f}%）
昨收：{prev_close:.2f} | 最高：{day_high_str} | 最低：{day_low_str}
成交量：{volume_str}"""

    return result


def query_fundamentals(ticker: str) -> str:
    """
    查询股票的基本面数据：市值、市盈率、所属行业等。
    ticker: 股票代码，如 AAPL
    """
    ticker = ticker.upper().strip()

    try:
        t, info, history = _load_ticker(ticker)
    except Exception as e:
        print(f"[FinanceTool] 基本面请求失败：{ticker} -> {e}")
        return "行情服务暂时不可用，请稍后再试。"

    if not _is_valid_ticker(info, history):
        return f"未找到股票代码：{ticker}，请确认代码是否正确（如 AAPL、MSFT）。"

    name = info.get("shortName") or info.get("longName") or ticker
    sector = info.get("sector", "未知")
    industry = info.get("industry", "未知")
    market_cap = info.get("marketCap")
    market_cap_str = f"{market_cap / 1e8:,.1f} 亿" if market_cap else "未知"
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    dividend_yield = info.get("dividendYield")
    eps = info.get("trailingEps")
    beta = info.get("beta")
    week_high = info.get("fiftyTwoWeekHigh")
    week_low = info.get("fiftyTwoWeekLow")
    currency = info.get("currency", "USD")

    pe_str = f"{trailing_pe:.2f}" if trailing_pe is not None else "未知"
    fpe_str = f"{forward_pe:.2f}" if forward_pe is not None else "未知"
    # yfinance 各版本对 dividendYield 的单位不一致：有的返回小数形式的比例
    # （如 0.0044 代表 0.44%），有的已经是百分比数值（如 0.44）。< 1 时按比例
    # 处理（*100），>= 1 时视为已是百分比，避免两种格式下都直接拼 "%" 导致
    # 数值缩小 100 倍或读起来像是股息率超过 100%。
    if dividend_yield is not None:
        dividend_yield_pct = dividend_yield * 100 if dividend_yield < 1 else dividend_yield
        div_str = f"{dividend_yield_pct:.2f}%"
    else:
        div_str = "无"
    eps_str = f"{eps:.2f}" if eps is not None else "未知"
    beta_str = f"{beta:.2f}" if beta is not None else "未知"
    range_str = (
        f"{week_low:.2f} - {week_high:.2f} {currency}"
        if week_low is not None and week_high is not None
        else "未知"
    )

    result = f"""【{name}（{ticker}）基本面】
行业：{sector} / {industry}
市值：{market_cap_str} {currency}
市盈率（TTM）：{pe_str} | 市盈率（预期）：{fpe_str}
每股收益（TTM）：{eps_str} | 股息率：{div_str}
Beta：{beta_str}
52周区间：{range_str}"""

    return result


def query_news(ticker: str, limit: int = 5) -> str:
    """
    查询股票的近期新闻标题。
    ticker: 股票代码，如 AAPL
    limit: 返回的新闻条数，默认 5
    """
    ticker = ticker.upper().strip()

    t, info, history = _load_ticker(ticker)

    if not _is_valid_ticker(info, history):
        return f"未找到股票代码：{ticker}，请确认代码是否正确（如 AAPL、MSFT）。"

    with _quiet():
        try:
            news_items = t.news
        except Exception as e:
            print(f"[FinanceTool] 新闻请求失败：{ticker} -> {e}")
            news_items = []

    if not news_items:
        return f"未找到 {ticker} 的近期新闻。"

    name = info.get("shortName") or info.get("longName") or ticker
    lines = [f"【{name}（{ticker}）近期新闻】"]
    for item in news_items[:limit]:
        content = item.get("content", item) if isinstance(item, dict) else item
        if not isinstance(content, dict):
            content = {}
        title = content.get("title", "（无标题）")
        pub_date = content.get("pubDate", "")
        lines.append(f"- {title}（{pub_date}）")

    return "\n".join(lines)


def finance_query(query_type: str, **kwargs) -> str:
    """
    统一入口。
    query_type: "quote"、"fundamentals" 或 "news"
    kwargs:
      quote: ticker=<str>
      fundamentals: ticker=<str>
      news: ticker=<str>, limit=<int>（可选）
    """
    if query_type == "quote":
        return query_quote(kwargs.get("ticker", ""))
    elif query_type == "fundamentals":
        return query_fundamentals(kwargs.get("ticker", ""))
    elif query_type == "news":
        return query_news(kwargs.get("ticker", ""), kwargs.get("limit", 5))
    else:
        return f"未知查询类型：{query_type}"


if __name__ == "__main__":
    print(finance_query("quote", ticker="AAPL"))
    print()
    print(finance_query("fundamentals", ticker="AAPL"))
    print()
    print(finance_query("news", ticker="AAPL", limit=3))
    print()
    print(finance_query("quote", ticker="ZZZZINVALID"))

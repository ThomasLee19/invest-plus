"""
Unit tests for backend/app/service/finance/finance_tool.py.

finance_tool.py only imports yfinance/requests lazily inside its functions
(no module-level import), so this suite can import it directly without any
sys.modules stubbing.

Coverage: query_quote/query_fundamentals must degrade gracefully (return a
friendly string) instead of raising when yfinance itself fails outright
(e.g. a transient network error inside _load_ticker), matching the existing
try/except behavior already present in query_news.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from app.service.finance import finance_tool  # noqa: E402


class FinanceToolNetworkFailureTests(unittest.TestCase):
    """A yfinance/network failure inside _load_ticker must not raise out of
    query_quote/query_fundamentals; it should degrade to a friendly message."""

    def test_query_quote_degrades_on_load_ticker_failure(self):
        with patch.object(
            finance_tool, "_load_ticker", side_effect=ConnectionError("boom")
        ):
            result = finance_tool.query_quote("AAPL")

        self.assertIsInstance(result, str)
        self.assertIn("暂时不可用", result)

    def test_query_fundamentals_degrades_on_load_ticker_failure(self):
        with patch.object(
            finance_tool, "_load_ticker", side_effect=ConnectionError("boom")
        ):
            result = finance_tool.query_fundamentals("AAPL")

        self.assertIsInstance(result, str)
        self.assertIn("暂时不可用", result)

    def test_finance_query_quote_entrypoint_degrades_too(self):
        with patch.object(
            finance_tool, "_load_ticker", side_effect=TimeoutError("timed out")
        ):
            result = finance_tool.finance_query("quote", ticker="AAPL")

        self.assertIsInstance(result, str)
        self.assertIn("暂时不可用", result)


class TickerCacheTests(unittest.TestCase):
    """_load_ticker caches per-ticker results for _TICKER_CACHE_TTL_SECONDS.

    Reflect-loop dedup (seen_actions/seen_prompts in agent.py) only matches on
    literal prompt text, so a differently-worded prompt resolving to the same
    ticker within one conversation would otherwise trigger a fresh yfinance
    call every time. This cache fixes that at the _load_ticker layer."""

    def setUp(self):
        finance_tool._ticker_cache.clear()

    def _patch_yfinance(self):
        history_mock = MagicMock()
        history_mock.empty = False
        ticker_mock = MagicMock()
        ticker_mock.info = {"symbol": "AAPL", "regularMarketPrice": 200}
        ticker_mock.history.return_value = history_mock
        ticker_cls = MagicMock(return_value=ticker_mock)
        return patch("yfinance.Ticker", ticker_cls), ticker_cls

    def test_second_call_within_ttl_skips_network(self):
        patcher, ticker_cls = self._patch_yfinance()
        with patcher:
            finance_tool._load_ticker("AAPL")
            finance_tool._load_ticker("AAPL")

        ticker_cls.assert_called_once()

    def test_different_tickers_are_not_conflated(self):
        patcher, ticker_cls = self._patch_yfinance()
        with patcher:
            finance_tool._load_ticker("AAPL")
            finance_tool._load_ticker("MSFT")

        self.assertEqual(ticker_cls.call_count, 2)

    def test_cache_expires_after_ttl(self):
        patcher, ticker_cls = self._patch_yfinance()
        fake_now = [1000.0]
        with patcher, patch.object(finance_tool.time, "monotonic", lambda: fake_now[0]):
            finance_tool._load_ticker("AAPL")
            fake_now[0] += finance_tool._TICKER_CACHE_TTL_SECONDS + 1
            finance_tool._load_ticker("AAPL")

        self.assertEqual(ticker_cls.call_count, 2)


if __name__ == "__main__":
    unittest.main()

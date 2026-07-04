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
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()

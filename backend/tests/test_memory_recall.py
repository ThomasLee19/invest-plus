"""Unit tests for the recall path added to agent.py:
  - _extract_tickers_loose (CJK-tolerant ticker extraction), and
  - recall_all_conclusions (denylist filtering + multi-ticker merge + no-DB-when-empty).

Same zero-third-party-deps import discipline as test_agent_loop.py: all external
SDKs are stubbed in sys.modules before importing agent.py. recall_conclusion_facts
is patched on the real service.memory.conclusion module (agent lazily imports it
from there at call time), so no DB is ever touched.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

_backend_dir = Path(__file__).parent.parent
_app_dir = _backend_dir / "app"
for _p in (str(_backend_dir), str(_app_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/compatible-mode/v1")

# Stub the third-party SDKs agent.py imports at load time (mirror test_agent_loop.py).
for _name, _attr in (("openai", "OpenAI"), ("dotenv", None), ("dashscope", None),
                     ("elasticsearch", "Elasticsearch"), ("xxhash", None), ("bs4", None)):
    if _name not in sys.modules:
        _m = types.ModuleType(_name)
        sys.modules[_name] = _m
if not hasattr(sys.modules["openai"], "OpenAI"):
    sys.modules["openai"].OpenAI = lambda *a, **k: None
if not hasattr(sys.modules["dotenv"], "load_dotenv"):
    sys.modules["dotenv"].load_dotenv = lambda *a, **k: False
if not hasattr(sys.modules["dashscope"], "TextReRank"):
    sys.modules["dashscope"].TextReRank = type("T", (), {"call": staticmethod(lambda *a, **k: None)})
if not hasattr(sys.modules["elasticsearch"], "Elasticsearch"):
    class _E:  # pragma: no cover
        def __init__(self, *a, **k):
            pass
    sys.modules["elasticsearch"].Elasticsearch = _E
if not hasattr(sys.modules["xxhash"], "xxh64"):
    sys.modules["xxhash"].xxh64 = lambda *a, **k: types.SimpleNamespace(hexdigest=lambda: "0")
if not hasattr(sys.modules["bs4"], "BeautifulSoup"):
    sys.modules["bs4"].BeautifulSoup = type("B", (), {})
    sys.modules["bs4"].NavigableString = type("N", (str,), {})
if "app.database.knowledgebase_operations" not in sys.modules:
    _kb = types.ModuleType("app.database.knowledgebase_operations")
    _kb.get_latest_user_upload = lambda user_id: None
    sys.modules["app.database.knowledgebase_operations"] = _kb

# utils.database stub so service.memory.conclusion imports without a real engine
# (agent.recall_all_conclusions lazily imports recall_conclusion_facts from it).
if "utils.database" not in sys.modules:
    _fake_db = types.ModuleType("utils.database")
    _fake_db.SessionLocal = lambda *a, **k: None
    sys.modules["utils.database"] = _fake_db

from app.service.agent import agent  # noqa: E402
from service.memory import conclusion as conclusion_mod  # noqa: E402


class ExtractTickersLooseTests(unittest.TestCase):
    """CJK-tolerant extraction: the whole reason the recall path does NOT reuse
    finance_tool's \\b-anchored _TICKER_RE (which misses tickers glued to Chinese)."""

    def test_ticker_glued_to_leading_chinese(self):
        self.assertEqual(agent._extract_tickers_loose("分析一下AAPL"), ["AAPL"])

    def test_ticker_glued_to_trailing_chinese(self):
        self.assertEqual(agent._extract_tickers_loose("AAPL的股价怎么样"), ["AAPL"])

    def test_multiple_spaced_tickers_preserved_and_deduped(self):
        self.assertEqual(agent._extract_tickers_loose("对比 AAPL 和 MSFT 和 AAPL"), ["AAPL", "MSFT"])

    def test_overlong_uppercase_run_yields_no_ticker(self):
        # A 7-letter all-caps run has no 1-5 window that isn't flanked by another
        # letter, so nothing is extracted (avoids splitting a long token).
        self.assertEqual(agent._extract_tickers_loose("AAPLABC"), [])

    def test_lowercase_letter_glued_before_ticker_blocks_match(self):
        # A latin lowercase letter immediately before the run fails the (?<![A-Za-z])
        # lookbehind -- so it isn't mistaken for a ticker (unlike CJK adjacency).
        self.assertEqual(agent._extract_tickers_loose("xAAPL"), [])


class RecallAllConclusionsTests(unittest.TestCase):
    def test_multi_ticker_recall_is_merged_per_candidate(self):
        def _fake_recall(ticker, fact_types=None):
            return [{"ticker": ticker, "fact_text": f"fact-{ticker}"}]

        with patch.object(conclusion_mod, "recall_conclusion_facts", side_effect=_fake_recall) as m:
            out = agent.recall_all_conclusions("对比 AAPL 和 MSFT")
        self.assertEqual({d["ticker"] for d in out}, {"AAPL", "MSFT"})
        self.assertEqual(m.call_count, 2)  # one recall per candidate, not just the first

    def test_cjk_tight_query_triggers_recall(self):
        with patch.object(
            conclusion_mod, "recall_conclusion_facts",
            return_value=[{"ticker": "AAPL", "fact_text": "毛利率提升"}],
        ) as m:
            out = agent.recall_all_conclusions("分析一下AAPL")
        m.assert_called_once_with("AAPL", fact_types=None)
        self.assertEqual(out[0]["ticker"], "AAPL")

    def test_spaced_financial_acronym_is_denylisted_no_db_query(self):
        # "什么是 ETF": ETF is extracted as a candidate but denylisted -> no recall.
        with patch.object(conclusion_mod, "recall_conclusion_facts") as m:
            out = agent.recall_all_conclusions("什么是 ETF")
        m.assert_not_called()
        self.assertEqual(out, [])

    def test_pure_concept_question_no_candidate_no_db_query(self):
        with patch.object(conclusion_mod, "recall_conclusion_facts") as m:
            out = agent.recall_all_conclusions("什么是市盈率")
        m.assert_not_called()
        self.assertEqual(out, [])


class FinanceToolBoundaryUnchangedTests(unittest.TestCase):
    """Guard: the recall additions must not have perturbed finance_tool's
    ticker constants. (The authoritative regression suite is
    test_agent_loop.py::FinanceToolTickerExtractionTests; this is a fast
    same-file smoke check.)"""

    def test_finance_ticker_re_and_stopwords_unchanged(self):
        self.assertEqual(agent._TICKER_RE.pattern, r"\b[A-Z]{1,5}\b")
        self.assertEqual(agent._TICKER_STOPWORDS, {"I", "A", "US", "CEO", "PE", "EPS"})

    def test_recall_denylist_supersets_stopwords_without_dead_MandA(self):
        self.assertTrue(agent._TICKER_STOPWORDS <= agent._RECALL_TICKER_DENYLIST)
        self.assertIn("ETF", agent._RECALL_TICKER_DENYLIST)
        self.assertNotIn("M&A", agent._RECALL_TICKER_DENYLIST)


if __name__ == "__main__":
    unittest.main()

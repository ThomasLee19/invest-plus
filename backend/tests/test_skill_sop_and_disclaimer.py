"""
Unit tests for Track 2 (Skill SOP library + disclaimer), all mock-LLM / no network.

Covers:
  - SOP file loading & frontmatter parsing (load_skill / _load_all_skills /
    _parse_skill_frontmatter) for all four SOP files
  - classify_skill(): code-enforced truncation to 2 when the LLM returns >=3,
    the empty (no-hit) case, invalid-name filtering, dedup, and graceful
    degradation to [] on LLM/parse failure
  - _append_disclaimer(): bilingual text keyed on the language param
  - disclaimer emission on BOTH final_answer() `event: end` paths (normal
    finish_reason termination AND the stream-exhausted fallback), asserted
    independently

Same zero-installed-packages / zero-network design as test_agent_loop.py: the
heavy third-party deps agent.py imports are stubbed via sys.modules *before*
agent.py is imported, and the LLM-calling boundary (_llm_json / _get_llm_client)
is mocked per test.
"""
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Stub external deps so agent.py imports cleanly with no installs/network ──
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/compatible-mode/v1")

if "openai" not in sys.modules:
    _fake_openai = types.ModuleType("openai")

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    _fake_openai.OpenAI = _FakeOpenAI
    sys.modules["openai"] = _fake_openai

if "dotenv" not in sys.modules:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *a, **kw: False
    sys.modules["dotenv"] = _fake_dotenv

if "dashscope" not in sys.modules:
    _fake_dashscope = types.ModuleType("dashscope")

    class _FakeTextReRank:
        @staticmethod
        def call(*args, **kwargs):
            raise NotImplementedError("dashscope.TextReRank.call must be mocked per-test")

    _fake_dashscope.TextReRank = _FakeTextReRank
    sys.modules["dashscope"] = _fake_dashscope

if "elasticsearch" not in sys.modules:
    _fake_es_module = types.ModuleType("elasticsearch")

    class _FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            pass

    _fake_es_module.Elasticsearch = _FakeElasticsearch
    sys.modules["elasticsearch"] = _fake_es_module

if "app.database.knowledgebase_operations" not in sys.modules:
    _fake_kb_ops = types.ModuleType("app.database.knowledgebase_operations")
    _fake_kb_ops.get_latest_user_upload = lambda user_id: None
    sys.modules["app.database.knowledgebase_operations"] = _fake_kb_ops

from app.service.agent import agent  # noqa: E402  (import after stubbing)


# ── SSE parsing helpers ──────────────────────────────────────────────────────

def _assistant_messages(events):
    """Extract parsed payloads of assistant token events (role=assistant)."""
    out = []
    for e in events:
        if '"role": "assistant"' not in e:
            continue
        payload = json.loads(e.split("data: ", 1)[1].strip())
        if payload.get("role") == "assistant":
            out.append(payload)
    return out


def _chunk(content, finish_reason):
    """Build one streaming chunk mimicking the OpenAI SDK shape agent.py reads."""
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(
            delta=types.SimpleNamespace(content=content, reasoning_content=None),
            finish_reason=finish_reason,
        )]
    )


class SkillSOPLoadingTests(unittest.TestCase):
    """The four SOP markdown files load and parse into the expected shape."""

    EXPECTED = {
        "valuation": ["P/E", "PEG"],
        "financial_statement": ["ROE"],
        "industry_comparison": ["对比"],
        "risk_scan": ["风险"],
    }

    def test_all_four_skills_load_in_declared_order(self):
        skills = agent._load_all_skills()
        self.assertEqual([s["name"] for s in skills], agent._SKILL_NAMES)
        self.assertEqual(len(skills), 4)

    def test_each_skill_has_frontmatter_and_body(self):
        for name in agent._SKILL_NAMES:
            skill = agent.load_skill(name)
            self.assertIsNotNone(skill, f"{name} failed to load")
            self.assertEqual(skill["name"], name)
            self.assertTrue(skill["description"], f"{name} missing description")
            self.assertIsInstance(skill["trigger_keywords"], list)
            self.assertGreater(len(skill["trigger_keywords"]), 3, f"{name} too few keywords")
            self.assertGreater(len(skill["body"]), 200, f"{name} body too short")

    def test_body_mentions_domain_indicators(self):
        for name, needles in self.EXPECTED.items():
            skill = agent.load_skill(name)
            for needle in needles:
                self.assertIn(
                    needle, skill["body"] + " ".join(skill["trigger_keywords"]),
                    f"{name} missing expected indicator {needle}",
                )

    def test_load_skill_unknown_name_returns_none(self):
        self.assertIsNone(agent.load_skill("does_not_exist"))

    def test_load_skill_missing_file_returns_none_gracefully(self):
        # Force an unreadable path: patch the skills dir to somewhere empty so the
        # read raises OSError and load_skill degrades to None (not raises).
        with patch.object(agent, "_SKILLS_DIR", agent._SKILLS_DIR / "no_such_subdir"):
            self.assertIsNone(agent.load_skill("valuation"))

    def test_parse_frontmatter_rejects_malformed(self):
        self.assertIsNone(agent._parse_skill_frontmatter("no frontmatter here"))
        self.assertIsNone(agent._parse_skill_frontmatter("---\nname: x\n(no closing)"))

    def test_parse_frontmatter_extracts_keyword_list(self):
        raw = (
            "---\n"
            "name: demo\n"
            "description: a demo skill\n"
            "trigger_keywords:\n"
            "  - alpha\n"
            "  - beta\n"
            "  - gamma\n"
            "---\n"
            "Body text that is reasonably long enough to be a real body." * 5
        )
        parsed = agent._parse_skill_frontmatter(raw)
        self.assertEqual(parsed["name"], "demo")
        self.assertEqual(parsed["description"], "a demo skill")
        self.assertEqual(parsed["trigger_keywords"], ["alpha", "beta", "gamma"])
        self.assertTrue(parsed["body"].startswith("Body text"))


class ClassifySkillTests(unittest.TestCase):
    """classify_skill() deterministic post-processing around the LLM call."""

    def _run(self, llm_payload):
        with patch.object(agent, "_llm_json", return_value=json.dumps(llm_payload)):
            return agent.classify_skill("AAPL 现在估值贵不贵，和同行比怎么样，风险大不大")

    def test_truncates_to_two_when_llm_returns_three(self):
        # Code-enforced cap: even though the LLM (in violation of the prompt)
        # returns three valid categories, only the first two survive.
        result = self._run({"skill_hits": ["valuation", "financial_statement", "industry_comparison"]})
        self.assertEqual(result, ["valuation", "financial_statement"])
        self.assertEqual(len(result), 2)

    def test_truncates_to_two_when_llm_returns_all_four(self):
        result = self._run({"skill_hits": agent._SKILL_NAMES})
        self.assertEqual(len(result), 2)
        self.assertEqual(result, agent._SKILL_NAMES[:2])

    def test_empty_list_when_no_hit(self):
        self.assertEqual(self._run({"skill_hits": []}), [])

    def test_single_hit_passes_through(self):
        self.assertEqual(self._run({"skill_hits": ["risk_scan"]}), ["risk_scan"])

    def test_invalid_names_filtered_out(self):
        self.assertEqual(self._run({"skill_hits": ["bogus", "valuation", "also_fake"]}), ["valuation"])

    def test_duplicate_names_deduped(self):
        self.assertEqual(self._run({"skill_hits": ["valuation", "valuation"]}), ["valuation"])

    def test_missing_key_returns_empty(self):
        self.assertEqual(self._run({"something_else": ["valuation"]}), [])

    def test_non_list_value_returns_empty(self):
        self.assertEqual(self._run({"skill_hits": "valuation"}), [])

    def test_malformed_json_returns_empty(self):
        with patch.object(agent, "_llm_json", return_value="}{ not json"):
            self.assertEqual(agent.classify_skill("x"), [])

    def test_llm_exception_degrades_to_empty(self):
        with patch.object(agent, "_llm_json", side_effect=RuntimeError("boom")):
            self.assertEqual(agent.classify_skill("x"), [])

    def test_classifier_prompt_lists_candidate_categories(self):
        captured = {}

        def _capture(prompt):
            captured["prompt"] = prompt
            return json.dumps({"skill_hits": []})

        with patch.object(agent, "_llm_json", side_effect=_capture):
            agent.classify_skill("some finance question")
        for name in agent._SKILL_NAMES:
            self.assertIn(name, captured["prompt"])
        self.assertIn("JSON", captured["prompt"])


class AppendDisclaimerTests(unittest.TestCase):
    """_append_disclaimer() text is language-keyed and non-empty."""

    def test_chinese_disclaimer(self):
        zh = agent._append_disclaimer("zh")
        self.assertIn("免责声明", zh)
        self.assertIn("投资", zh)
        self.assertTrue(zh.strip())

    def test_english_disclaimer(self):
        en = agent._append_disclaimer("en")
        self.assertIn("Disclaimer", en)
        self.assertIn("investment advice", en)

    def test_languages_differ(self):
        self.assertNotEqual(agent._append_disclaimer("zh"), agent._append_disclaimer("en"))

    def test_non_zh_falls_back_to_english(self):
        # lang_instruction pattern: anything that isn't "zh" is treated as English.
        self.assertEqual(agent._append_disclaimer("auto"), agent._append_disclaimer("en"))


class DisclaimerEmissionTests(unittest.TestCase):
    """The disclaimer is emitted on BOTH final_answer() event:end paths."""

    def _drive(self, chunks, language):
        """Run final_answer() down to the Answer stream with tools disabled, the
        LLM client faked to yield `chunks`, and collect the SSE events.

        Patches _get_llm_client directly (per its docstring's recommendation)
        rather than the OpenAI class, since _get_llm_client caches its client
        globally and class-patching would be defeated by a cached instance."""
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda *a, **k: iter(chunks))
            )
        )
        with patch.object(agent, "agent_plan", return_value=None), \
             patch.object(agent, "_get_llm_client", return_value=fake_client):
            return list(agent.final_answer("介绍一下你自己", language=language))

    def test_disclaimer_on_normal_finish_reason_path_zh(self):
        # finish_reason="stop" drives the in-loop termination branch.
        events = self._drive([_chunk("这是正文回答。", "stop")], language="zh")

        self.assertEqual(events[-1], "event: end\ndata: [DONE]\n\n")
        # Exactly one end event => single termination path taken.
        self.assertEqual(sum(1 for e in events if e.startswith("event: end")), 1)

        msgs = _assistant_messages(events)
        self.assertGreaterEqual(len(msgs), 2)  # body + disclaimer
        last = msgs[-1]
        self.assertEqual(last["content"], agent._append_disclaimer("zh"))
        self.assertIs(last["thinking"], False)  # must persist into model_answer
        # Disclaimer is the last event before the end sentinel.
        self.assertIn('"role": "assistant"', events[-2])

    def test_disclaimer_on_stream_exhausted_fallback_path_en(self):
        # finish_reason=None on every chunk => the in-loop branch never fires,
        # the `if not ended` fallback must still append the disclaimer + end.
        events = self._drive([_chunk("answer body", None)], language="en")

        self.assertEqual(events[-1], "event: end\ndata: [DONE]\n\n")
        self.assertEqual(sum(1 for e in events if e.startswith("event: end")), 1)

        msgs = _assistant_messages(events)
        self.assertGreaterEqual(len(msgs), 2)
        last = msgs[-1]
        self.assertEqual(last["content"], agent._append_disclaimer("en"))
        self.assertIs(last["thinking"], False)
        self.assertIn('"role": "assistant"', events[-2])

    def test_disclaimer_language_follows_final_answer_language(self):
        zh_events = self._drive([_chunk("正文", "stop")], language="zh")
        en_events = self._drive([_chunk("body", "stop")], language="en")
        self.assertEqual(_assistant_messages(zh_events)[-1]["content"], agent._append_disclaimer("zh"))
        self.assertEqual(_assistant_messages(en_events)[-1]["content"], agent._append_disclaimer("en"))


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for the agent loop's LLM-driven decision logic (should_continue),
the bounded reflection while-loop in final_answer(), and tool-error propagation.

Design constraint: this suite must run with ZERO installed third-party packages
and ZERO network access, so the real `openai` SDK and the real `dotenv` package
(agent.py calls load_dotenv() at import time as of the fix for the load-order
bug where DASHSCOPE_API_KEY was only populated by accident via chat_rt.py's
import order) are stubbed via sys.modules *before* agent.py is imported. Within
each test, the actual LLM-calling boundary (_llm_json) is mocked with
unittest.mock so should_continue()'s own parsing/decision logic is exercised
against controlled, deterministic responses rather than a live model.

These tests were originally written in Phase 1, before the finance tool
existed, so the mocked memory fixtures still use Pokemon-domain strings
(garchomp, pokeapi_query) as arbitrary example content. That's harmless: the
functions under test (should_continue, process_actions, the reflection loop
in final_answer) are exercised entirely via mocks/patches, so the literal
domain words in the fixture data don't affect what's being verified — the
loop-mechanism and error-propagation behavior is domain-agnostic by
construction. Finance-domain end-to-end scenarios belong in Phase 5.
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

# agent.py fails fast at import time if DASHSCOPE_BASE_URL is unset (it would
# otherwise silently leak requests to the public OpenAI endpoint with a
# DashScope key). Set a harmless placeholder so that guard doesn't break this
# suite's import — no real network call is ever made since _get_llm_client()
# is lazy and every test patches the LLM-calling boundary directly.
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
    # _rerank_candidates() calls dashscope.TextReRank.call() (Step 2, v5 —
    # switched from a raw `requests` call to the official SDK so DashScope's
    # own client resolves the correct service). Stub it the same way as
    # openai/dotenv above so agent.py still imports with zero installs;
    # individual tests patch TextReRank.call with their own fake responses.
    _fake_dashscope = types.ModuleType("dashscope")

    class _FakeTextReRank:
        @staticmethod
        def call(*args, **kwargs):
            raise NotImplementedError("dashscope.TextReRank.call must be mocked per-test")

    _fake_dashscope.TextReRank = _FakeTextReRank
    sys.modules["dashscope"] = _fake_dashscope

if "elasticsearch" not in sys.modules:
    # rag_search() does `from elasticsearch import Elasticsearch` as a local
    # import (only when actually called, not at module load time), so this
    # isn't needed for agent.py to import cleanly -- but is needed for any
    # test that calls rag_search() itself (Step 9's BM25-vs-kNN/rerank
    # wiring test below). Individual tests patch `Elasticsearch` with their
    # own fake instance to capture/control the ES query body and response.
    _fake_es_module = types.ModuleType("elasticsearch")

    class _FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, index=None, body=None):
            raise NotImplementedError("elasticsearch.Elasticsearch must be mocked per-test")

    _fake_es_module.Elasticsearch = _FakeElasticsearch
    sys.modules["elasticsearch"] = _fake_es_module

if "app.database.knowledgebase_operations" not in sys.modules:
    # rag_search() imports get_latest_user_upload() at module load time (Step
    # 10, upload boost). The real module pulls in sqlalchemy and a live
    # DATABASE_URL via app/utils/database.py, which this suite deliberately
    # has neither of (see module docstring). Stub it the same way as
    # openai/dotenv above so agent.py still imports cleanly.
    _fake_kb_ops = types.ModuleType("app.database.knowledgebase_operations")
    _fake_kb_ops.get_latest_user_upload = lambda user_id: None
    sys.modules["app.database.knowledgebase_operations"] = _fake_kb_ops

if "xxhash" not in sys.modules:
    # scripts/index_finance.py (imported read-only by
    # KeywordDynamicTemplateRegexTests below, US-001) does `import xxhash`
    # for chunk-id hashing. Stubbed the same way as openai/dotenv/
    # elasticsearch above so that import doesn't require an actual install,
    # preserving this suite's zero-installed-packages guarantee.
    _fake_xxhash = types.ModuleType("xxhash")
    _fake_xxhash.xxh64 = lambda *a, **kw: types.SimpleNamespace(hexdigest=lambda: "0")
    sys.modules["xxhash"] = _fake_xxhash

if "bs4" not in sys.modules:
    # Same rationale as xxhash above: scripts/index_finance.py does
    # `from bs4 import BeautifulSoup, NavigableString` for HTML->text
    # extraction. Only needs to exist at import time here -- the new test
    # below never calls the HTML-parsing functions.
    _fake_bs4 = types.ModuleType("bs4")

    class _FakeBeautifulSoup:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeNavigableString(str):
        pass

    _fake_bs4.BeautifulSoup = _FakeBeautifulSoup
    _fake_bs4.NavigableString = _FakeNavigableString
    sys.modules["bs4"] = _fake_bs4

from app.service.agent import agent  # noqa: E402  (import after stubbing)


def _import_index_finance_module():
    """Import scripts/index_finance.py by file path for
    KeywordDynamicTemplateRegexTests (US-001). It isn't a package and isn't
    on sys.path by default, so this loads it directly rather than requiring
    the test to re-type a copy of its KEYWORD_DYNAMIC_TEMPLATE_REGEX
    constant, which would defeat the point of a regression test (a copy
    can't catch the original changing)."""
    import importlib.util

    scripts_dir = _backend_dir.parent / "scripts"
    spec = importlib.util.spec_from_file_location("index_finance", scripts_dir / "index_finance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _llm_json_returning(payload) -> str:
    """Build a fake `_llm_json` return value: a JSON string, optionally with
    surrounding prose the way real LLM output sometimes includes it."""
    return json.dumps(payload, ensure_ascii=False)


class ShouldContinueTests(unittest.TestCase):
    """US-5: should_continue() against mocked LLM responses, no live calls."""

    def test_sufficient_when_clear_answer_present(self):
        memory = [{"提问": "garchomp speed stat", "结果": "Garchomp base speed: 102"}]
        mocked_response = _llm_json_returning({
            "sufficient": True,
            "rationale": "已获得完整的种族值数据，足以回答。",
            "actions": [],
        })
        with patch.object(agent, "_llm_json", return_value=mocked_response) as mocked:
            decision = agent.should_continue("garchomp 速度种族值多少", memory)
            mocked.assert_called_once()

        self.assertTrue(decision["sufficient"])
        self.assertEqual(decision["actions"], [])
        self.assertIn("种族值", decision["rationale"])

    def test_not_sufficient_returns_retry_action_on_empty_result(self):
        memory = [{"提问": "iron valiant battle strategy", "结果": []}]
        mocked_response = _llm_json_returning({
            "sufficient": False,
            "rationale": "rag_search 未返回任何对战策略内容，需要补充网络搜索。",
            "actions": [
                {"action_name": "web_search", "prompts": ["iron valiant competitive strategy 2024"]}
            ],
        })
        with patch.object(agent, "_llm_json", return_value=mocked_response):
            decision = agent.should_continue("铁巨剑适合什么打法", memory)

        self.assertFalse(decision["sufficient"])
        self.assertEqual(len(decision["actions"]), 1)
        self.assertEqual(decision["actions"][0]["action_name"], "web_search")
        self.assertIn("rag_search", decision["rationale"])

    def test_reacts_to_tool_error_entry_in_memory(self):
        memory = [{
            "提问": "garchomp stats",
            "结果": "[工具调用失败] pokeapi_query: Connection timeout",
            "错误": True,
        }]
        mocked_response = _llm_json_returning({
            "sufficient": False,
            "rationale": "pokeapi_query 调用失败（超时），需要重试。",
            "actions": [
                {"action_name": "pokeapi_query", "prompts": ["garchomp stats"]}
            ],
        })
        with patch.object(agent, "_llm_json", return_value=mocked_response):
            decision = agent.should_continue("garchomp 种族值", memory)

        self.assertFalse(decision["sufficient"])
        self.assertTrue(any(a["action_name"] == "pokeapi_query" for a in decision["actions"]))
        self.assertIn("失败", decision["rationale"])

    def test_malformed_llm_output_falls_back_to_safe_stop(self):
        memory = [{"提问": "x", "结果": "y"}]
        with patch.object(agent, "_llm_json", return_value="not valid json at all"):
            decision = agent.should_continue("test query", memory)

        self.assertTrue(decision["sufficient"])
        self.assertEqual(decision["actions"], [])
        self.assertIn("parse error", decision["rationale"])

    def test_missing_sufficient_field_falls_back_to_safe_stop(self):
        memory = [{"提问": "x", "结果": "y"}]
        mocked_response = _llm_json_returning({"rationale": "oops, forgot the required field"})
        with patch.object(agent, "_llm_json", return_value=mocked_response):
            decision = agent.should_continue("test query", memory)

        self.assertTrue(decision["sufficient"])
        self.assertEqual(decision["actions"], [])
        self.assertIn("parse error", decision["rationale"])

    def test_string_false_is_not_treated_as_sufficient(self):
        """Regression test for bool("false") == True in Python: the LLM often
        emits "sufficient" as a JSON string rather than a real boolean, and a
        bare bool() cast would misread the literal string "false" as truthy,
        stopping the reflection loop prematurely on insufficient info."""
        memory = [{"提问": "iron valiant battle strategy", "结果": []}]
        mocked_response = _llm_json_returning({
            "sufficient": "false",
            "rationale": "仍需补充信息。",
            "actions": [{"action_name": "web_search", "prompts": ["iron valiant strategy"]}],
        })
        with patch.object(agent, "_llm_json", return_value=mocked_response):
            decision = agent.should_continue("铁巨剑适合什么打法", memory)

        self.assertFalse(decision["sufficient"])
        self.assertEqual(len(decision["actions"]), 1)

    def test_string_true_is_treated_as_sufficient(self):
        memory = [{"提问": "garchomp speed stat", "结果": "Garchomp base speed: 102"}]
        mocked_response = _llm_json_returning({
            "sufficient": "true",
            "rationale": "已获得完整数据。",
            "actions": [],
        })
        with patch.object(agent, "_llm_json", return_value=mocked_response):
            decision = agent.should_continue("garchomp 速度种族值多少", memory)

        self.assertTrue(decision["sufficient"])


class ProcessActionsErrorPropagationTests(unittest.TestCase):
    """US-3: tool exceptions must land in memory, not just be printed."""

    def test_tool_exception_produces_visible_memory_entry(self):
        actions = [{"action_name": "rag_search", "prompt": "garchomp moveset"}]
        with patch.object(agent, "rag_search", side_effect=RuntimeError("ES connection refused")):
            memory = agent.process_actions(actions, language="en")

        self.assertEqual(len(memory), 1)
        entry = memory[0]
        self.assertTrue(entry.get("错误"))
        self.assertIn("ES connection refused", entry["结果"])

    def test_successful_tool_call_has_no_error_marker(self):
        actions = [{"action_name": "rag_search", "prompt": "garchomp moveset"}]
        with patch.object(agent, "rag_search", return_value=[{"id": 1, "content_with_weight": "stub"}]):
            memory = agent.process_actions(actions, language="en")

        self.assertEqual(len(memory), 1)
        self.assertNotIn("错误", memory[0])


class ReflectionLoopTests(unittest.TestCase):
    """US-2/US-4: the bounded while-loop in final_answer() must be genuinely
    LLM-driven (iterates more than once when asked to, stops on sufficient,
    and distinguishes a safety-cap stop from an LLM-signaled stop), and must
    stream should_continue()'s rationale into the existing SSE content field.

    v5 note: a later bug fix made final_answer() skip Act+Reflect entirely
    when agent_plan() returns None/empty (agent.py's `if actions:` guard) —
    previously an identity/history/off-topic query's null plan didn't stop
    should_continue() from independently deciding to search anyway. These
    reflect-loop mechanics tests used to exploit `plan_result=None` as a
    shortcut to skip straight to a mocked process_actions()/should_continue()
    fixture; that shortcut is now a real no-op by design, so
    _drive_final_answer() defaults to a minimal well-formed plan instead.
    """

    def _drive_final_answer(self, decisions, plan_result=None, process_actions_result=None):
        """Run final_answer() with agent_plan/process_actions/should_continue
        mocked, and the final-answer streaming LLM call stubbed to emit a
        single completed chunk immediately. `decisions` is a list of dicts
        consumed one per should_continue() call, in order. `process_actions_result`
        overrides the memory process_actions() returns (defaults to the
        original string-only fixture used by the pre-existing tests below).
        `plan_result` defaults to a minimal single-action plan (not None) so
        Act+Reflect actually runs — these tests exercise the reflect loop's
        iteration/logging mechanics via the mocked should_continue/
        process_actions, so the plan's specific content doesn't matter, only
        that it's non-empty."""
        if plan_result is None:
            plan_result = [{"action_name": "rag_search", "prompts": ["q"]}]
        decisions_iter = iter(decisions)

        def _fake_should_continue(query, memory):
            return next(decisions_iter)

        fake_chunk = types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                delta=types.SimpleNamespace(content="done", reasoning_content=None),
                finish_reason="stop",
            )]
        )

        if process_actions_result is None:
            process_actions_result = [{"提问": "q", "结果": "r"}]

        with patch.object(agent, "agent_plan", return_value=plan_result), \
             patch.object(agent, "process_actions", return_value=process_actions_result), \
             patch.object(agent, "should_continue", side_effect=_fake_should_continue), \
             patch.object(agent, "OpenAI") as mocked_openai_cls:
            mocked_client = mocked_openai_cls.return_value
            mocked_client.chat.completions.create.return_value = [fake_chunk]
            events = list(agent.final_answer("test query", language="en"))

        return events

    def test_loop_iterates_multiple_times_when_llm_keeps_requesting_actions(self):
        decisions = [
            {"sufficient": False, "rationale": "需要补充种族值数据", "actions": [
                {"action_name": "pokeapi_query", "prompts": ["garchomp stats"]}
            ]},
            {"sufficient": False, "rationale": "还需要确认最新 meta 排名", "actions": [
                {"action_name": "web_search", "prompts": ["garchomp tier ranking 2024"]}
            ]},
            {"sufficient": True, "rationale": "现在信息已经完整", "actions": []},
        ]
        events = self._drive_final_answer(decisions)

        agent_events = [e for e in events if '"role": "agent"' in e]
        # Two reflection iterations actually requested actions (the third just
        # signals sufficient with no action), so we expect 2 streamed
        # "补充调用" messages.
        followup_events = [e for e in agent_events if "补充调用" in e]
        self.assertEqual(len(followup_events), 2)

    def test_rationale_streamed_into_existing_content_field(self):
        decisions = [
            {"sufficient": False, "rationale": "需要补充种族值数据", "actions": [
                {"action_name": "pokeapi_query", "prompts": ["garchomp stats"]}
            ]},
            {"sufficient": True, "rationale": "信息已足够", "actions": []},
        ]
        events = self._drive_final_answer(decisions)

        followup_events = [e for e in events if "补充调用" in e]
        self.assertEqual(len(followup_events), 1)
        payload = json.loads(followup_events[0].split("data: ", 1)[1].strip())
        self.assertEqual(payload["role"], "agent")
        self.assertIn("需要补充种族值数据", payload["content"])
        self.assertNotIn("thinking", payload)  # no new schema field added

    def test_llm_signaled_stop_does_not_hit_safety_cap(self):
        decisions = [
            {"sufficient": True, "rationale": "信息已足够，第一轮就判定停止", "actions": []},
        ]
        # agent_plan must return a real (non-empty) plan here: a None/empty
        # plan now short-circuits Act+Reflect entirely (see class docstring),
        # which would make should_continue() never get called at all rather
        # than being called once and stopping on its own — the exact
        # distinction this test exists to verify.
        with patch.object(agent, "agent_plan", return_value=[{"action_name": "rag_search", "prompts": ["q"]}]), \
             patch.object(agent, "process_actions", return_value=[]), \
             patch.object(agent, "should_continue", side_effect=iter(decisions)) as mocked_sc, \
             patch.object(agent, "OpenAI") as mocked_openai_cls:
            fake_chunk = types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    delta=types.SimpleNamespace(content="done", reasoning_content=None),
                    finish_reason="stop",
                )]
            )
            mocked_client = mocked_openai_cls.return_value
            mocked_client.chat.completions.create.return_value = [fake_chunk]
            list(agent.final_answer("test query", language="en"))

        # should_continue was called exactly once: the LLM stopped the loop on
        # its first judgment, proving the loop doesn't force extra iterations.
        self.assertEqual(mocked_sc.call_count, 1)

    def test_safety_cap_is_hit_and_distinguishable_when_llm_never_signals_sufficient(self):
        # Always request more actions -> loop should hit MAX_REFLECTION_ITERATIONS
        # and stop via the cap path, never via an LLM sufficient=True signal.
        never_sufficient = {
            "sufficient": False,
            "rationale": "总是觉得不够",
            "actions": [{"action_name": "web_search", "prompts": ["more info"]}],
        }
        decisions = [never_sufficient] * 10  # more than enough to exhaust the cap

        # See test_llm_signaled_stop_does_not_hit_safety_cap: agent_plan must
        # return a real plan or Act+Reflect (and should_continue with it)
        # never runs at all, which would trivially "pass" this test for the
        # wrong reason (0 calls, not 5).
        with patch.object(agent, "agent_plan", return_value=[{"action_name": "rag_search", "prompts": ["q"]}]), \
             patch.object(agent, "process_actions", return_value=[{"提问": "q", "结果": "r"}]), \
             patch.object(agent, "should_continue", side_effect=lambda q, m: never_sufficient) as mocked_sc, \
             patch.object(agent, "OpenAI") as mocked_openai_cls, \
             patch("builtins.print") as mocked_print:
            fake_chunk = types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    delta=types.SimpleNamespace(content="done", reasoning_content=None),
                    finish_reason="stop",
                )]
            )
            mocked_client = mocked_openai_cls.return_value
            mocked_client.chat.completions.create.return_value = [fake_chunk]
            list(agent.final_answer("test query", language="en"))

        self.assertEqual(mocked_sc.call_count, 5)  # MAX_REFLECTION_ITERATIONS
        cap_logs = [
            call for call in mocked_print.call_args_list
            if call.args and "安全上限" in str(call.args[0])
        ]
        self.assertTrue(cap_logs, "expected a distinct cap-stop log line when the safety cap is hit")


class DocumentsSSEEventTests(unittest.TestCase):
    """Round 3: final_answer() must emit a `documents` SSE event built from
    any list-valued (rag_search-style) memory results, without leaking a
    `documents` key into the existing per-token assistant events, and must
    stay silent (no `documents` event at all) when memory only has the
    string-only results the pre-existing ReflectionLoopTests fixtures use.

    Reuses ReflectionLoopTests._drive_final_answer (unbound) rather than
    duplicating the mocking setup — the helper doesn't touch instance state,
    just `self.assertEqual` never gets called on the mismatched instance.
    """

    def _drive_final_answer(self, decisions, plan_result=None, process_actions_result=None):
        return ReflectionLoopTests._drive_final_answer(
            self, decisions, plan_result=plan_result, process_actions_result=process_actions_result
        )

    def test_documents_event_emitted_for_list_valued_rag_result(self):
        rag_result = [
            {
                "id": "doc1",
                "document_name": "10-K_AAPL.pdf",
                "content_with_weight": "Apple reported revenue of $394B.",
                "source": "rag_search",
                "_score": 0.9,
            },
            {
                "id": "doc2",
                "document_name": "news_MSFT.pdf",
                "content_with_weight": "Microsoft cloud growth accelerated.",
                "source": "rag_search",
                "_score": 0.8,
            },
        ]
        process_actions_result = [{"提问": "q", "结果": rag_result}]
        decisions = [{"sufficient": True, "rationale": "信息已足够", "actions": []}]

        events = self._drive_final_answer(
            decisions, process_actions_result=process_actions_result
        )

        documents_events = [e for e in events if '"documents"' in e]
        self.assertEqual(len(documents_events), 1)
        payload = json.loads(documents_events[0].split("data: ", 1)[1].strip())
        self.assertEqual(
            payload["documents"],
            [
                {
                    "document_id": "0",
                    "document_name": "10-K_AAPL.pdf",
                    "content_with_weight": "Apple reported revenue of $394B.",
                },
                {
                    "document_id": "1",
                    "document_name": "news_MSFT.pdf",
                    "content_with_weight": "Microsoft cloud growth accelerated.",
                },
            ],
        )

    def test_per_token_events_do_not_leak_documents_key(self):
        rag_result = [
            {
                "id": "doc1",
                "document_name": "10-K_AAPL.pdf",
                "content_with_weight": "Apple revenue info.",
            }
        ]
        process_actions_result = [{"提问": "q", "结果": rag_result}]
        decisions = [{"sufficient": True, "rationale": "信息已足够", "actions": []}]

        events = self._drive_final_answer(
            decisions, process_actions_result=process_actions_result
        )

        token_events = [e for e in events if '"role": "assistant"' in e]
        self.assertEqual(len(token_events), 1)
        payload = json.loads(token_events[0].split("data: ", 1)[1].strip())
        self.assertEqual(set(payload.keys()), {"role", "content", "thinking"})
        self.assertNotIn("documents", payload)

    def test_no_documents_event_when_memory_results_are_string_only(self):
        # Default process_actions_result ({"提问": "q", "结果": "r"}) matches
        # the pre-existing ReflectionLoopTests fixtures: a plain string
        # result, never a list. No documents event should be emitted.
        decisions = [{"sufficient": True, "rationale": "信息已足够", "actions": []}]

        events = self._drive_final_answer(decisions)

        documents_events = [e for e in events if '"documents"' in e]
        self.assertEqual(len(documents_events), 0)

    def test_documents_event_only_includes_rag_search_shaped_entries_when_mixed_with_web_search(self):
        # web_search() also returns list[dict], but shaped {title,url,content}
        # — no "content_with_weight" key. The shape-filter in final_answer()
        # must exclude these and keep only rag_search-shaped dicts.
        web_search_result = [
            {"title": "Fed raises rates", "url": "https://example.com/fed", "content": "The Fed raised rates today."},
        ]
        rag_result = [
            {
                "id": "doc1",
                "document_name": "10-K_AAPL.pdf",
                "content_with_weight": "Apple reported revenue of $394B.",
                "source": "rag_search",
                "_score": 0.9,
            },
        ]
        process_actions_result = [
            {"提问": "q1", "结果": web_search_result},
            {"提问": "q2", "结果": rag_result},
        ]
        decisions = [{"sufficient": True, "rationale": "信息已足够", "actions": []}]

        events = self._drive_final_answer(
            decisions, process_actions_result=process_actions_result
        )

        documents_events = [e for e in events if '"documents"' in e]
        self.assertEqual(len(documents_events), 1)
        payload = json.loads(documents_events[0].split("data: ", 1)[1].strip())
        self.assertEqual(
            payload["documents"],
            [
                {
                    "document_id": "0",
                    "document_name": "10-K_AAPL.pdf",
                    "content_with_weight": "Apple reported revenue of $394B.",
                },
            ],
        )


class RerankCandidatesTests(unittest.TestCase):
    """Step 10: _rerank_candidates() must fail open (return the pre-rerank
    order unchanged) when the DashScope rerank call fails, and must actually
    re-sort candidates by the new relevance scores on success.

    v5: rewritten against dashscope.TextReRank.call (the SDK-based transport
    that replaced the raw `requests.post` call to a hardcoded REST endpoint —
    see the plan's v5 changelog). Response shape mirrors the SDK's actual
    return value: `.status_code`/`.output` on the response, `.output.results`
    as a list of objects exposing `.index`/`.relevance_score`, not dicts.
    """

    def test_rerank_failure_returns_original_candidates_unchanged(self):
        candidates = [
            {"id": 1, "content_with_weight": "first chunk", "_score": 5.0},
            {"id": 2, "content_with_weight": "second chunk", "_score": 3.0},
        ]
        with patch.object(agent.dashscope.TextReRank, "call", side_effect=RuntimeError("network error")):
            result = agent._rerank_candidates("test query", candidates)

        self.assertEqual(result, candidates)
        self.assertIs(result, candidates)

    def test_rerank_non_200_response_returns_original_candidates_unchanged(self):
        candidates = [
            {"id": 1, "content_with_weight": "first chunk", "_score": 5.0},
            {"id": 2, "content_with_weight": "second chunk", "_score": 3.0},
        ]
        fake_response = types.SimpleNamespace(
            status_code=401, output=None, code="InvalidApiKey", message="Invalid API-key provided."
        )
        with patch.object(agent.dashscope.TextReRank, "call", return_value=fake_response):
            result = agent._rerank_candidates("test query", candidates)

        self.assertEqual(result, candidates)

    def test_rerank_success_resorts_by_new_scores(self):
        candidates = [
            {"id": 1, "content_with_weight": "first chunk", "_score": 5.0},
            {"id": 2, "content_with_weight": "second chunk", "_score": 3.0},
        ]
        fake_output = types.SimpleNamespace(
            results=[
                types.SimpleNamespace(index=0, relevance_score=0.1),
                types.SimpleNamespace(index=1, relevance_score=0.9),
            ]
        )
        fake_response = types.SimpleNamespace(status_code=200, output=fake_output)
        with patch.object(agent.dashscope.TextReRank, "call", return_value=fake_response):
            result = agent._rerank_candidates("test query", candidates)

        self.assertEqual([c["id"] for c in result], [2, 1])
        self.assertEqual(result[0]["_score"], 0.9)
        self.assertEqual(result[1]["_score"], 0.1)


class UploadBoostTests(unittest.TestCase):
    """Step 10: _apply_upload_boost() is the unconditional terminal step after
    reranking — it must promote the current user's latest upload into top-5
    regardless of whether the pool it receives is a successfully reranked
    order or the degraded (pre-rerank) order, and must no-op when there's no
    boost target."""

    def test_promotes_boost_doc_into_top5_from_reranked_order(self):
        # Simulates the post-rerank pool: the boost doc sits outside the
        # first 5 positions after reranking.
        candidates = [
            {"id": 1, "document_name": "10-K_AAPL.pdf", "_score": 0.95},
            {"id": 2, "document_name": "10-K_AAPL.pdf", "_score": 0.90},
            {"id": 3, "document_name": "news_MSFT.pdf", "_score": 0.85},
            {"id": 4, "document_name": "news_MSFT.pdf", "_score": 0.80},
            {"id": 5, "document_name": "10-K_AAPL.pdf", "_score": 0.75},
            {"id": 6, "document_name": "my_upload.pdf", "_score": 0.40},
            {"id": 7, "document_name": "news_MSFT.pdf", "_score": 0.10},
        ]
        result = agent._apply_upload_boost(candidates, "my_upload.pdf")

        self.assertEqual(len(result), 5)
        self.assertEqual(result[4]["id"], 6)
        self.assertEqual([c["id"] for c in result[:4]], [1, 2, 3, 4])

    def test_promotes_boost_doc_into_top5_from_degraded_pre_rerank_order(self):
        # Simulates the degraded pool (rerank failed, original ES order
        # preserved) — boost placement must not depend on rerank success.
        candidates = [
            {"id": 1, "document_name": "news_MSFT.pdf", "_score": 12.3},
            {"id": 2, "document_name": "10-K_AAPL.pdf", "_score": 11.1},
            {"id": 3, "document_name": "news_MSFT.pdf", "_score": 9.8},
            {"id": 4, "document_name": "10-K_AAPL.pdf", "_score": 8.4},
            {"id": 5, "document_name": "news_MSFT.pdf", "_score": 7.2},
            {"id": 6, "document_name": "10-K_AAPL.pdf", "_score": 6.5},
            {"id": 7, "document_name": "my_upload.pdf", "_score": 5.0},
        ]
        result = agent._apply_upload_boost(candidates, "my_upload.pdf")

        self.assertEqual(len(result), 5)
        self.assertEqual(result[4]["id"], 7)
        self.assertEqual([c["id"] for c in result[:4]], [1, 2, 3, 4])

    def test_no_boost_docnm_returns_plain_top5_slice(self):
        candidates = [
            {"id": 1, "document_name": "news_MSFT.pdf", "_score": 12.3},
            {"id": 2, "document_name": "10-K_AAPL.pdf", "_score": 11.1},
            {"id": 3, "document_name": "news_MSFT.pdf", "_score": 9.8},
            {"id": 4, "document_name": "10-K_AAPL.pdf", "_score": 8.4},
            {"id": 5, "document_name": "news_MSFT.pdf", "_score": 7.2},
            {"id": 6, "document_name": "10-K_AAPL.pdf", "_score": 6.5},
            {"id": 7, "document_name": "my_upload.pdf", "_score": 5.0},
        ]
        result = agent._apply_upload_boost(candidates, None)

        self.assertEqual([c["id"] for c in result], [1, 2, 3, 4, 5])


class FinanceToolTickerExtractionTests(unittest.TestCase):
    """finance_tool() must not pick a standalone stopword (I/A/US/CEO/PE/EPS)
    as the ticker when a real ticker is present later in the sub-question."""

    def test_stopword_before_real_ticker_resolves_to_real_ticker(self):
        captured = {}

        def _fake_finance_query(kind, ticker=None):
            captured["kind"] = kind
            captured["ticker"] = ticker
            return "stub"

        with patch.object(agent, "_finance_query", side_effect=_fake_finance_query):
            agent.finance_tool("How do I check AAPL price")

        self.assertEqual(captured["ticker"], "AAPL")

    def test_stopword_is_used_only_when_it_is_the_sole_candidate(self):
        captured = {}
        with patch.object(agent, "_finance_query", side_effect=lambda k, ticker=None: captured.update(ticker=ticker) or "stub"):
            agent.finance_tool("I want a quote")

        self.assertEqual(captured["ticker"], "I")

    def test_no_ticker_returns_guidance_message(self):
        result = agent.finance_tool("how are you today")
        self.assertIn("未能从问题中识别出股票代码", result)


class StripFillerWordsTests(unittest.TestCase):
    """Step 9/10: _strip_filler_words() must remove Chinese/English filler
    and question words while preserving ticker symbols and financial terms,
    and rag_search() must apply it only to the BM25 match text -- the kNN
    embedding call and _rerank_candidates must still receive the original,
    unmodified query (semantic search/rerank need full sentence context)."""

    def test_strips_chinese_question_word_keeps_financial_term(self):
        self.assertEqual(agent._strip_filler_words("什么是市盈率"), "市盈率")

    def test_strips_chinese_filler_keeps_ticker(self):
        result = agent._strip_filler_words("AAPL的股价是多少")
        self.assertIn("AAPL", result)
        self.assertNotIn("是多少", result)

    def test_strips_english_filler_keeps_ticker_and_term(self):
        result = agent._strip_filler_words("what is the P/E ratio of AAPL")
        self.assertIn("AAPL", result)
        self.assertIn("P/E ratio", result)
        self.assertNotIn("what is", result.lower())
        self.assertNotIn(" the ", f" {result.lower()} ")

    def test_falls_back_to_original_query_when_stripping_empties_it(self):
        # A query that's entirely filler words must not degrade to an empty
        # BM25 match clause -- fall back to the original query untouched.
        self.assertEqual(agent._strip_filler_words("请问"), "请问")

    def test_uppercase_ticker_colliding_with_filler_word_is_preserved(self):
        # Several real US tickers are also common English filler words
        # (ON=ON Semiconductor, SO=Southern Co, ARE=Alexandria Real Estate,
        # AN=AutoNation, DO=Diamond Offshore, GO=Grocery Outlet). The filler
        # regex must only match the lowercase form -- agent_plan's prompt
        # already mandates uppercase tickers in generated sub-questions, so
        # case is a reliable discriminator here, not an arbitrary heuristic.
        for query, ticker in [
            ("ON stock price", "ON"),
            ("SO dividend yield", "SO"),
            ("ARE quarterly earnings", "ARE"),
            ("is ON a buy", "ON"),
            ("AN stock forecast", "AN"),
            ("GO stock price", "GO"),
            ("DO stock price", "DO"),
        ]:
            with self.subTest(query=query, ticker=ticker):
                result = agent._strip_filler_words(query)
                self.assertIn(ticker, result.split())

    def test_rag_search_strips_only_the_bm25_match_text(self):
        query_with_filler = "what is AAPL price"
        captured = {}

        class _FakeEsInstance:
            def search(self, index=None, body=None):
                captured["body"] = body
                return {"hits": {"hits": []}}

        with patch.object(agent, "_get_es", return_value=_FakeEsInstance()), \
             patch.object(agent, "_embed_query", return_value=None) as mocked_embed, \
             patch.object(agent, "_rerank_candidates", side_effect=lambda q, c: c) as mocked_rerank:
            agent.rag_search(query_with_filler)

        bm25_match_text = captured["body"]["query"]["bool"]["must"]["match"]["content_ltks"]
        self.assertEqual(bm25_match_text, agent._strip_filler_words(query_with_filler))
        self.assertNotEqual(bm25_match_text, query_with_filler)

        # kNN (_embed_query) and _rerank_candidates must receive the raw,
        # unstripped query -- only the BM25 match text is filler-stripped.
        mocked_embed.assert_called_once_with(query_with_filler)
        mocked_rerank.assert_called_once()
        self.assertEqual(mocked_rerank.call_args.args[0], query_with_filler)


class ScopeShouldClausesTests(unittest.TestCase):
    """Step 6a: _scope_should_clauses(session_id) builds the tri-state filter
    (seed corpus OR (user_upload AND (global OR current session))) exactly
    once, reused by both the BM25 should and the kNN filter in rag_search."""

    def test_real_session_id_produces_expected_shape(self):
        clauses = agent._scope_should_clauses("session_a")
        self.assertEqual(clauses[0], {"terms": {"source_kwd": ["sec_filing", "news", "educational"]}})
        upload_clause = clauses[1]["bool"]
        self.assertIn({"term": {"source_kwd": "user_upload"}}, upload_clause["must"])
        self.assertIn(
            {"bool": {"must_not": {"exists": {"field": "session_id"}}}},
            upload_clause["should"],
        )
        self.assertIn({"term": {"session_id": "session_a"}}, upload_clause["should"])
        self.assertEqual(upload_clause["minimum_should_match"], 1)

    def test_none_session_id_does_not_crash_and_keeps_shape(self):
        clauses = agent._scope_should_clauses(None)
        upload_clause = clauses[1]["bool"]
        self.assertIn({"term": {"session_id": None}}, upload_clause["should"])


def _es_bool_matches(query: dict, doc: dict) -> bool:
    """Minimal ES query-DSL evaluator covering only the clause shapes used by
    _scope_should_clauses/rag_search (term, terms, exists, bool/must/must_not/
    should/minimum_should_match, and a no-op "match" since BM25 text scoring
    isn't what these tests exercise). Lets the session-scoping tests below
    assert against the real query body rag_search() builds, without a live ES."""
    if "match" in query:
        return True
    if "term" in query:
        (field, value), = query["term"].items()
        return doc.get(field) == value
    if "terms" in query:
        (field, values), = query["terms"].items()
        return doc.get(field) in values
    if "exists" in query:
        return doc.get(query["exists"]["field"]) is not None
    if "bool" in query:
        b = query["bool"]
        musts = b.get("must", [])
        if isinstance(musts, dict):
            musts = [musts]
        if not all(_es_bool_matches(m, doc) for m in musts):
            return False
        must_not = b.get("must_not")
        if must_not:
            must_not = [must_not] if isinstance(must_not, dict) else must_not
            if any(_es_bool_matches(mn, doc) for mn in must_not):
                return False
        shoulds = b.get("should", [])
        if shoulds:
            matched = sum(1 for s in shoulds if _es_bool_matches(s, doc))
            if matched < (b.get("minimum_should_match") or 0):
                return False
        return True
    raise ValueError(f"unsupported query clause in test evaluator: {query}")


class _ScopedFakeElasticsearch:
    """Evaluates the real bool query rag_search() builds against a fixed doc
    set via _es_bool_matches, standing in for a live Elasticsearch so the
    session-scoping behavior is verified against the actual query shape."""

    def __init__(self, docs):
        self._docs = docs

    def search(self, index=None, body=None):
        hits = [{"_source": doc, "_score": 1.0} for doc in self._docs if _es_bool_matches(body["query"], doc)]
        return {"hits": {"hits": hits}}


class SessionScopedRagSearchTests(unittest.TestCase):
    """Step 6/6a acceptance criteria: a chat message in session X retrieves
    seed corpus + dataset-global uploads + its own session's uploads, and must
    NOT retrieve a different session's upload."""

    _DOCS = [
        {"docnm_kwd": "session_a_upload.pdf", "source_kwd": "user_upload", "session_id": "session_a",
         "content_with_weight": "session a content"},
        {"docnm_kwd": "session_b_upload.pdf", "source_kwd": "user_upload", "session_id": "session_b",
         "content_with_weight": "session b content"},
        {"docnm_kwd": "global_upload.pdf", "source_kwd": "user_upload", "session_id": None,
         "content_with_weight": "global content"},
        {"docnm_kwd": "10-K_AAPL.pdf", "source_kwd": "sec_filing", "session_id": None,
         "content_with_weight": "seed corpus content"},
    ]

    def _search(self, session_id):
        with patch.object(agent, "_get_es", return_value=_ScopedFakeElasticsearch(self._DOCS)), \
             patch.object(agent, "_embed_query", return_value=None), \
             patch.object(agent, "_rerank_candidates", side_effect=lambda q, c: c):
            results = agent.rag_search("some query", session_id)
        return {r["document_name"] for r in results}

    def test_own_session_upload_is_retrieved(self):
        self.assertIn("session_a_upload.pdf", self._search("session_a"))

    def test_other_session_upload_is_not_retrieved(self):
        names = self._search("session_a")
        self.assertNotIn("session_b_upload.pdf", names)

    def test_global_upload_is_retrieved_from_any_session(self):
        for session_id in ("session_a", "session_b"):
            with self.subTest(session_id=session_id):
                self.assertIn("global_upload.pdf", self._search(session_id))

    def test_seed_corpus_is_always_retrieved(self):
        for session_id in ("session_a", "session_b"):
            with self.subTest(session_id=session_id):
                self.assertIn("10-K_AAPL.pdf", self._search(session_id))


class KeywordDynamicTemplateRegexTests(unittest.TestCase):
    """US-001: rag_search's session scoping (_scope_should_clauses, above)
    and chat_rt.py's delete_file both run exact-match ES `term` queries
    against `session_id`. Those only work because `session_id` is mapped to
    ES `keyword` (not analyzed text) -- and that mapping is entirely
    implicit: scripts/index_finance.py's dynamic index template auto-maps
    any field matching KEYWORD_DYNAMIC_TEMPLATE_REGEX to `keyword`, and
    `session_id` happens to qualify only because it ends in "_id". Nothing
    currently guards that coincidence. This test imports the actual regex
    constant from scripts/index_finance.py (not a re-typed copy, which
    couldn't catch the original changing) and asserts it still matches
    "session_id". If the field is ever renamed, or the template regex is
    ever narrowed to stop covering "_id" suffixes, this fails loudly instead
    of `term` queries on session_id silently starting to match nothing."""

    @classmethod
    def setUpClass(cls):
        cls.index_finance = _import_index_finance_module()

    def test_dynamic_template_regex_matches_session_id_field(self):
        pattern = self.index_finance.KEYWORD_DYNAMIC_TEMPLATE_REGEX
        self.assertRegex("session_id", pattern)

    def test_dynamic_template_regex_rejects_a_non_id_field(self):
        # Guards against the regex being loosened into something so broad
        # the assertion above would be meaningless (e.g. matching anything).
        pattern = self.index_finance.KEYWORD_DYNAMIC_TEMPLATE_REGEX
        self.assertNotRegex("session_title", pattern)


if __name__ == "__main__":
    unittest.main()

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
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Stub external deps so agent.py imports cleanly with no installs/network ──
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

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

from app.service.agent import agent  # noqa: E402  (import after stubbing)


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
    """

    def _drive_final_answer(self, decisions, plan_result=None):
        """Run final_answer() with agent_plan/process_actions/should_continue
        mocked, and the final-answer streaming LLM call stubbed to emit a
        single completed chunk immediately. `decisions` is a list of dicts
        consumed one per should_continue() call, in order."""
        decisions_iter = iter(decisions)

        def _fake_should_continue(query, memory):
            return next(decisions_iter)

        fake_chunk = types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                delta=types.SimpleNamespace(content="done", reasoning_content=None),
                finish_reason="stop",
            )]
        )

        with patch.object(agent, "agent_plan", return_value=plan_result), \
             patch.object(agent, "process_actions", return_value=[{"提问": "q", "结果": "r"}]), \
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
        with patch.object(agent, "agent_plan", return_value=None), \
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

        with patch.object(agent, "agent_plan", return_value=None), \
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


class RerankCandidatesTests(unittest.TestCase):
    """Step 10: _rerank_candidates() must fail open (return the pre-rerank
    order unchanged) when the DashScope rerank call fails, and must actually
    re-sort candidates by the new relevance scores on success."""

    def test_rerank_failure_returns_original_candidates_unchanged(self):
        candidates = [
            {"id": 1, "content_with_weight": "first chunk", "_score": 5.0},
            {"id": 2, "content_with_weight": "second chunk", "_score": 3.0},
        ]
        with patch.object(agent.requests, "post", side_effect=RuntimeError("network error")):
            result = agent._rerank_candidates("test query", candidates)

        self.assertEqual(result, candidates)
        self.assertIs(result, candidates)

    def test_rerank_non_200_response_returns_original_candidates_unchanged(self):
        candidates = [
            {"id": 1, "content_with_weight": "first chunk", "_score": 5.0},
            {"id": 2, "content_with_weight": "second chunk", "_score": 3.0},
        ]
        fake_response = types.SimpleNamespace(status_code=500, text="internal error")
        with patch.object(agent.requests, "post", return_value=fake_response):
            result = agent._rerank_candidates("test query", candidates)

        self.assertEqual(result, candidates)

    def test_rerank_success_resorts_by_new_scores(self):
        candidates = [
            {"id": 1, "content_with_weight": "first chunk", "_score": 5.0},
            {"id": 2, "content_with_weight": "second chunk", "_score": 3.0},
        ]
        fake_response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {
                "output": {
                    "results": [
                        {"index": 0, "relevance_score": 0.1},
                        {"index": 1, "relevance_score": 0.9},
                    ]
                }
            },
        )
        with patch.object(agent.requests, "post", return_value=fake_response):
            result = agent._rerank_candidates("test query", candidates)

        self.assertEqual([c["id"] for c in result], [2, 1])
        self.assertEqual(result[0]["_score"], 0.9)
        self.assertEqual(result[1]["_score"], 0.1)


if __name__ == "__main__":
    unittest.main()

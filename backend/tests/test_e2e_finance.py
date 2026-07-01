"""
Phase 5 端到端验证脚本（真实存活栈冒烟测试，非 CI 自动化用例）

前提：需要一个正在运行的后端（backend/app 下 `uvicorn app_main:app --port 8000`），
且该后端能访问真实的 DashScope LLM、yfinance 与已填充的 Elasticsearch finance_kb
索引。因涉及真实网络调用与 LLM 推理成本，不适合纳入 pytest/CI 自动跑批，与
test_agent.py 的"手动冒烟测试"约定保持一致，通过 `python backend/tests/test_e2e_finance.py`
直接运行。

驱动 .omc/plans/finance-agent-migration-plan.md Phase 5（steps 14-17）的三个场景：
1. AAPL 复合查询 —— 验证多工具运行时动态编排 + LLM 给出的补充调用理由
2. MSFT 单一行情查询 —— 验证恰好一次工具调用（不触发额外 reflect 补充动作）
3. 无效 ticker 查询 —— 验证工具"未找到"结果不导致后端崩溃，且 LLM 观察到该
   信息缺口并如实告知，而非编造数据
"""
import json
import sys

import requests

BASE_URL = "http://localhost:8000"


def create_session() -> str:
    resp = requests.post(f"{BASE_URL}/create_session", timeout=10)
    resp.raise_for_status()
    return resp.json()["session_id"]


def chat(session_id: str, message: str) -> tuple[int, list[dict]]:
    """POST /chat，返回 (http_status, 解析出的 SSE data 载荷列表)。"""
    resp = requests.post(
        f"{BASE_URL}/chat",
        params={"session_id": session_id},
        json={"message": message},
        stream=True,
        timeout=120,
    )
    events = []
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            payload = line[len("data: "):]
            if payload == "[DONE]":
                continue
            events.append(json.loads(payload))
    return resp.status_code, events


def _tool_call_messages(events: list[dict]) -> list[str]:
    """提取 agent 角色的工具调用/补充调用消息内容。"""
    return [e["content"] for e in events if e.get("role") == "agent"]


def _final_answer_text(events: list[dict]) -> str:
    return "".join(
        e.get("content", "") for e in events if e.get("role") == "assistant" and e.get("thinking") is False
    )


def test_aapl_complex_query() -> bool:
    """AAPL 复合查询：验证多工具运行时动态编排 + LLM 给出的调用理由。"""
    print("\n=== US-2: AAPL 复合查询（价格 + 新闻/10-K 定性分析）===")
    session_id = create_session()
    status, events = chat(
        session_id,
        "What is AAPL's current stock price, and what recent news or 10-K risk "
        "factors might explain its recent performance?",
    )

    tool_msgs = _tool_call_messages(events)
    tools_used = set()
    for msg in tool_msgs:
        for name in ("finance_query", "rag_search", "web_search"):
            if name in msg:
                tools_used.add(name)

    has_rationale = any("原因：" in msg for msg in tool_msgs)
    answer = _final_answer_text(events)
    mentions_aapl = "AAPL" in answer.upper() or "APPLE" in answer.upper()

    ok = (
        status == 200
        and "finance_query" in tools_used
        and "rag_search" in tools_used
        and len(tools_used) >= 2
        and has_rationale
        and len(answer.strip()) > 0
        and mentions_aapl
    )
    print(f"  HTTP status: {status}")
    print(f"  Tools used: {tools_used}")
    print(f"  Has LLM-stated rationale for reflection actions: {has_rationale}")
    print(f"  Total tool-call messages: {len(tool_msgs)}")
    print(f"  Final answer length: {len(answer)} chars")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return bool(ok)


def test_msft_simple_query() -> bool:
    """MSFT 单一行情查询：验证恰好一次工具调用。"""
    print("\n=== US-3: MSFT 简单行情查询（应恰好一次工具调用）===")
    session_id = create_session()
    status, events = chat(session_id, "What is MSFT's current stock price?")

    tool_msgs = _tool_call_messages(events)
    answer = _final_answer_text(events)

    ok = (
        status == 200
        and len(tool_msgs) == 1
        and "finance_query" in tool_msgs[0]
        and len(answer.strip()) > 0
    )
    print(f"  HTTP status: {status}")
    print(f"  Tool-call messages ({len(tool_msgs)}): {tool_msgs}")
    print(f"  Final answer length: {len(answer)} chars")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return bool(ok)


def test_invalid_ticker_query() -> bool:
    """无效 ticker 查询：验证不崩溃 + LLM 如实告知信息缺口。"""
    print("\n=== US-4: 无效 ticker 查询（不应崩溃，应如实告知）===")
    session_id = create_session()
    status, events = chat(session_id, "What is ZZZZINVALID's current stock price?")

    answer = _final_answer_text(events)
    answer_lower = answer.lower()
    acknowledges_failure = any(
        kw in answer_lower for kw in ("invalid", "not found", "未找到", "no stock", "could not")
    )

    ok = status == 200 and len(events) > 0 and acknowledges_failure
    print(f"  HTTP status: {status}")
    print(f"  Acknowledges failure in final answer: {acknowledges_failure}")
    print(f"  Final answer: {answer[:200]}")
    print(f"  {'PASS' if ok else 'FAIL'}")
    return bool(ok)


if __name__ == "__main__":
    try:
        requests.post(f"{BASE_URL}/create_session", timeout=3).raise_for_status()
    except Exception as e:
        print(f"ERROR: backend not reachable at {BASE_URL} ({e})")
        print("Start it first: cd backend/app && uvicorn app_main:app --port 8000")
        sys.exit(1)

    results = {
        "US-2 (AAPL complex)": test_aapl_complex_query(),
        "US-3 (MSFT simple)": test_msft_simple_query(),
        "US-4 (invalid ticker)": test_invalid_ticker_query(),
    }

    print("\n" + "=" * 60)
    print("Phase 5 E2E summary:")
    for name, passed in results.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(results.values()) else 1)

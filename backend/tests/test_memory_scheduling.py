"""Discriminative test for the every-5th-turn memory-extraction scheduling in
chat_rt.chat().

Drives the real FastAPI routing stack via TestClient (fastapi/starlette/sqlalchemy
are installed) with the app-local heavy modules stubbed the same way
test_chat_router.py does. Asserts background_tasks.add_task(extract_memory, ...)
fires iff (prior_count + 1) % 5 == 0 -- a discriminative check (prior_count 4 -> the
5th turn triggers; 3 -> the 4th turn does not), not a "latency unchanged" non-test.
"""
import sys
import types
import unittest
from pathlib import Path

_backend_dir = Path(__file__).parent.parent
_app_dir = _backend_dir / "app"
for _p in (str(_backend_dir), str(_app_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ok_final_answer(*args, **kwargs):
    # Tolerates whatever kwargs the merge step (worker-3) may later pass
    # (history, session_id, user_profile, ...).
    yield 'data: {"content": "hi there", "thinking": false}\n\n'


# ── Stub app-local heavy modules before importing chat_rt ─────────────────────
class _CtxNullSession:
    """Minimal context-manager DB session for any incidental recall (e.g. a
    recall_user_profile the merge step may add): every read yields "nothing"."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        class _R:
            def fetchone(self_inner):
                return None

            def fetchall(self_inner):
                return []

        return _R()

    def commit(self):
        pass

    def rollback(self):
        pass


if "utils.database" not in sys.modules:
    _fake_db = types.ModuleType("utils.database")
    _fake_db.SessionLocal = lambda *a, **k: _CtxNullSession()
    _fake_db.get_db = lambda: iter(())
    sys.modules["utils.database"] = _fake_db

if "utils.es_client" not in sys.modules:
    _fake_es = types.ModuleType("utils.es_client")
    _fake_es.get_es_client = lambda *a, **k: None
    sys.modules["utils.es_client"] = _fake_es

if "service.agent.agent" not in sys.modules:
    # Permissive stub: resilient to the merge step importing extra symbols
    # (classify_skill, load_skill, ...) from agent -- any missing name resolves
    # to a harmless no-op; final_answer is a proper SSE generator.
    _fake_agent = types.ModuleType("service.agent.agent")
    _fake_agent.final_answer = _ok_final_answer

    def _agent_getattr(name):
        return lambda *a, **k: None

    _fake_agent.__getattr__ = _agent_getattr
    sys.modules["service.agent.agent"] = _fake_agent

if "service.core.file_parse" not in sys.modules:
    _fake_fp = types.ModuleType("service.core.file_parse")
    _fake_fp.execute_insert_process = lambda *a, **k: None
    sys.modules["service.core.file_parse"] = _fake_fp

if "database.knowledgebase_operations" not in sys.modules:
    _fake_kb = types.ModuleType("database.knowledgebase_operations")
    _fake_kb.insert_knowledgebase = lambda *a, **k: None
    _fake_kb.delete_knowledgebase_entry = lambda *a, **k: None
    sys.modules["database.knowledgebase_operations"] = _fake_kb

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import router.chat_rt as chat_rt  # noqa: E402


class _CountingSessionLocal:
    """Context-manager fake whose COUNT(*) answers a configurable prior_count so
    the handler's will_be_turn = prior_count + 1 lands on / off the 5-boundary."""

    prior_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        stmt_text = str(stmt)
        pc = _CountingSessionLocal.prior_count

        class _R:
            def fetchone(self_inner):
                if "SELECT 1 FROM sessions" in stmt_text:
                    return (1,)
                if "SELECT COUNT(*) FROM messages" in stmt_text:
                    return (pc,)
                return None

            def fetchall(self_inner):
                return []

        return _R()

    def commit(self):
        pass

    def rollback(self):
        pass


class ExtractionSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(chat_rt.router)
        self.client = TestClient(self.app)
        self._recorded = []
        self._orig_session_local = chat_rt.SessionLocal
        self._orig_final_answer = chat_rt.final_answer
        self._orig_extract = chat_rt.extract_memory
        chat_rt.SessionLocal = _CountingSessionLocal
        chat_rt.final_answer = _ok_final_answer
        chat_rt.extract_memory = lambda sid: self._recorded.append(sid)

    def tearDown(self):
        chat_rt.SessionLocal = self._orig_session_local
        chat_rt.final_answer = self._orig_final_answer
        chat_rt.extract_memory = self._orig_extract

    def test_fifth_turn_schedules_extraction(self):
        _CountingSessionLocal.prior_count = 4  # will_be_turn = 5 -> trigger
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 200)
        # TestClient runs background tasks after the response body completes.
        self.assertEqual(self._recorded, ["sess0001"])

    def test_fourth_turn_does_not_schedule_extraction(self):
        _CountingSessionLocal.prior_count = 3  # will_be_turn = 4 -> no trigger
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._recorded, [])


if __name__ == "__main__":
    unittest.main()

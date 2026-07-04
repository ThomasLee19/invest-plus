"""
TestClient-level tests for router/history_rt.py.

history_rt.py imports `_validate_session_id` from router.chat_rt, so importing
it pulls in chat_rt's whole import chain (schemas.chat, utils.database,
utils.es_client, service.agent.agent, service.core.file_parse,
database.knowledgebase_operations). Those app-local heavy modules are stubbed
the same way test_chat_router.py stubs them, before either router module is
imported, so this file can run standalone with no real DB/ES/LLM.

Coverage (L1): delete_session/get_messages must reject an empty session_id
with a 400, consistent with chat()'s existing behavior, rather than silently
no-oping (_validate_session_id("") returns None, which would otherwise let
delete_session report a false "已删除" success while deleting nothing).
"""
import sys
import types
from pathlib import Path

import unittest

_app_dir = Path(__file__).parent.parent / "app"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

if "utils.database" not in sys.modules:
    _fake_db = types.ModuleType("utils.database")

    def _get_db():  # pragma: no cover - not exercised by the rejection paths
        raise RuntimeError("get_db should not be called in these tests")

    class _SessionLocal:  # pragma: no cover - unused here
        def __enter__(self):
            raise RuntimeError("SessionLocal not stubbed for this test")

        def __exit__(self, *a):
            return False

    _fake_db.get_db = _get_db
    _fake_db.SessionLocal = _SessionLocal
    sys.modules["utils.database"] = _fake_db

if "utils.es_client" not in sys.modules:
    _fake_es_client = types.ModuleType("utils.es_client")
    _fake_es_client.get_es_client = lambda: None
    sys.modules["utils.es_client"] = _fake_es_client

if "service.agent.agent" not in sys.modules:
    _fake_agent = types.ModuleType("service.agent.agent")
    _fake_agent.final_answer = lambda *a, **kw: iter(())
    sys.modules["service.agent.agent"] = _fake_agent

if "service.core.file_parse" not in sys.modules:
    _fake_fp = types.ModuleType("service.core.file_parse")
    _fake_fp.execute_insert_process = lambda *a, **kw: None
    sys.modules["service.core.file_parse"] = _fake_fp

if "database.knowledgebase_operations" not in sys.modules:
    _fake_kb = types.ModuleType("database.knowledgebase_operations")
    _fake_kb.insert_knowledgebase = lambda *a, **kw: None
    _fake_kb.delete_knowledgebase_entry = lambda *a, **kw: None
    sys.modules["database.knowledgebase_operations"] = _fake_kb

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import router.history_rt as history_rt  # noqa: E402


def _get_db_override():
    # get_db is a Depends() for db.execute; the 400 rejection happens before
    # any db.execute call, so a stub that would blow up if actually used is
    # fine here -- it just must not raise while FastAPI resolves the Depends.
    yield None


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(history_rt.router)
    app.dependency_overrides[history_rt.get_db] = _get_db_override
    return TestClient(app)


class EmptySessionIdRejectionTests(unittest.TestCase):
    """L1: empty session_id must be rejected consistently with chat()'s 400,
    not silently treated as a no-op success."""

    def setUp(self):
        self.client = _make_client()

    def test_delete_session_with_empty_session_id_returns_400_not_false_success(self):
        resp = self.client.delete("/sessions", params={"session_id": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("已删除", resp.text)

    def test_get_messages_with_empty_session_id_returns_400(self):
        resp = self.client.get("/messages", params={"session_id": ""})
        self.assertEqual(resp.status_code, 400)

    def test_delete_session_with_path_traversal_session_id_is_rejected(self):
        resp = self.client.delete("/sessions", params={"session_id": "../../etc"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()

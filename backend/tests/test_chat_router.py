"""
TestClient-level tests for router/chat_rt.py.

Unlike test_agent_loop.py (which stubs *all* third-party packages and never
imports fastapi), these tests drive the real fastapi routing stack via
fastapi.testclient.TestClient. fastapi + starlette + sqlalchemy must therefore
be installed for this file to run — they are not stubbed here. What *is* stubbed
(the same sys.modules-before-import pattern test_agent_loop.py uses) are the
app-local heavy modules chat_rt.py imports at load time: the DB engine
(utils.database), the ES client (utils.es_client), the agent pipeline
(service.agent.agent), the file-parse/index path (service.core.file_parse) and
the knowledgebase ops (database.knowledgebase_operations). There is no test DB
or live Elasticsearch in this environment, so those boundaries are faked and the
tests assert on the router's own validation / cleanup / scoping behavior, which
is what chat_rt.py owns.

Coverage:
  (a) malformed / empty session_id is rejected (400) before any side effect
  (b) an oversized upload is rejected (413) and the partial file is cleaned up
  (c) a disallowed file extension is rejected (400) before anything is written
  (d) delete_file scopes its ES delete to the caller's session, so it cannot
      touch another session's file (neither in ES nor on disk)
"""
import io
import os
import shutil
import sys
import types
from pathlib import Path

import unittest

# chat_rt.py imports are rooted at backend/app (e.g. `from utils.database import
# get_db`), so that directory must be on sys.path — mirroring how the app itself
# is run (uvicorn app_main:app from backend/app).
_app_dir = Path(__file__).parent.parent / "app"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


# ── Stub the app-local heavy modules before importing chat_rt ────────────────
# utils.database.create_engine(DATABASE_URL) would run at import time against a
# non-existent DB; replace the whole module with lightweight fakes. Individual
# tests can swap SessionLocal for a context-manager fake when they need one.
if "utils.database" not in sys.modules:
    _fake_db = types.ModuleType("utils.database")

    def _get_db():  # pragma: no cover - not exercised by the rejection paths
        raise RuntimeError("get_db should not be called in these tests")

    class _SessionLocal:  # pragma: no cover - swapped per-test when needed
        def __enter__(self):
            raise RuntimeError("SessionLocal not stubbed for this test")

        def __exit__(self, *a):
            return False

    _fake_db.get_db = _get_db
    _fake_db.SessionLocal = _SessionLocal
    sys.modules["utils.database"] = _fake_db

_ES_HOLDER = {"client": None}

if "utils.es_client" not in sys.modules:
    _fake_es_client = types.ModuleType("utils.es_client")
    _fake_es_client.get_es_client = lambda: _ES_HOLDER["client"]
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

import router.chat_rt as chat_rt  # noqa: E402


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_rt.router)
    return TestClient(app)


class SessionIdValidationTests(unittest.TestCase):
    """(a) /chat must reject malformed and empty session_id before any work."""

    def setUp(self):
        self.client = _make_client()

    def test_path_traversal_session_id_is_rejected(self):
        resp = self.client.post(
            "/chat", params={"session_id": "../../etc"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Invalid session_id")

    def test_empty_session_id_is_rejected(self):
        # ?session_id= satisfies Query(...) (present but empty); _validate returns
        # None, and chat() must 400 rather than proceed to a NULL-session insert.
        resp = self.client.post("/chat", params={"session_id": ""}, json={"message": "hi"})
        self.assertEqual(resp.status_code, 400)

    def test_empty_message_is_rejected_by_schema(self):
        # min_length=1 on ChatRequest.message -> 422 before the pipeline runs.
        resp = self.client.post(
            "/chat", params={"session_id": "abc123"}, json={"message": ""}
        )
        self.assertEqual(resp.status_code, 422)


class UploadValidationTests(unittest.TestCase):
    """(b)/(c) upload rejection + partial-file cleanup and extension gating."""

    def setUp(self):
        self.client = _make_client()
        self._orig_storage = chat_rt.STORAGE_DIR
        self._orig_max = chat_rt.MAX_UPLOAD_BYTES
        self._tmp = Path(
            os.environ.get("PYTEST_TMP", "/tmp")
        ) / f"invest_upload_test_{os.getpid()}"
        self._tmp.mkdir(parents=True, exist_ok=True)
        chat_rt.STORAGE_DIR = str(self._tmp)

    def tearDown(self):
        chat_rt.STORAGE_DIR = self._orig_storage
        chat_rt.MAX_UPLOAD_BYTES = self._orig_max
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_oversized_upload_is_rejected_and_partial_file_removed(self):
        chat_rt.MAX_UPLOAD_BYTES = 10  # tiny cap so a small payload trips it
        payload = b"x" * 5000
        resp = self.client.post(
            "/upload_files/",
            params={"session_id": "sess0001"},
            files={"files": ("big.txt", io.BytesIO(payload), "text/plain")},
        )
        self.assertEqual(resp.status_code, 413)
        # The partially-written file must have been cleaned up.
        written = self._tmp / "sess0001" / "big.txt"
        self.assertFalse(written.exists(), "oversized partial upload was not cleaned up")

    def test_disallowed_extension_is_rejected_before_writing(self):
        resp = self.client.post(
            "/upload_files/",
            params={"session_id": "sess0001"},
            files={"files": ("evil.exe", io.BytesIO(b"data"), "application/octet-stream")},
        )
        self.assertEqual(resp.status_code, 400)
        # Nothing should have been written for the rejected batch.
        self.assertFalse((self._tmp / "sess0001" / "evil.exe").exists())

    def test_disallowed_extension_rejects_whole_batch_upfront(self):
        # A valid file listed before a disallowed one must NOT be written/indexed:
        # extension validation happens for the whole batch before any write.
        resp = self.client.post(
            "/upload_files/",
            params={"session_id": "sess0001"},
            files=[
                ("files", ("good.txt", io.BytesIO(b"ok"), "text/plain")),
                ("files", ("evil.exe", io.BytesIO(b"data"), "application/octet-stream")),
            ],
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse((self._tmp / "sess0001" / "good.txt").exists(),
                         "an earlier valid file was written despite a later invalid file")


class _RecordingEs:
    """Captures the delete_by_query body and reports zero deletions."""

    def __init__(self):
        self.last_body = None

    def delete_by_query(self, index=None, body=None, refresh=None):
        self.last_body = body
        return {"deleted": 0}


class _RecordingSessionLocal:
    """Fake SessionLocal: a context-manager DB session that records every
    executed statement so tests can assert whether an INSERT was attempted,
    without a real database."""

    calls: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        _RecordingSessionLocal.calls.append((str(stmt), params))

        class _Result:
            def fetchall(self_inner):
                return []

        return _Result()

    def commit(self):
        pass

    def rollback(self):
        pass


def _failing_final_answer(*args, **kwargs):
    # A generator function (has a `yield`, even if unreachable) so calling it
    # returns an iterator lazily -- the RuntimeError only fires once stream()
    # actually starts iterating it, mirroring a real mid-stream LLM/API failure.
    raise RuntimeError("upstream LLM boom")
    yield  # pragma: no cover


class StreamMidFailureTests(unittest.TestCase):
    """M1: an exception raised while iterating final_answer() must not escape
    stream() uncaught -- it must yield a well-formed SSE error event plus a
    proper terminator, and _persist() must not write a blank successful turn
    when no answer content was ever collected."""

    def setUp(self):
        self.client = _make_client()
        _RecordingSessionLocal.calls = []
        self._orig_session_local = chat_rt.SessionLocal
        self._orig_final_answer = chat_rt.final_answer
        chat_rt.SessionLocal = _RecordingSessionLocal
        chat_rt.final_answer = _failing_final_answer

    def tearDown(self):
        chat_rt.SessionLocal = self._orig_session_local
        chat_rt.final_answer = self._orig_final_answer

    def test_stream_terminates_cleanly_on_mid_stream_failure(self):
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("event: end", body)
        self.assertIn("data: [DONE]", body)
        self.assertIn('"role": "assistant"', body)

    def test_blank_turn_is_not_persisted_when_no_answer_collected(self):
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 200)
        insert_calls = [
            c for c in _RecordingSessionLocal.calls if "INSERT INTO messages" in c[0]
        ]
        self.assertEqual(
            insert_calls, [], "a blank turn must not be persisted after a mid-stream failure"
        )


class DeleteFileScopingTests(unittest.TestCase):
    """(d) delete_file must scope to the caller's session — it cannot delete a
    different session's same-named file, in ES or on disk."""

    def setUp(self):
        self.client = _make_client()
        self._orig_storage = chat_rt.STORAGE_DIR
        self._tmp = Path("/tmp") / f"invest_delete_test_{os.getpid()}"
        self._tmp.mkdir(parents=True, exist_ok=True)
        chat_rt.STORAGE_DIR = str(self._tmp)
        self._es = _RecordingEs()
        _ES_HOLDER["client"] = self._es

    def tearDown(self):
        chat_rt.STORAGE_DIR = self._orig_storage
        _ES_HOLDER["client"] = None
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_delete_scopes_es_query_to_caller_session(self):
        resp = self.client.request(
            "DELETE", "/delete_file/", params={"file_name": "report.pdf", "session_id": "sessAAAA"}
        )
        self.assertEqual(resp.status_code, 200)
        must = self._es.last_body["query"]["bool"]["must"]
        self.assertIn({"term": {"session_id": "sessAAAA"}}, must)
        # user_upload constraint ensures seed corpus is never deletable here.
        self.assertIn({"term": {"source_kwd": "user_upload"}}, must)

    def test_delete_does_not_remove_other_sessions_disk_file(self):
        # Two sessions each have report.pdf on disk; deleting session A's copy
        # must leave session B's copy untouched.
        (self._tmp / "sessAAAA").mkdir(parents=True, exist_ok=True)
        (self._tmp / "sessBBBB").mkdir(parents=True, exist_ok=True)
        file_a = self._tmp / "sessAAAA" / "report.pdf"
        file_b = self._tmp / "sessBBBB" / "report.pdf"
        file_a.write_bytes(b"a")
        file_b.write_bytes(b"b")

        resp = self.client.request(
            "DELETE", "/delete_file/", params={"file_name": "report.pdf", "session_id": "sessAAAA"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(file_a.exists(), "caller session's own file should be removed")
        self.assertTrue(file_b.exists(), "another session's file must not be removed")


if __name__ == "__main__":
    unittest.main()

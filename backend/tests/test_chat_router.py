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
    without a real database.

    session_exists controls the fake answer to the "SELECT 1 FROM sessions
    WHERE session_id = :sid" existence check chat() runs before persisting;
    defaults to True so tests that don't care about that check (e.g.
    StreamMidFailureTests) keep behaving as if the session is real.
    """

    calls: list = []
    session_exists = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        _RecordingSessionLocal.calls.append((str(stmt), params))

        exists = _RecordingSessionLocal.session_exists

        class _Result:
            def fetchall(self_inner):
                return []

            def fetchone(self_inner):
                return (1,) if exists else None

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
        _RecordingSessionLocal.session_exists = True
        self._orig_session_local = chat_rt.SessionLocal
        self._orig_final_answer = chat_rt.final_answer
        chat_rt.SessionLocal = _RecordingSessionLocal
        chat_rt.final_answer = _failing_final_answer

    def tearDown(self):
        chat_rt.SessionLocal = self._orig_session_local
        chat_rt.final_answer = self._orig_final_answer
        _RecordingSessionLocal.session_exists = True

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


def _ok_final_answer(*args, **kwargs):
    # A minimal well-formed SSE stream so _persist() has an answer to collect.
    yield 'data: {"content": "hi there", "thinking": false}\n\n'


class SessionExistenceTests(unittest.TestCase):
    """Fix 1: /chat must reject a well-formed but nonexistent session_id
    instead of silently persisting an orphan message (messages.session_id has
    no FK, so the INSERT would otherwise succeed while the sessions row never
    gets updated)."""

    def setUp(self):
        self.client = _make_client()
        _RecordingSessionLocal.calls = []
        _RecordingSessionLocal.session_exists = True
        self._orig_session_local = chat_rt.SessionLocal
        self._orig_final_answer = chat_rt.final_answer
        chat_rt.SessionLocal = _RecordingSessionLocal
        chat_rt.final_answer = _ok_final_answer

    def tearDown(self):
        chat_rt.SessionLocal = self._orig_session_local
        chat_rt.final_answer = self._orig_final_answer
        _RecordingSessionLocal.session_exists = True

    def test_chat_rejects_well_formed_but_nonexistent_session_id(self):
        _RecordingSessionLocal.session_exists = False
        resp = self.client.post(
            "/chat", params={"session_id": "sessGHOST"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 404)
        insert_calls = [
            c for c in _RecordingSessionLocal.calls if "INSERT INTO messages" in c[0]
        ]
        self.assertEqual(
            insert_calls, [],
            "no message should be persisted for a session that doesn't exist",
        )

    def test_chat_proceeds_when_session_exists(self):
        _RecordingSessionLocal.session_exists = True
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 200)
        insert_calls = [
            c for c in _RecordingSessionLocal.calls if "INSERT INTO messages" in c[0]
        ]
        self.assertEqual(len(insert_calls), 1)


class _RecordingEsFiles:
    """Fake ES client for /get_files/: returns a composite-aggregation shaped
    response spanning two different sessions, so tests can assert the current
    cross-session (global) behavior of get_files."""

    def search(self, index=None, body=None):
        return {
            "aggregations": {
                "by_file": {
                    "buckets": [
                        {
                            "latest": {
                                "hits": {
                                    "hits": [{
                                        "_source": {
                                            "docnm_kwd": "sessionA.txt",
                                            "create_time": "2026-01-01T00:00:00",
                                            "session_id": "sessAAAA",
                                        }
                                    }]
                                }
                            }
                        },
                        {
                            "latest": {
                                "hits": {
                                    "hits": [{
                                        "_source": {
                                            "docnm_kwd": "sessionB.txt",
                                            "create_time": "2026-01-02T00:00:00",
                                            "session_id": "sessBBBB",
                                        }
                                    }]
                                }
                            }
                        },
                    ]
                }
            }
        }


class GetFilesGlobalViewTests(unittest.TestCase):
    """Fix 2: get_files intentionally has no session_id filter -- it backs the
    frontend Repository page (api.repository.list() takes no session_id), which
    shows uploads across all sessions. This test documents/pins that current
    behavior so a future accidental narrowing to one session doesn't slip in
    unnoticed alongside a real bug fix elsewhere."""

    def setUp(self):
        self.client = _make_client()
        _ES_HOLDER["client"] = _RecordingEsFiles()

    def tearDown(self):
        _ES_HOLDER["client"] = None

    def test_get_files_returns_uploads_across_all_sessions(self):
        resp = self.client.get("/get_files/")
        self.assertEqual(resp.status_code, 200)
        session_ids = {row["session_id"] for row in resp.json()}
        self.assertEqual(session_ids, {"sessAAAA", "sessBBBB"})


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


class _HistoryAwareSessionLocal:
    """Fake SessionLocal for the chat() happy-path test (debug/26_7_4_debug_4.md
    test-coverage gap): unlike _RecordingSessionLocal (which answers every
    fetchone/fetchall the same way regardless of query), this one routes based
    on which statement is being executed, so a single fake DB can serve the
    session-existence check, the history read, and the persist+rename writes
    within one request and still return query-appropriate results."""

    calls: list = []
    history_rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        stmt_text = str(stmt)
        _HistoryAwareSessionLocal.calls.append((stmt_text, params))

        class _Result:
            def fetchone(self_inner):
                if "SELECT 1 FROM sessions" in stmt_text:
                    return (1,)
                return None

            def fetchall(self_inner):
                if "SELECT user_question, model_answer FROM messages" in stmt_text:
                    return list(_HistoryAwareSessionLocal.history_rows)
                return []

        return _Result()

    def commit(self):
        pass

    def rollback(self):
        pass


class ChatSuccessPathTests(unittest.TestCase):
    """debug/26_7_4_debug_4.md test-coverage gap: chat()'s success path had no
    test -- the answer must actually get persisted, the session's default name
    must get renamed on the first message, and history must be read back in
    the correct (oldest-first) order for a multi-turn conversation."""

    def setUp(self):
        self.client = _make_client()
        _HistoryAwareSessionLocal.calls = []
        _HistoryAwareSessionLocal.history_rows = []
        self._orig_session_local = chat_rt.SessionLocal
        self._orig_final_answer = chat_rt.final_answer
        chat_rt.SessionLocal = _HistoryAwareSessionLocal
        chat_rt.final_answer = _ok_final_answer

    def tearDown(self):
        chat_rt.SessionLocal = self._orig_session_local
        chat_rt.final_answer = self._orig_final_answer

    def test_answer_is_persisted_with_full_collected_content(self):
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "hi"}
        )
        self.assertEqual(resp.status_code, 200)
        insert_calls = [
            c for c in _HistoryAwareSessionLocal.calls if "INSERT INTO messages" in c[0]
        ]
        self.assertEqual(len(insert_calls), 1)
        params = insert_calls[0][1]
        self.assertEqual(params["q"], "hi")
        self.assertEqual(params["a"], "hi there")  # _ok_final_answer's single chunk

    def test_default_session_name_is_renamed_on_first_message(self):
        long_question = "what is AAPL's PE ratio and dividend yield this quarter"
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": long_question}
        )
        self.assertEqual(resp.status_code, 200)
        update_calls = [
            c for c in _HistoryAwareSessionLocal.calls
            if "UPDATE sessions SET session_name" in c[0]
        ]
        self.assertEqual(len(update_calls), 1)
        params = update_calls[0][1]
        self.assertEqual(params["name"], long_question[:20] + "...")
        self.assertEqual(params["default_name"], chat_rt.DEFAULT_SESSION_NAME)
        self.assertEqual(params["sid"], "sess0001")

    def test_history_passed_to_final_answer_is_reversed_to_oldest_first_order(self):
        # The DB query orders rows `created_at DESC` (newest first); chat()
        # must reverse them back to oldest-first before handing them to
        # final_answer()'s `history` argument.
        _HistoryAwareSessionLocal.history_rows = [
            types.SimpleNamespace(user_question="q3", model_answer="a3"),  # newest
            types.SimpleNamespace(user_question="q2", model_answer="a2"),
            types.SimpleNamespace(user_question="q1", model_answer="a1"),  # oldest
        ]
        captured = {}

        def _capturing_final_answer(question, history=None, session_id=None):
            captured["history"] = history
            yield 'data: {"content": "ok", "thinking": false}\n\n'

        chat_rt.final_answer = _capturing_final_answer
        resp = self.client.post(
            "/chat", params={"session_id": "sess0001"}, json={"message": "q4"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            captured["history"],
            [
                {"user": "q1", "assistant": "a1"},
                {"user": "q2", "assistant": "a2"},
                {"user": "q3", "assistant": "a3"},
            ],
        )


class _RecordingEsOfficialExamples:
    """Fake ES client for /get_official_examples/: returns a terms-aggregation
    shaped response with two distinct source_kwd values, so the test can
    assert chunk_method is derived correctly per source and the response shape
    matches what the frontend expects."""

    def search(self, index=None, body=None):
        return {
            "aggregations": {
                "by_file": {
                    "buckets": [
                        {
                            "latest": {
                                "hits": {
                                    "hits": [{
                                        "_source": {
                                            "docnm_kwd": "AAPL_10K.htm",
                                            "create_time": "2026-01-01T00:00:00",
                                            "source_kwd": "sec_filing",
                                        }
                                    }]
                                }
                            }
                        },
                        {
                            "latest": {
                                "hits": {
                                    "hits": [{
                                        "_source": {
                                            "docnm_kwd": "intro-to-pe-ratio.md",
                                            "create_time": "2026-01-02T00:00:00",
                                            "source_kwd": "educational",
                                        }
                                    }]
                                }
                            }
                        },
                    ]
                }
            }
        }


class GetOfficialExamplesTests(unittest.TestCase):
    """debug/26_7_4_debug_4.md test-coverage gap: get_official_examples'
    aggregation/parsing had no test."""

    def setUp(self):
        self.client = _make_client()
        _ES_HOLDER["client"] = _RecordingEsOfficialExamples()

    def tearDown(self):
        _ES_HOLDER["client"] = None

    def test_returns_one_entry_per_file_with_expected_shape(self):
        resp = self.client.get("/get_official_examples/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        names = {row["file_name"] for row in body}
        self.assertEqual(names, {"AAPL_10K.htm", "intro-to-pe-ratio.md"})
        for row in body:
            self.assertEqual(row["status"], "Indexed")
            self.assertIn("chunk_method", row)
            self.assertIn("updated_at", row)


if __name__ == "__main__":
    unittest.main()

"""
Unit test for `get_latest_user_upload()` (backend/app/database/knowledgebase_operations.py).

This project's DB layer (`app/utils/database.py`) talks to a real Postgres via
`DATABASE_URL` (from repo-root `.env`) — there's no in-memory test DB. This
test connects to that real database, inserts a handful of `knowledgebases`
rows for two distinct (uniquely-suffixed) session_ids with explicit,
deterministic `created_at` timestamps, and asserts `get_latest_user_upload()`
returns only the correct session's most recent upload. All inserted rows are
deleted in tearDown so no fixture data is left behind in the dev DB.

If the DB is unreachable, the whole class is skipped with a clear reason
(checked once in setUpClass, not silently assumed).
"""
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

_backend_dir = Path(__file__).parent.parent
_app_dir = _backend_dir / "app"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from utils.database import SessionLocal  # noqa: E402
from database.knowledgebase_operations import (  # noqa: E402
    get_latest_user_upload,
    insert_knowledgebase,
    delete_knowledgebase_entry,
)


class GetLatestUserUploadTests(unittest.TestCase):
    """Step 10 requirement: `get_latest_user_upload` returns only the queried
    session's most recent upload, not another session's and not an older one."""

    @classmethod
    def setUpClass(cls):
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        except OperationalError as exc:
            raise unittest.SkipTest(f"DATABASE_URL unreachable: {exc}") from exc
        finally:
            db.close()

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.session_a = f"test_sess_a_{suffix}"[:16]
        self.session_b = f"test_sess_b_{suffix}"[:16]
        self._inserted_ids = []

        now = datetime.utcnow()
        db = SessionLocal()
        try:
            self._insert(db, self.session_a, "a_older.pdf", now - timedelta(minutes=10))
            self._insert(db, self.session_a, "a_newest.pdf", now - timedelta(minutes=1))
            self._insert(db, self.session_b, "b_newest.pdf", now - timedelta(minutes=1))
            db.commit()
        finally:
            db.close()

    def _insert(self, db, session_id, file_name, created_at):
        row = db.execute(
            text(
                "INSERT INTO knowledgebases (user_id, file_name, session_id, created_at) "
                "VALUES (:uid, :fn, :sid, :ca) RETURNING id"
            ),
            {"uid": "1", "fn": file_name, "sid": session_id, "ca": created_at},
        ).fetchone()
        self._inserted_ids.append(row.id)

    def tearDown(self):
        if not self._inserted_ids:
            return
        db = SessionLocal()
        try:
            db.execute(
                text("DELETE FROM knowledgebases WHERE id = ANY(:ids)"),
                {"ids": self._inserted_ids},
            )
            db.commit()
        finally:
            db.close()

    def test_returns_most_recent_upload_for_correct_session(self):
        self.assertEqual(get_latest_user_upload(self.session_a), "a_newest.pdf")

    def test_does_not_return_another_sessions_upload(self):
        result = get_latest_user_upload(self.session_a)
        self.assertNotEqual(result, "b_newest.pdf")

    def test_does_not_return_older_upload_from_same_session(self):
        result = get_latest_user_upload(self.session_a)
        self.assertNotEqual(result, "a_older.pdf")

    def test_returns_none_for_unknown_session(self):
        self.assertIsNone(get_latest_user_upload(f"nonexistent_{uuid.uuid4().hex}"[:16]))

    def test_returns_none_for_falsy_session_id(self):
        self.assertIsNone(get_latest_user_upload(None))
        self.assertIsNone(get_latest_user_upload(""))


class DeleteKnowledgebaseEntryTests(unittest.TestCase):
    """US-002: `delete_knowledgebase_entry` removes only the matching
    (file_name, session_id) row — it must not touch another session's or the
    global bucket's row for the same filename, and vice versa."""

    @classmethod
    def setUpClass(cls):
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        except OperationalError as exc:
            raise unittest.SkipTest(f"DATABASE_URL unreachable: {exc}") from exc
        finally:
            db.close()

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.session_a = f"test_del_a_{suffix}"[:16]
        self.session_b = f"test_del_b_{suffix}"[:16]
        self.file_name = f"del_test_{suffix}.pdf"
        self._cleanup_rows = []  # list of (file_name, session_id) to clean up in tearDown

    def _row_exists(self, file_name, session_id):
        db = SessionLocal()
        try:
            if session_id:
                row = db.execute(
                    text(
                        "SELECT 1 FROM knowledgebases WHERE file_name = :fn AND session_id = :sid"
                    ),
                    {"fn": file_name, "sid": session_id},
                ).fetchone()
            else:
                row = db.execute(
                    text(
                        "SELECT 1 FROM knowledgebases WHERE file_name = :fn AND session_id IS NULL"
                    ),
                    {"fn": file_name},
                ).fetchone()
            return row is not None
        finally:
            db.close()

    def tearDown(self):
        db = SessionLocal()
        try:
            for file_name, session_id in self._cleanup_rows:
                if session_id:
                    db.execute(
                        text(
                            "DELETE FROM knowledgebases WHERE file_name = :fn AND session_id = :sid"
                        ),
                        {"fn": file_name, "sid": session_id},
                    )
                else:
                    db.execute(
                        text(
                            "DELETE FROM knowledgebases WHERE file_name = :fn AND session_id IS NULL"
                        ),
                        {"fn": file_name},
                    )
            db.commit()
        finally:
            db.close()

    def test_deletes_matching_session_row(self):
        insert_knowledgebase("1", self.file_name, self.session_a)
        self._cleanup_rows.append((self.file_name, self.session_a))
        self.assertTrue(self._row_exists(self.file_name, self.session_a))

        delete_knowledgebase_entry(self.file_name, self.session_a)

        self.assertFalse(self._row_exists(self.file_name, self.session_a))

    def test_does_not_delete_other_sessions_same_filename_row(self):
        insert_knowledgebase("1", self.file_name, self.session_a)
        insert_knowledgebase("1", self.file_name, self.session_b)
        self._cleanup_rows.append((self.file_name, self.session_a))
        self._cleanup_rows.append((self.file_name, self.session_b))

        delete_knowledgebase_entry(self.file_name, self.session_a)

        self.assertFalse(self._row_exists(self.file_name, self.session_a))
        self.assertTrue(self._row_exists(self.file_name, self.session_b))

    def test_does_not_delete_global_bucket_row_with_same_filename(self):
        insert_knowledgebase("1", self.file_name, self.session_a)
        insert_knowledgebase("1", self.file_name, None)
        self._cleanup_rows.append((self.file_name, self.session_a))
        self._cleanup_rows.append((self.file_name, None))

        delete_knowledgebase_entry(self.file_name, self.session_a)

        self.assertFalse(self._row_exists(self.file_name, self.session_a))
        self.assertTrue(self._row_exists(self.file_name, None))

    def test_deletes_only_global_bucket_row_when_session_id_falsy(self):
        insert_knowledgebase("1", self.file_name, None)
        insert_knowledgebase("1", self.file_name, self.session_a)
        self._cleanup_rows.append((self.file_name, None))
        self._cleanup_rows.append((self.file_name, self.session_a))

        delete_knowledgebase_entry(self.file_name, None)

        self.assertFalse(self._row_exists(self.file_name, None))
        self.assertTrue(self._row_exists(self.file_name, self.session_a))

    def test_get_latest_user_upload_no_longer_returns_deleted_file(self):
        """Simulates the post-delete_file state: once the knowledgebases row
        is pruned, get_latest_user_upload must stop surfacing that filename
        for the upload-boost logic in agent.py's rag_search."""
        insert_knowledgebase("1", self.file_name, self.session_a)
        self._cleanup_rows.append((self.file_name, self.session_a))
        self.assertEqual(get_latest_user_upload(self.session_a), self.file_name)

        delete_knowledgebase_entry(self.file_name, self.session_a)

        self.assertIsNone(get_latest_user_upload(self.session_a))


if __name__ == "__main__":
    unittest.main()

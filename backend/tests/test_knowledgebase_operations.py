"""
Unit test for `get_latest_user_upload()` (backend/app/database/knowledgebase_operations.py).

This project's DB layer (`app/utils/database.py`) talks to a real Postgres via
`DATABASE_URL` (from repo-root `.env`) — there's no in-memory test DB. This
test connects to that real database, inserts a handful of `knowledgebases`
rows for two distinct (uniquely-suffixed) user_ids with explicit, deterministic
`created_at` timestamps, and asserts `get_latest_user_upload()` returns only
the correct user's most recent upload. All inserted rows are deleted in
tearDown so no fixture data is left behind in the dev DB.

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
from database.knowledgebase_operations import get_latest_user_upload  # noqa: E402


class GetLatestUserUploadTests(unittest.TestCase):
    """Step 10 requirement: `get_latest_user_upload` returns only the queried
    user's most recent upload, not another user's and not an older one."""

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
        self.user_a = f"test_user_a_{suffix}"
        self.user_b = f"test_user_b_{suffix}"
        self._inserted_ids = []

        now = datetime.utcnow()
        db = SessionLocal()
        try:
            self._insert(db, self.user_a, "a_older.pdf", now - timedelta(minutes=10))
            self._insert(db, self.user_a, "a_newest.pdf", now - timedelta(minutes=1))
            self._insert(db, self.user_b, "b_newest.pdf", now - timedelta(minutes=1))
            db.commit()
        finally:
            db.close()

    def _insert(self, db, user_id, file_name, created_at):
        row = db.execute(
            text(
                "INSERT INTO knowledgebases (user_id, file_name, created_at) "
                "VALUES (:uid, :fn, :ca) RETURNING id"
            ),
            {"uid": user_id, "fn": file_name, "ca": created_at},
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

    def test_returns_most_recent_upload_for_correct_user(self):
        self.assertEqual(get_latest_user_upload(self.user_a), "a_newest.pdf")

    def test_does_not_return_another_users_upload(self):
        result = get_latest_user_upload(self.user_a)
        self.assertNotEqual(result, "b_newest.pdf")

    def test_does_not_return_older_upload_from_same_user(self):
        result = get_latest_user_upload(self.user_a)
        self.assertNotEqual(result, "a_older.pdf")

    def test_returns_none_for_unknown_user(self):
        self.assertIsNone(get_latest_user_upload(f"nonexistent_{uuid.uuid4().hex}"))


if __name__ == "__main__":
    unittest.main()

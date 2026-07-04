from sqlalchemy import text
from utils.database import SessionLocal


def insert_knowledgebase(user_id: str, file_name: str, session_id: str | None = None):
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO knowledgebases (user_id, file_name, session_id) "
                "VALUES (:uid, :fn, :sid)"
            ),
            {"uid": user_id, "fn": file_name, "sid": session_id},
        )
        db.commit()
    finally:
        db.close()


def delete_knowledgebase_entry(file_name: str, session_id: str | None = None) -> None:
    """删除 knowledgebases 表中匹配 file_name 且属于指定 scope 的行。

    scope 规则与仓库其他地方一致：session_id 为空/None 时代表全局桶
    （WHERE session_id IS NULL），否则只删除该 session 自己的行，
    不会误删其他 session 或全局桶下的同名文件记录。
    """
    db = SessionLocal()
    try:
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


def get_latest_user_upload(session_id: str | None) -> str | None:
    if not session_id:
        return None
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT file_name FROM knowledgebases WHERE session_id = :sid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"sid": session_id},
        ).fetchone()
        return row.file_name if row else None
    finally:
        db.close()

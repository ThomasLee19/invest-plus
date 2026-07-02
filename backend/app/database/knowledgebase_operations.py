from sqlalchemy import text
from utils.database import SessionLocal


def insert_knowledgebase(user_id: str, file_name: str):
    db = SessionLocal()
    try:
        db.execute(
            text("INSERT INTO knowledgebases (user_id, file_name) VALUES (:uid, :fn)"),
            {"uid": user_id, "fn": file_name},
        )
        db.commit()
    finally:
        db.close()


def verify_user_knowledgebase(user_id: str) -> bool:
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT 1 FROM knowledgebases WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        return row is not None
    finally:
        db.close()


def get_user_kb_files(user_id: str) -> list[str]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT file_name FROM knowledgebases WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchall()
        return [r.file_name for r in rows]
    finally:
        db.close()


def get_latest_user_upload(user_id: str) -> str | None:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT file_name FROM knowledgebases WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        return row.file_name if row else None
    finally:
        db.close()

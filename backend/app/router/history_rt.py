from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from utils.database import get_db

router = APIRouter()

USER_ID = "1"


@router.delete("/sessions")
async def delete_session(session_id: str = Query(...), db: Session = Depends(get_db)):
    try:
        db.execute(text("DELETE FROM messages WHERE session_id = :sid"), {"sid": session_id})
        db.execute(text("DELETE FROM sessions WHERE session_id = :sid"), {"sid": session_id})
        db.commit()
        return {"message": "已删除"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def get_sessions(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            text("SELECT session_id, session_name, created_at FROM sessions WHERE user_id = :uid ORDER BY created_at DESC"),
            {"uid": USER_ID},
        ).fetchall()
        return [
            {"session_id": r.session_id, "session_name": r.session_name, "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S")}
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages")
async def get_messages(session_id: str = Query(...), db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            text("SELECT user_question, model_answer, think, created_at FROM messages WHERE session_id = :sid ORDER BY created_at ASC"),
            {"sid": session_id},
        ).fetchall()
        return [
            {
                "user_question": r.user_question,
                "model_answer": r.model_answer,
                "think": r.think,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

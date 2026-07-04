from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from utils.database import get_db
from router.chat_rt import _validate_session_id

router = APIRouter()

USER_ID = "1"


# 全部用同步 def（而非 async def）：FastAPI 会把它们扔进线程池执行，避免每个
# handler 里的同步 db.execute 阻塞事件循环——这些 handler 都没有真正需要
# await 的地方。
@router.delete("/sessions")
def delete_session(session_id: str = Query(...), db: Session = Depends(get_db)):
    session_id = _validate_session_id(session_id)
    # 空字符串同样要拒绝：_validate_session_id("") 返回 None（其"全局 scope"
    # 语义在 chat()/upload_files 里是合法的可选参数），但这里 session_id 是
    # 必填路径参数，None 一路传给下面的 DELETE ... WHERE session_id = :sid
    # 只会匹配 0 行，却仍返回"已删除"，造成假成功。与 chat() 的 400 行为保持一致。
    if session_id is None:
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        db.execute(text("DELETE FROM messages WHERE session_id = :sid"), {"sid": session_id})
        db.execute(text("DELETE FROM sessions WHERE session_id = :sid"), {"sid": session_id})
        db.commit()
        return {"message": "已删除"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
def get_sessions(db: Session = Depends(get_db)):
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
def get_messages(session_id: str = Query(...), db: Session = Depends(get_db)):
    session_id = _validate_session_id(session_id)
    if session_id is None:
        raise HTTPException(status_code=400, detail="session_id is required")
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

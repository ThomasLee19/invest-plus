import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Body, File, HTTPException, Query, Depends, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from schemas.chat import ChatRequest
from utils.database import get_db
from service.agent.agent import final_answer
from service.core.file_parse import execute_insert_process
from database.knowledgebase_operations import insert_knowledgebase

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "../../../storage/file")
ALLOWED_EXTENSIONS = {".txt", ".md"}

router = APIRouter()

USER_ID = "1"


@router.post("/create_session")
async def create_session(db: Session = Depends(get_db)):
    session_id = str(uuid.uuid4()).replace("-", "")[:16]
    try:
        db.execute(
            text("INSERT INTO sessions (session_id, session_name, user_id) VALUES (:sid, :name, :uid)"),
            {"sid": session_id, "name": "新对话", "uid": USER_ID},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"session_id": session_id, "status": "success"}


@router.post("/chat")
async def chat(
    session_id: str = Query(...),
    request: ChatRequest = Body(...),
    db: Session = Depends(get_db),
):
    question = request.message

    # 查询该 session 的历史对话（最近 5 轮）
    rows = db.execute(
        text(
            "SELECT user_question, model_answer FROM messages "
            "WHERE session_id = :sid ORDER BY created_at DESC LIMIT 5"
        ),
        {"sid": session_id},
    ).fetchall()
    history = [{"user": r.user_question, "assistant": r.model_answer} for r in reversed(rows)]

    # 流式生成，同时收集完整回答用于存库
    collected_answer: list[str] = []
    collected_think: list[str] = []

    def stream():
        for event in final_answer(question, history=history):
            import json, re
            yield event
            # 收集 answer / think 内容
            m = re.search(r"data: (.+)", event)
            if m:
                try:
                    data = json.loads(m.group(1))
                    if data.get("thinking") is False:
                        collected_answer.append(data.get("content", ""))
                    elif data.get("thinking") is True:
                        collected_think.append(data.get("content", ""))
                except Exception:
                    pass

        # 流结束后写入数据库
        try:
            db.execute(
                text(
                    "INSERT INTO messages (session_id, user_question, model_answer, think) "
                    "VALUES (:sid, :q, :a, :t)"
                ),
                {
                    "sid": session_id,
                    "q": question,
                    "a": "".join(collected_answer),
                    "t": "".join(collected_think) or None,
                },
            )
            # 如果是第一条消息，用问题前 20 字更新 session_name
            count = db.execute(
                text("SELECT COUNT(*) FROM messages WHERE session_id = :sid"),
                {"sid": session_id},
            ).scalar()
            if count == 1:
                session_name = question[:20] + ("..." if len(question) > 20 else "")
                db.execute(
                    text("UPDATE sessions SET session_name = :name WHERE session_id = :sid"),
                    {"name": session_name, "sid": session_id},
                )
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[chat_rt] 写入消息失败：{e}")

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/upload_files/")
async def upload_files(
    session_id: str = Query(default="default"),
    files: list[UploadFile] = File(...),
):
    results = []
    for file in files:
        suffix = os.path.splitext(file.filename)[1].lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"{file.filename} 不支持，仅支持 .txt 和 .md 文件",
            )

        save_dir = os.path.join(STORAGE_DIR, session_id)
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, file.filename)

        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        try:
            execute_insert_process(file_path, file.filename, USER_ID)
            insert_knowledgebase(USER_ID, file.filename)
            results.append({"file": file.filename, "status": "success"})
        except Exception as e:
            results.append({"file": file.filename, "status": "failed", "error": str(e)})

    return {"status": "success", "results": results}


@router.get("/get_files/")
async def get_files():
    """返回用户上传的文档列表（从 ES 查询 source_kwd=user_upload）。"""
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(
            os.getenv("ES_URL", "http://localhost:1200"),
            basic_auth=("elastic", "infini_rag_flow"),
            verify_certs=False,
            ssl_show_warn=False,
            request_timeout=30,
        )
        resp = es.search(
            index="pokemon_kb",
            body={
                "query": {"term": {"source_kwd": "user_upload"}},
                "collapse": {"field": "docnm_kwd"},
                "size": 100,
                "_source": ["docnm_kwd", "user_id", "create_time"],
            },
        )
        seen = {}
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            name = src.get("docnm_kwd", "")
            if name and name not in seen:
                seen[name] = {
                    "file_name": name,
                    # 真实上传时间；存量旧文件无 create_time 时回退为当前时间
                    "updated_at": src.get("create_time") or datetime.utcnow().isoformat(),
                }
        return list(seen.values())
    except Exception as e:
        return []


@router.delete("/delete_file/")
async def delete_file(file_name: str = Query(...)):
    """从 ES 删除指定文件名的所有 chunks。"""
    try:
        from elasticsearch import Elasticsearch
        es = Elasticsearch(
            os.getenv("ES_URL", "http://localhost:1200"),
            basic_auth=("elastic", "infini_rag_flow"),
            verify_certs=False,
            ssl_show_warn=False,
            request_timeout=30,
        )
        # refresh=True：删除后立即刷新，确保前端紧接着的 /get_files/ 查询
        # 不再返回已删文件（与上传端 refresh="wait_for" 对称）。
        result = es.delete_by_query(
            index="pokemon_kb",
            body={"query": {"term": {"docnm_kwd": file_name}}},
            refresh=True,
        )
        deleted = result.get("deleted", 0)

        # 同步清理本地磁盘文件：上传时存在 storage/file/<session_id>/<file_name>，
        # 但 delete_file 不带 session_id，故遍历所有 session 子目录删除同名文件，
        # 避免磁盘副本长期残留累积占用空间。
        removed_files = 0
        if os.path.isdir(STORAGE_DIR):
            for session_dir in os.listdir(STORAGE_DIR):
                fp = os.path.join(STORAGE_DIR, session_dir, file_name)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        removed_files += 1
                    except OSError as e:
                        print(f"[delete_file] 删除本地文件失败 {fp}：{e}")

        return {"message": f"已删除 {file_name}（{deleted} 个分块，{removed_files} 个本地文件）"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

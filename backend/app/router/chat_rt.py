import json
import logging
import os
import re
import uuid
from datetime import datetime
from fastapi import APIRouter, Body, File, HTTPException, Query, Depends, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from schemas.chat import ChatRequest
from utils.database import get_db, SessionLocal
from utils.es_client import get_es_client
from service.agent.agent import final_answer
from service.core.file_parse import execute_insert_process
from database.knowledgebase_operations import insert_knowledgebase, delete_knowledgebase_entry

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "../../../storage/file")
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_REQUEST = 10
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
DEFAULT_SESSION_NAME = "新对话"
# 真实 session_id 由 uuid4().hex[:16] 生成（见 create_session），故只接受定长字母数字
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")

router = APIRouter()
logger = logging.getLogger(__name__)

USER_ID = "1"


def _validate_session_id(session_id: str | None) -> str | None:
    """校验 session_id 格式，防止路径穿越（如 session_id=../../etc）。
    None/空字符串代表全局 scope，视为合法。
    """
    if not session_id:
        return None
    if not SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return session_id


def _safe_filename(file_name: str) -> str:
    """仅取路径最后一段，防止文件名中的 ../ 段逃逸出 STORAGE_DIR。"""
    name = os.path.basename(file_name or "")
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid file name")
    return name


@router.post("/create_session")
async def create_session(db: Session = Depends(get_db)):
    session_id = str(uuid.uuid4()).replace("-", "")[:16]
    try:
        db.execute(
            text("INSERT INTO sessions (session_id, session_name, user_id) VALUES (:sid, :name, :uid)"),
            {"sid": session_id, "name": DEFAULT_SESSION_NAME, "uid": USER_ID},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"session_id": session_id, "status": "success"}


@router.post("/chat")
def chat(
    session_id: str = Query(...),
    request: ChatRequest = Body(...),
):
    # 同步 def（而非 async def）：FastAPI 会把它扔进线程池执行，避免下面这条
    # 同步 db.execute 历史查询阻塞事件循环——这个 handler 本身也没有需要
    # await 的地方（流式部分是普通同步生成器，不是 async generator）。
    session_id = _validate_session_id(session_id)
    # 空字符串 / 非法 session_id 立即拒绝：否则 session_id=None 会一路走到
    # _persist 的 INSERT，撞 messages.session_id NOT NULL 约束，异常被吞掉，
    # 流式答案被静默丢弃、从不入库。
    if session_id is None:
        raise HTTPException(status_code=400, detail="session_id is required")
    question = request.message

    # 查询该 session 的历史对话（最近 5 轮）。用独立的短生命周期 session：
    # Depends(get_db) 的连接直到整个 StreamingResponse body（Plan→Act→Reflect
    # →Answer 全流程，可能数十秒）被消费完才 close，会把连接池占满；这里查完
    # 立即归还连接，与 _persist 的写库同理。
    with SessionLocal() as read_db:
        rows = read_db.execute(
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

    def _persist():
        # 用独立的短生命周期 session 做落库写入，而不是复用请求作用域的
        # db（那个连接会在整个流式生成期间被占用）。落库放在 finally 里，
        # 这样客户端中途断连（generator 被 GeneratorExit 提前关闭）时这条
        # 回答依然会被写入，而不是随着流一起被静默丢弃。
        with SessionLocal() as write_db:
            try:
                write_db.execute(
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
                # 仅在 session 仍是刚创建时的默认名时才重命名——用 WHERE 条件
                # 代替原来的 "SELECT COUNT(*) == 1" 判断，天然避免了并发下
                # 两条同时到达的首条消息互相漏判/重复改名的竞态。
                session_name = question[:20] + ("..." if len(question) > 20 else "")
                write_db.execute(
                    text(
                        "UPDATE sessions SET session_name = :name "
                        "WHERE session_id = :sid AND session_name = :default_name"
                    ),
                    {"name": session_name, "sid": session_id, "default_name": DEFAULT_SESSION_NAME},
                )
                write_db.commit()
            except Exception as e:
                write_db.rollback()
                print(f"[chat_rt] 写入消息失败：{e}")

    def stream():
        try:
            for event in final_answer(question, history=history, session_id=session_id):
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
        finally:
            _persist()

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/upload_files/")
async def upload_files(
    session_id: str | None = Query(default=None),
    files: list[UploadFile] = File(...),
):
    session_id = _validate_session_id(session_id)
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多上传 {MAX_FILES_PER_REQUEST} 个文件",
        )

    # 先整体校验每个文件的文件名/扩展名，任何一个不合法就整批拒绝——在写盘/
    # 索引任何一个文件之前。否则批次中靠后的非法文件会导致整个请求抛异常，而
    # 靠前的文件已被写盘并索引进 ES + Postgres，重试时又会重复索引。
    safe_names = []
    for file in files:
        safe_name = _safe_filename(file.filename)
        suffix = os.path.splitext(safe_name)[1].lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"{safe_name} 不支持，仅支持 .txt、.md 和 .pdf 文件",
            )
        safe_names.append(safe_name)

    results = []
    for file, safe_name in zip(files, safe_names):
        save_dir = os.path.join(STORAGE_DIR, session_id or "global")
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, safe_name)

        # 分块读取并边读边校验大小，而不是先 file.read() 整体载入内存再判断
        # 长度——否则恶意的超大文件在被拒绝之前就已经把整个内容读进了内存，
        # 原先的大小上限起不到防内存耗尽 DoS 的作用。
        size = 0
        try:
            with open(file_path, "wb") as f:
                while True:
                    chunk = await file.read(UPLOAD_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"{safe_name} 超过上传大小限制（{MAX_UPLOAD_BYTES // (1024 * 1024)}MB）",
                        )
                    f.write(chunk)
        except HTTPException:
            if os.path.isfile(file_path):
                os.remove(file_path)
            raise

        try:
            # OCR/版式解析/表格识别/向量化/ES 写入都是重 CPU + 阻塞 IO 操作，
            # 用 run_in_threadpool 丢到线程池执行，避免整个事件循环（包括其他
            # 并发用户的 /chat 流式请求）被一次文件解析卡住。
            await run_in_threadpool(execute_insert_process, file_path, safe_name, USER_ID, session_id)
            await run_in_threadpool(insert_knowledgebase, USER_ID, safe_name, session_id)
            results.append({"file": safe_name, "status": "success"})
        except Exception as e:
            # 索引失败时清理已写盘的文件，避免留下无对应 ES/PG 记录的孤儿文件
            # （否则重试会与残留文件叠加，且磁盘上多出无法通过接口删除的垃圾）。
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError as rm_err:
                    logger.warning("upload_files failed to remove %s after index error: %s", file_path, rm_err)
            results.append({"file": safe_name, "status": "failed", "error": str(e)})

    return {"status": "success", "results": results}


def _chunk_method_for_upload(file_name: str) -> str:
    suffix = os.path.splitext(file_name)[1].lower()
    return "DeepDoc" if suffix == ".pdf" else "Plain text"


def _chunk_method_for_official(source_kwd: str) -> str:
    return "HTML" if source_kwd == "sec_filing" else "Markdown"


@router.get("/get_files/")
def get_files():
    """返回所有 session 上传的文档列表（从 ES 查询 source_kwd=user_upload）。

    用 composite 聚合按 (docnm_kwd, session_id) 分桶，而非对原始 chunk 文档做
    size:1000 的扁平查询——单个文件可能有数百个 chunk，chunk 总数一旦超过
    1000，ES 会静默截断且不保证返回哪些文档的 chunk，导致整份文件从列表中消失。
    聚合的 size 现在受"不同文件数"约束而非"chunk 数"约束，不会再截断。
    """
    try:
        es = get_es_client()
        resp = es.search(
            index="finance_kb",
            body={
                "size": 0,
                "query": {"term": {"source_kwd": "user_upload"}},
                "aggs": {
                    "by_file": {
                        "composite": {
                            "size": 10000,
                            "sources": [
                                {"docnm_kwd": {"terms": {"field": "docnm_kwd"}}},
                                {
                                    "session_id": {
                                        "terms": {"field": "session_id", "missing_bucket": True}
                                    }
                                },
                            ],
                        },
                        "aggs": {
                            "latest": {
                                "top_hits": {
                                    "size": 1,
                                    "_source": ["docnm_kwd", "create_time", "session_id"],
                                }
                            }
                        },
                    }
                },
            },
        )
        results = []
        for bucket in resp["aggregations"]["by_file"]["buckets"]:
            src = bucket["latest"]["hits"]["hits"][0]["_source"]
            name = src.get("docnm_kwd", "")
            if not name:
                continue
            results.append({
                "file_name": name,
                # 真实上传时间；存量旧文件无 create_time 时回退为当前时间
                "updated_at": src.get("create_time") or datetime.utcnow().isoformat(),
                "chunk_method": _chunk_method_for_upload(name),
                "status": "Indexed",
                "session_id": src.get("session_id"),
            })
        return results
    except Exception as e:
        # 不再吞异常返回 []——那会让 ES 故障与"确实没有文件"无法区分，前端会把
        # 后端宕机误显示为空列表。返回 500，让调用方能分辨后端故障与真正的空。
        logger.exception("get_files failed")
        raise HTTPException(status_code=500, detail=f"get_files failed: {e}")


@router.get("/get_official_examples/")
def get_official_examples():
    """返回官方示例语料列表（source_kwd 属于 sec_filing/news/educational）。

    同 get_files：用 terms 聚合按 docnm_kwd 分桶，避免对原始 chunk 做
    size:1000 扁平查询时因 chunk 数超限而静默丢失整份文件。
    """
    try:
        es = get_es_client()
        resp = es.search(
            index="finance_kb",
            body={
                "size": 0,
                "query": {"terms": {"source_kwd": ["sec_filing", "news", "educational"]}},
                "aggs": {
                    "by_file": {
                        "terms": {"field": "docnm_kwd", "size": 10000},
                        "aggs": {
                            "latest": {
                                "top_hits": {
                                    "size": 1,
                                    "_source": ["docnm_kwd", "create_time", "source_kwd"],
                                }
                            }
                        },
                    }
                },
            },
        )
        results = []
        for bucket in resp["aggregations"]["by_file"]["buckets"]:
            src = bucket["latest"]["hits"]["hits"][0]["_source"]
            name = src.get("docnm_kwd", "")
            if not name:
                continue
            results.append({
                "file_name": name,
                "updated_at": src.get("create_time") or datetime.utcnow().isoformat(),
                "chunk_method": _chunk_method_for_official(src.get("source_kwd", "")),
                "status": "Indexed",
            })
        return results
    except Exception as e:
        # 同 get_files：不吞异常返回 []，改为 500，区分后端故障与真正的空列表。
        logger.exception("get_official_examples failed")
        raise HTTPException(status_code=500, detail=f"get_official_examples failed: {e}")


@router.delete("/delete_file/")
def delete_file(file_name: str = Query(...), session_id: str | None = Query(default=None)):
    """删除指定文件名在指定 session（或全局桶）下的所有 chunks。

    session_id 必须与上传时的 scope 一致：不带 session_id 匹配 ES 中
    session_id 字段不存在（全局上传），否则会误删其他 session 的同名文件。
    """
    session_id = _validate_session_id(session_id)
    file_name = _safe_filename(file_name)
    try:
        es = get_es_client()
        scope_clause = (
            {"bool": {"must_not": {"exists": {"field": "session_id"}}}}
            if not session_id
            else {"term": {"session_id": session_id}}
        )
        # refresh=True：删除后立即刷新，确保前端紧接着的 /get_files/ 查询
        # 不再返回已删文件（与上传端 refresh="wait_for" 对称）。
        result = es.delete_by_query(
            index="finance_kb",
            body={
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"docnm_kwd": file_name}},
                            # 官方语料（sec_filing/news/educational）没有 session_id 字段，
                            # 与"全局上传"的 scope_clause 语义重叠——加上 source_kwd 限定，
                            # 确保此接口只能删除用户上传的文档，不会误删种子语料库。
                            {"term": {"source_kwd": "user_upload"}},
                            scope_clause,
                        ],
                    }
                }
            },
            refresh=True,
        )
        deleted = result.get("deleted", 0)

        # 同步清理本地磁盘文件：上传时存在 storage/file/<session_id or "global">/<file_name>，
        # 只清理该 scope 自己的目录，避免误删其他 session 的同名文件。
        removed_files = 0
        scope_dir = os.path.join(STORAGE_DIR, session_id or "global")
        fp = os.path.join(scope_dir, file_name)
        if os.path.isfile(fp):
            try:
                os.remove(fp)
                removed_files += 1
            except OSError as e:
                logger.warning("delete_file failed to remove local file %s: %s", fp, e)

        # 同步清理 Postgres knowledgebases 表中的对应行，避免 get_latest_user_upload
        # 返回一个已在 ES/磁盘中不存在的陈旧文件名（upload boost 静默失效）。
        delete_knowledgebase_entry(file_name, session_id)

        return {"message": f"已删除 {file_name}（{deleted} 个分块，{removed_files} 个本地文件）"}
    except Exception as e:
        logger.exception("delete_file failed")
        raise HTTPException(status_code=500, detail=str(e))

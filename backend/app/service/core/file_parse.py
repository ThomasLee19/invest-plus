"""
轻量文件解析：支持 .txt / .md
切 chunk → 生成 embedding → 写入 ES pokemon_kb（source_kwd="user_upload"）
"""
import os
import hashlib
import datetime
from pathlib import Path
from openai import OpenAI
from elasticsearch import Elasticsearch

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)
ES_URL = os.getenv("ES_URL", "http://localhost:1200")
ES_INDEX = "pokemon_kb"
MAX_CHUNK = 1500


def _chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) > MAX_CHUNK and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        chunks.append(current.strip())
    return chunks


def _embed(texts: list[str]) -> list[list[float]]:
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)
    resp = client.embeddings.create(
        model="text-embedding-v3",
        input=texts,
        dimensions=1024,
        encoding_format="float",
    )
    return [item.embedding for item in resp.data]


def execute_insert_process(file_path: str, file_name: str, user_id: str):
    text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    chunks = _chunk_text(text)
    if not chunks:
        return

    vectors = _embed(chunks)

    es = Elasticsearch(
        ES_URL,
        basic_auth=("elastic", "infini_rag_flow"),
        verify_certs=False,
        ssl_show_warn=False,
        request_timeout=60,
    )

    # 整个文件的所有 chunk 用同一上传时间戳（字段名与 index_smogon.py 保持一致）
    create_time = str(datetime.datetime.now())[:19]

    docs = []
    for chunk, vec in zip(chunks, vectors):
        doc_id = hashlib.md5(f"{user_id}{file_name}{chunk}".encode()).hexdigest()
        docs.append({
            "_index": ES_INDEX,
            "_id": doc_id,
            "_source": {
                "doc_id": doc_id,
                "docnm_kwd": file_name,
                "source_kwd": "user_upload",
                "user_id": user_id,
                "content_with_weight": chunk,
                "content_ltks": chunk,
                "create_time": create_time,
                "q_1024_vec": vec,
            },
        })

    from elasticsearch.helpers import bulk
    # refresh="wait_for"：阻塞到写入的 doc 可被搜索后再返回，确保上传接口返回时
    # 前端紧接着的 /get_files/ 查询能立即查到新文件（ES 默认 1s refresh_interval
    # 内新 doc 不可搜索，否则列表会看不到刚上传的文件）。比 refresh=True 更省 ES，
    # 不强制立即刷新整个 shard，只等下一次自然 refresh。
    success, errors = bulk(es, docs, raise_on_error=False, refresh="wait_for")
    print(f"[file_parse] {file_name}: {success} chunks 写入 ES，{len(errors)} 失败")

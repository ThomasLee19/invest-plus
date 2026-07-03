"""
文件解析：支持 .txt / .md（轻量段落切分）与 .pdf（DeepDoc OCR+版面+表格识别）
切 chunk → 生成 embedding → 写入 ES（source_kwd="user_upload"）

PDF 路基于移植自 FinReportRAG 的 DeepDoc 流水线（service/core/deepdoc + service/core/rag），
模型/词典已随仓库放在 service/core/rag/res 下，首次运行无需联网下载。
"""
import os
import re
import hashlib
import datetime
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

# 独立于调用方的 import 顺序显式加载 .env（同 agent.py 的修复原因）。
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
)
ES_URL = os.getenv("ES_URL", "http://localhost:1200")
ES_INDEX = "finance_kb"

# .txt/.md 路按字符切分（与历史新闻/教育内容一致）
MAX_CHUNK = 1500
# PDF 路按 token 切分。FinReportRAG 默认 128 token，偏小，会把财报表格/论述拆碎；
# 这里取 384 token，约等于上面 1500 字符（英文）的规模，使 PDF chunk 与现有 txt/news
# chunk 落进同一个索引时尺度一致——BM25 词频饱和与 agent.py 里 _KNN_BOOST=8.0 的混合
# 权重就无需为两套差异巨大的 chunk 尺度重新调参；同时仍远低于 text-embedding-v3 的
# 8192 token 上限，保持向量语义聚焦。表格的连贯性由 tokenize_table 的 batch_size 控制，
# 与此值无关。
PDF_CHUNK_TOKEN_NUM = 384

# DashScope text-embedding-v3 单次请求最多 10 条输入
_EMBED_BATCH = 10

# 去掉表格/排版标记，得到送进 embedding 的"干净文本"：content_with_weight 里保留字面
# HTML 表格用于前端展示，但向量只编码表格的实际内容，而不是 <td>/<tr> 这类噪声。
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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


def _clean_for_embedding(text: str) -> str:
    t = _HTML_TAG_RE.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _embed(texts: list[str]) -> list[list[float]]:
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i:i + _EMBED_BATCH]
        resp = client.embeddings.create(
            model="text-embedding-v3",
            input=batch,
            dimensions=1024,
            encoding_format="float",
        )
        vectors.extend(item.embedding for item in resp.data)
    return vectors


def _build_pdf_items(file_path: str, file_name: str,
                     from_page: int = 0, to_page: int = 100000) -> list[tuple[str, str]]:
    """跑 DeepDoc 流水线，返回 [(display_text, embed_text), ...]。
    display_text 进 content_with_weight（表格保留 HTML 供展示），
    embed_text 是去标记后的干净文本，进 content_ltks 并用于生成向量。
    """
    # 重依赖（onnxruntime/xgboost/opencv 等）按需懒加载，避免拖慢 txt/md 路
    from service.core.deepdoc.parser.pdf_parser import RAGFlowPdfParser
    from service.core.rag.nlp import (
        rag_tokenizer, naive_merge, tokenize_table, tokenize_chunks,
    )

    def _noop(*args, **kwargs):
        pass

    class _Pdf(RAGFlowPdfParser):
        def __call__(self, filename, from_page=0, to_page=100000, zoomin=3, callback=None):
            self.__images__(filename, zoomin, from_page, to_page, callback)
            self._layouts_rec(zoomin)
            self._table_transformer_job(zoomin)
            self._text_merge()
            tbls = self._extract_table_figure(True, zoomin, True, True)
            self._concat_downward()
            return [(b["text"], self._line_tag(b, zoomin)) for b in self.boxes], tbls

    parser = _Pdf()
    sections, tables = parser(file_path, from_page=from_page, to_page=to_page, callback=_noop)

    doc = {
        "docnm_kwd": file_name,
        "title_tks": rag_tokenizer.tokenize(re.sub(r"\.[a-zA-Z]+$", "", file_name)),
    }
    doc["title_sm_tks"] = rag_tokenizer.fine_grained_tokenize(doc["title_tks"])

    # 表格单独成块（content_with_weight 保留 HTML/markdown）
    parsed = tokenize_table(tables, doc, eng=True)
    # 叙述文本按 token 合并；先去掉 _line_tag 追加的 @@page##位置标记，避免污染正文
    chunks = naive_merge(sections, PDF_CHUNK_TOKEN_NUM, "\n!?。；！？")
    chunks = [parser.remove_tag(c) for c in chunks]
    parsed.extend(tokenize_chunks(chunks, doc, eng=True, pdf_parser=None))

    items: list[tuple[str, str]] = []
    for d in parsed:
        display = (d.get("content_with_weight") or "").strip()
        if not display:
            continue
        embed_text = _clean_for_embedding(display)
        if not embed_text:
            continue
        items.append((display, embed_text))
    return items


def execute_insert_process(file_path: str, file_name: str, user_id: str, session_id: str | None = None):
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        items = _build_pdf_items(file_path, file_name)
    else:
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        # 纯文本展示与向量同源
        items = [(c, c) for c in _chunk_text(text)]

    if not items:
        print(f"[file_parse] {file_name}: 无可索引内容")
        return

    vectors = _embed([embed_text for _, embed_text in items])

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
    for (display, embed_text), vec in zip(items, vectors):
        # scope 哨兵值随 doc_id 一起哈希：不同 session（含 global）上传同名同内容
        # 文件时不会产生相同的 _id，避免第二次写入静默覆盖第一次（跨 scope 冲突）。
        doc_id = hashlib.md5(f"{session_id or 'global'}{file_name}{display}".encode()).hexdigest()
        docs.append({
            "_index": ES_INDEX,
            "_id": doc_id,
            "_source": {
                "doc_id": doc_id,
                "docnm_kwd": file_name,
                "source_kwd": "user_upload",
                "user_id": user_id,
                "session_id": session_id,
                # 展示用：表格保留字面 HTML
                "content_with_weight": display,
                # BM25 检索 + 与向量同源：去标记后的干净文本
                "content_ltks": embed_text,
                "create_time": create_time,
                "q_1024_vec": vec,
            },
        })

    # refresh="wait_for"：阻塞到写入的 doc 可被搜索后再返回，确保上传接口返回时
    # 前端紧接着的 /get_files/ 查询能立即查到新文件（ES 默认 1s refresh_interval
    # 内新 doc 不可搜索，否则列表会看不到刚上传的文件）。比 refresh=True 更省 ES，
    # 不强制立即刷新整个 shard，只等下一次自然 refresh。
    success, errors = bulk(es, docs, raise_on_error=False, refresh="wait_for")
    print(f"[file_parse] {file_name}: {success} chunks 写入 ES，{len(errors)} 失败")

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
from elasticsearch.helpers import bulk

from app.utils.es_client import get_es_client

# 独立于调用方的 import 顺序显式加载 .env（同 agent.py 的修复原因）。
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL")
if not DASHSCOPE_BASE_URL:
    raise RuntimeError(
        "DASHSCOPE_BASE_URL is not set. Set it in your .env file (see .env.example) — "
        "leaving it unset makes the OpenAI client fall back to the public OpenAI endpoint, "
        "leaking requests made with a DashScope key."
    )
ES_INDEX = "finance_kb"

# .txt/.md 路按字符切分（与历史新闻/教育内容一致）
MAX_CHUNK = 1500
# text-embedding-v3 输入上限约 8192 token；与 rag/nlp.naive_merge 的
# _MAX_EMBED_TOKENS 保持一致，留出余量避免单个 chunk 卡在临界值附近越界。
_MAX_EMBED_TOKENS = 8000
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
    # PDF 路的 naive_merge 是按 token 累积的，天然有 _MAX_EMBED_TOKENS 硬上限；
    # 这里按字符累积，没有等价保护，需要在每个 chunk 定稿时补上——否则一段没有
    # 空行分隔的超长段落会原样成为一个 chunk，送进 _embed 时因超模型 token 上限
    # 而让整份文件一个 chunk 都写不进 ES。
    from service.core.rag.utils import num_tokens_from_string, truncate

    def _finalize(piece: str) -> None:
        piece = piece.strip()
        if not piece:
            return
        remaining = piece
        while remaining and num_tokens_from_string(remaining) > _MAX_EMBED_TOKENS:
            head = truncate(remaining, _MAX_EMBED_TOKENS)
            chunks.append(head)
            remaining = remaining[len(head):]
        if remaining:
            chunks.append(remaining)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > MAX_CHUNK and current:
            _finalize(current)
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        _finalize(current)
    return chunks


def _clean_for_embedding(text: str) -> str:
    t = _HTML_TAG_RE.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


_openai_client = OpenAI(
    api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL, timeout=60.0, max_retries=2
)


def _embed(texts: list[str]) -> list[list[float]]:
    client = _openai_client
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i:i + _EMBED_BATCH]
        try:
            resp = client.embeddings.create(
                model="text-embedding-v3",
                input=batch,
                dimensions=1024,
                encoding_format="float",
            )
        except Exception as e:
            raise RuntimeError(
                f"embedding batch {i // _EMBED_BATCH} (chunks {i}-{i + len(batch) - 1}) failed: {e}"
            ) from e
        # 数量对不上就必须报错，而不是让下游 zip(items, vectors) 静默截断掉尾部
        # chunk——那样文件仍会被标记为 success，实际上部分内容根本没有写入 ES。
        if len(resp.data) != len(batch):
            raise RuntimeError(
                f"embedding batch {i // _EMBED_BATCH} (chunks {i}-{i + len(batch) - 1}) "
                f"returned {len(resp.data)} vectors for {len(batch)} inputs"
            )
        # 按 index 排序后再取 embedding，不依赖 provider 返回顺序与输入顺序一致，
        # 否则一旦顺序不一致，向量会错位挂到错误的 chunk 上。
        vectors.extend(item.embedding for item in sorted(resp.data, key=lambda item: item.index))
    return vectors


# DeepDoc 的 _Pdf.__call__ 默认 to_page=100000，对一份被精心构造的超大 PDF 会
# 同步跑满每一页的 OCR+版面+表格识别，耗尽 CPU/内存且没有上限。这里给用户上传路
# 一个合理的页数上限（超出的页直接不解析，而不是让请求无限跑下去）。
MAX_PDF_PAGES = 50


def _build_pdf_items(file_path: str, file_name: str,
                     from_page: int = 0, to_page: int = MAX_PDF_PAGES) -> list[tuple[str, str]]:
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
        from service.core.rag.nlp import find_codec

        raw = Path(file_path).read_bytes()
        # 先探测编码再解码，而不是直接以 utf-8 + errors="ignore" 硬解——
        # 后者会把非 UTF-8（如 GB2312/Latin-1）字节静默丢弃，导致索引进
        # 乱码文本。find_codec 探测失败时仍回退 utf-8，行为不变。
        text = raw.decode(find_codec(raw), errors="ignore")
        # 纯文本展示与向量同源
        items = [(c, c) for c in _chunk_text(text)]

    if not items:
        print(f"[file_parse] {file_name}: 无可索引内容")
        return

    vectors = _embed([embed_text for _, embed_text in items])

    es = get_es_client()

    # 整个文件的所有 chunk 用同一上传时间戳（字段名与 index_smogon.py 保持一致）
    upload_time = datetime.datetime.now(datetime.timezone.utc)
    create_time = str(upload_time)[:19]
    create_timestamp_flt = upload_time.timestamp()

    docs = []
    for i, ((display, embed_text), vec) in enumerate(zip(items, vectors)):
        # scope 哨兵值随 doc_id 一起哈希：不同 session（含 global）上传同名同内容
        # 文件时不会产生相同的 _id，避免第二次写入静默覆盖第一次（跨 scope 冲突）。
        # 序号 i 同样加入哈希：重复内容（如相同的表头/样板文字）的 chunk 若不带序号
        # 会算出相同的 doc_id，导致后写入的 chunk 在 ES 里静默覆盖先写入的那个。
        doc_id = hashlib.md5(f"{session_id or 'global'}{file_name}{i}{display}".encode()).hexdigest()
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
                "create_timestamp_flt": create_timestamp_flt,
                "q_1024_vec": vec,
            },
        })

    # refresh="wait_for"：阻塞到写入的 doc 可被搜索后再返回，确保上传接口返回时
    # 前端紧接着的 /get_files/ 查询能立即查到新文件（ES 默认 1s refresh_interval
    # 内新 doc 不可搜索，否则列表会看不到刚上传的文件）。比 refresh=True 更省 ES，
    # 不强制立即刷新整个 shard，只等下一次自然 refresh。
    success, errors = bulk(es, docs, raise_on_error=False, refresh="wait_for")
    print(f"[file_parse] {file_name}: {success} chunks 写入 ES，{len(errors)} 失败")
    if errors and success == 0:
        raise RuntimeError(
            f"{file_name}: all {len(errors)} chunk(s) failed to index into ES "
            f"(0 succeeded) — first error: {errors[0]}"
        )
    if errors:
        logging.warning(
            "[file_parse] %s: %d/%d chunks failed to index into ES",
            file_name, len(errors), len(docs),
        )

"""
Finance corpus indexing script.

Chunks data/filings, data/news, data/educational -> generates embeddings ->
writes into Elasticsearch index "finance_kb" (the renamed pokemon_kb).
Follows legacy/index_smogon.py's pattern: idempotent chunk IDs via xxhash,
same dynamic-template ES mapping, source_kwd to distinguish content types.

INTEGRATION NOTE (filings/PDF parsing):
Track C's spec asked this script to call into Track B's ported DeepDoc PDF
parser in backend/app/service/core/file_parse.py for filings. Two things
changed that interface assumption, flagged here for a wiring check once
Track B lands:
  1. SEC EDGAR does not serve modern 10-K/10-Q/8-K filings as PDF; the
     primary document is always HTML (iXBRL). scripts/fetch_filings.py
     therefore downloaded .htm files, not .pdf.
  2. Track B's DeepDoc port (PdfParser + OCR/layout/table-transformer) is
     PDF-specific, so it cannot consume these .htm files directly as-is.
  This script instead does its own lightweight HTML -> text extraction
  (via BeautifulSoup), converting <table> elements to pipe-delimited
  markdown-ish rows so table structure survives chunking without raw HTML
  markup polluting the embedded text (the same concern flagged in Track
  B's own task spec for its PDF table handling). If/when an HTML branch is
  added to file_parse.py's pipeline (or filings are re-sourced as PDF),
  swap parse_filing_html() below for that call.

Run:
    python scripts/index_finance.py
"""

import os
import re
import time
import datetime
from pathlib import Path

import xxhash
from bs4 import BeautifulSoup, NavigableString
from openai import OpenAI
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
FILINGS_DIR = DATA_DIR / "filings"
NEWS_DIR = DATA_DIR / "news"
EDUCATIONAL_DIR = DATA_DIR / "educational"

INDEX_NAME = "finance_kb"
EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_DIMS = 1024
REQUEST_DELAY = 0.3
MAX_CHUNK = 1500
MIN_PARA = 30

ES_URL = os.getenv("ES_URL", "http://localhost:1200")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

# Dynamic-template regex (below, in ensure_index) that auto-maps any field
# matching this pattern to ES `keyword` type. Hoisted to a named constant
# (rather than left as an inline string literal) so tests can import and
# assert against the actual pattern -- e.g. that `session_id` still matches
# it -- instead of re-typing a copy that could silently drift out of sync.
KEYWORD_DYNAMIC_TEMPLATE_REGEX = r"^(.*_(kwd|id)|uid)$"


def get_es() -> Elasticsearch:
    password = os.getenv("ELASTIC_PASSWORD")
    if not password:
        raise RuntimeError(
            "ELASTIC_PASSWORD is not set. Set it in your .env file (see .env.example)."
        )
    # verify_certs only disabled for loopback-ish hosts, mirroring
    # backend/app/utils/es_client.py's policy (this standalone script has no
    # sys.path hookup into backend/app, so the logic is duplicated locally
    # rather than imported).
    is_loopback = any(h in ES_URL for h in ("localhost", "127.0.0.1", "es01", "elasticsearch"))
    return Elasticsearch(
        ES_URL,
        basic_auth=("elastic", password),
        verify_certs=not is_loopback,
        request_timeout=600,
    )


def ensure_index(es: Elasticsearch):
    if es.indices.exists(index=INDEX_NAME):
        print(f"[ES] index '{INDEX_NAME}' already exists, skipping creation")
        return
    es.indices.create(
        index=INDEX_NAME,
        settings={"index": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "1s"}},
        mappings={
            "dynamic_templates": [
                {"kwd": {
                    "match_pattern": "regex",
                    "match": KEYWORD_DYNAMIC_TEMPLATE_REGEX,
                    "mapping": {"type": "keyword", "store": True}
                }},
                {"ltks": {
                    "match": "*_ltks",
                    "mapping": {"type": "text", "analyzer": "whitespace", "store": True}
                }},
                {"with_weight": {
                    "match_pattern": "regex",
                    "match": "^.*_with_weight$",
                    "mapping": {"type": "text", "index": False, "store": True}
                }},
                {"vec_1024": {
                    "match": "*_1024_vec",
                    "mapping": {
                        "type": "dense_vector",
                        "dims": EMBEDDING_DIMS,
                        "index": True,
                        "similarity": "cosine",
                    }
                }},
            ]
        },
    )
    print(f"[ES] index '{INDEX_NAME}' created")


def generate_embedding(text: str) -> list[float] | None:
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)
    try:
        resp = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
            dimensions=EMBEDDING_DIMS,
            encoding_format="float",
        )
        return resp.data[0].embedding
    except Exception as e:
        print(f"  [embedding failed] {e}")
        return None


def chunk_text(text: str, prefix: str) -> list[str]:
    """Paragraph-based chunker, ~500-1500 chars/chunk, prefixed with context (ticker/title)."""
    paragraphs = re.split(r"\n{2,}", text)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > MIN_PARA]

    chunks = []
    current = ""

    for para in paragraphs:
        if len(para) > MAX_CHUNK:
            if current:
                chunks.append(f"{prefix}\n\n{current}")
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            buf = ""
            for sent in sentences:
                if len(buf) + len(sent) < MAX_CHUNK:
                    buf = (buf + " " + sent).strip()
                else:
                    if buf:
                        chunks.append(f"{prefix}\n\n{buf}")
                    buf = sent
            if buf:
                chunks.append(f"{prefix}\n\n{buf}")
            continue

        if len(current) + len(para) + 2 <= MAX_CHUNK:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(f"{prefix}\n\n{current}")
            current = para

    if current:
        chunks.append(f"{prefix}\n\n{current}")

    return chunks


def parse_filing_html(html: str) -> str:
    """
    HTML -> plain text, with <table> elements flattened to pipe-delimited
    rows first so tabular structure survives chunking without leaking raw
    HTML markup into the embedded text. See module docstring for why this
    exists instead of calling Track B's PDF-specific parser.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Modern EDGAR filings are inline-XBRL: the cover-page facts are
    # duplicated into a hidden <ix:header> block that would otherwise dump
    # raw XBRL tag/context noise ahead of the actual filing text.
    for hidden in soup.find_all("ix:header"):
        hidden.decompose()
    for hidden in soup.select('[style*="display:none"], [style*="display: none"]'):
        hidden.decompose()

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        md_table = "\n".join(rows)
        table.replace_with(NavigableString(f"\n\n{md_table}\n\n"))

    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def index_chunks(es: Elasticsearch, chunks: list[str], doc_id: str, docnm: str,
                  source_kwd: str, extra_fields: dict) -> tuple[int, int, int]:
    """Embed + bulk-index chunks. Returns (written, skipped, failed)."""
    written, skipped, failed = 0, 0, 0
    operations = []

    for chunk in chunks:
        chunk_id = xxhash.xxh64((chunk + INDEX_NAME).encode("utf-8")).hexdigest()

        if es.exists(index=INDEX_NAME, id=chunk_id):
            skipped += 1
            continue

        vec = generate_embedding(chunk)
        if vec is None:
            failed += 1
            continue
        time.sleep(REQUEST_DELAY)

        doc = {
            "doc_id": doc_id,
            "docnm_kwd": docnm,
            "source_kwd": source_kwd,
            "content_with_weight": chunk,
            "content_ltks": re.sub(r"[#\-\*`|]", " ", chunk).lower(),
            "create_time": str(datetime.datetime.now())[:19],
            "create_timestamp_flt": datetime.datetime.now().timestamp(),
            f"q_{EMBEDDING_DIMS}_vec": vec,
            **extra_fields,
        }
        operations.extend([
            {"index": {"_index": INDEX_NAME, "_id": chunk_id}},
            doc,
        ])
        written += 1

    if operations:
        es.bulk(operations=operations, refresh=False, timeout="60s")

    return written, skipped, failed


def index_filings(es: Elasticsearch) -> tuple[int, int, int]:
    total_w, total_s, total_f = 0, 0, 0
    if not FILINGS_DIR.exists():
        return total_w, total_s, total_f

    for ticker_dir in sorted(FILINGS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name

        for filing_path in sorted(ticker_dir.glob("*.htm")):
            # filename: {form}_{filingDate}_{accession}.htm
            parts = filing_path.stem.split("_")
            form = parts[0] if parts else "unknown"
            filing_date = parts[1] if len(parts) > 1 else ""

            html = filing_path.read_text(encoding="utf-8", errors="ignore")
            text = parse_filing_html(html)
            prefix = f"{ticker} {form} ({filing_date})"
            chunks = chunk_text(text, prefix)

            doc_id = xxhash.xxh64(filing_path.name.encode()).hexdigest()
            w, s, f = index_chunks(
                es, chunks, doc_id, filing_path.name, "sec_filing",
                {"ticker_kwd": ticker.lower(), "form_kwd": form.lower()},
            )
            total_w += w
            total_s += s
            total_f += f
            print(f"  {ticker}/{filing_path.name}: {len(chunks)} chunks (written={w}, skipped={s}, failed={f})")

    return total_w, total_s, total_f


def index_news(es: Elasticsearch) -> tuple[int, int, int]:
    total_w, total_s, total_f = 0, 0, 0
    if not NEWS_DIR.exists():
        return total_w, total_s, total_f

    for ticker_dir in sorted(NEWS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name

        for news_path in sorted(ticker_dir.glob("*.md")):
            text = news_path.read_text(encoding="utf-8")
            prefix = f"{ticker} news"
            chunks = chunk_text(text, prefix)

            doc_id = xxhash.xxh64(news_path.name.encode()).hexdigest()
            w, s, f = index_chunks(
                es, chunks, doc_id, news_path.name, "news",
                {"ticker_kwd": ticker.lower()},
            )
            total_w += w
            total_s += s
            total_f += f
            print(f"  {ticker}/{news_path.name}: {len(chunks)} chunks (written={w}, skipped={s}, failed={f})")

    return total_w, total_s, total_f


def index_educational(es: Elasticsearch) -> tuple[int, int, int]:
    total_w, total_s, total_f = 0, 0, 0
    if not EDUCATIONAL_DIR.exists():
        return total_w, total_s, total_f

    for article_path in sorted(EDUCATIONAL_DIR.glob("*.md")):
        text = article_path.read_text(encoding="utf-8")
        title = article_path.stem.replace("_", " ").title()
        chunks = chunk_text(text, title)

        doc_id = xxhash.xxh64(article_path.name.encode()).hexdigest()
        w, s, f = index_chunks(
            es, chunks, doc_id, article_path.name, "educational", {},
        )
        total_w += w
        total_s += s
        total_f += f
        print(f"  {article_path.name}: {len(chunks)} chunks (written={w}, skipped={s}, failed={f})")

    return total_w, total_s, total_f


def main():
    es = get_es()
    ensure_index(es)

    print(f"\nIndex: {INDEX_NAME}\n")

    print("[filings]")
    fw, fs, ff = index_filings(es)

    print("\n[news]")
    nw, ns, nf = index_news(es)

    print("\n[educational]")
    ew, edu_skipped, ef = index_educational(es)

    total_w = fw + nw + ew
    total_s = fs + ns + edu_skipped
    total_f = ff + nf + ef

    print("\n" + "=" * 60)
    print(f"Done. {total_w} chunks written, {total_s} skipped (already indexed), {total_f} failed")
    print(f"  filings:     {fw} written, {fs} skipped, {ff} failed")
    print(f"  news:        {nw} written, {ns} skipped, {nf} failed")
    print(f"  educational: {ew} written, {edu_skipped} skipped, {ef} failed")
    print(f"ES index: {INDEX_NAME}")
    print("=" * 60)


if __name__ == "__main__":
    main()

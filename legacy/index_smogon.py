"""
Smogon 攻略索引脚本
将 data/smogon/*.md 切块 -> 生成 embedding -> 写入 Elasticsearch (pokemon_kb)

切块策略：
  按空行分段，每段约 300-800 字符，保留精灵名作为上下文前缀。

运行方式：
    python scripts/index_smogon.py
"""

import os
import re
import time
import xxhash
import datetime
from pathlib import Path
from openai import OpenAI
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data" / "smogon"
INDEX_NAME = "pokemon_kb"
EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_DIMS = 1024
REQUEST_DELAY = 0.3

ES_URL = os.getenv("ES_URL", "http://localhost:1200")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")


def get_es() -> Elasticsearch:
    return Elasticsearch(
        ES_URL,
        basic_auth=("elastic", "infini_rag_flow"),
        verify_certs=False,
        ssl_show_warn=False,
        request_timeout=600,
    )


def ensure_index(es: Elasticsearch):
    if es.indices.exists(index=INDEX_NAME):
        print(f"[ES] index '{INDEX_NAME}' 已存在，跳过创建")
        return
    es.indices.create(
        index=INDEX_NAME,
        settings={"index": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "1s"}},
        mappings={
            "dynamic_templates": [
                {"kwd": {
                    "match_pattern": "regex",
                    "match": "^(.*_(kwd|id)|uid)$",
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
    print(f"[ES] index '{INDEX_NAME}' 创建成功")


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
        print(f"  [embedding 失败] {e}")
        return None


def chunk_smogon(md_text: str, pokemon_name: str) -> list[str]:
    """
    将 Smogon 攻略按段落切块，每块约 500-1500 字符（硬上限 1500）。
    每块前缀加上精灵名，保证检索上下文。
    """
    MAX_CHUNK = 1500
    MIN_PARA = 30

    # 去掉 source 行和标题
    lines = md_text.splitlines()
    lines = [l for l in lines if not l.startswith("Source:") and not l.startswith("# ")]
    text = "\n".join(lines)

    # 按双换行分段
    paragraphs = re.split(r"\n{2,}", text)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > MIN_PARA]

    chunks = []
    current = ""

    for para in paragraphs:
        # 单段超过硬上限，强制按句子切分
        if len(para) > MAX_CHUNK:
            if current:
                chunks.append(f"{pokemon_name}\n\n{current}")
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            buf = ""
            for sent in sentences:
                if len(buf) + len(sent) < MAX_CHUNK:
                    buf = (buf + " " + sent).strip()
                else:
                    if buf:
                        chunks.append(f"{pokemon_name}\n\n{buf}")
                    buf = sent
            if buf:
                chunks.append(f"{pokemon_name}\n\n{buf}")
            continue

        if len(current) + len(para) + 2 <= MAX_CHUNK:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(f"{pokemon_name}\n\n{current}")
            current = para

    if current:
        chunks.append(f"{pokemon_name}\n\n{current}")

    return chunks


def main():
    es = get_es()
    ensure_index(es)

    md_files = sorted(DATA_DIR.glob("*.md"))
    print(f"共找到 {len(md_files)} 个攻略文件，开始索引...\n")

    total_chunks = 0
    skipped = 0
    failed = 0

    for md_path in md_files:
        md_text = md_path.read_text(encoding="utf-8")
        pokemon_name = md_path.stem.replace("-", " ").title()
        doc_id = xxhash.xxh64(md_path.name.encode()).hexdigest()

        chunks = chunk_smogon(md_text, pokemon_name)
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
                "docnm_kwd": md_path.name,
                "source_kwd": "smogon",
                "pokemon_kwd": pokemon_name.lower(),
                "content_with_weight": chunk,
                "content_ltks": re.sub(r"[#\-\*`]", " ", chunk).lower(),
                "create_time": str(datetime.datetime.now())[:19],
                "create_timestamp_flt": datetime.datetime.now().timestamp(),
                f"q_{EMBEDDING_DIMS}_vec": vec,
            }
            operations.extend([
                {"index": {"_index": INDEX_NAME, "_id": chunk_id}},
                doc,
            ])
            total_chunks += 1

        if operations:
            es.bulk(operations=operations, refresh=False, timeout="60s")

        print(f"  ✓ {md_path.name}  ({len(chunks)} chunks)")

    print(f"\n完成！写入 {total_chunks} chunks，跳过 {skipped}，失败 {failed}")
    print(f"ES index: {INDEX_NAME}")


if __name__ == "__main__":
    main()

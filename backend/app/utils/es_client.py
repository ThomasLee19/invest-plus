import os
from urllib.parse import urlparse

from elasticsearch import Elasticsearch

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "es01", "elasticsearch"}


def _is_loopback(url: str) -> bool:
    """精确匹配 URL 的 hostname（而非子串匹配）：`host in url` 会被形似
    "notlocalhost.evil.com" 或 "elasticsearch.attacker.net" 这类域名绕过，
    错误地将其判定为回环地址并关闭证书校验（verify_certs=False）。"""
    return urlparse(url).hostname in _LOOPBACK_HOSTS


def get_es_client() -> Elasticsearch:
    url = os.getenv("ES_URL", "http://localhost:1200")
    password = os.getenv("ELASTIC_PASSWORD")
    if not password:
        raise RuntimeError(
            "ELASTIC_PASSWORD is not set. Set it in your .env file (see .env.example)."
        )
    return Elasticsearch(
        url,
        basic_auth=("elastic", password),
        verify_certs=not _is_loopback(url),
        request_timeout=30,
    )

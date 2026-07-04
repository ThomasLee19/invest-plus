import os
import threading
from urllib.parse import urlparse

from elasticsearch import Elasticsearch

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "es01", "elasticsearch"}

_es_client = None
_es_client_lock = threading.Lock()


def _is_loopback(url: str) -> bool:
    """精确匹配 URL 的 hostname（而非子串匹配）：`host in url` 会被形似
    "notlocalhost.evil.com" 或 "elasticsearch.attacker.net" 这类域名绕过，
    错误地将其判定为回环地址并关闭证书校验（verify_certs=False）。"""
    return urlparse(url).hostname in _LOOPBACK_HOSTS


def get_es_client() -> Elasticsearch:
    """惰性构建并复用同一个 ES 客户端实例。每次调用都新建一个 Elasticsearch(...)
    会不断打开新连接池却永不关闭，反复调用（如 get_files/delete_file 等接口）
    下会泄漏连接——改为双检锁单例，与 agent.py 的 _get_es() 保持一致。"""
    global _es_client
    if _es_client is None:
        with _es_client_lock:
            if _es_client is None:
                url = os.getenv("ES_URL", "http://localhost:1200")
                password = os.getenv("ELASTIC_PASSWORD")
                if not password:
                    raise RuntimeError(
                        "ELASTIC_PASSWORD is not set. Set it in your .env file (see .env.example)."
                    )
                _es_client = Elasticsearch(
                    url,
                    basic_auth=("elastic", password),
                    verify_certs=not _is_loopback(url),
                    request_timeout=30,
                )
    return _es_client

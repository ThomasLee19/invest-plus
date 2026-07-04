import os

from elasticsearch import Elasticsearch

_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "es01", "elasticsearch")


def _is_loopback(url: str) -> bool:
    return any(host in url for host in _LOOPBACK_HOSTS)


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
    )

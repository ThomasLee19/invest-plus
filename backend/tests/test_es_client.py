"""
Unit tests for utils/es_client.py's _is_loopback() (L2).

`elasticsearch` isn't installed in this test environment (mirrors the
zero-installed-packages constraint documented in test_agent_loop.py), so it's
stubbed before import the same way. _is_loopback() itself is a pure function
with no I/O, so no other stubbing is needed.
"""
import sys
import types
from pathlib import Path

import unittest

_app_dir = Path(__file__).parent.parent / "app"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

if "elasticsearch" not in sys.modules:
    _fake_es_module = types.ModuleType("elasticsearch")

    class _FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            pass

    _fake_es_module.Elasticsearch = _FakeElasticsearch
    sys.modules["elasticsearch"] = _fake_es_module

# Other test modules in this suite (test_chat_router/test_history_router)
# stub out "utils.es_client" wholesale in sys.modules before importing chat_rt
# (they only need get_es_client(), not the real module). Since `python -m
# unittest` runs all test files in one process, that fake can still be sitting
# in sys.modules by the time this file imports -- drop it so the import below
# loads the real module and its real _is_loopback(), not a stand-in.
sys.modules.pop("utils.es_client", None)

from utils.es_client import _is_loopback  # noqa: E402


class IsLoopbackTests(unittest.TestCase):
    """Real loopback URLs must still match; lookalike hostnames that merely
    contain a loopback host as a substring must not."""

    def test_real_localhost_url_is_loopback(self):
        self.assertTrue(_is_loopback("http://localhost:1200"))

    def test_real_127_0_0_1_url_is_loopback(self):
        self.assertTrue(_is_loopback("http://127.0.0.1:9200"))

    def test_docker_service_names_are_loopback(self):
        self.assertTrue(_is_loopback("http://es01:9200"))
        self.assertTrue(_is_loopback("https://elasticsearch:9200"))

    def test_lookalike_hostname_is_not_loopback(self):
        # Substring match would incorrectly treat these as loopback and
        # disable certificate verification against a real remote host.
        self.assertFalse(_is_loopback("http://notlocalhost.evil.com:9200"))
        self.assertFalse(_is_loopback("http://elasticsearch.attacker.net:9200"))
        self.assertFalse(_is_loopback("http://es01.attacker.net:9200"))

    def test_real_remote_host_is_not_loopback(self):
        self.assertFalse(_is_loopback("https://es.example.com:9200"))


if __name__ == "__main__":
    unittest.main()

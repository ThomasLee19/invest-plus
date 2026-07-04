"""
Regression tests for scripts/index_finance.py's index_chunks() chunk_id
namespacing (debug/26_7_4_debug_4.md, Low: "index_finance.py:227-267").

chunk_id used to be derived only from the chunk text's hash, with no
per-document namespace. That meant identical chunk text across two
*different* documents collided on the same ES _id -- the second document's
chunk would be treated as "already exists" and silently skipped, permanently
dropping a legitimate chunk. It also meant two identical chunks within the
same batch would overwrite each other under the same _id while `written`
was still counted for both, inflating the count.

This mirrors the dynamic-import-of-scripts-module pattern used by
test_agent_loop.py's IndexChunksBulkResultTests / IndexFinanceEncodingConsistencyTests
(see that file for the original pattern) so scripts/index_finance.py can be
loaded and exercised without being an installed package.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))


def _import_index_finance_module():
    # test_agent_loop.py, if it already ran in this pytest session, replaces
    # sys.modules["xxhash"] with a stub whose xxh64(...).hexdigest() always
    # returns the constant "0" (it only needs xxhash to be importable, not
    # correct, for its own unrelated tests). This suite's tests genuinely
    # depend on distinct inputs producing distinct digests, so make sure the
    # real package -- which is an actual dependency of index_finance.py, not
    # merely optional -- is what gets imported here.
    if "xxhash" in sys.modules and not hasattr(sys.modules["xxhash"], "__file__"):
        del sys.modules["xxhash"]
    import xxhash  # noqa: F401  (re-imported fresh above if it had been stubbed)

    scripts_dir = _backend_dir.parent / "scripts"
    spec = importlib.util.spec_from_file_location("index_finance", scripts_dir / "index_finance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingFakeElasticsearch:
    """Standing in for a live ES: exists() reports whatever ids have already
    been "indexed" via a prior bulk() call, so a chunk_id collision across
    two separate index_chunks() calls (i.e. two different documents) is
    observable the same way it would be against a real cluster."""

    def __init__(self):
        self.indexed_ids = set()
        self.bulk_calls = []

    def exists(self, index=None, id=None):
        return id in self.indexed_ids

    def bulk(self, operations=None, refresh=None, timeout=None):
        self.bulk_calls.append(operations)
        items = []
        for op in operations[0::2]:
            doc_id = op["index"]["_id"]
            self.indexed_ids.add(doc_id)
            items.append({"index": {"_id": doc_id, "status": 201}})
        return {"errors": False, "items": items}


class IndexChunksNamespacedIdTests(unittest.TestCase):
    """L: chunk_id must be namespaced by doc_id so identical chunk text in
    different documents doesn't collide on the same ES _id."""

    @classmethod
    def setUpClass(cls):
        cls.index_finance = _import_index_finance_module()

    def test_identical_chunk_text_across_two_documents_both_get_indexed(self):
        fake_es = _RecordingFakeElasticsearch()
        duplicate_text = "Risk factors are described in Item 1A of this filing."

        with patch.object(self.index_finance, "generate_embedding", return_value=[0.0] * 1024):
            w1, s1, f1 = self.index_finance.index_chunks(
                fake_es, [duplicate_text], "doc-aapl", "AAPL 10-K", "filing", {},
            )
            w2, s2, f2 = self.index_finance.index_chunks(
                fake_es, [duplicate_text], "doc-msft", "MSFT 10-K", "filing", {},
            )

        self.assertEqual((w1, s1, f1), (1, 0, 0), "first document's chunk should be written")
        self.assertEqual(
            (w2, s2, f2), (1, 0, 0),
            "second document's chunk has identical text but a different doc_id, "
            "so it must be written too, not silently skipped as 'already exists'",
        )

        all_written_ids = {
            op["index"]["_id"]
            for calls in fake_es.bulk_calls
            for op in calls[0::2]
        }
        self.assertEqual(len(all_written_ids), 2, "the two documents' chunks must get distinct _ids")

    def test_duplicate_chunk_text_within_same_batch_is_not_double_counted(self):
        fake_es = _RecordingFakeElasticsearch()
        duplicate_text = "Boilerplate disclaimer repeated at the top of every table."

        with patch.object(self.index_finance, "generate_embedding", return_value=[0.0] * 1024):
            written, skipped, failed = self.index_finance.index_chunks(
                fake_es, [duplicate_text, duplicate_text], "doc-aapl", "AAPL 10-K", "filing", {},
            )

        self.assertEqual(written, 1, "a batch-internal duplicate chunk_id must count as written once, not twice")
        self.assertEqual(failed, 0)

        total_ops_sent = sum(len(calls) for calls in fake_es.bulk_calls)
        self.assertEqual(total_ops_sent, 2, "only one index op (id + doc pair) should be sent for the duplicate")


if __name__ == "__main__":
    unittest.main()

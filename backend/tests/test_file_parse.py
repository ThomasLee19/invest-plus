"""
Unit tests for service/core/file_parse.py's embedding-count validation (L5)
and per-chunk doc_id uniqueness (L8).

Mirrors test_agent_loop.py's zero-installed-packages approach: openai,
dotenv and elasticsearch(.helpers) are stubbed via sys.modules before
file_parse.py is imported, so this suite needs no real network access or
third-party installs. The module is imported as `app.service.core.file_parse`
(not `service.core.file_parse`) because file_parse.py itself does
`from app.utils.es_client import get_es_client`, which requires the `app`
package to resolve from backend/ on sys.path -- the same layout agent.py's
`from app.utils.es_client import get_es_client` relies on in test_agent_loop.py.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
# file_parse.py mixes two import roots: `from app.utils.es_client import ...`
# (rooted at backend/) and `from service.core.rag.nlp import find_codec`
# (rooted at backend/app/, done lazily inside execute_insert_process for the
# non-PDF branch). Both dirs must be on sys.path for the module to import and
# run end-to-end, same as the real uvicorn process needs.
_app_dir = _backend_dir / "app"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

import os  # noqa: E402
os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/compatible-mode/v1")

if "openai" not in sys.modules:
    _fake_openai = types.ModuleType("openai")

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    _fake_openai.OpenAI = _FakeOpenAI
    sys.modules["openai"] = _fake_openai

if "dotenv" not in sys.modules:
    _fake_dotenv = types.ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *a, **kw: False
    sys.modules["dotenv"] = _fake_dotenv

if "elasticsearch" not in sys.modules:
    _fake_es_module = types.ModuleType("elasticsearch")

    class _FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            pass

    _fake_es_module.Elasticsearch = _FakeElasticsearch
    sys.modules["elasticsearch"] = _fake_es_module

if "elasticsearch.helpers" not in sys.modules:
    _fake_es_helpers = types.ModuleType("elasticsearch.helpers")
    _fake_es_helpers.bulk = lambda *a, **kw: (0, [])
    sys.modules["elasticsearch.helpers"] = _fake_es_helpers

# execute_insert_process's .txt/.md branch lazily imports find_codec from
# this package, whose real __init__ pulls in datrie/chardet/hanziconv/PIL
# (not installed here). Only find_codec's return value matters for these
# tests, so stub it directly rather than installing the whole rag/nlp tree.
# Set the attribute rather than skipping outright when the module already
# exists -- another test module running earlier in the same process (e.g.
# test_pdf_parser.py) may have already stubbed service.core.rag.nlp with a
# different attribute set, and both must end up present regardless of
# import order.
if "service.core.rag.nlp" not in sys.modules:
    sys.modules["service.core.rag.nlp"] = types.ModuleType("service.core.rag.nlp")
if not hasattr(sys.modules["service.core.rag.nlp"], "find_codec"):
    sys.modules["service.core.rag.nlp"].find_codec = lambda raw: "utf-8"

from app.service.core import file_parse  # noqa: E402


class EmbedCountMismatchTests(unittest.TestCase):
    """L5: a provider response with fewer vectors than requested inputs must
    raise instead of letting zip() silently drop the trailing chunks."""

    def test_short_batch_response_raises_instead_of_truncating(self):
        class _FakeResp:
            data = [types.SimpleNamespace(index=0, embedding=[0.1, 0.2])]

        class _FakeEmbeddings:
            def create(self, **kwargs):
                return _FakeResp()

        class _FakeClient:
            embeddings = _FakeEmbeddings()

        with patch.object(file_parse, "_openai_client", _FakeClient()):
            with self.assertRaises(RuntimeError):
                file_parse._embed(["chunk one", "chunk two", "chunk three"])

    def test_matching_batch_response_returns_all_vectors(self):
        class _FakeResp:
            data = [
                types.SimpleNamespace(index=1, embedding=[1.0]),
                types.SimpleNamespace(index=0, embedding=[0.0]),
            ]

        class _FakeEmbeddings:
            def create(self, **kwargs):
                return _FakeResp()

        class _FakeClient:
            embeddings = _FakeEmbeddings()

        with patch.object(file_parse, "_openai_client", _FakeClient()):
            vectors = file_parse._embed(["chunk zero", "chunk one"])
        # sorted by .index, so [0.0] (index 0) must come before [1.0] (index 1)
        self.assertEqual(vectors, [[0.0], [1.0]])


class DocIdUniquenessTests(unittest.TestCase):
    """L8: two chunks with identical content must not collide on doc_id."""

    def test_identical_content_chunks_get_distinct_doc_ids(self):
        # Two paragraphs long enough (and identical) that _chunk_text splits
        # them into two separate, content-identical chunks.
        para = "Boilerplate disclosure text. " * 40  # > MAX_CHUNK/2, well-formed
        text = para + "\n\n" + para
        tmp_dir = Path(_backend_dir) / "tests" / "_tmp_file_parse"
        tmp_dir.mkdir(exist_ok=True)
        file_path = tmp_dir / "dup_content.txt"
        file_path.write_text(text, encoding="utf-8")

        captured = {}

        class _FakeEs:
            pass

        def _fake_bulk(es, docs, **kwargs):
            captured["docs"] = docs
            return len(docs), []

        try:
            with patch.object(file_parse, "_embed", side_effect=lambda texts: [[0.0] for _ in texts]), \
                 patch.object(file_parse, "get_es_client", return_value=_FakeEs()), \
                 patch.object(file_parse, "bulk", _fake_bulk):
                file_parse.execute_insert_process(str(file_path), "dup_content.txt", "user1", "sess0001")
        finally:
            file_path.unlink(missing_ok=True)
            tmp_dir.rmdir()

        docs = captured["docs"]
        self.assertEqual(len(docs), 2, "expected two identical-content chunks")
        self.assertEqual(docs[0]["_source"]["content_with_weight"],
                          docs[1]["_source"]["content_with_weight"])
        self.assertNotEqual(docs[0]["_id"], docs[1]["_id"],
                             "identical-content chunks must not collide on doc_id")


class ChunkTextTokenCapTests(unittest.TestCase):
    """Medium #2 (debug/26_7_4_debug_4.md): a single .txt/.md paragraph with no
    blank-line breaks must still be split so no chunk handed to _embed can
    exceed the embedding model's token budget, even though _chunk_text
    otherwise only splits on blank lines and a MAX_CHUNK *character* cap."""

    def test_single_oversized_paragraph_is_split_within_token_budget(self):
        from service.core.rag.utils import num_tokens_from_string

        # One paragraph, no "\n\n" anywhere, well over 40k chars -> well over
        # the ~8000 token safety cap on typical English/punctuation text.
        huge_paragraph = "The quick brown fox jumps over the lazy dog. " * 1000
        self.assertGreater(len(huge_paragraph), 40000)

        chunks = file_parse._chunk_text(huge_paragraph)

        self.assertGreater(len(chunks), 1, "oversized paragraph must be split into multiple chunks")
        for chunk in chunks:
            self.assertLessEqual(
                num_tokens_from_string(chunk), file_parse._MAX_EMBED_TOKENS,
                "every chunk handed to _embed must stay within the embedding token budget",
            )
        # No content should be silently dropped while splitting.
        self.assertEqual("".join(chunks), huge_paragraph.strip())

    def test_normal_paragraphs_still_split_on_blank_lines(self):
        # Regression guard: two paragraphs each big enough on their own to
        # blow the MAX_CHUNK *character* accumulation cap must still land in
        # separate chunks, same as before this change (mirrors the sizing
        # used by DocIdUniquenessTests above).
        para = "Boilerplate disclosure text. " * 40  # > MAX_CHUNK/2, well-formed
        text = para + "\n\n" + para
        self.assertEqual(file_parse._chunk_text(text), [para.strip(), para.strip()])


class NaiveMergeCombinedTokenCapTests(unittest.TestCase):
    """Medium #3 (debug/26_7_4_debug_4.md): naive_merge's add_chunk truncates
    an oversized piece to _MAX_EMBED_TOKENS before merging, but must also
    refuse to merge it onto an existing chunk if the combined token count
    would exceed the embedding model's real input limit -- otherwise a small
    existing chunk plus an 8000-token truncated piece produces a ~8300-token
    chunk that still fails at _embed time."""

    def test_truncated_oversized_piece_does_not_merge_past_safety_threshold(self):
        # This module's own sys.modules["service.core.rag.nlp"] entry is the
        # lightweight find_codec-only stub set up above for file_parse's
        # sake (see the block before `from app.service.core import
        # file_parse`), not the real module -- so naive_merge/
        # num_tokens_from_string/_MAX_MERGED_CHUNK_TOKENS aren't on it. Load
        # a separate, real copy of the package (tiktoken/chardet/hanziconv/
        # PIL/nltk are actually installed in this test environment) under a
        # private module name so it doesn't collide with or replace that
        # stub.
        import importlib.util

        nlp_dir = _app_dir / "service" / "core" / "rag" / "nlp"
        spec = importlib.util.spec_from_file_location(
            "test_file_parse_real_rag_nlp", nlp_dir / "__init__.py",
            submodule_search_locations=[str(nlp_dir)],
        )
        rag_nlp = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = rag_nlp
        spec.loader.exec_module(rag_nlp)

        # A small "normal" section (well under chunk_token_num=384) followed
        # by one enormous section with no delimiter hits, forcing add_chunk's
        # _MAX_EMBED_TOKENS truncation path.
        small_section = "Existing accumulated chunk content. " * 30
        huge_section = "supercalifragilisticexpialidocious " * 20000

        sections = [(small_section, ""), (huge_section, "")]
        chunks = rag_nlp.naive_merge(sections, chunk_token_num=384, delimiter="\n。；！？")

        # The huge, truncated piece must have been forced into its own chunk
        # rather than appended onto the small existing one.
        self.assertEqual(len(chunks), 2)
        small_chunk_tokens = rag_nlp.num_tokens_from_string(chunks[0])
        huge_chunk_tokens = rag_nlp.num_tokens_from_string(chunks[1])

        self.assertLessEqual(
            small_chunk_tokens, rag_nlp._MAX_MERGED_CHUNK_TOKENS,
            "the untouched small chunk must stay well under the merge safety threshold",
        )
        # The truncated piece itself is allowed to sit near _MAX_EMBED_TOKENS
        # (that cap is what keeps it under the model's real input limit on
        # its own) -- what must NOT happen is the small chunk's content
        # getting merged onto it and pushing it past that cap, which is
        # exactly the ~8300-token bug this fix closes.
        self.assertLessEqual(huge_chunk_tokens, rag_nlp._MAX_EMBED_TOKENS)
        self.assertGreater(
            huge_chunk_tokens, rag_nlp._MAX_MERGED_CHUNK_TOKENS,
            "sanity check: the truncated piece must be large enough to actually "
            "exercise the merge-safety threshold, not just the plain chunk_token_num check",
        )


if __name__ == "__main__":
    unittest.main()

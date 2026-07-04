"""
Unit tests for service/core/deepdoc/parser/pdf_parser.py's __images__:
  - M3: aggregate rasterization memory across all pages must stay bounded
    regardless of page count (MAX_TOTAL_RENDER_PIXELS), not just per-page.
  - M4: a pdfplumber.open() failure must raise a clear error instead of
    leaving self.page_images/self.page_chars unset for later code to crash
    on with an unrelated AttributeError.

None of xgboost/pdfplumber/PIL/pypdf/numpy/huggingface_hub/the real
service.core.deepdoc.vision OCR stack are installed in this environment, so
(mirroring test_agent_loop.py's and test_file_parse.py's zero-installed-
packages approach) they're all stubbed via sys.modules before pdf_parser.py
is imported. RAGFlowPdfParser.__init__ downloads/loads real OCR/layout
models, which is irrelevant to the logic under test here, so instances are
built with object.__new__ to skip it entirely -- __images__ and
_safe_render_resolution don't read any state __init__ would have set except
self.ocr, which is stubbed in directly.
"""
import sys
import types
import unittest
from pathlib import Path

_backend_dir = Path(__file__).parent.parent
_app_dir = _backend_dir / "app"
for _p in (str(_backend_dir), str(_app_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _stub(name, build):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        build(mod)
        sys.modules[name] = mod


_stub("xgboost", lambda m: setattr(m, "Booster", type("Booster", (), {})))
_stub("PIL", lambda m: None)
_stub("PIL.Image", lambda m: setattr(m, "Image", object))
if "PIL" in sys.modules:
    sys.modules["PIL"].Image = sys.modules["PIL.Image"]


def _build_numpy(m):
    def median(seq):
        seq = sorted(seq)
        n = len(seq)
        if n == 0:
            return 0
        mid = n // 2
        return seq[mid] if n % 2 else (seq[mid - 1] + seq[mid]) / 2

    def cumsum(seq):
        out, total = [], 0
        for x in seq:
            total += x
            out.append(total)
        return out

    m.median = median
    m.cumsum = cumsum
    m.array = lambda x, dtype=None: x
    m.float32 = float


_stub("numpy", _build_numpy)
_stub("pypdf", lambda m: setattr(m, "PdfReader", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no outline"))))
_stub("huggingface_hub", lambda m: setattr(m, "snapshot_download", lambda **kw: ""))


def _build_vision(m):
    class _NoOp:
        def __init__(self, *a, **kw):
            pass

    class _Recognizer(_NoOp):
        @staticmethod
        def sort_Y_firstly(arr, _th):
            return arr

        @staticmethod
        def find_overlapped(c, bxs):
            return None

    m.OCR = _NoOp
    m.Recognizer = _Recognizer
    m.LayoutRecognizer = _NoOp
    m.TableStructureRecognizer = _NoOp


_stub("service.core.deepdoc.vision", _build_vision)
# Set the attribute rather than skipping outright when the module already
# exists -- another test module running earlier in the same process (e.g.
# test_file_parse.py) may have already stubbed service.core.rag.nlp with a
# different attribute set (find_codec), and both must end up present
# regardless of import order.
if "service.core.rag.nlp" not in sys.modules:
    sys.modules["service.core.rag.nlp"] = types.ModuleType("service.core.rag.nlp")
if not hasattr(sys.modules["service.core.rag.nlp"], "rag_tokenizer"):
    sys.modules["service.core.rag.nlp"].rag_tokenizer = types.SimpleNamespace(tokenize=lambda s: s)


class _FakeImage:
    def __init__(self, w_px, h_px):
        self.size = (w_px, h_px)

    def crop(self, box):
        return self


class _FakePage:
    def __init__(self, width_pt, height_pt):
        self.width = width_pt
        self.height = height_pt

    def to_image(self, resolution=None):
        w_px = int(self.width * resolution / 72)
        h_px = int(self.height * resolution / 72)
        return types.SimpleNamespace(annotated=_FakeImage(w_px, h_px))

    def dedupe_chars(self):
        return self

    @property
    def chars(self):
        return []


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def close(self):
        pass


def _stub_pdfplumber(open_impl):
    mod = types.ModuleType("pdfplumber")
    mod.open = open_impl
    sys.modules["pdfplumber"] = mod


# Provide a working pdfplumber stub for the initial import (module-level
# `import pdfplumber` in pdf_parser.py); individual tests below monkeypatch
# pdf_parser.pdfplumber.open per-case via unittest.mock.patch.
_stub_pdfplumber(lambda *a, **kw: _FakePdf([]))

from service.core.deepdoc.parser import pdf_parser as pdf_parser_mod  # noqa: E402
from unittest.mock import patch  # noqa: E402


def _bare_parser():
    """RAGFlowPdfParser instance with __init__ skipped (no real OCR/layout
    model loading), but with the one attribute __images__ actually reads
    off self (self.ocr) stubbed in."""
    parser = object.__new__(pdf_parser_mod.RAGFlowPdfParser)
    parser.ocr = types.SimpleNamespace(detect=lambda arr: [])
    return parser


class CorruptPdfRaisesCleanlyTests(unittest.TestCase):
    """M4: pdfplumber.open() failing must raise a clear error, with
    self.page_images/self.page_chars already initialized to [] rather than
    left unset, instead of letting later code crash with an AttributeError."""

    def test_open_failure_raises_instead_of_swallowing(self):
        parser = _bare_parser()
        with patch.object(pdf_parser_mod.pdfplumber, "open",
                           side_effect=RuntimeError("not a PDF")):
            with self.assertRaises(ValueError) as ctx:
                parser.__images__(b"not actually a pdf", zoomin=3)
        self.assertIn("Failed to parse PDF", str(ctx.exception))
        # Even on failure, these must be real (empty) lists, not unset --
        # otherwise callers that inspect parser state after catching the
        # raised error would hit an unrelated AttributeError instead.
        self.assertEqual(parser.page_images, [])
        self.assertEqual(parser.page_chars, [])


class AggregateRenderBudgetTests(unittest.TestCase):
    """M3: total rasterized pixels held across all pages must stay bounded
    by MAX_TOTAL_RENDER_PIXELS regardless of page count, and a normal
    reasonably-sized PDF must render unaffected (no scaling applied)."""

    def test_normal_pdf_pages_render_at_full_resolution(self):
        # Three US-Letter pages (612x792pt) -- ordinary case, well under both
        # the per-page cap and this run's share of the aggregate budget.
        pages = [_FakePage(612, 792) for _ in range(3)]
        parser = _bare_parser()
        with patch.object(pdf_parser_mod.pdfplumber, "open", return_value=_FakePdf(pages)):
            parser.__images__(b"fake-pdf-bytes", zoomin=3)

        self.assertEqual(len(parser.page_images), 3)
        expected_w = int(612 * (72 * 3) / 72)
        expected_h = int(792 * (72 * 3) / 72)
        for img in parser.page_images:
            self.assertEqual(img.size, (expected_w, expected_h),
                              "a normal-sized PDF must render at full (unscaled) resolution")

    def test_many_huge_pages_stay_under_aggregate_pixel_budget(self):
        # 50 pages, each with an enormous MediaBox (in points) that would,
        # uncapped, rasterize far past the per-page cap on its own -- this
        # simulates the crafted-PDF OOM scenario from the debug report.
        huge_pt = 20000  # ~ arbitrarily large page in points
        pages = [_FakePage(huge_pt, huge_pt) for _ in range(50)]
        parser = _bare_parser()
        with patch.object(pdf_parser_mod.pdfplumber, "open", return_value=_FakePdf(pages)):
            parser.__images__(b"fake-pdf-bytes", zoomin=3)

        self.assertEqual(len(parser.page_images), 50)
        total_pixels = sum(w * h for (w, h) in (img.size for img in parser.page_images))
        # Some float-rounding slack, but must stay close to the aggregate
        # budget -- not anywhere near the old unbounded
        # MAX_PAGE_RENDER_PIXELS * 50 (~1.5B) behavior.
        self.assertLessEqual(total_pixels, pdf_parser_mod.RAGFlowPdfParser.MAX_TOTAL_RENDER_PIXELS * 1.05)

    def test_per_page_area_never_exceeds_per_page_cap_even_with_budget_headroom(self):
        # A single huge page with lots of aggregate budget available must
        # still be clamped by the existing per-page MAX_PAGE_RENDER_PIXELS
        # cap (M3 must not regress the pre-existing per-page guard).
        pages = [_FakePage(50000, 50000)]
        parser = _bare_parser()
        with patch.object(pdf_parser_mod.pdfplumber, "open", return_value=_FakePdf(pages)):
            parser.__images__(b"fake-pdf-bytes", zoomin=3)

        w, h = parser.page_images[0].size
        self.assertLessEqual(w * h, pdf_parser_mod.RAGFlowPdfParser.MAX_PAGE_RENDER_PIXELS * 1.05)


if __name__ == "__main__":
    unittest.main()

# backend/tests/test_ingestion_engine.py
# Tests for the NBC-ingestion-scope upgrade to the extraction engine:
# page_quality, ocr_engine, ocr_retry, table_extractor, block_classifier,
# ingestion_log.
#
# OCR-engine/retry tests use a stub engine implementing the OCREngine
# protocol rather than invoking real Tesseract, matching the existing
# suite's convention (test_plan_extractor.py) of not requiring
# Tesseract/Poppler in CI. table_extractor tests use a fake pdfplumber-
# shaped page rather than rendering a real PDF table, since building one
# reportlab can rasterize into vector line intersections pdfplumber's
# find_tables() would actually detect is not practical at test time.

from __future__ import annotations

import io
import logging
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import pdfplumber

from plan_extractor.page_quality import (
    PageClass,
    PAGE_CLASS_TO_ROUTE,
    classify_page,
    quality_label,
)
from plan_extractor.ocr_engine import OCRResult, OCRWord
from plan_extractor.ocr_retry import run_ocr_with_retry, score_ocr_result
from plan_extractor.table_extractor import extract_tables, ExtractedTable
from plan_extractor.block_classifier import BlockType, classify_block_text, classify_line
from plan_extractor.ingestion_log import PageIngestionLog
from plan_extractor.file_router import route_file, FileType, _classify_pdf_page

FIXTURES = Path(__file__).parent / "fixtures"


def _make_vector_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 10)
    y = 750
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_blank_pdf(pages: int = 1) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(pages):
        c.showPage()
    c.save()
    return buf.getvalue()


class TestPageQuality:
    def test_native_text_page_classified_as_native_text(self):
        pdf_bytes = _make_vector_pdf(["Some real embedded text content here."])
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_class, signals = classify_page(pdf.pages[0])
        assert page_class == PageClass.NATIVE_TEXT
        assert PAGE_CLASS_TO_ROUTE[page_class] == "vector"
        assert signals.text_len > 0

    def test_blank_page_classified_as_scanned(self):
        pdf_bytes = _make_blank_pdf(pages=1)
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_class, _signals = classify_page(pdf.pages[0])
        assert page_class == PageClass.SCANNED
        assert PAGE_CLASS_TO_ROUTE[page_class] == "scanned"

    def test_quality_label_bands(self):
        assert quality_label(0.95) == "GOOD"
        assert quality_label(0.90) == "GOOD"
        assert quality_label(0.80) == "REVIEW"
        assert quality_label(0.75) == "REVIEW"
        assert quality_label(0.50) == "BAD"

    def test_real_dense_cad_pages_classified_mixed(self):
        """Regression: a real 7-page CAD export with zero text objects but
        thousands of real lines/curves per page must classify as MIXED
        (route "mixed" — both native extraction and OCR attempted), never
        SCANNED (which would mean whole-page OCR only, previously slow/
        memory-heavy enough to crash a request on a large sheet)."""
        pdf_bytes = (FIXTURES / "ALL_BASIC_DRAWING.pdf").read_bytes()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_class, _signals = classify_page(page)
                assert page_class in (PageClass.MIXED, PageClass.NATIVE_TEXT)

    def test_real_mixed_document_pages_classified_per_page(self):
        """Regression: the 4-page real upload has 3 pages that are pure
        scans (2 large photos + 1 small letter) and 1 page with a real
        native text layer — verified by manual inspection this session."""
        pdf_bytes = (FIXTURES / "LAYOUT_PLAN_PLOTING_PLAN_PARKING_LETTER.pdf").read_bytes()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            classes = [classify_page(p)[0] for p in pdf.pages]
        assert classes[2] == PageClass.NATIVE_TEXT
        assert classes[0] == PageClass.IMAGE_ONLY
        assert classes[1] == PageClass.IMAGE_ONLY
        assert classes[3] == PageClass.IMAGE_ONLY


class _FakePDFPage:
    """Duck-types just enough of a pdfplumber Page for classify_page /
    _classify_pdf_page to work without needing a real PDF."""

    def __init__(self, text="", n_lines=0, images=None, width=1000.0, height=1000.0):
        self._text = text
        self.lines = [{} for _ in range(n_lines)]
        self.rects = []
        self.curves = []
        self.images = images or []
        self.width = width
        self.height = height

    def extract_text(self):
        return self._text


class TestMixedPageAlwaysGetsOCR:
    def test_mixed_page_with_no_image_still_routes_to_mixed(self):
        """Regression: an earlier version of this code skipped OCR on a
        MIXED page with zero embedded raster images, reasoning there was
        "nothing to scan." That was wrong and has been reverted — OCR runs
        against a RASTERIZED RENDER of the whole page (pdf2image/poppler),
        not against embedded image objects, so a page with fonts flattened
        to vector outlines still renders as legible pixel text once
        rasterized. Verified directly against a real file (see
        test_real_dense_cad_pages_classified_mixed / Stage 0 diagnosis):
        OCR-ing ALL_BASIC_DRAWING.pdf's rasterized pages recovered
        "CLIENT ROYAL LANDMARK HOTEL" and real dimension figures that
        native pdfplumber extraction could never find on this file (it has
        no real text objects at all). Such a page must route to "mixed",
        not be silently downgraded to vector-only."""
        page = _FakePDFPage(text="", n_lines=300, images=[])
        assert _classify_pdf_page(page) == "mixed"

    def test_mixed_page_with_an_image_also_routes_to_mixed(self):
        page = _FakePDFPage(text="", n_lines=300, images=[{"x0": 0, "top": 0}])
        assert _classify_pdf_page(page) == "mixed"


class _StubEngine:
    """Implements the OCREngine protocol without touching real Tesseract."""

    name = "stub"

    def __init__(self, responses: dict[str, OCRResult]):
        self._responses = responses
        self.calls: list[str] = []

    def process_page(self, image, config: str = "") -> OCRResult:
        self.calls.append(config)
        return self._responses[config]


def _ocr_result(words: list[tuple[str, float]], confidence: float) -> OCRResult:
    return OCRResult(
        raw_text=" ".join(w for w, _ in words),
        words=[OCRWord(text=w, confidence=c, bbox=(0, 0, 1, 1)) for w, c in words],
        mean_confidence=confidence,
        engine_name="stub",
    )


class TestOCRRetry:
    def test_score_penalizes_garbage_tokens(self):
        clean = _ocr_result([("SCALE", 90.0), ("AREA", 90.0)], confidence=90.0)
        garbage = _ocr_result([("...", 90.0), ("|||", 90.0)], confidence=90.0)
        assert score_ocr_result(clean) > score_ocr_result(garbage)

    def test_score_is_zero_for_engine_error(self):
        errored = OCRResult(raw_text="", engine_name="stub", error="boom")
        assert score_ocr_result(errored) == 0.0

    def test_early_exit_once_good_threshold_cleared(self):
        engine = _StubEngine({
            "--psm 3": _ocr_result([("GOODTEXT", 99.0)] * 5, confidence=99.0),
            "--psm 6": _ocr_result([("x", 10.0)], confidence=10.0),
            "--psm 11": _ocr_result([("x", 10.0)], confidence=10.0),
        })
        from PIL import Image
        result = run_ocr_with_retry(Image.new("RGB", (10, 10), "white"), engine)
        assert result.winning_config == "--psm 3"
        assert result.attempt_count == 1
        assert engine.calls == ["--psm 3"]

    def test_runs_full_ladder_and_picks_best_when_none_clear_good(self):
        engine = _StubEngine({
            "--psm 3": _ocr_result([("a", 40.0)], confidence=40.0),
            "--psm 6": _ocr_result([("b", 70.0)], confidence=70.0),
            "--psm 11": _ocr_result([("c", 60.0)], confidence=60.0),
        })
        from PIL import Image
        result = run_ocr_with_retry(Image.new("RGB", (10, 10), "white"), engine)
        assert result.attempt_count == 3
        assert result.winning_config == "--psm 6"
        assert engine.calls == ["--psm 3", "--psm 6", "--psm 11"]


class _FakeTable:
    def __init__(self, bbox, rows):
        self.bbox = bbox
        self._rows = rows

    def extract(self):
        return self._rows


class _FakePage:
    def __init__(self, tables):
        self._tables = tables

    def find_tables(self):
        return self._tables


class TestTableExtractor:
    def test_rejects_noisy_low_fill_false_positive(self):
        """Regression: a real 44x11 grid covering 91% of a real page, with
        only 17% of cells non-empty, was a find_tables() false positive
        that swallowed unrelated running text — verified against a real
        file this session. A low cell-fill-ratio table must be rejected."""
        rows = [[None] * 11 for _ in range(44)]
        rows[0][0] = "Project Title: some long unrelated paragraph of text"
        rows[1][5] = "Inward Date"
        page = _FakePage([_FakeTable(bbox=(0, 0, 1000, 1000), rows=rows)])
        assert extract_tables(page, page_index=0) == []

    def test_accepts_clean_high_fill_table(self):
        rows = [
            ["SUR NO.", "AREA", "F.P. NO"],
            ["24/1", "1350.00", "24"],
        ]
        page = _FakePage([_FakeTable(bbox=(0, 0, 100, 50), rows=rows)])
        tables = extract_tables(page, page_index=0)
        assert len(tables) == 1
        assert tables[0].fill_ratio == 1.0
        assert "SUR NO." in tables[0].to_markdown()

    def test_rejects_pathologically_large_grid(self):
        rows = [[str(i * 100 + j) for j in range(103)] for i in range(59)]
        page = _FakePage([_FakeTable(bbox=(0, 0, 5000, 5000), rows=rows)])
        assert extract_tables(page, page_index=0) == []

    def test_real_parking_letter_page_filters_the_one_false_positive(self):
        """Regression against the real file: page 2 has 10 find_tables()
        results, 9 legitimate small tables and 1 huge false positive
        (91% page area, 17% fill) that must be filtered out."""
        pdf_bytes = (FIXTURES / "LAYOUT_PLAN_PLOTING_PLAN_PARKING_LETTER.pdf").read_bytes()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            tables = extract_tables(pdf.pages[2], page_index=2)
        assert len(tables) == 9
        for t in tables:
            assert t.fill_ratio >= 0.35


class TestBlockClassifier:
    def test_floor_label_line_classified(self):
        assert classify_block_text("GROUND FLOOR PLAN") == BlockType.FLOOR_LABEL

    def test_room_label_line_classified(self):
        assert classify_block_text("KITCHEN") == BlockType.ROOM_LABEL

    def test_notes_line_classified(self):
        assert classify_block_text("NOTES: structure as per engineer") == BlockType.NOTES

    def test_unrelated_line_is_unknown(self):
        assert classify_block_text("some random unrelated caption") == BlockType.UNKNOWN

    def test_title_block_zone_wins_over_keyword_match(self):
        """A line inside the title-block position zone is TITLE_BLOCK even
        if it happens to contain a room keyword — position is checked
        first by design."""
        page_width, page_height = 1000.0, 1000.0
        bbox = (900.0, 950.0, 990.0, 960.0)  # right+bottom zone
        block = classify_line("KITCHEN reference in project title", bbox, page_width, page_height)
        assert block.block_type == BlockType.TITLE_BLOCK

    def test_keyword_wins_outside_title_block_zone(self):
        page_width, page_height = 1000.0, 1000.0
        bbox = (100.0, 100.0, 200.0, 110.0)  # nowhere near the title-block zone
        block = classify_line("KITCHEN", bbox, page_width, page_height)
        assert block.block_type == BlockType.ROOM_LABEL


class TestIngestionLog:
    def test_bad_quality_logs_at_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="plan_extractor.ingestion"):
            PageIngestionLog(
                document_id="doc1", page_index=0, page_class="scanned",
                extraction_method="ocr", quality_label="BAD",
            ).emit()
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_good_quality_logs_at_info_not_warning(self, caplog):
        with caplog.at_level(logging.INFO, logger="plan_extractor.ingestion"):
            PageIngestionLog(
                document_id="doc1", page_index=0, page_class="vector",
                extraction_method="vector", quality_label="GOOD",
            ).emit()
        assert all(r.levelno != logging.WARNING for r in caplog.records)
        assert any(r.levelno == logging.INFO for r in caplog.records)


class TestGeminiModelConfig:
    def test_default_model_is_not_the_decommissioned_one(self):
        """Regression: 'gemini-2.0-flash' (this file's previous hardcoded
        model id) was shut down by Google on 2026-06-01 — every Gemini call
        this pipeline made would have failed on every request, silently
        falling through to Tesseract even with a valid API key configured.
        This just guards against ever hardcoding that exact dead id again."""
        import plan_extractor.scanned_pdf_extractor as spe
        assert spe.GEMINI_MODEL != "gemini-2.0-flash"
        assert spe.GEMINI_MODEL

    def test_model_is_configurable_via_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
        import importlib
        import plan_extractor.scanned_pdf_extractor as spe
        importlib.reload(spe)
        try:
            assert spe.GEMINI_MODEL == "gemini-3.5-flash"
        finally:
            monkeypatch.delenv("GEMINI_MODEL", raising=False)
            importlib.reload(spe)


class TestProjectNameFromOCR:
    def test_recovers_client_name_stopping_at_next_label(self):
        """Regression: verified directly against a real file
        (ALL_BASIC_DRAWING.pdf) whose flat (no-newline) OCR text reads
        "...CLIENT ROYAL LANDMARK HOTEL PROJECT DWG NO DATE..." — there is
        no punctuation Tesseract preserved to bound the name, so this must
        stop at the next label-like word ("PROJECT") instead."""
        from plan_extractor.scanned_pdf_extractor import _extract_project_name_from_ocr
        text = "ONLY FOR REFERENCE CLIENT ROYAL LANDMARK HOTEL PROJECT DWG NO DATE NORTH"
        assert _extract_project_name_from_ocr(text) == "ROYAL LANDMARK HOTEL"

    def test_does_not_false_positive_on_boilerplate_owner_mention(self):
        """Regression: a real file's legal boilerplate reads "...DEVELOPER,
        OWNER FROM THEIR RESPONSIBILITIES, IMPOSED UNDER THE ACT..." — an
        earlier draft of this matcher included a bare "owner" keyword and
        would have captured "FROM THEIR RESPONSIBILITIES..." as a project
        name. Only "CLIENT"/"PROJECT NAME"/"BUILDING NAME" trigger a match."""
        from plan_extractor.scanned_pdf_extractor import _extract_project_name_from_ocr
        text = "SHALL NOT DISCHARGE THE OWNER FROM THEIR RESPONSIBILITIES IMPOSED UNDER THE ACT"
        assert _extract_project_name_from_ocr(text) is None

    def test_no_match_returns_none(self):
        from plan_extractor.scanned_pdf_extractor import _extract_project_name_from_ocr
        assert _extract_project_name_from_ocr("SCALE 1:100 GROUND FLOOR PLAN") is None


class TestGeminiFallbackReasonCategorization:
    def test_deprecated_model_error_is_labeled_specifically(self, monkeypatch):
        """Regression: this pipeline's Gemini model id was, in fact, dead
        (see TestGeminiModelConfig) — every call would have raised a "model
        not found"-style error. Before this fix that fell into a generic
        "Gemini API error" bucket; it now names the real, actionable cause
        so a deployer doesn't have to guess from a raw exception string."""
        import plan_extractor.scanned_pdf_extractor as spe

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
        monkeypatch.setattr(spe, "_rasterize_pdf_page", lambda *a, **k: (b"fake-png-bytes", None))

        class _FakeModel:
            def __init__(self, *a, **k):
                pass

            def generate_content(self, *a, **k):
                raise Exception("404 model not found: models/gemini-2.0-flash is not supported")

        class _FakeGenAI:
            GenerationConfig = lambda *a, **k: None

            @staticmethod
            def configure(**k):
                pass

            GenerativeModel = _FakeModel

        import sys
        monkeypatch.setitem(sys.modules, "google.generativeai", _FakeGenAI)
        monkeypatch.setattr("PIL.Image.open", lambda *a, **k: object())

        result = spe.extract_with_gemini(b"irrelevant", page_num=0)
        assert result["success"] is False
        assert "not found/deprecated" in result["error"]
        assert "GEMINI_MODEL" in result["error"]

    def test_rate_limit_error_still_labeled_as_rate_limit(self, monkeypatch):
        import plan_extractor.scanned_pdf_extractor as spe

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
        monkeypatch.setattr(spe, "_rasterize_pdf_page", lambda *a, **k: (b"fake-png-bytes", None))

        class _FakeModel:
            def __init__(self, *a, **k):
                pass

            def generate_content(self, *a, **k):
                raise Exception("429 Resource exhausted: quota exceeded")

        class _FakeGenAI:
            GenerationConfig = lambda *a, **k: None

            @staticmethod
            def configure(**k):
                pass

            GenerativeModel = _FakeModel

        import sys
        monkeypatch.setitem(sys.modules, "google.generativeai", _FakeGenAI)
        monkeypatch.setattr("PIL.Image.open", lambda *a, **k: object())

        result = spe.extract_with_gemini(b"irrelevant", page_num=0)
        assert result["success"] is False
        assert "rate limit/quota exceeded" in result["error"]

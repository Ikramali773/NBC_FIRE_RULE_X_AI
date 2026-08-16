# backend/tests/test_plan_extractor.py
# Tests for the PDF building-plan extraction module (plan_extractor/).
#
# Uses reportlab (already a backend dependency, for report_pdf.py) to build
# synthetic vector PDFs at test time — no fixture files needed. The scanned/
# OCR path is exercised with a stubbed extract_from_scanned_pdf so these
# tests don't require Tesseract/Poppler to be installed in CI; the OCR
# stub returns realistic per-page data shaped like the real function.

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from plan_extractor.file_router import route_file, FileType
from plan_extractor.pdf_vector_extractor import extract_from_vector_pdf, _detect_areas
from plan_extractor.scale_detector import detect_scale
from plan_extractor.pipeline import run_extraction, _merge_pdf_extraction
from plan_extractor.field_mapper import map_to_form_fields
from plan_extractor.confidence_tagger import tag_confidence

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
    """A PDF with pages that have no extractable text at all — simulates a scanned page."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(pages):
        c.showPage()
    c.save()
    return buf.getvalue()


class TestScaleDetector:
    def test_detects_real_scale_ratio(self):
        result = detect_scale(text_labels=["SCALE", "1:100", "PROJECT", "NAME"])
        assert result["value"] == "1:100"
        assert result["confidence"] != "red"

    def test_do_not_scale_disclaimer_is_not_a_scale(self):
        """Regression test for a real false positive found in testing:
        'DO NOT SCALE THE DRAWING' must never be read as a usable ratio."""
        result = detect_scale(text_labels=["DO", "NOT", "SCALE", "THE", "DRAWING"])
        assert result["value"] is None
        assert result["confidence"] == "red"

    def test_do_not_scale_alongside_real_scale_still_detects_the_real_one(self):
        result = detect_scale(text_labels=["DO", "NOT", "SCALE", "THE", "DRAWING", "SCALE", "1:200"])
        assert result["value"] == "1:200"


class TestVectorPdfExtraction:
    def test_extracts_height_floors_kitchen_as_green(self):
        pdf_bytes = _make_vector_pdf([
            "BUILDING HEIGHT = 18.5 m",
            "NO. OF FLOORS = 6",
            "KITCHEN",
            "SPRINKLER SYSTEM PROPOSED",
        ])
        data = extract_from_vector_pdf(pdf_bytes)
        assert data["height"]["value"] == 18.5
        assert data["height"]["source"] == "text_label"
        assert data["floors"]["value"] == 6
        assert data["kitchen"] == {"value": True, "source": "text_label"}
        assert data["sprinklers"] == {"value": True, "source": "text_label"}

    def test_only_pages_filter_skips_excluded_pages(self):
        pdf_bytes = _make_vector_pdf(["KITCHEN"])
        included = extract_from_vector_pdf(pdf_bytes, only_pages={0})
        excluded = extract_from_vector_pdf(pdf_bytes, only_pages={99})
        assert included["kitchen"] is not None
        assert excluded["kitchen"] is None

    def test_basement_area_not_double_counted_as_a_floor_area(self):
        """Regression test: 'BASEMENT AREA = 380 sqm' was previously being
        matched by both the basement-specific and generic-sqm patterns,
        appearing twice in the areas list and corrupting per-floor indexing."""
        text = "FLOOR AREA = 450 sqm\nBASEMENT AREA = 380 sqm"
        areas = _detect_areas(text)
        values_by_label = [(a["label"], a["value"]) for a in areas]
        assert values_by_label.count(("basement_area", 380.0)) == 1
        # The basement figure must not also appear tagged as a generic/floor area.
        assert ("generic_area", 380.0) not in values_by_label
        assert ("floor_area", 380.0) not in values_by_label

    def test_field_mapper_excludes_basement_from_per_floor_areas(self):
        pdf_bytes = _make_vector_pdf([
            "FLOOR AREA = 450 sqm",
            "BASEMENT AREA = 380 sqm",
            "1 BASEMENT LEVEL",
        ])
        data = extract_from_vector_pdf(pdf_bytes)
        mapped = map_to_form_fields(data, source_file_type="vector_pdf")
        floor_values = [f["value"] for f in mapped["per_floor_areas_m2"]]
        assert 380.0 not in floor_values
        assert mapped["basement_area_m2"]["value"] == 380.0


class TestFileRouter:
    def test_routes_text_pdf_as_vector(self):
        pdf_bytes = _make_vector_pdf(["Some real embedded text content here."])
        route = route_file(pdf_bytes, "plan.pdf")
        assert route.file_type == FileType.VECTOR_PDF
        assert route.page_types == ["vector"]

    def test_routes_blank_pdf_as_scanned(self):
        pdf_bytes = _make_blank_pdf(pages=1)
        route = route_file(pdf_bytes, "plan.pdf")
        assert route.file_type == FileType.SCANNED_PDF
        assert route.page_types == ["scanned"]

    def test_classifies_each_page_of_a_mixed_document_independently(self):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setFont("Helvetica", 10)
        c.drawString(50, 750, "Real embedded text on page one.")
        c.showPage()  # Page 2 intentionally left blank — no extractable text.
        c.showPage()
        c.save()
        pdf_bytes = buf.getvalue()

        route = route_file(pdf_bytes, "mixed.pdf")
        assert route.page_types == ["vector", "scanned"]

    def test_dense_geometry_page_with_no_text_layer_is_vector_not_scanned(self):
        """Regression test for a real production failure: a 7-page CAD export
        (ALL_BASIC_DRAWING.pdf) has zero extractable text on every page (its
        fonts are flattened to outlined vector paths) but thousands of real
        lines/curves per page. Before this fix, zero-length text alone routed
        every page to OCR — rasterizing 7 large-format sheets at once was
        slow/memory-heavy enough to crash the request ("Failed to fetch" in
        the browser). Real structural vector geometry must win over an empty
        text layer."""
        pdf_bytes = (FIXTURES / "ALL_BASIC_DRAWING.pdf").read_bytes()
        route = route_file(pdf_bytes, "ALL_BASIC_DRAWING.pdf")
        assert route.file_type == FileType.VECTOR_PDF
        assert all(t == "vector" for t in route.page_types)

    def test_genuinely_scanned_photo_pdf_still_routes_to_scanned(self):
        """Same fix must not misclassify an actual scan (no text, no vector
        geometry, one embedded raster image) as vector."""
        pdf_bytes = (FIXTURES / "Appr_Layout_Plan_scanned.pdf").read_bytes()
        route = route_file(pdf_bytes, "Appr_Layout_Plan.pdf")
        assert route.file_type == FileType.SCANNED_PDF


class TestMergePdfExtraction:
    """Stage 2+5 merge — vector-page results always win; OCR only fills gaps."""

    def test_ocr_fills_a_field_vector_pages_did_not_find(self):
        vector_data = extract_from_vector_pdf(_make_vector_pdf(["KITCHEN"]))
        scanned_result = {
            "source_stage": "5b_tesseract",
            "data": {"height": {"value": 12.0, "source": "tesseract_ocr"}, "areas": [], "floor_labels": [], "room_labels": []},
            "raw_text_labels": ["HEIGHT", "12", "m"],
            "warnings": [],
        }
        merged = _merge_pdf_extraction(vector_data, scanned_result)
        assert merged["kitchen"] == {"value": True, "source": "text_label"}  # from vector
        assert merged["height"] == {"value": 12.0, "source": "tesseract_ocr"}  # filled from OCR

    def test_vector_value_is_never_overwritten_by_ocr(self):
        vector_data = extract_from_vector_pdf(_make_vector_pdf(["BUILDING HEIGHT = 18.5 m"]))
        scanned_result = {
            "source_stage": "5b_tesseract",
            "data": {"height": {"value": 99.0, "source": "tesseract_ocr"}, "areas": [], "floor_labels": [], "room_labels": []},
            "raw_text_labels": [],
            "warnings": [],
        }
        merged = _merge_pdf_extraction(vector_data, scanned_result)
        assert merged["height"]["value"] == 18.5
        assert merged["height"]["source"] == "text_label"

    def test_no_scanned_pages_returns_vector_data_unchanged(self):
        vector_data = extract_from_vector_pdf(_make_vector_pdf(["KITCHEN"]))
        merged = _merge_pdf_extraction(vector_data, None)
        assert merged["kitchen"] == {"value": True, "source": "text_label"}


class TestRunExtractionIntegration:
    def test_vector_pdf_end_to_end_produces_green_confidence_fields(self):
        pdf_bytes = _make_vector_pdf([
            "PROJECT: Test Towers",
            "BUILDING HEIGHT = 20 m",
            "NO. OF FLOORS = 5",
            "KITCHEN",
            "Mumbai, Maharashtra",
            "DO NOT SCALE THE DRAWING",
            "SCALE 1:150",
        ])
        result = run_extraction(pdf_bytes, "plan.pdf")
        assert result["success"] is True
        data = result["data"]
        assert data["height_m"]["value"] == 20.0
        assert data["height_m"]["confidence"] == "green"
        assert data["kitchen_present"]["confidence"] == "green"
        assert data["detected_scale"]["value"] == "1:150"
        assert data["building_status"]["value"] is None
        assert data["building_status"]["confidence"] == "red"

    def test_scanned_pdf_with_ocr_tools_missing_degrades_gracefully(self, monkeypatch):
        """When Tesseract/Poppler genuinely aren't available, the pipeline
        must not crash — it should return success with red/null fields and
        a specific, diagnosable warning, not a generic 500."""
        import plan_extractor.scanned_pdf_extractor as spe

        def fake_rasterize(file_bytes, page_num=0, dpi=300):
            return None, "Poppler binary not found (pdftoppm/pdfinfo) — check backend deployment config: simulated"

        monkeypatch.setattr(spe, "_rasterize_pdf_page", fake_rasterize)

        pdf_bytes = _make_blank_pdf(pages=1)
        result = run_extraction(pdf_bytes, "scan.pdf")

        assert result["success"] is True
        assert data_has_specific_poppler_warning(result)

    def test_real_zero_text_cad_file_completes_without_crashing(self):
        """Regression test for the real 'Failed to fetch' production bug:
        a 7-page, zero-text-layer CAD file was being misrouted entirely to
        OCR and never completed. It must now go down the fast vector path
        and finish successfully, even though every field ends up red/null
        (this specific file genuinely has no extractable text — that's an
        honest result, not a bug)."""
        pdf_bytes = (FIXTURES / "ALL_BASIC_DRAWING.pdf").read_bytes()
        result = run_extraction(pdf_bytes, "ALL_BASIC_DRAWING.pdf")
        assert result["success"] is True
        assert result["data"]["_extraction_quality"]["total_fields"] > 0


def data_has_specific_poppler_warning(result: dict) -> bool:
    return any("Poppler binary not found" in w for w in result["warnings"])

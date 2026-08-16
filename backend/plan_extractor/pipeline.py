# backend/plan_extractor/pipeline.py
# Main Extraction Pipeline Orchestrator
#
# Runs Stages 1 → 8 in order and returns the complete extraction result.

from __future__ import annotations

import traceback
from typing import Optional

from plan_extractor.file_router import route_file, FileType
from plan_extractor.pdf_vector_extractor import extract_from_vector_pdf
from plan_extractor.dxf_parser import extract_from_dxf, analyze_dxf_data
from plan_extractor.dwg_converter import convert_dwg_to_dxf, cleanup_temp_dir
from plan_extractor.scanned_pdf_extractor import extract_from_scanned_pdf
from plan_extractor.scale_detector import detect_scale
from plan_extractor.field_mapper import map_to_form_fields
from plan_extractor.confidence_tagger import tag_confidence

MAX_OCR_PAGES_PER_REQUEST = 5


def _empty_vector_result() -> dict:
    """Same shape as extract_from_vector_pdf's return, for when a PDF has no vector pages at all."""
    return {
        "raw_text_labels": [], "all_words": [], "dimension_values": [], "polygons": [],
        "title_block": {}, "project_info": {}, "height": None, "floors": None, "areas": [],
        "occupancy_hint": None, "construction_type": None, "kitchen": None, "sprinklers": None,
        "basement": {"area": None, "levels": None}, "scale": None,
        "floor_labels": [], "room_labels": [], "warnings": [],
    }


def _merge_pdf_extraction(vector_data: Optional[dict], scanned_result: Optional[dict]) -> dict:
    """
    Merge pdfplumber (Stage 2, vector pages) results with OCR (Stage 5,
    router-flagged scanned pages) results into one extraction_data dict
    shaped like extract_from_vector_pdf's schema.

    Vector/text-based values always win when present — they're eligible for
    green confidence. OCR only fills fields the vector pages didn't find,
    and those fields carry their own OCR source tag so the field mapper
    caps them at amber, per Stage 6.
    """
    merged = dict(vector_data) if vector_data else _empty_vector_result()

    if not scanned_result:
        return merged

    ocr = scanned_result.get("data", {}) or {}
    ocr_source = scanned_result.get("source_stage", "5b_tesseract")

    merged["raw_text_labels"] = list(merged.get("raw_text_labels", [])) + list(scanned_result.get("raw_text_labels", []))
    merged["warnings"] = list(merged.get("warnings", [])) + list(scanned_result.get("warnings", []))

    if not merged.get("height") and ocr.get("height"):
        merged["height"] = ocr["height"]
    if not merged.get("floors") and ocr.get("floors"):
        merged["floors"] = ocr["floors"]

    project_info = dict(merged.get("project_info") or {})
    if not project_info.get("project_name") and ocr.get("project_name"):
        project_info["project_name"] = {"value": ocr["project_name"], "source": ocr_source}
    merged["project_info"] = project_info

    if not merged.get("kitchen") and ocr.get("kitchen"):
        merged["kitchen"] = {"value": True, "source": ocr_source}
    if not merged.get("sprinklers") and ocr.get("sprinklers"):
        merged["sprinklers"] = {"value": True, "source": ocr_source}

    if not merged.get("occupancy_hint") and ocr.get("occupancy_hint"):
        merged["occupancy_hint"] = {"hint": ocr["occupancy_hint"], "proposed_code": None}

    merged["areas"] = list(merged.get("areas", [])) + list(ocr.get("areas", []))

    basement = dict(merged.get("basement") or {"area": None, "levels": None})
    if basement.get("levels") is None and ocr.get("basement_levels") is not None:
        basement["levels"] = ocr["basement_levels"]
    merged["basement"] = basement

    merged["floor_labels"] = sorted(set(list(merged.get("floor_labels", [])) + list(ocr.get("floor_labels", []))))
    merged["room_labels"] = sorted(set(list(merged.get("room_labels", [])) + list(ocr.get("room_labels", []))))

    return merged


def run_extraction(file_bytes: bytes, filename: str) -> dict:
    """
    Run the full extraction pipeline on an uploaded file.

    Stages:
        1. File Router — detect file type (PDF vector/scanned, DWG)
        2. Vector PDF Extractor (pdfplumber) — for vector PDFs
        3. DXF Parser (ezdxf) — for DXF files (from DWG conversion)
        4. DWG Converter (LibreDWG dwg2dxf) — DWG → DXF
        5. Scanned PDF Fallback — Gemini (5a) + Tesseract (5b)
        6. Scale/Unit Detection
        7. Field Mapper — map to form fields
        8. Confidence Tagger — green/amber/red

    Returns:
        Complete extraction result dict ready for the frontend review popup.
    """
    result = {
        "success": False,
        "error": None,
        "data": None,
        "warnings": [],
    }

    try:
        # ━━━ Stage 1: File Router ━━━
        route = route_file(file_bytes, filename)

        if route.error:
            result["error"] = route.error
            return result

        file_type = route.file_type
        extraction_data = {}
        raw_text_labels = []
        dxf_header_units = None

        # ━━━ Stage 2 + 5: PDF, routed per-page ━━━
        # The router classifies pages individually (route.page_types), but the
        # overall file_type above is only a majority-vote label used for
        # display/source-stage purposes. Every vector page always goes through
        # pdfplumber (Stage 2, green-eligible); every page the router actually
        # flagged as scanned goes through OCR (Stage 5) — regardless of which
        # path "wins" the document-level label. This handles mixed PDFs
        # correctly instead of forcing the whole document down one path.
        if file_type in (FileType.VECTOR_PDF, FileType.SCANNED_PDF):
            page_types = route.page_types or []
            vector_pages = {i for i, t in enumerate(page_types) if t == "vector"}
            scanned_pages = [i for i, t in enumerate(page_types) if t == "scanned"]

            # OCR is expensive (rasterize + Tesseract, optionally Gemini) —
            # cap how many pages a single request will run it on so a large
            # multi-page scan can't make one upload hang or exhaust memory.
            # Never silently truncated: capped pages are surfaced as a warning.
            if len(scanned_pages) > MAX_OCR_PAGES_PER_REQUEST:
                result["warnings"].append(
                    f"{len(scanned_pages)} scanned page(s) found — only the first "
                    f"{MAX_OCR_PAGES_PER_REQUEST} were OCR'd to keep this request fast; "
                    "the rest have no extracted data."
                )
                scanned_pages = scanned_pages[:MAX_OCR_PAGES_PER_REQUEST]

            print(
                f"[Pipeline] Routing {filename}: {len(vector_pages)} vector page(s) "
                f"(Stage 2), {len(scanned_pages)} scanned page(s) (Stage 5)"
            )

            vector_data = extract_from_vector_pdf(file_bytes, only_pages=vector_pages) if vector_pages else None
            scanned_result = extract_from_scanned_pdf(file_bytes, page_numbers=scanned_pages) if scanned_pages else None

            extraction_data = _merge_pdf_extraction(vector_data, scanned_result)
            raw_text_labels = extraction_data.get("raw_text_labels", [])
            result["warnings"].extend(extraction_data.get("warnings", []))

            if scanned_result:
                if scanned_result.get("gemini_attempted"):
                    if scanned_result.get("gemini_succeeded"):
                        result["warnings"].append("Used Gemini vision for scanned page(s).")
                    else:
                        result["warnings"].append(
                            f"Gemini failed on scanned page(s), fell back to Tesseract. "
                            f"Reason: {scanned_result.get('fallback_reason', 'unknown')}"
                        )
                else:
                    result["warnings"].append(
                        "No Gemini API key configured — used Tesseract OCR for scanned page(s)."
                    )

        # ━━━ Stage 4 → 3: DWG → DXF ━━━
        elif file_type == FileType.DWG:
            print(f"[Pipeline] Routing to Stage 4 (DWG → DXF): {filename}")
            conversion = convert_dwg_to_dxf(file_bytes, filename)

            if not conversion.success:
                result["error"] = conversion.error
                result["warnings"].extend(conversion.warnings)
                return result

            result["warnings"].extend(conversion.warnings)

            try:
                # Stage 3: Parse the converted DXF
                print(f"[Pipeline] Running Stage 3 (DXF Parser) on converted file")
                dxf_raw = extract_from_dxf(conversion.dxf_path)
                extraction_data = analyze_dxf_data(dxf_raw)
                raw_text_labels = dxf_raw.get("raw_text_labels", [])
                dxf_header_units = dxf_raw.get("header_units")
                result["warnings"].extend(dxf_raw.get("warnings", []))
            finally:
                # Clean up temp files
                if conversion.dxf_path:
                    cleanup_temp_dir(conversion.dxf_path)

        else:
            result["error"] = f"Unsupported file type: {file_type}"
            return result

        # ━━━ Stage 6: Scale/Unit Detection ━━━
        print("[Pipeline] Running Stage 6 (Scale Detection)")
        scale_info = detect_scale(
            text_labels=raw_text_labels,
            dxf_header_units=dxf_header_units,
        )

        # ━━━ Stage 7: Field Mapper ━━━
        print("[Pipeline] Running Stage 7 (Field Mapper)")
        mapped = map_to_form_fields(
            extraction_data=extraction_data,
            source_file_type=file_type.value,
        )

        # Add scale and raw labels
        mapped["detected_scale"] = scale_info
        mapped["raw_text_labels"] = raw_text_labels[:200]  # Cap for payload size
        mapped["warnings"] = result["warnings"]

        # ━━━ Stage 8: Confidence Tagger ━━━
        print("[Pipeline] Running Stage 8 (Confidence Tagger)")
        tagged = tag_confidence(mapped)

        result["success"] = True
        result["data"] = tagged

    except Exception as e:
        traceback.print_exc()
        result["error"] = f"Extraction pipeline error: {str(e)}"

    return result

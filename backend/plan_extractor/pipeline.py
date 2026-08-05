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

        # ━━━ Stage 2: Vector PDF ━━━
        if file_type == FileType.VECTOR_PDF:
            print(f"[Pipeline] Routing to Stage 2 (Vector PDF): {filename}")
            extraction_data = extract_from_vector_pdf(file_bytes)
            raw_text_labels = extraction_data.get("raw_text_labels", [])
            result["warnings"].extend(extraction_data.get("warnings", []))

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

        # ━━━ Stage 5: Scanned PDF ━━━
        elif file_type == FileType.SCANNED_PDF:
            print(f"[Pipeline] Routing to Stage 5 (Scanned PDF): {filename}")
            scanned_result = extract_from_scanned_pdf(file_bytes)
            extraction_data = scanned_result.get("data", {})
            extraction_data["source_stage"] = scanned_result.get("source_stage", "stage5")

            # Add metadata about Gemini vs Tesseract path
            if scanned_result.get("gemini_attempted"):
                if scanned_result.get("gemini_succeeded"):
                    result["warnings"].append("Used Gemini vision for scanned PDF extraction.")
                else:
                    result["warnings"].append(
                        f"Gemini failed, fell back to Tesseract OCR. "
                        f"Reason: {scanned_result.get('fallback_reason', 'unknown')}"
                    )
            else:
                result["warnings"].append(
                    "No Gemini API key configured — used Tesseract OCR for scanned PDF."
                )

            raw_text_labels = scanned_result.get("raw_text_labels", [])
            result["warnings"].extend(scanned_result.get("warnings", []))

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

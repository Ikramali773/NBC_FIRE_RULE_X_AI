# backend/plan_extractor/scanned_pdf_extractor.py
# Stage 5 — Scanned PDF Fallback
#
# Stage 5a: Gemini vision (if GEMINI_API_KEY is set)
# Stage 5b: pytesseract + pdf2image (guaranteed fallback)
#
# ONLY invoked for pages the file router flagged as scanned — never for vector PDFs.

from __future__ import annotations

import io
import json
import os
import re
import traceback
from typing import Optional


def _rasterize_pdf_page(file_bytes: bytes, page_num: int = 0, dpi: int = 300) -> Optional[bytes]:
    """
    Rasterize a single PDF page to a PNG image using pdf2image.
    Requires poppler to be installed as a system package.
    """
    try:
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(
            file_bytes,
            first_page=page_num + 1,
            last_page=page_num + 1,
            dpi=dpi,
            fmt="png",
        )
        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        print(f"[Scanned PDF] pdf2image rasterization failed: {e}")
    return None


def extract_with_gemini(file_bytes: bytes, page_num: int = 0) -> dict:
    """
    Stage 5a — Use Gemini vision API to extract building data from a scanned PDF page.

    Returns a dict with extracted fields. All results are capped at amber confidence.
    Falls through to Stage 5b on ANY error.
    """
    result = {
        "success": False,
        "source_stage": "5a_gemini",
        "data": {},
        "raw_text": "",
        "error": None,
    }

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your-key-here":
        result["error"] = "No Gemini API key set — skipping to Tesseract fallback"
        return result

    # Rasterize the page
    image_bytes = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = "Failed to rasterize PDF page for Gemini"
        return result

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Structured prompt asking for specific building data
        prompt = """Analyze this building floor plan image and extract the following information.
Return your answer as a JSON object with these exact keys:

{
  "building_height_m": <number or null>,
  "floor_count": <number or null>,
  "floor_labels": [<list of floor labels like "GF", "F1", "F2" if visible>],
  "room_labels": [<list of room/space labels found>],
  "dimension_text": [<list of any printed dimension text like "12.5 m", "3500 mm">],
  "scale_note": <string like "1:100" or null if not visible>,
  "project_name": <string or null>,
  "address_text": <string or null - any address/location text visible>,
  "area_values": [{"label": "<label>", "value": <number>, "unit": "sqm"}],
  "occupancy_hint": <string describing apparent building use, e.g. "residential", "hotel">,
  "construction_keywords": [<any keywords about construction material visible>],
  "kitchen_visible": <true/false>,
  "sprinkler_visible": <true/false>,
  "basement_levels": <number or null>
}

Only include information you can actually see in the image. Use null for anything not visible.
Return ONLY the JSON object, no other text."""

        import PIL.Image
        pil_image = PIL.Image.open(io.BytesIO(image_bytes))

        response = model.generate_content(
            [prompt, pil_image],
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2000,
            ),
        )

        response_text = response.text.strip()
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response_text = "\n".join(lines)

        result["raw_text"] = response_text

        try:
            parsed = json.loads(response_text)
            result["success"] = True
            result["data"] = {
                "height": {"value": parsed.get("building_height_m"), "source": "gemini_vision"}
                if parsed.get("building_height_m") else None,
                "floors": {"value": parsed.get("floor_count"), "source": "gemini_vision"}
                if parsed.get("floor_count") else None,
                "floor_labels": parsed.get("floor_labels", []),
                "room_labels": parsed.get("room_labels", []),
                "dimension_text": parsed.get("dimension_text", []),
                "scale": parsed.get("scale_note"),
                "project_name": parsed.get("project_name"),
                "address_text": parsed.get("address_text"),
                "areas": [
                    {"value": a["value"], "label": a.get("label", ""), "source": "gemini_vision"}
                    for a in parsed.get("area_values", [])
                    if isinstance(a, dict) and a.get("value")
                ],
                "occupancy_hint": parsed.get("occupancy_hint"),
                "construction_keywords": parsed.get("construction_keywords", []),
                "kitchen": parsed.get("kitchen_visible"),
                "sprinklers": parsed.get("sprinkler_visible"),
                "basement_levels": parsed.get("basement_levels"),
            }
        except json.JSONDecodeError as e:
            result["error"] = f"Failed to parse Gemini response as JSON: {str(e)}"

    except Exception as e:
        error_msg = str(e)
        # Check for rate limiting
        if "429" in error_msg or "quota" in error_msg.lower() or "rate" in error_msg.lower():
            result["error"] = f"Gemini rate limit/quota exceeded — falling through to Tesseract: {error_msg}"
        else:
            result["error"] = f"Gemini API error — falling through to Tesseract: {error_msg}"
        traceback.print_exc()

    return result


def extract_with_tesseract(file_bytes: bytes, page_num: int = 0) -> dict:
    """
    Stage 5b — Use pytesseract to OCR a scanned PDF page.

    This is the guaranteed fallback — no API key needed.
    No semantic understanding — can only report raw text strings.
    """
    result = {
        "success": False,
        "source_stage": "5b_tesseract",
        "data": {},
        "raw_text": "",
        "error": None,
    }

    # Rasterize the page
    image_bytes = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = "Failed to rasterize PDF page for Tesseract OCR"
        return result

    try:
        import pytesseract
        import PIL.Image

        pil_image = PIL.Image.open(io.BytesIO(image_bytes))
        ocr_text = pytesseract.image_to_string(pil_image)
        result["raw_text"] = ocr_text
        result["success"] = True

        # Basic keyword matching — no semantic understanding
        data = {
            "height": None,
            "floors": None,
            "areas": [],
            "scale": None,
            "project_name": None,
            "occupancy_hint": None,
            "construction_keywords": [],
            "kitchen": None,
            "sprinklers": None,
            "basement_levels": None,
        }

        text_lower = ocr_text.lower()

        # Height — only if keyword "height" is adjacent to a number
        h_match = re.search(r"(?:height|ht)\s*[=:]\s*(\d+\.?\d*)\s*(?:m|mtr)?", ocr_text, re.IGNORECASE)
        if h_match:
            val = float(h_match.group(1))
            if 2.0 <= val <= 500.0:
                data["height"] = {"value": val, "source": "tesseract_ocr"}

        # Floors
        f_match = re.search(r"(\d+)\s*(?:floors?|storeys?)", ocr_text, re.IGNORECASE)
        if f_match:
            val = int(f_match.group(1))
            if 1 <= val <= 200:
                data["floors"] = {"value": val, "source": "tesseract_ocr"}

        # Areas — only with clear keyword
        for m in re.finditer(r"(?:area)\s*[=:]\s*(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)?", ocr_text, re.IGNORECASE):
            val = float(m.group(1))
            if 5.0 <= val <= 100000.0:
                data["areas"].append({"value": val, "label": "ocr_area", "source": "tesseract_ocr"})

        # Scale
        s_match = re.search(r"(?:scale)\s*[=:]\s*(1\s*:\s*\d+)", ocr_text, re.IGNORECASE)
        if s_match:
            data["scale"] = s_match.group(1).replace(" ", "")

        # Kitchen / sprinkler
        if re.search(r"\bkitchen\b", ocr_text, re.IGNORECASE):
            data["kitchen"] = True
        if re.search(r"\bsprinkler", ocr_text, re.IGNORECASE):
            data["sprinklers"] = True

        result["data"] = data

    except Exception as e:
        result["error"] = f"Tesseract OCR failed: {str(e)}. Ensure tesseract is installed on the system."
        traceback.print_exc()

    return result


def extract_from_scanned_pdf(file_bytes: bytes) -> dict:
    """
    Extract building data from a scanned PDF.

    Tries Gemini (5a) first, falls through to Tesseract (5b) on any error.
    """
    combined = {
        "source_stage": "5b_tesseract",  # Updated if Gemini succeeds
        "gemini_attempted": False,
        "gemini_succeeded": False,
        "fallback_reason": None,
        "data": {},
        "raw_text_labels": [],
        "warnings": [],
    }

    # ── Stage 5a: Try Gemini first ──
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key and api_key != "your-key-here":
        combined["gemini_attempted"] = True
        gemini_result = extract_with_gemini(file_bytes, page_num=0)

        if gemini_result["success"]:
            combined["gemini_succeeded"] = True
            combined["source_stage"] = "5a_gemini"
            combined["data"] = gemini_result["data"]
            combined["raw_text_labels"] = (
                gemini_result.get("raw_text", "").split() if gemini_result.get("raw_text") else []
            )
            return combined
        else:
            combined["fallback_reason"] = gemini_result.get("error", "Unknown Gemini error")
            combined["warnings"].append(
                f"Gemini fallback failed, using Tesseract: {gemini_result.get('error', '')}"
            )

    # ── Stage 5b: Tesseract fallback ──
    tess_result = extract_with_tesseract(file_bytes, page_num=0)

    if tess_result["success"]:
        combined["data"] = tess_result["data"]
        combined["raw_text_labels"] = tess_result.get("raw_text", "").split()
    else:
        combined["warnings"].append(f"Tesseract also failed: {tess_result.get('error', '')}")

    return combined

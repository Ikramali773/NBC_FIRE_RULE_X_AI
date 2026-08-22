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

from plan_extractor.label_categorizer import detect_floor_labels, detect_room_labels
from plan_extractor.ingestion_log import PageIngestionLog
from plan_extractor.ocr_engine import TesseractEngine
from plan_extractor.ocr_retry import run_ocr_with_retry

_tesseract_engine = TesseractEngine()

# Large-format architectural sheets (e.g. ARCH E-size, ~2400x1700 PDF points)
# rasterized at a fixed 300 DPI produce ~10000x7000px images — tens of
# megapixels that can be slow enough to time out the request or exhaust
# Railway's memory. But a flat pixel cap passed to pdf2image's `size` param
# ALWAYS resizes to that dimension — even downscaling a normal A4-ish page
# that was never at risk, which measurably hurts OCR accuracy on already
# low-resolution scans (verified: forcing a 3509x2480 render for an A4 page
# down to 3000x2120 lost text pdftoppm would otherwise have rendered
# clearly). Instead, compute an effective DPI from the page's real point
# dimensions so only genuinely oversized sheets get scaled down.
#
# The cap itself must sit above ordinary scanned-sheet sizes, not just
# "small" ones: standard architectural sheets up to A2 (1684x1191pt) need
# ~7000px on their long side at 300 DPI — a cap of 3000 was silently
# downscaling completely normal A4/A3/A2 scans too, which is exactly the
# real file this was verified against. 8000px covers A2 fully at full
# quality and only trims genuinely oversized A1/A0-and-up sheets.
MAX_RASTER_DIMENSION_PX = 8000
TARGET_DPI = 300


def _effective_dpi(file_bytes: bytes, page_num: int) -> int:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page = pdf.pages[page_num]
            longest_pt = max(page.width, page.height)
    except Exception:
        return TARGET_DPI

    longest_px_at_target = longest_pt / 72 * TARGET_DPI
    if longest_px_at_target <= MAX_RASTER_DIMENSION_PX:
        return TARGET_DPI
    return max(72, int(MAX_RASTER_DIMENSION_PX / (longest_pt / 72)))


def _rasterize_pdf_page(file_bytes: bytes, page_num: int = 0, dpi: Optional[int] = None) -> tuple[Optional[bytes], Optional[str]]:
    """
    Rasterize a single PDF page to a PNG image using pdf2image.
    Requires poppler to be installed as a system package.

    Returns (image_bytes, error_message). error_message is a specific,
    diagnosable string identifying which tool failed and why — never a
    silent None on failure.
    """
    if dpi is None:
        dpi = _effective_dpi(file_bytes, page_num)

    try:
        from pdf2image import convert_from_bytes
        from pdf2image.exceptions import PDFInfoNotInstalledError

        try:
            images = convert_from_bytes(
                file_bytes,
                first_page=page_num + 1,
                last_page=page_num + 1,
                dpi=dpi,
                fmt="png",
            )
        except PDFInfoNotInstalledError as e:
            return None, (
                "Poppler binary not found (pdftoppm/pdfinfo) — check backend "
                f"deployment config: {e}"
            )

        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return buf.getvalue(), None
        return None, f"Poppler returned no pages for page {page_num + 1}."
    except ImportError as e:
        return None, f"pdf2image not installed — check backend requirements.txt: {e}"
    except Exception as e:
        return None, f"PDF rasterization failed on page {page_num + 1}: {e}"


# Tesseract's raw OCR text has no newlines at all (TesseractEngine joins
# words with a single space — see ocr_engine.py), so a name pattern can't
# stop at "\n" the way the vector-text path's title-block regex does. This
# stops at the next recognized label-like word instead, and requires an
# explicit "CLIENT"/"PROJECT NAME"/"BUILDING NAME" keyword — not a bare
# "project"/"owner", which showed up as a false-positive trigger inside
# ordinary legal-boilerplate sentences on a real test file ("...DEVELOPER,
# OWNER FROM THEIR RESPONSIBILITIES...").
_PROJECT_NAME_OCR_RE = re.compile(r"\b(?:CLIENT|PROJECT\s*NAME|BUILDING\s*NAME)\b\s*[:\-]?\s*(.+)", re.IGNORECASE)
_PROJECT_NAME_OCR_STOP_WORDS = {
    "project", "name", "dwg", "date", "drawing", "scale", "checked", "client",
    "architect", "consultant", "sheet", "no", "rev", "revision", "by",
    "from", "the", "their", "under", "for", "and", "is", "was", "of", "to",
}


def _extract_project_name_from_ocr(ocr_text: str) -> Optional[str]:
    """
    Best-effort project/client name recovery from raw OCR text — verified
    directly against a real file (ALL_BASIC_DRAWING.pdf) whose OCR text
    reads "...CLIENT ROYAL LANDMARK HOTEL PROJECT DWG NO DATE..." with no
    punctuation Tesseract could use as a boundary; this recovers "ROYAL
    LANDMARK HOTEL" by stopping at the next label-like word instead.
    """
    m = _PROJECT_NAME_OCR_RE.search(ocr_text)
    if not m:
        return None

    name_words = []
    for w in m.group(1).split()[:8]:
        if w.strip(".,:;-").lower() in _PROJECT_NAME_OCR_STOP_WORDS:
            break
        name_words.append(w)

    if not name_words:
        return None
    name = " ".join(name_words).strip(" .,:-")
    return name[:100] if len(name) >= 3 else None


# Model id is environment-configurable, not hardcoded, because Google
# periodically retires Gemini model ids. Two real retirements hit this
# exact default in the same project: "gemini-2.0-flash" was shut down on
# 2026-06-01, and "gemini-2.5-flash" (this file's next default) started
# 404ing for new API keys before its own announced 2026-10-16 retirement
# date — confirmed directly against a real key via the health-check
# endpoint, with Google's own error naming the replacement: "This model
# models/gemini-2.5-flash is no longer available to new users. Please
# update your code to use models/gemini-3.6-flash". "gemini-3.6-flash" is
# the new default — GEMINI_MODEL lets a deployer bump this forward with an
# env change, not a code change, whenever it happens again.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip() or "gemini-3.6-flash"


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
    image_bytes, raster_error = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = raster_error or "Failed to rasterize PDF page for Gemini"
        return result

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)

        # Structured prompt asking for specific building data. Explicitly
        # asks for the CONTEXT around each dimension/area figure (not just
        # the raw number) — a real test file has a dense sheet full of bare
        # numbers (2.2800, 8.6724, 43.0000, ...) with no per-number label
        # Tesseract's regex path could ever attach meaning to; a vision
        # model that can actually look at table headers/column position can
        # tell "this number is a wall dimension" from "this number is a
        # floor's built-up area" in a way pure OCR text never could.
        prompt = """Analyze this building/architectural drawing image and extract the following information.
Return your answer as a JSON object with these exact keys:

{
  "building_height_m": <number or null>,
  "floor_count": <number or null>,
  "floor_labels": [<list of floor labels like "GF", "F1", "F2" if visible>],
  "room_labels": [<list of room/space labels found>],
  "dimensions": [
    {"text": "<the printed figure, e.g. '12.5 m'>", "context": "<what this number appears to label or sit next to, e.g. 'wall dimension on east elevation', 'value in a table column headed AREA', 'unclear'>"}
  ],
  "scale_note": <string like "1:100" or null if not visible>,
  "project_name": <string or null — the project/building/client name, even if not explicitly labeled "project name" (e.g. a name next to "CLIENT:" or in a title block)>,
  "address_text": <string or null - any address/location text visible>,
  "area_values": [
    {"label": "<what this area value represents, e.g. 'ground floor built-up area', 'plot area', 'unclear'>", "value": <number>, "unit": "sqm", "context": "<e.g. 'row in a table headed AREA STATEMENT', 'unclear'>"}
  ],
  "occupancy_hint": <string describing apparent building use, e.g. "residential", "hotel">,
  "construction_keywords": [<any keywords about construction material visible>],
  "kitchen_visible": <true/false>,
  "sprinkler_visible": <true/false>,
  "basement_levels": <number or null>
}

Only include information you can actually see in the image. Use null for anything not visible,
and "unclear" for context you genuinely cannot determine — never invent a plausible-sounding
label or value for something you cannot actually read.
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
                "dimensions": [
                    d for d in parsed.get("dimensions", [])
                    if isinstance(d, dict) and d.get("text")
                ],
                "scale": parsed.get("scale_note"),
                "project_name": parsed.get("project_name"),
                "address_text": parsed.get("address_text"),
                "areas": [
                    {
                        "value": a["value"],
                        "label": a.get("label", ""),
                        "context": a.get("context"),
                        "source": "gemini_vision",
                    }
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
        error_lower = error_msg.lower()
        # Categorize the real failure reason as specifically as possible —
        # a generic bucket here previously would have hidden exactly the
        # failure mode this pipeline was actually hitting (a decommissioned
        # model id returning a "not found"-style error on every call).
        if "429" in error_msg or "quota" in error_lower or "rate" in error_lower:
            result["error"] = f"Gemini rate limit/quota exceeded — falling through to Tesseract: {error_msg}"
        elif "404" in error_msg or "not found" in error_lower or "not supported" in error_lower or "deprecated" in error_lower:
            result["error"] = (
                f"Gemini model '{GEMINI_MODEL}' not found/deprecated (set GEMINI_MODEL to a "
                f"current model id) — falling through to Tesseract: {error_msg}"
            )
        elif "timeout" in error_lower or "timed out" in error_lower:
            result["error"] = f"Gemini request timed out — falling through to Tesseract: {error_msg}"
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
    image_bytes, raster_error = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = raster_error or "Failed to rasterize PDF page for Tesseract OCR"
        return result

    try:
        import PIL.Image

        pil_image = PIL.Image.open(io.BytesIO(image_bytes))
        # Preprocess (deskew/contrast) then try PSM 3 -> 6 -> 11, scoring
        # each attempt on confidence + garbage-token ratio and stopping
        # early once a result clears the GOOD threshold, instead of always
        # hardcoding PSM 11. PSM 11 ("sparse text: find as much text as
        # possible, no particular order") is still frequently the winner on
        # architectural sheets — scattered labels/tables/callouts with no
        # reading order read far worse under PSM 3's flowing-prose
        # assumption — but it is not universally best, hence a ladder.
        retry_result = run_ocr_with_retry(pil_image, _tesseract_engine)
        ocr_text = retry_result.best.raw_text

        if not retry_result.best.success:
            result["error"] = retry_result.best.error
            return result

        PageIngestionLog(
            document_id="",
            page_index=page_num,
            page_class="scanned",
            extraction_method="ocr",
            ocr_engine=_tesseract_engine.name,
            ocr_config=retry_result.winning_config,
            ocr_confidence=retry_result.best.mean_confidence,
            ocr_retry_count=retry_result.attempt_count,
            quality_score=retry_result.quality_score,
            quality_label=retry_result.quality_label,
        ).emit()

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
            "floor_labels": detect_floor_labels(ocr_text),
            "room_labels": detect_room_labels(ocr_text),
        }

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

        # Project/client name
        project_name = _extract_project_name_from_ocr(ocr_text)
        if project_name:
            data["project_name"] = project_name

        # Kitchen / sprinkler
        if re.search(r"\bkitchen\b", ocr_text, re.IGNORECASE):
            data["kitchen"] = True
        if re.search(r"\bsprinkler", ocr_text, re.IGNORECASE):
            data["sprinklers"] = True

        # Basement — only with clear keyword context, matching the pdfplumber path
        b_match = re.search(r"(\d+)\s*(?:basement|bsmt)\s*(?:level|floor)?s?", ocr_text, re.IGNORECASE)
        if b_match:
            val = int(b_match.group(1))
            if 1 <= val <= 10:
                data["basement_levels"] = val

        result["data"] = data

    except Exception as e:
        result["error"] = f"Tesseract OCR failed: {str(e)}. Ensure tesseract is installed on the system."
        traceback.print_exc()

    return result


def extract_from_scanned_pdf(file_bytes: bytes, page_numbers: Optional[list[int]] = None) -> dict:
    """
    Extract building data from all pages the file router flagged as scanned.

    Tries Gemini (5a) first per page, falls through to Tesseract (5b) on any
    error. Results across pages are merged: the first non-null value found
    for each scalar field wins, and list fields (areas, labels) are combined.

    Args:
        page_numbers: 0-indexed pages to OCR. Defaults to [0] for backward
            compatibility when the caller doesn't know page boundaries.
    """
    if not page_numbers:
        page_numbers = [0]

    combined = {
        "source_stage": "5b_tesseract",  # Updated if Gemini succeeds on any page
        "gemini_attempted": False,
        "gemini_succeeded": False,
        "fallback_reason": None,
        "data": {
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
            "floor_labels": [],
            "room_labels": [],
            "dimensions": [],
        },
        "raw_text_labels": [],
        "warnings": [],
    }

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    gemini_enabled = bool(api_key and api_key != "your-key-here")

    for page_num in page_numbers:
        page_data = None
        page_raw_text = ""

        # ── Stage 5a: Try Gemini first for this page ──
        if gemini_enabled:
            combined["gemini_attempted"] = True
            gemini_result = extract_with_gemini(file_bytes, page_num=page_num)

            if gemini_result["success"]:
                combined["gemini_succeeded"] = True
                combined["source_stage"] = "5a_gemini"
                page_data = gemini_result["data"]
                page_raw_text = gemini_result.get("raw_text", "")
            else:
                combined["fallback_reason"] = gemini_result.get("error", "Unknown Gemini error")
                combined["warnings"].append(
                    f"Page {page_num + 1}: Gemini fallback failed, using Tesseract: "
                    f"{gemini_result.get('error', '')}"
                )

        # ── Stage 5b: Tesseract fallback for this page ──
        if page_data is None:
            tess_result = extract_with_tesseract(file_bytes, page_num=page_num)
            if tess_result["success"]:
                page_data = tess_result["data"]
                page_raw_text = tess_result.get("raw_text", "")
            else:
                combined["warnings"].append(
                    f"Page {page_num + 1}: Tesseract also failed: {tess_result.get('error', '')}"
                )

        if not page_data:
            continue

        combined["raw_text_labels"].extend(page_raw_text.split() if page_raw_text else [])

        cdata = combined["data"]
        for scalar_key in ("height", "floors", "scale", "project_name", "occupancy_hint",
                           "kitchen", "sprinklers", "basement_levels"):
            if not cdata.get(scalar_key) and page_data.get(scalar_key):
                cdata[scalar_key] = page_data[scalar_key]

        cdata["areas"].extend(page_data.get("areas", []))
        cdata["construction_keywords"].extend(page_data.get("construction_keywords", []))
        cdata["floor_labels"].extend(page_data.get("floor_labels", []))
        cdata["room_labels"].extend(page_data.get("room_labels", []))
        cdata["dimensions"].extend(page_data.get("dimensions", []))

    cdata = combined["data"]
    cdata["floor_labels"] = sorted(set(cdata["floor_labels"]))
    cdata["room_labels"] = sorted(set(cdata["room_labels"]))

    return combined

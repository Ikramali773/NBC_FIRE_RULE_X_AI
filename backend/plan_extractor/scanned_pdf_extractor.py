# backend/plan_extractor/scanned_pdf_extractor.py
# Stage 5 — Scanned PDF Fallback chain, tried in order for pages with NO
# real extractable text (pages pdfplumber can already read directly never
# reach any of this):
#
# Stage 5a: Gemini vision       (if GEMINI_API_KEY is set)
# Stage 5b: Groq vision         (if GROQ_API_KEY is set)
# Stage 5c: OpenRouter free vision (if OPENROUTER_API_KEY is set)
# Stage 5d: Mistral OCR         (if MISTRAL_API_KEY is set)
# Stage 5e: Tesseract           (guaranteed final fallback, no key needed)
#
# Every stage falls through to the next on ANY failure (missing key,
# deprecated model, rate limit, timeout, malformed response) with the
# specific real reason logged — never a generic "it failed" message.
# Every AI-provider-sourced value is capped at amber confidence by
# field_mapper.py, never green — a vision/OCR read of a rasterized page is
# never treated as directly-extracted text, regardless of which provider
# produced it.
#
# ONLY invoked for pages the file router flagged as scanned — never for vector PDFs.

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import traceback
from typing import Optional

import requests

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

# Shared by every "smart" vision provider (Gemini, Groq, OpenRouter) — all
# three are general vision-language chat models capable of following a
# custom extraction prompt and returning structured JSON, unlike Mistral's
# dedicated OCR endpoint (which only returns raw extracted text/markdown,
# handled separately via _extract_fields_from_plain_text, the same path
# Tesseract uses). Explicitly asks for the CONTEXT around each
# dimension/area figure (not just the raw number) — a real test file has a
# dense sheet full of bare numbers (2.2800, 8.6724, 43.0000, ...) with no
# per-number label Tesseract's regex path could ever attach meaning to; a
# vision model that can actually look at table headers/column position can
# tell "this number is a wall dimension" from "this number is a floor's
# built-up area" in a way pure OCR text never could.
VISION_EXTRACTION_PROMPT = """Analyze this building/architectural drawing image and extract the following information.
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


def _strip_json_fences(text: str) -> str:
    """Vision models frequently wrap JSON in ```json ... ``` even when told
    not to — strip it defensively rather than letting json.loads fail."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return text.strip()


def _parse_vision_json_data(parsed: dict, source_tag: str) -> dict:
    """Map a parsed VISION_EXTRACTION_PROMPT JSON response into this
    pipeline's common per-page data shape, tagged with which provider
    produced it (source_tag) so it's always traceable downstream — reused
    identically by Gemini, Groq, and OpenRouter so the three "smart"
    providers can never silently drift into different field shapes."""
    return {
        "height": {"value": parsed.get("building_height_m"), "source": source_tag}
        if parsed.get("building_height_m") else None,
        "floors": {"value": parsed.get("floor_count"), "source": source_tag}
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
                "source": source_tag,
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


def _categorize_vision_api_error(
    provider_label: str,
    model_hint: Optional[str],
    error_msg: str,
    config_hint: Optional[str] = None,
) -> str:
    """Categorize a vision-provider API failure as specifically as possible
    — a generic bucket here would hide exactly the failure mode this
    pipeline has actually hit in production (a decommissioned model id
    returning a "not found"-style error on every call). Shared by every
    provider in the chain so a deployer sees the same diagnosable shape of
    message regardless of which one failed. config_hint names the env var
    a deployer can change to fix a dead model id — only meaningful for
    Gemini, whose model is manually pinned via GEMINI_MODEL; Groq/
    OpenRouter's models are auto-discovered at call time instead, so a
    "not found" there means _pick_*_vision_model's fallback logic ran dry,
    not that a config value needs editing."""
    error_lower = error_msg.lower()
    if "429" in error_msg or "quota" in error_lower or "rate" in error_lower:
        return f"{provider_label} rate limit/quota exceeded — falling through to next provider: {error_msg}"
    if "404" in error_msg or "not found" in error_lower or "not supported" in error_lower or "deprecated" in error_lower:
        model_note = f"model '{model_hint}' " if model_hint else "model "
        hint = f" (set {config_hint} to a current model id)" if config_hint else ""
        return (
            f"{provider_label} {model_note}not found/deprecated{hint} — falling through to next provider: {error_msg}"
        )
    if "401" in error_msg or "403" in error_msg or ("invalid" in error_lower and "key" in error_lower):
        return f"{provider_label} API key invalid/revoked — falling through to next provider: {error_msg}"
    if "timeout" in error_lower or "timed out" in error_lower:
        return f"{provider_label} request timed out — falling through to next provider: {error_msg}"
    return f"{provider_label} API error — falling through to next provider: {error_msg}"


def extract_with_gemini(file_bytes: bytes, page_num: int = 0) -> dict:
    """
    Stage 5a — Use Gemini vision API to extract building data from a scanned PDF page.

    Returns a dict with extracted fields. All results are capped at amber confidence.
    Falls through to the next provider on ANY error.
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
        result["error"] = "No Gemini API key set — skipping to next provider"
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

        import PIL.Image
        pil_image = PIL.Image.open(io.BytesIO(image_bytes))

        response = model.generate_content(
            [VISION_EXTRACTION_PROMPT, pil_image],
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2000,
            ),
        )

        response_text = _strip_json_fences(response.text)
        result["raw_text"] = response_text

        try:
            parsed = json.loads(response_text)
            result["success"] = True
            result["data"] = _parse_vision_json_data(parsed, "gemini_vision")
        except json.JSONDecodeError as e:
            result["error"] = f"Failed to parse Gemini response as JSON: {str(e)}"

    except Exception as e:
        result["error"] = _categorize_vision_api_error("Gemini", GEMINI_MODEL, str(e), config_hint="GEMINI_MODEL")
        traceback.print_exc()

    return result


# ── Shared HTTP helper for OpenAI-compatible chat-completions vision APIs ──
# Groq and OpenRouter both document full OpenAI Chat Completions
# compatibility for vision-capable models (image_url content parts, the
# same request/response shape) — one implementation covers both rather
# than writing near-duplicate request-building code per provider.

def _call_openai_compatible_vision(
    base_url: str,
    api_key: str,
    model: str,
    image_bytes: bytes,
    prompt: str,
    extra_headers: Optional[dict] = None,
    use_json_mode: bool = False,
    timeout_s: int = 60,
) -> tuple[Optional[str], Optional[str]]:
    """Returns (response_text, error). use_json_mode requests strict JSON
    output via response_format — only passed when the specific model/
    provider is confirmed to support it (some free/community models
    reject an unsupported response_format outright), otherwise the prompt's
    own "return ONLY the JSON object" instruction carries the same weight
    Gemini's call already relies on."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, default_headers=extra_headers or {}, timeout=timeout_s)
        b64 = base64.b64encode(image_bytes).decode("ascii")

        kwargs = {}
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            max_tokens=2000,
            temperature=0.1,
            **kwargs,
        )
        text = response.choices[0].message.content
        if not text:
            return None, "Empty response content"
        return text, None
    except Exception as e:
        return None, str(e)


# ── Live model discovery for Groq and OpenRouter ──
# Both providers' free/available vision-model lineups have changed before
# without notice (Groq deprecated Llama 4 Scout and Maverick for the free
# tier in 2026 — see _pick_groq_vision_model), so a hardcoded model id is
# a real, recurring outage risk (exactly what happened to this file's
# Gemini default twice). Each call verifies the preferred model is still
# live against the provider's own current listing rather than assuming.
# Short in-process cache avoids one GET /models call per page of a
# multi-page document.
_MODEL_DISCOVERY_CACHE_TTL_S = 600
_groq_model_cache: dict = {"model": None, "error": None, "ts": 0.0}
_openrouter_model_cache: dict = {"model": None, "error": None, "ts": 0.0}

# Groq deprecated its previous vision lineup for the free/dev tier —
# Llama 4 Maverick (2026-03-09) and Llama 4 Scout (2026-06-17) are both
# gone. qwen/qwen3.6-27b is Groq's own documented current replacement
# (confirmed via Groq's docs as of 2026-08): vision+text multimodal,
# supports JSON mode and image_url content, chat.completions endpoint.
_GROQ_PREFERRED_VISION_MODEL = "qwen/qwen3.6-27b"

# OpenRouter free-tier vision model availability rotates; this is the
# current best-documented free, vision-capable, document-OCR-competent
# choice as of 2026-08 (confirmed live on OpenRouter's public model list).
_OPENROUTER_PREFERRED_FREE_VISION_MODEL = "qwen/qwen2.5-vl-72b-instruct:free"


def _pick_groq_vision_model(api_key: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (model_id, error). Confirms the preferred model id is still
    present in Groq's live model list before using it."""
    now = time.time()
    if _groq_model_cache["model"] and now - _groq_model_cache["ts"] < _MODEL_DISCOVERY_CACHE_TTL_S:
        return _groq_model_cache["model"], None

    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        ids = {m.get("id") for m in resp.json().get("data", [])}
    except Exception as e:
        return None, f"Failed to fetch Groq's current model list: {e}"

    if _GROQ_PREFERRED_VISION_MODEL in ids:
        _groq_model_cache.update(model=_GROQ_PREFERRED_VISION_MODEL, error=None, ts=now)
        return _GROQ_PREFERRED_VISION_MODEL, None

    # Preferred model no longer listed — look for any other plausibly
    # vision-capable id rather than failing outright on a rename/rotation.
    for candidate in ids:
        if candidate and any(hint in candidate.lower() for hint in ("vl", "vision", "qwen", "scout", "maverick")):
            _groq_model_cache.update(model=candidate, error=None, ts=now)
            return candidate, None

    return None, (
        f"Preferred model '{_GROQ_PREFERRED_VISION_MODEL}' is no longer listed by Groq, and no other "
        f"vision-hinted model was found among {len(ids)} currently listed models"
    )


def _pick_openrouter_free_vision_model() -> tuple[Optional[str], Optional[str]]:
    """Returns (model_id, error). Filters OpenRouter's public (no-auth-
    required) model listing for a currently free, image-input-capable
    model, preferring the documented default if it's still listed."""
    now = time.time()
    if _openrouter_model_cache["model"] and now - _openrouter_model_cache["ts"] < _MODEL_DISCOVERY_CACHE_TTL_S:
        return _openrouter_model_cache["model"], None

    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        resp.raise_for_status()
        models = resp.json().get("data", [])
    except Exception as e:
        return None, f"Failed to fetch OpenRouter's current model list: {e}"

    by_id = {m.get("id"): m for m in models}
    if _OPENROUTER_PREFERRED_FREE_VISION_MODEL in by_id:
        _openrouter_model_cache.update(model=_OPENROUTER_PREFERRED_FREE_VISION_MODEL, error=None, ts=now)
        return _OPENROUTER_PREFERRED_FREE_VISION_MODEL, None

    for m in models:
        model_id = m.get("id") or ""
        pricing = m.get("pricing") or {}
        modality = ((m.get("architecture") or {}).get("modality") or "")
        is_free = model_id.endswith(":free") or pricing.get("prompt") == "0"
        supports_image = "image" in modality
        if is_free and supports_image:
            _openrouter_model_cache.update(model=model_id, error=None, ts=now)
            return model_id, None

    return None, f"No free, image-input-capable model currently listed among {len(models)} OpenRouter models"


def extract_with_groq(file_bytes: bytes, page_num: int = 0) -> dict:
    """Stage 5b — Groq vision, tried after Gemini. Same structured-JSON
    request/response shape as Gemini (_parse_vision_json_data), tagged
    "groq_vision" so it's always traceable which provider actually answered."""
    result = {"success": False, "source_stage": "5b_groq", "data": {}, "raw_text": "", "error": None}

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key or api_key == "your-key-here":
        result["error"] = "No Groq API key set — skipping to next provider"
        return result

    image_bytes, raster_error = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = raster_error or "Failed to rasterize PDF page for Groq"
        return result

    model, model_error = _pick_groq_vision_model(api_key)
    if not model:
        result["error"] = f"No usable Groq vision model available — {model_error}"
        return result

    response_text, call_error = _call_openai_compatible_vision(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        model=model,
        image_bytes=image_bytes,
        prompt=VISION_EXTRACTION_PROMPT,
        use_json_mode=True,  # qwen/qwen3.6-27b on Groq documents JSON mode support
    )
    if call_error:
        result["error"] = _categorize_vision_api_error("Groq", model, call_error)
        return result

    response_text = _strip_json_fences(response_text)
    result["raw_text"] = response_text
    try:
        parsed = json.loads(response_text)
        result["success"] = True
        result["data"] = _parse_vision_json_data(parsed, "groq_vision")
    except json.JSONDecodeError as e:
        result["error"] = f"Failed to parse Groq response as JSON: {str(e)}"

    return result


def extract_with_openrouter(file_bytes: bytes, page_num: int = 0) -> dict:
    """Stage 5c — OpenRouter free vision model, tried after Groq. Same
    structured-JSON shape, tagged "openrouter_vision". JSON mode is NOT
    requested here (unlike Groq) since the underlying free model varies by
    availability and not all of them reliably support response_format —
    the prompt's own "return ONLY the JSON object" instruction is relied
    on instead, same as Gemini."""
    result = {"success": False, "source_stage": "5c_openrouter", "data": {}, "raw_text": "", "error": None}

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key or api_key == "your-key-here":
        result["error"] = "No OpenRouter API key set — skipping to next provider"
        return result

    image_bytes, raster_error = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = raster_error or "Failed to rasterize PDF page for OpenRouter"
        return result

    model, model_error = _pick_openrouter_free_vision_model()
    if not model:
        result["error"] = f"No usable OpenRouter free vision model available — {model_error}"
        return result

    response_text, call_error = _call_openai_compatible_vision(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        model=model,
        image_bytes=image_bytes,
        prompt=VISION_EXTRACTION_PROMPT,
        extra_headers={
            "HTTP-Referer": "https://github.com/Ikramali773/NBC_FIRE_RULE_X_AI",
            "X-Title": "FireRuleX",
        },
        use_json_mode=False,
    )
    if call_error:
        result["error"] = _categorize_vision_api_error("OpenRouter", model, call_error)
        return result

    response_text = _strip_json_fences(response_text)
    result["raw_text"] = response_text
    try:
        parsed = json.loads(response_text)
        result["success"] = True
        result["data"] = _parse_vision_json_data(parsed, "openrouter_vision")
    except json.JSONDecodeError as e:
        result["error"] = f"Failed to parse OpenRouter response as JSON: {str(e)}"

    return result


_MISTRAL_OCR_MODEL = os.environ.get("MISTRAL_OCR_MODEL", "mistral-ocr-latest").strip() or "mistral-ocr-latest"


def extract_with_mistral(file_bytes: bytes, page_num: int = 0) -> dict:
    """
    Stage 5d — Mistral OCR, tried after OpenRouter and before Tesseract.

    Unlike Gemini/Groq/OpenRouter, Mistral's OCR endpoint is a dedicated
    document-OCR API (POST /v1/ocr) — it returns raw extracted text/markdown
    per page, not custom-prompted structured JSON, so its output is parsed
    the same way Tesseract's raw OCR text is (_extract_fields_from_plain_text)
    rather than via _parse_vision_json_data. This is deliberately the LAST
    AI provider before Tesseract: it's purpose-built for document OCR and
    is the one most likely to read dense, degraded, small-print content
    (e.g. area/FSI tables on scanned government-approved plans) better than
    a general vision chat model or Tesseract can.
    """
    result = {"success": False, "source_stage": "5d_mistral", "data": {}, "raw_text": "", "error": None}

    api_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not api_key or api_key == "your-key-here":
        result["error"] = "No Mistral API key set — skipping to Tesseract fallback"
        return result

    image_bytes, raster_error = _rasterize_pdf_page(file_bytes, page_num)
    if not image_bytes:
        result["error"] = raster_error or "Failed to rasterize PDF page for Mistral OCR"
        return result

    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = requests.post(
            "https://api.mistral.ai/v1/ocr",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _MISTRAL_OCR_MODEL,
                "document": {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
            },
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        result["error"] = _categorize_vision_api_error("Mistral OCR", _MISTRAL_OCR_MODEL, str(e))
        return result

    pages = payload.get("pages") or []
    if not pages:
        result["error"] = "Mistral OCR returned no pages in its response"
        return result

    # A single rasterized page image is submitted, so exactly one page is
    # expected back — join defensively in case the API ever splits it.
    ocr_text = "\n".join((p.get("markdown") or p.get("text") or "") for p in pages).strip()
    if not ocr_text:
        result["error"] = "Mistral OCR returned an empty page"
        return result

    result["raw_text"] = ocr_text
    result["success"] = True
    result["data"] = _extract_fields_from_plain_text(ocr_text, source_tag="mistral_ocr")
    return result


def _extract_fields_from_plain_text(ocr_text: str, source_tag: str) -> dict:
    """
    Basic keyword/regex matching over raw OCR'd text — no semantic
    understanding, can only report what's literally adjacent to a
    recognized keyword. Shared by Tesseract and Mistral OCR (both return
    plain extracted text rather than custom-prompted structured JSON,
    unlike Gemini/Groq/OpenRouter's _parse_vision_json_data path).
    source_tag distinguishes which OCR engine actually produced the text
    downstream (e.g. "tesseract_ocr" vs "mistral_ocr").
    """
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
            data["height"] = {"value": val, "source": source_tag}

    # Floors
    f_match = re.search(r"(\d+)\s*(?:floors?|storeys?)", ocr_text, re.IGNORECASE)
    if f_match:
        val = int(f_match.group(1))
        if 1 <= val <= 200:
            data["floors"] = {"value": val, "source": source_tag}

    # Areas — only with clear keyword
    for m in re.finditer(r"(?:area)\s*[=:]\s*(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)?", ocr_text, re.IGNORECASE):
        val = float(m.group(1))
        if 5.0 <= val <= 100000.0:
            data["areas"].append({"value": val, "label": "ocr_area", "source": source_tag})

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

    return data


def extract_with_tesseract(file_bytes: bytes, page_num: int = 0) -> dict:
    """
    Stage 5e — Use pytesseract to OCR a scanned PDF page.

    This is the guaranteed fallback — no API key needed, always works even
    if all four AI providers are unconfigured or fail.
    No semantic understanding — can only report raw text strings.
    """
    result = {
        "success": False,
        "source_stage": "5e_tesseract",
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
        result["data"] = _extract_fields_from_plain_text(ocr_text, source_tag="tesseract_ocr")

    except Exception as e:
        result["error"] = f"Tesseract OCR failed: {str(e)}. Ensure tesseract is installed on the system."
        traceback.print_exc()

    return result


# Ordered fallback chain: (source_stage id, human label, required env var
# or None if no key is needed, extraction function). Tried in this exact
# order per page, stopping at the first one that succeeds. Tesseract has no
# env var gate — it's always attempted last, guaranteeing the chain always
# produces SOME result even with zero API keys configured.
_PROVIDER_CHAIN = [
    ("5a_gemini", "Gemini", "GEMINI_API_KEY", extract_with_gemini),
    ("5b_groq", "Groq", "GROQ_API_KEY", extract_with_groq),
    ("5c_openrouter", "OpenRouter", "OPENROUTER_API_KEY", extract_with_openrouter),
    ("5d_mistral", "Mistral OCR", "MISTRAL_API_KEY", extract_with_mistral),
    ("5e_tesseract", "Tesseract", None, extract_with_tesseract),
]


def _provider_key_configured(env_var: Optional[str]) -> bool:
    if env_var is None:
        return True
    key = os.environ.get(env_var, "").strip()
    return bool(key and key != "your-key-here")


def extract_from_scanned_pdf(file_bytes: bytes, page_numbers: Optional[list[int]] = None) -> dict:
    """
    Extract building data from all pages the file router flagged as scanned.

    Tries each provider in _PROVIDER_CHAIN in order per page — Gemini ->
    Groq -> OpenRouter -> Mistral OCR -> Tesseract — stopping at the first
    one that succeeds. A provider with no key configured is skipped
    silently (no warning noise for the common all-keys-blank case); a
    provider that WAS attempted (key present) but failed logs the specific
    real reason and falls through. Results across pages are merged: the
    first non-null value found for each scalar field wins, and list fields
    (areas, labels) are combined.

    Args:
        page_numbers: 0-indexed pages to OCR. Defaults to [0] for backward
            compatibility when the caller doesn't know page boundaries.
    """
    if not page_numbers:
        page_numbers = [0]

    combined = {
        "source_stage": "5e_tesseract",  # Updated to whichever provider actually answers
        "gemini_attempted": False,
        "gemini_succeeded": False,
        "fallback_reason": None,
        "provider_usage": {label: {"attempted": 0, "succeeded": 0} for _, label, _, _ in _PROVIDER_CHAIN},
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

    for page_num in page_numbers:
        page_data = None
        page_raw_text = ""

        for stage_id, label, env_var, extract_fn in _PROVIDER_CHAIN:
            if not _provider_key_configured(env_var):
                continue

            if label == "Gemini":
                combined["gemini_attempted"] = True
            combined["provider_usage"][label]["attempted"] += 1

            provider_result = extract_fn(file_bytes, page_num=page_num)

            if provider_result["success"]:
                combined["provider_usage"][label]["succeeded"] += 1
                combined["source_stage"] = stage_id
                page_data = provider_result["data"]
                page_raw_text = provider_result.get("raw_text", "")
                if label == "Gemini":
                    combined["gemini_succeeded"] = True
                break

            reason = provider_result.get("error", f"Unknown {label} error")
            if label == "Gemini":
                combined["fallback_reason"] = reason
            combined["warnings"].append(f"Page {page_num + 1}: {label} failed: {reason}")

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

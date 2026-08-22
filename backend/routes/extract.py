# backend/routes/extract.py
# POST /api/extract       — Extract building data from PDF/DWG file
# GET  /api/extract/health-check — Verify Gemini/Groq/OpenRouter/Mistral keys
#
# This route is part of the new plan extraction module.
# It does NOT touch engine.py, rule_engine.py, or any rules/*.json.

from __future__ import annotations

import os
import requests
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from plan_extractor.pipeline import run_extraction
from plan_extractor.scanned_pdf_extractor import GEMINI_MODEL

router = APIRouter()

# Every provider check below is a metadata/listing call, never a generation
# call — zero token cost, so this endpoint can be hit freely without
# worrying about quota, per the requirement that it "must not consume
# meaningful quota."
_HEALTH_CHECK_TIMEOUT_S = 8

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB (DWG files can be large)


@router.post("/api/extract")
async def extract_building_plan(file: UploadFile = File(...)):
    """
    Extract building parameters from a PDF or DWG building plan.

    Returns structured extraction data with confidence indicators
    for the frontend review popup.
    """
    try:
        # Validate file
        if not file.filename:
            return JSONResponse(
                content={"error": "No file provided."},
                status_code=400,
            )

        ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
        if ext not in ("pdf", "dwg"):
            return JSONResponse(
                content={"error": f"Unsupported file type '.{ext}'. Only .pdf and .dwg files are accepted."},
                status_code=400,
            )

        # Read file bytes
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            return JSONResponse(
                content={
                    "error": f"File too large ({len(content) / 1024 / 1024:.1f}MB). Maximum is 20MB."
                },
                status_code=400,
            )

        if len(content) == 0:
            return JSONResponse(
                content={"error": "File is empty."},
                status_code=400,
            )

        # Run the extraction pipeline
        result = run_extraction(content, file.filename)

        if not result["success"]:
            return JSONResponse(
                content={
                    "error": result.get("error", "Extraction failed."),
                    "warnings": result.get("warnings", []),
                },
                status_code=422,
            )

        return JSONResponse(
            content={
                "success": True,
                "data": result["data"],
                "warnings": result.get("warnings", []),
            },
        )

    except Exception as err:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            content={"error": f"Internal server error during extraction: {str(err)}"},
            status_code=500,
        )


@router.get("/api/extract/health-check")
async def extraction_health_check():
    """
    Health check for the extraction module.

    If a Gemini API key is present, makes one minimal API call
    to verify the key is valid. Does NOT consume meaningful quota.
    """
    health = {
        "extraction_module": "ok",
        "pdfplumber": "unknown",
        "ezdxf": "unknown",
        "dwg2dxf": "unknown",
        "pdf2image": "unknown",
        "tesseract": "unknown",
        "gemini": "unconfigured",
        "gemini_model": GEMINI_MODEL,
        "groq": "unconfigured",
        "openrouter": "unconfigured",
        "mistral": "unconfigured",
    }

    # ── Check pdfplumber ──
    try:
        import pdfplumber
        health["pdfplumber"] = f"ok (v{pdfplumber.__version__})"
    except ImportError:
        health["pdfplumber"] = "not installed"

    # ── Check ezdxf ──
    try:
        import ezdxf
        health["ezdxf"] = f"ok (v{ezdxf.__version__})"
    except ImportError:
        health["ezdxf"] = "not installed"

    # ── Check dwg2dxf ──
    try:
        from plan_extractor.dwg_converter import _find_dwg2dxf
        path = _find_dwg2dxf()
        health["dwg2dxf"] = f"ok ({path})" if path else "not found on PATH"
    except Exception as e:
        health["dwg2dxf"] = f"error: {str(e)}"

    # ── Check pdf2image ──
    try:
        import pdf2image
        health["pdf2image"] = "ok"
    except ImportError:
        health["pdf2image"] = "not installed"

    # ── Check tesseract ──
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        health["tesseract"] = f"ok (v{version})"
    except Exception as e:
        health["tesseract"] = f"not available: {str(e)}"

    # ── Check Gemini ──
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key and api_key != "your-key-here":
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(GEMINI_MODEL)
            # Minimal text-only call — does not use vision or process any file
            response = model.generate_content(
                "Reply with exactly: OK",
                generation_config=genai.GenerationConfig(
                    temperature=0,
                    max_output_tokens=5,
                ),
            )
            if response and response.text:
                health["gemini"] = "ok (key valid, API responding)"
            else:
                health["gemini"] = "warning (key present but empty response)"
        except Exception as e:
            health["gemini"] = f"error (key present but API call failed: {str(e)})"
    else:
        health["gemini"] = "unconfigured (no key — Tesseract-only mode)"

    # ── Check Groq — GET /models is a metadata listing call, zero token cost ──
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key and groq_key != "your-key-here":
        try:
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {groq_key}"},
                timeout=_HEALTH_CHECK_TIMEOUT_S,
            )
            if resp.status_code == 200:
                count = len(resp.json().get("data", []))
                health["groq"] = f"ok (key valid, {count} model(s) listed)"
            elif resp.status_code == 401:
                health["groq"] = "error (401 — key invalid or revoked)"
            else:
                health["groq"] = f"error (HTTP {resp.status_code}: {resp.text[:200]})"
        except Exception as e:
            health["groq"] = f"error (request failed: {str(e)})"
    else:
        health["groq"] = "unconfigured (no key — falls through to next provider)"

    # ── Check OpenRouter — GET /key reports the key's own credit/rate info ──
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter_key and openrouter_key != "your-key-here":
        try:
            resp = requests.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {openrouter_key}"},
                timeout=_HEALTH_CHECK_TIMEOUT_S,
            )
            if resp.status_code == 200:
                health["openrouter"] = "ok (key valid, API responding)"
            elif resp.status_code == 401:
                health["openrouter"] = "error (401 — key invalid or revoked)"
            else:
                health["openrouter"] = f"error (HTTP {resp.status_code}: {resp.text[:200]})"
        except Exception as e:
            health["openrouter"] = f"error (request failed: {str(e)})"
    else:
        health["openrouter"] = "unconfigured (no key — falls through to next provider)"

    # ── Check Mistral — GET /models is a metadata listing call, zero token cost ──
    mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if mistral_key and mistral_key != "your-key-here":
        try:
            resp = requests.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {mistral_key}"},
                timeout=_HEALTH_CHECK_TIMEOUT_S,
            )
            if resp.status_code == 200:
                count = len(resp.json().get("data", []))
                health["mistral"] = f"ok (key valid, {count} model(s) listed)"
            elif resp.status_code == 401:
                health["mistral"] = "error (401 — key invalid or revoked)"
            else:
                health["mistral"] = f"error (HTTP {resp.status_code}: {resp.text[:200]})"
        except Exception as e:
            health["mistral"] = f"error (request failed: {str(e)})"
    else:
        health["mistral"] = "unconfigured (no key — falls through to Tesseract)"

    return JSONResponse(content=health)

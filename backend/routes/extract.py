# backend/routes/extract.py
# POST /api/extract       — Extract building data from PDF/DWG file
# GET  /api/extract/health-check — Verify Gemini API key
#
# This route is part of the new plan extraction module.
# It does NOT touch engine.py, rule_engine.py, or any rules/*.json.

from __future__ import annotations

import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from plan_extractor.pipeline import run_extraction

router = APIRouter()

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
            model = genai.GenerativeModel("gemini-2.0-flash")
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

    return JSONResponse(content=health)

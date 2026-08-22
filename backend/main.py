# backend/main.py
# FastAPI Application Entry Point
#
# Runs on port 8000 with CORS enabled for Next.js frontend (port 3000).
# Mounts all API routes under /api/*.

import os
import shutil
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _check_ocr_dependencies() -> None:
    """
    Verify Tesseract and Poppler are actually installed and runnable on this
    host. Both are system-level packages that `pip install` does not
    provide — pytesseract/pdf2image import fine even when the underlying
    binaries are missing, so failures otherwise only surface later when a
    real file is uploaded. Logging this at boot makes that failure mode
    immediately visible in deployment logs instead.
    """
    missing = []

    tesseract_path = shutil.which("tesseract")
    if tesseract_path is None:
        missing.append("tesseract (binary not found on PATH)")
    else:
        try:
            subprocess.run(
                ["tesseract", "--version"],
                capture_output=True,
                timeout=10,
            )
        except Exception as e:
            missing.append(f"tesseract (found on PATH but failed to run: {e})")

    poppler_path = shutil.which("pdftoppm")
    if poppler_path is None:
        missing.append("poppler/pdftoppm (binary not found on PATH)")
    else:
        try:
            # pdftoppm -v exits non-zero on some poppler builds even when
            # working correctly, so just confirm the process launches.
            subprocess.run(
                ["pdftoppm", "-v"],
                capture_output=True,
                timeout=10,
            )
        except Exception as e:
            missing.append(f"poppler/pdftoppm (found on PATH but failed to run: {e})")

    if missing:
        print("━" * 60)
        print(f"  OCR dependencies: MISSING — {'; '.join(missing)}")
        print("  Check deployment config (e.g. backend/nixpacks.toml on Railway).")
        print("━" * 60)
    else:
        print("━" * 60)
        print("  OCR dependencies: READY")
        print("━" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup: Verify Tesseract + Poppler are installed and runnable ──
    _check_ocr_dependencies()

    # ── Startup: Log Gemini API key status ──
    from plan_extractor.scanned_pdf_extractor import GEMINI_MODEL

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key and gemini_key != "your-key-here":
        print("━" * 60)
        print(f"  Gemini vision fallback: ENABLED (key found, model={GEMINI_MODEL})")
        print("━" * 60)
    else:
        print("━" * 60)
        print("  Gemini vision fallback: DISABLED (no key set —")
        print("  using Tesseract-only OCR fallback for scanned pages)")
        print("━" * 60)

    # ── Startup: Log Groq / OpenRouter / Mistral key status ──
    # Same ENABLED/DISABLED pattern as Gemini above, one line per provider,
    # so the full fallback chain's live status is visible from the
    # deployment log alone — no file upload needed to check.
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    print("━" * 60)
    if groq_key and groq_key != "your-key-here":
        print("  Groq vision fallback: ENABLED (key found)")
    else:
        print("  Groq vision fallback: DISABLED (no key)")
    print("━" * 60)

    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    print("━" * 60)
    if openrouter_key and openrouter_key != "your-key-here":
        print("  OpenRouter vision fallback: ENABLED (key found)")
    else:
        print("  OpenRouter vision fallback: DISABLED (no key)")
    print("━" * 60)

    mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    print("━" * 60)
    if mistral_key and mistral_key != "your-key-here":
        print("  Mistral OCR fallback: ENABLED (key found)")
    else:
        print("  Mistral OCR fallback: DISABLED (no key)")
    print("━" * 60)

    yield


from routes.analyze import router as analyze_router
from routes.analyze_manual import router as analyze_manual_router
from routes.analyze_simple import router as analyze_simple_router
from routes.analyze_mixed import router as analyze_mixed_router
from routes.report_pdf import router as report_pdf_router
from routes.extract import router as extract_router
from routes.placement import router as placement_router

app = FastAPI(
    title="FireRuleX API",
    description="AI-powered fire extinguisher compliance checker (IS 2190:2024 & NBC 2016 Part IV)",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS: allow Next.js frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(analyze_router)
app.include_router(analyze_manual_router)
app.include_router(analyze_simple_router)
app.include_router(analyze_mixed_router)
app.include_router(report_pdf_router)
app.include_router(extract_router)
app.include_router(placement_router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "FireRuleX API", "version": "0.3.0"}

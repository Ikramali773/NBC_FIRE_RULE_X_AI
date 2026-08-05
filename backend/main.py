# backend/main.py
# FastAPI Application Entry Point
#
# Runs on port 8000 with CORS enabled for Next.js frontend (port 3000).
# Mounts all API routes under /api/*.

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup: Log Gemini API key status ──
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key and gemini_key != "your-key-here":
        print("━" * 60)
        print("  Gemini vision fallback: ENABLED (key found)")
        print("━" * 60)
    else:
        print("━" * 60)
        print("  Gemini vision fallback: DISABLED (no key set —")
        print("  using Tesseract-only OCR fallback for scanned pages)")
        print("━" * 60)
    yield


from routes.analyze import router as analyze_router
from routes.analyze_manual import router as analyze_manual_router
from routes.analyze_simple import router as analyze_simple_router
from routes.analyze_mixed import router as analyze_mixed_router
from routes.report_pdf import router as report_pdf_router
from routes.extract import router as extract_router

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


@app.get("/")
async def root():
    return {"status": "ok", "service": "FireRuleX API", "version": "0.3.0"}

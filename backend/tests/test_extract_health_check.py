# backend/tests/test_extract_health_check.py
# Regression test for GET /api/extract/health-check's Poppler check.
#
# Real-world bug this guards against: pdf2image (the Python package)
# importing successfully does NOT mean the pdftoppm/pdfinfo binaries it
# wraps are actually installed. A real deployment reported health-check
# showing "pdf2image: ok" while every Stage 5 provider (Gemini, Groq,
# OpenRouter, Mistral OCR, Tesseract) failed identically with "Poppler
# binary not found" on the very first real extraction — the health-check
# gave no warning of this. poppler is now checked as its own real
# subprocess-level check, independent of the pdf2image package check.

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.extract import router as extract_router


def _client():
    app = FastAPI()
    app.include_router(extract_router)
    return TestClient(app)


class TestPopplerHealthCheck:
    def test_reports_ok_when_pdftoppm_on_path(self, monkeypatch):
        import routes.extract as route_module
        monkeypatch.setattr(route_module.shutil, "which", lambda cmd: "/usr/bin/pdftoppm" if cmd == "pdftoppm" else None)
        monkeypatch.setattr(route_module.subprocess, "run", lambda *a, **k: None)

        resp = _client().get("/api/extract/health-check")
        assert resp.status_code == 200
        assert resp.json()["poppler"].startswith("ok (")

    def test_reports_not_found_when_pdftoppm_missing(self, monkeypatch):
        """Regression: this exact scenario reported 'pdf2image: ok' while
        poppler was genuinely missing on a real deployment — this field
        must independently and clearly say so."""
        import routes.extract as route_module
        monkeypatch.setattr(route_module.shutil, "which", lambda cmd: None)

        resp = _client().get("/api/extract/health-check")
        assert resp.status_code == 200
        data = resp.json()
        assert "not found on PATH" in data["poppler"]
        # pdf2image (the Python package) is a separate, independent check —
        # it must not silently mask a missing poppler binary as "ok".
        assert "package only" in data["pdf2image"]

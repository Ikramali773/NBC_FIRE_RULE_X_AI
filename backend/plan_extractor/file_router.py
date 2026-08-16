# backend/plan_extractor/file_router.py
# Stage 1 — File Router
#
# Detects whether input is PDF or DWG.
# For PDF, detects vector (has extractable text layer) vs scanned (no text).

from __future__ import annotations

import io
import tempfile
from enum import Enum
from pathlib import Path
from typing import Optional

import pdfplumber


class FileType(str, Enum):
    VECTOR_PDF = "vector_pdf"
    SCANNED_PDF = "scanned_pdf"
    DWG = "dwg"
    UNKNOWN = "unknown"


class RouteResult:
    """Result of file routing — tells the pipeline which extraction path to use."""

    def __init__(
        self,
        file_type: FileType,
        file_bytes: bytes,
        temp_path: Optional[Path] = None,
        error: Optional[str] = None,
        page_types: Optional[list[str]] = None,
    ):
        self.file_type = file_type
        self.file_bytes = file_bytes
        self.temp_path = temp_path
        self.error = error
        # Per-page classification for multi-page PDFs
        self.page_types = page_types or []


def _is_dwg(data: bytes) -> bool:
    """Check DWG magic bytes: files start with 'AC10' or similar."""
    return data[:4].startswith(b"AC10") or data[:2] == b"AC"


def _is_pdf(data: bytes) -> bool:
    """Check PDF magic bytes."""
    return data[:5] == b"%PDF-"


# Some CAD-to-PDF exporters flatten text to outlined vector paths (no real
# text objects at all) while still drawing real wall/dimension geometry —
# a page like that has zero extractable text but thousands of lines/curves.
# Routing it to OCR anyway is both wrong (there's nothing scanned/rasterized
# to read) and dangerous: OCR rasterizes every such page at high DPI, which
# for a real multi-page CAD sheet can be slow/memory-heavy enough to crash
# or time out the request. A page with substantial vector geometry is
# "vector" regardless of text length — actually verified against a real
# 7-page, zero-text-layer CAD export that was previously mis-routed to OCR.
MIN_VECTOR_PATHS_FOR_VECTOR_PAGE = 200


def _classify_pdf_page(page) -> str:
    """Classify a single PDF page as vector or scanned."""
    text = (page.extract_text() or "").strip()
    if len(text) >= 10:
        return "vector"

    path_count = len(page.lines or []) + len(page.rects or []) + len(page.curves or [])
    if path_count >= MIN_VECTOR_PATHS_FOR_VECTOR_PAGE:
        return "vector"

    return "scanned"


def route_file(file_bytes: bytes, filename: str) -> RouteResult:
    """
    Route an uploaded file to the correct extraction pipeline.

    Returns a RouteResult with file_type indicating which extractor to use.
    """
    ext = Path(filename).suffix.lower()

    # ── DWG detection ──
    if ext == ".dwg" or _is_dwg(file_bytes):
        return RouteResult(
            file_type=FileType.DWG,
            file_bytes=file_bytes,
        )

    # ── PDF detection ──
    if ext == ".pdf" or _is_pdf(file_bytes):
        try:
            pdf_io = io.BytesIO(file_bytes)
            with pdfplumber.open(pdf_io) as pdf:
                if len(pdf.pages) == 0:
                    return RouteResult(
                        file_type=FileType.UNKNOWN,
                        file_bytes=file_bytes,
                        error="PDF has no pages.",
                    )

                page_types = []
                vector_pages = 0
                scanned_pages = 0

                for page in pdf.pages:
                    ptype = _classify_pdf_page(page)
                    page_types.append(ptype)
                    if ptype == "vector":
                        vector_pages += 1
                    else:
                        scanned_pages += 1

                # If majority of pages are vector, classify as vector PDF
                if vector_pages >= scanned_pages:
                    file_type = FileType.VECTOR_PDF
                else:
                    file_type = FileType.SCANNED_PDF

                return RouteResult(
                    file_type=file_type,
                    file_bytes=file_bytes,
                    page_types=page_types,
                )
        except Exception as e:
            return RouteResult(
                file_type=FileType.UNKNOWN,
                file_bytes=file_bytes,
                error=f"Failed to read PDF: {str(e)}",
            )

    # ── Unknown format ──
    return RouteResult(
        file_type=FileType.UNKNOWN,
        file_bytes=file_bytes,
        error=f"Unsupported file type: {ext}. Only .pdf and .dwg files are accepted.",
    )

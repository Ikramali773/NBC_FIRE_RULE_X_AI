# backend/plan_extractor/page_quality.py
# Page inspection and classification (per the NBC ingestion architecture scope).
#
# Replaces a single character-count threshold with a weighted combination of
# signals: text-layer presence/density, garbage-character ratio, image count,
# and vector-path density. "Do not use a single character-count threshold.
# Compute a configurable quality score and combine multiple signals."
#
# Also provides the GOOD/REVIEW/BAD quality-score banding used elsewhere
# (OCR retry selection, per-page diagnostics/logging).

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class PageClass(str, Enum):
    NATIVE_TEXT = "native_text"
    SCANNED = "scanned"
    MIXED = "mixed"
    POOR_TEXT = "poor_text"
    IMAGE_ONLY = "image_only"


# Real CAD-to-PDF exports can flatten text to outlined vector paths with
# zero real text objects — a page can have thousands of real lines/curves
# and still read as empty text. Routing such a page to OCR anyway is both
# wrong (nothing was actually scanned) and dangerous (OCR rasterizes at
# high DPI, which for a large real sheet can be slow/memory-heavy enough
# to crash a request) — verified against a real 7-page CAD export
# (ALL_BASIC_DRAWING.pdf) that was previously misrouted entirely to OCR.
MIN_VECTOR_PATHS_FOR_STRUCTURAL_CONTENT = 200

# Matches the previous single-threshold behavior's cutover point exactly
# (kept identical on purpose, for backward compatibility with existing
# extraction behavior) — the actual improvement here is combining this
# with the garbage-ratio and geometry signals below, not moving the bar.
MIN_CHARS_FOR_NATIVE_TEXT = 10

# A text layer dominated by control/replacement characters indicates a
# broken encoding or font-substitution artifact, not usable text — even
# if the character count alone looks "native".
MAX_GARBAGE_CHAR_RATIO = 0.15

_GARBAGE_CHARS_RE = re.compile(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]")

# GOOD/REVIEW/BAD quality bands (scope §13) — initial heuristics, not
# universal truth. Kept as module constants so they're easy to retune.
QUALITY_GOOD_THRESHOLD = 0.90
QUALITY_REVIEW_THRESHOLD = 0.75


@dataclass
class PageSignals:
    text_len: int
    image_count: int
    vector_path_count: int
    garbage_char_ratio: float
    page_area_pt2: float
    text_density: float  # chars per 1000 pt^2 — scale-independent "how text-heavy is this page"


def compute_page_signals(page) -> PageSignals:
    text = page.extract_text() or ""
    text_len = len(text)
    garbage = len(_GARBAGE_CHARS_RE.findall(text))
    garbage_ratio = (garbage / text_len) if text_len else 0.0

    vector_path_count = len(page.lines or []) + len(page.rects or []) + len(page.curves or [])
    image_count = len(page.images or [])
    page_area = float(page.width) * float(page.height)
    text_density = (text_len / page_area * 1000) if page_area else 0.0

    return PageSignals(
        text_len=text_len,
        image_count=image_count,
        vector_path_count=vector_path_count,
        garbage_char_ratio=garbage_ratio,
        page_area_pt2=page_area,
        text_density=text_density,
    )


def classify_page(page) -> tuple[PageClass, PageSignals]:
    """
    Classify a page by combining multiple signals rather than one threshold.

      NATIVE_TEXT — a usable text layer exists; native extraction alone is
        reliable, regardless of how much vector geometry is also present.
      POOR_TEXT — some text exists but is dominated by garbage/replacement
        characters (broken encoding) — not trustworthy alone.
      MIXED — no usable text layer, but substantial real vector geometry
        (thousands of lines/curves) — likely a CAD page with text flattened
        to outlined paths. Run BOTH native extraction and OCR and merge;
        neither alone is guaranteed sufficient.
      IMAGE_ONLY — no usable text, no structural geometry, but an embedded
        raster image — a genuine scan/photograph.
      SCANNED — none of the above (e.g. a blank or near-empty page).
    """
    s = compute_page_signals(page)

    if s.text_len > 0 and s.garbage_char_ratio > MAX_GARBAGE_CHAR_RATIO:
        return PageClass.POOR_TEXT, s

    if s.text_len >= MIN_CHARS_FOR_NATIVE_TEXT:
        return PageClass.NATIVE_TEXT, s

    if s.vector_path_count >= MIN_VECTOR_PATHS_FOR_STRUCTURAL_CONTENT:
        return PageClass.MIXED, s

    if s.image_count > 0:
        return PageClass.IMAGE_ONLY, s

    return PageClass.SCANNED, s


# How each PageClass maps onto the pipeline's existing two-path routing
# ("vector" = native extraction only, "scanned"/"mixed" = OCR involved).
# MIXED and POOR_TEXT both route through "mixed" — in both cases the
# native text layer alone isn't trustworthy enough to skip OCR, but there
# may still be real value in it, so both extractors run and get merged.
PAGE_CLASS_TO_ROUTE = {
    PageClass.NATIVE_TEXT: "vector",
    PageClass.IMAGE_ONLY: "scanned",
    PageClass.SCANNED: "scanned",
    PageClass.MIXED: "mixed",
    PageClass.POOR_TEXT: "mixed",
}


def quality_label(score: float) -> str:
    """GOOD (>=0.90) / REVIEW (0.75-0.89) / BAD (<0.75) — configurable thresholds, not universal truth."""
    if score >= QUALITY_GOOD_THRESHOLD:
        return "GOOD"
    if score >= QUALITY_REVIEW_THRESHOLD:
        return "REVIEW"
    return "BAD"

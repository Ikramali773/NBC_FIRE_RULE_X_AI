# backend/plan_extractor/placement/floor_detector.py
# Multi-floor detection for the placement pipeline: which pages of an
# uploaded multi-page vector PDF are floors, and what floor each one is.
#
# Reuses plan_extractor.label_categorizer.FLOOR_LABEL_PATTERNS (already
# battle-tested in the main text-extraction pipeline) rather than a second,
# duplicate keyword list.
#
# A page's text can contain more than one floor-label match — e.g. a real
# file's "FIRST FLOOR" page also has a small room inside it literally named
# "Terrace". Font size disambiguates: verified directly against that exact
# real page that the big page caption ("FIRST FLOOR") renders at a clearly
# larger font size than the small in-plan room label ("Terrace"), so the
# largest-font match is taken as the page's real floor identity.

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional

import pdfplumber

from plan_extractor.label_categorizer import FLOOR_LABEL_PATTERNS


@dataclass
class FloorPage:
    page_index: int
    floor_label: Optional[str]  # None if no floor keyword found on this page at all


def detect_page_floor_label(page) -> Optional[str]:
    """
    Find every FLOOR_LABEL_PATTERNS match in the page's text, then pick the
    one rendered at the largest font size (the page's real floor caption)
    over any smaller incidental match (e.g. a room named "Terrace" on a
    page whose real floor is "FIRST FLOOR"). Falls back to the first regex
    match (in pattern order) if font-size data isn't available.
    """
    text = page.extract_text() or ""
    candidates: list[str] = []
    for pat in FLOOR_LABEL_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidates.append(re.sub(r"\s+", " ", m.group(0).strip().upper()))
    if not candidates:
        return None

    try:
        words = page.extract_words(extra_attrs=["size"]) or []
    except Exception:
        words = []
    if not words:
        return candidates[0]

    best_label, best_size = candidates[0], -1.0
    for label in candidates:
        first_token = label.split()[0]
        for w in words:
            token = (w.get("text") or "").upper().rstrip(":")
            if token.startswith(first_token[:3]):
                size = float(w.get("size", 0) or 0)
                if size > best_size:
                    best_size = size
                    best_label = label
    return best_label


def detect_floors(pdf_bytes: bytes) -> list[FloorPage]:
    """One FloorPage per page, in page order. A page with no floor keyword
    still gets an entry (floor_label=None) — never silently dropped; the
    caller decides what to do with an unlabeled page."""
    floors: list[FloorPage] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            floors.append(FloorPage(page_index=i, floor_label=detect_page_floor_label(page)))
    return floors

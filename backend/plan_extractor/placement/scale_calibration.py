# backend/plan_extractor/placement/scale_calibration.py
# Phase 3a, Step 3 — Scale calibration (the highest-risk step).
#
# Every distance-based placement decision depends on knowing the drawing's
# real-world scale. This is derived here by cross-referencing printed room
# dimension text already extractable via Phase 1's text layer (e.g.
# "3370X5170", meaning 3370mm x 5170mm) against the geometric size of the
# same room in the drawing, measured by ray-casting from the label's
# position out to the nearest wall in each direction.
#
# This is NEVER silently applied — the caller must surface the returned
# ScaleCalibration as an editable, user-confirmable value, exactly like
# plan_extractor/scale_detector.py's existing rule for the text-extraction
# pipeline. A wrong scale here doesn't just mislabel an area (as in Phase
# 1/2) — it silently produces wrong physical dot placement, so confidence
# must reflect real consistency across multiple independent room samples,
# not just "a number was found."

from __future__ import annotations

import io
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pdfplumber

from .geometry_extractor import GeometryResult

# "3370X5170", "3370 X 5170", "3370x5170mm" — width x depth in mm, the
# convention observed directly in KASTURBA_GANDHI.pdf's room labels.
DIMENSION_PAIR_RE = re.compile(r"\b(\d{3,6})\s*[xX×]\s*(\d{3,6})\b")

MIN_SAMPLES_FOR_HIGH_CONFIDENCE = 3
MAX_RAY_DISTANCE_PX = 4000
OUTLIER_REJECT_RATIO = 1.2  # drop samples whose scale is >20% off the median —
                             # a room's internal partitions/fixtures near the
                             # label can make the ray-cast undershoot the true
                             # wall-to-wall extent, so real variation across
                             # correctly-measured rooms should otherwise be small


@dataclass
class ScaleSample:
    label_text: str
    x_pt: float
    y_pt: float
    printed_mm: tuple[int, int]
    measured_pt: tuple[float, float]
    mm_per_pt: float


@dataclass
class ScaleCalibration:
    mm_per_pt: Optional[float]
    confidence: str  # "green" | "amber" | "red"
    samples: list[ScaleSample] = field(default_factory=list)
    rejected_samples: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "mm_per_pt": self.mm_per_pt,
            "confidence": self.confidence,
            "sample_count": len(self.samples),
            "rejected_samples": self.rejected_samples,
            "note": self.note,
            "editable": True,
        }


def _cast_ray(wall_mask: np.ndarray, row: int, col: int, drow: int, dcol: int, max_dist: int) -> int:
    """Distance in px from (row, col) to the nearest wall pixel in direction (drow, dcol)."""
    r, c = row, col
    h, w = wall_mask.shape
    for dist in range(1, max_dist + 1):
        r += drow
        c += dcol
        if r < 0 or r >= h or c < 0 or c >= w:
            return dist - 1
        if wall_mask[r, c]:
            return dist
    return max_dist


def _measure_room_bbox_pt(geometry: GeometryResult, x_pt: float, y_pt: float) -> Optional[tuple[float, float]]:
    row, col = geometry.to_raster(x_pt, y_pt)
    h, w = geometry.wall_mask.shape
    if not (0 <= row < h and 0 <= col < w) or geometry.wall_mask[row, col]:
        return None  # label sits on/outside a wall pixel — can't measure from here

    left = _cast_ray(geometry.wall_mask, row, col, 0, -1, MAX_RAY_DISTANCE_PX)
    right = _cast_ray(geometry.wall_mask, row, col, 0, 1, MAX_RAY_DISTANCE_PX)
    up = _cast_ray(geometry.wall_mask, row, col, -1, 0, MAX_RAY_DISTANCE_PX)
    down = _cast_ray(geometry.wall_mask, row, col, 1, 0, MAX_RAY_DISTANCE_PX)

    width_px = left + right
    height_px = up + down
    if width_px <= 0 or height_px <= 0:
        return None
    return width_px / geometry.raster_scale, height_px / geometry.raster_scale


def calibrate_scale(pdf_bytes: bytes, page_index: int, geometry: GeometryResult) -> ScaleCalibration:
    """
    Find printed room-dimension labels (WIDTHxDEPTH in mm), measure the
    corresponding room's geometric extent by ray-casting from the label
    to the nearest walls, and derive mm-per-PDF-point from the ratio.
    """
    samples: list[ScaleSample] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[page_index]
        text = page.extract_text() or ""
        words = page.extract_words(keep_blank_chars=False) or []

        matches = list(DIMENSION_PAIR_RE.finditer(text))
        if not matches:
            return ScaleCalibration(
                mm_per_pt=None, confidence="red",
                note="No room dimension labels (e.g. '3370X5170') found in the text layer — "
                     "scale cannot be calibrated automatically. Enter it manually.",
            )

        # Match each dimension string to its word position(s) by locating the
        # matching combined digits in the word stream near each other.
        for m in matches:
            mm_a, mm_b = int(m.group(1)), int(m.group(2))
            label_text = m.group(0)
            pos = _find_label_position(words, str(mm_a), str(mm_b))
            if pos is None:
                continue
            x_pt, y_pt = pos
            measured = _measure_room_bbox_pt(geometry, x_pt, y_pt)
            if measured is None:
                continue
            w_pt, h_pt = measured
            printed_hi, printed_lo = max(mm_a, mm_b), min(mm_a, mm_b)
            measured_hi, measured_lo = max(w_pt, h_pt), min(w_pt, h_pt)
            if measured_hi <= 0 or measured_lo <= 0:
                continue
            mm_per_pt = (printed_hi / measured_hi + printed_lo / measured_lo) / 2
            samples.append(ScaleSample(
                label_text=label_text, x_pt=x_pt, y_pt=y_pt,
                printed_mm=(mm_a, mm_b), measured_pt=(w_pt, h_pt), mm_per_pt=mm_per_pt,
            ))

    if not samples:
        return ScaleCalibration(
            mm_per_pt=None, confidence="red",
            note=f"Found {len(matches)} dimension label(s) in text but couldn't locate/measure "
                 "any of them geometrically — scale cannot be calibrated automatically. Enter it manually.",
        )

    values = [s.mm_per_pt for s in samples]
    median = statistics.median(values)
    kept = [s for s in samples if median / OUTLIER_REJECT_RATIO <= s.mm_per_pt <= median * OUTLIER_REJECT_RATIO]
    rejected = len(samples) - len(kept)

    final_values = [s.mm_per_pt for s in kept] or values
    mm_per_pt = statistics.mean(final_values)
    spread = (max(final_values) - min(final_values)) / mm_per_pt if mm_per_pt else 1.0

    if len(kept) >= MIN_SAMPLES_FOR_HIGH_CONFIDENCE and spread < 0.15:
        confidence = "green"
        note = f"Calibrated from {len(kept)} consistent room-dimension labels (spread {spread:.0%})."
    elif len(kept) >= 1:
        confidence = "amber"
        note = (f"Calibrated from {len(kept)} room-dimension label(s) (spread {spread:.0%}) — "
                "please verify against a known dimension before trusting placement distances.")
    else:
        confidence = "red"
        note = "Dimension labels found but too inconsistent to trust — enter scale manually."

    return ScaleCalibration(
        mm_per_pt=mm_per_pt, confidence=confidence, samples=kept,
        rejected_samples=rejected, note=note,
    )


def _find_label_position(words: list[dict], mm_a: str, mm_b: str) -> Optional[tuple[float, float]]:
    """
    Locate the (x, y-center) of a 'AAAAxBBBB' dimension label in the word
    stream. pdfplumber may return it as one token ("3370X5170") or split
    across adjacent tokens ("3370", "X5170") depending on font kerning.
    """
    for i, w in enumerate(words):
        wt = w.get("text", "")
        if mm_a in wt and mm_b in wt:
            return _word_center(w)
        if mm_a in wt and i + 1 < len(words) and mm_b in words[i + 1].get("text", ""):
            return _word_center(w)
    return None


def _word_center(w: dict) -> tuple[float, float]:
    return (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2

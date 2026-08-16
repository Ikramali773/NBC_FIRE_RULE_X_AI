# backend/plan_extractor/placement/geometry_extractor.py
# Phase 3a, Step 1 — Wall/room geometry extraction from vector PDF line data.
#
# Unlike plan_extractor/pdf_vector_extractor.py (which pulls TEXT — labels,
# dimensions), this pulls SHAPES: it rasterizes the page's wall-like vector
# lines onto a pixel grid, then uses connected-component labeling to recover
# the building's walkable interior as a mask. This only works on pages with
# real vector line geometry (file_router's "vector" pages) — it cannot run
# on a scanned/photographed page, since there are no lines to rasterize.
#
# The raster + flood-fill approach was chosen over pure vector polygon
# algebra (merging/closing thousands of raw line segments into exact room
# polygons) because it is far more robust to the gaps, T-junctions, and
# near-misses that appear in real CAD-exported line data — at the cost of
# some geometric precision, which is acceptable here since the output feeds
# a walkable-space graph (walkable_graph.py), not an exact CAD reconstruction.
#
# Constants below (RASTER_SCALE, WALL_STROKE_PX, OPENING_RADIUS_PX, ...) are
# empirically tuned against KASTURBA_GANDHI.pdf's ground floor, per this
# project's own stated validation strategy: prove the pipeline on a
# confirmed-clean file first, then retune/generalize once more real files
# are available (Phase 3a Scope, Section 7).

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pdfplumber
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage.morphology import opening, disk

RASTER_SCALE = 2.0       # raster px per PDF point
WALL_STROKE_PX = 6       # rasterized wall line thickness, in raster px
OPENING_RADIUS_PX = 14   # morphological opening radius — smooths furniture/
                         # fixture-scale noise while preserving room/corridor
                         # scale structure (see prototyping notes in Phase 3a)
MIN_REGION_PX = 500      # ignore connected regions smaller than this (noise)


@dataclass
class GeometryResult:
    page_width_pt: float
    page_height_pt: float
    raster_scale: float
    wall_mask: np.ndarray             # bool grid, True = wall/obstacle
    interior_mask: np.ndarray         # bool grid, True = walkable building interior
    interior_regions: list[dict]      # [{"label": int, "size_px": int, "bbox": (r0,c0,r1,c1)}, ...]
    warnings: list[str] = field(default_factory=list)

    def to_pdf_point(self, row: int, col: int) -> tuple[float, float]:
        """Convert a raster (row, col) back to PDF point space (x, y=top)."""
        return col / self.raster_scale, row / self.raster_scale

    def to_raster(self, x_pt: float, y_pt: float) -> tuple[int, int]:
        """Convert a PDF point-space (x, top) coordinate to raster (row, col)."""
        return int(round(y_pt * self.raster_scale)), int(round(x_pt * self.raster_scale))


def _wall_segments(page: pdfplumber.page.Page) -> list[tuple[float, float, float, float]]:
    """
    Collect wall-like straight segments: real line objects, plus rect
    outlines (rects in CAD-exported PDFs are typically wall panels, door/
    window frames, or similar wall-adjacent features — using their outline
    as 4 segments is a safe superset, since a missed wall is worse than an
    extra one for this purpose: it would silently merge two rooms).
    """
    segments = []
    for line in page.lines or []:
        segments.append((line["x0"], line["top"], line["x1"], line["bottom"]))
    for rect in page.rects or []:
        x0, x1, top, bottom = rect["x0"], rect["x1"], rect["top"], rect["bottom"]
        segments.append((x0, top, x1, top))
        segments.append((x1, top, x1, bottom))
        segments.append((x1, bottom, x0, bottom))
        segments.append((x0, bottom, x0, top))
    return segments


def _rasterize(segments, width_pt: float, height_pt: float, scale: float, stroke_px: int) -> np.ndarray:
    w, h = max(1, int(width_pt * scale)), max(1, int(height_pt * scale))
    img = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(img)
    for x0, y0, x1, y1 in segments:
        draw.line([(x0 * scale, y0 * scale), (x1 * scale, y1 * scale)], fill=1, width=stroke_px)
    return np.array(img, dtype=bool)


def extract_geometry(
    pdf_bytes: bytes,
    page_index: int,
    raster_scale: float = RASTER_SCALE,
    opening_radius_px: int = OPENING_RADIUS_PX,
) -> GeometryResult:
    """
    Extract the walkable building interior for one PDF page as a raster mask.

    Approach:
      1. Rasterize every wall-like line/rect-outline onto a boolean grid.
      2. Morphologically open the inverse (open-space) mask to smooth away
         furniture/fixture/hatching-scale noise without eroding real
         room/corridor-scale openings.
      3. Label connected open-space components. The component(s) touching
         the raster border are "outside the building" (the page's margin
         and title-block whitespace); everything else, above a minimum
         size, is candidate walkable interior (rooms, corridors, courtyards).
    """
    warnings: list[str] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if page_index >= len(pdf.pages):
            raise ValueError(f"Page index {page_index} out of range ({len(pdf.pages)} pages).")
        page = pdf.pages[page_index]
        segments = _wall_segments(page)

        if len(segments) < 20:
            warnings.append(
                f"Only {len(segments)} wall-like line segments found on this page — "
                "geometry extraction may be unreliable (page may be mostly text/scanned)."
            )

        wall_mask = _rasterize(segments, page.width, page.height, raster_scale, WALL_STROKE_PX)
        open_mask = ~wall_mask
        smoothed = opening(open_mask, disk(opening_radius_px))

        labeled, num_labels = ndimage.label(smoothed, structure=np.ones((3, 3)))
        if num_labels == 0:
            warnings.append("No open regions found after rasterization — check wall-line density.")
            return GeometryResult(
                page_width_pt=page.width, page_height_pt=page.height,
                raster_scale=raster_scale, wall_mask=wall_mask,
                interior_mask=np.zeros_like(wall_mask), interior_regions=[], warnings=warnings,
            )

        border_labels = set(labeled[0, :]) | set(labeled[-1, :]) | set(labeled[:, 0]) | set(labeled[:, -1])
        border_labels.discard(0)

        sizes = ndimage.sum(smoothed, labeled, range(1, num_labels + 1))
        interior_regions = []
        interior_mask = np.zeros_like(wall_mask)
        for i, size in enumerate(sizes):
            label_id = i + 1
            if label_id in border_labels or size < MIN_REGION_PX:
                continue
            region_mask = labeled == label_id
            rows, cols = np.nonzero(region_mask)
            bbox = (int(rows.min()), int(cols.min()), int(rows.max()), int(cols.max()))
            interior_regions.append({"label": label_id, "size_px": int(size), "bbox": bbox})
            interior_mask |= region_mask

        interior_regions.sort(key=lambda r: -r["size_px"])

        if not interior_regions:
            warnings.append(
                "No interior (non-border-touching) region found — the drawing may not "
                "have a fully enclosed building envelope, or wall lines have gaps."
            )

        return GeometryResult(
            page_width_pt=page.width, page_height_pt=page.height,
            raster_scale=raster_scale, wall_mask=wall_mask,
            interior_mask=interior_mask, interior_regions=interior_regions,
            warnings=warnings,
        )

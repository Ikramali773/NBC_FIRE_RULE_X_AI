# backend/plan_extractor/placement/validate_kasturba.py
# Phase 3a, Step 6 — Ground-truth validation against KASTURBA_GANDHI.pdf.
#
# This is a ONE-OFF validation script, not a shipped pipeline feature. The
# product (Step 1-5) only ever suggests placement on an UNMARKED input —
# it never needs to detect existing markup on a real user upload. This
# script exists purely to produce Phase 3a's documented pass/fail evidence:
# it (a) extracts where the real consultant actually placed extinguishers
# in Kasturba's finished, already-marked-up drawing, by locating the CO2
# (blue, ~5pt circle) and ABC (red, ~5pt circle) symbols defined in that
# drawing's own legend, then (b) runs the real placement pipeline against
# the SAME file — treating it as if it were a plain, unmarked input — and
# (c) reports the numeric distance between suggested and real placement.
#
# Run from backend/:  python -m plan_extractor.placement.validate_kasturba

from __future__ import annotations

import io
import json
import math
from pathlib import Path

import pdfplumber

from .geometry_extractor import extract_geometry
from .walkable_graph import build_walkable_graph
from .scale_calibration import calibrate_scale
from .placement_algorithm import suggest_placement

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "KASTURBA_GANDHI.pdf"
PAGE_INDEX = 0  # Ground floor

# Symbol appearance, read directly from the drawing's own legend:
# "Co2 TYPE FIRE EXTINGUISHER (4.5 KG.)" -> blue dot
# "ABC TYPE FIRE EXTINGUISHER (6 KG.)"   -> red dot
# Both render as several small curve fragments approximating a circle; the
# one whose bounding box is near-square in this size range is the icon's
# outer boundary (see Phase 3a validation notes for how this was derived).
DOT_SIZE_RANGE = (3.0, 8.0)
DOT_SQUARENESS_TOLERANCE = 0.6
CLUSTER_RADIUS_PT = 5.0
PAIR_RADIUS_PT = 15.0        # CO2+ABC dots at the same station are drawn ~6-7pt apart
LEGEND_X_FRACTION = 0.85     # legend box occupies the right ~15% of the sheet


def _is_dot(curve: dict, color: tuple) -> bool:
    w = curve["x1"] - curve["x0"]
    h = curve["bottom"] - curve["top"]
    return (
        curve.get("non_stroking_color") == color
        and DOT_SIZE_RANGE[0] <= w <= DOT_SIZE_RANGE[1]
        and DOT_SIZE_RANGE[0] <= h <= DOT_SIZE_RANGE[1]
        and abs(w - h) < DOT_SQUARENESS_TOLERANCE
    )


def _cluster(points: list[tuple[float, float]], radius: float) -> list[tuple[float, float]]:
    clusters: list[list[tuple[float, float]]] = []
    for p in points:
        for cl in clusters:
            if math.hypot(cl[0][0] - p[0], cl[0][1] - p[1]) < radius:
                cl.append(p)
                break
        else:
            clusters.append([p])
    return [(sum(x for x, _ in cl) / len(cl), sum(y for _, y in cl) / len(cl)) for cl in clusters]


def extract_ground_truth(pdf_bytes: bytes, page_index: int) -> list[tuple[float, float]]:
    """Return real consultant-placed extinguisher-station coordinates (PDF
    point space), one per physical station (CO2+ABC pair collapsed to their
    midpoint), excluding the legend's own sample icons."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[page_index]
        legend_x_min = page.width * LEGEND_X_FRACTION

        blue_raw = [(c["x0"], c["top"]) for c in page.curves if _is_dot(c, (0.0, 0.0, 1.0))]
        red_raw = [(c["x0"], c["top"]) for c in page.curves if _is_dot(c, (1.0, 0.0, 0.0))]

        blue = [p for p in _cluster(blue_raw, CLUSTER_RADIUS_PT) if p[0] < legend_x_min]
        red = _cluster(red_raw, CLUSTER_RADIUS_PT)

        stations = []
        for b in blue:
            paired_red = [r for r in red if math.hypot(r[0] - b[0], r[1] - b[1]) < PAIR_RADIUS_PT]
            if paired_red:
                r = paired_red[0]
                stations.append(((b[0] + r[0]) / 2, (b[1] + r[1]) / 2))
            else:
                stations.append(b)
        return stations


def _nearest_distances_m(
    points_a: list[tuple[float, float]],
    points_b: list[tuple[float, float]],
    mm_per_pt: float,
) -> list[float]:
    out = []
    for a in points_a:
        if not points_b:
            out.append(float("inf"))
            continue
        d_pt = min(math.hypot(a[0] - b[0], a[1] - b[1]) for b in points_b)
        out.append(d_pt * mm_per_pt / 1000.0)
    return out


def run_validation() -> dict:
    pdf_bytes = FIXTURE_PATH.read_bytes()

    ground_truth = extract_ground_truth(pdf_bytes, PAGE_INDEX)

    geometry = extract_geometry(pdf_bytes, PAGE_INDEX)
    walkable = build_walkable_graph(geometry)
    scale = calibrate_scale(pdf_bytes, PAGE_INDEX, geometry)

    report = {
        "fixture": str(FIXTURE_PATH.name),
        "ground_truth_station_count": len(ground_truth),
        "ground_truth_points_pt": ground_truth,
        "scale_calibration": scale.to_dict(),
        "by_hazard_level": {},
    }

    for hazard_type in ("low", "moderate", "high"):
        result = suggest_placement(geometry, walkable, scale, hazard_type)
        suggested_pts = [(p.x_pt, p.y_pt) for p in result.points]

        gt_to_suggested = _nearest_distances_m(ground_truth, suggested_pts, scale.mm_per_pt)
        suggested_to_gt = _nearest_distances_m(suggested_pts, ground_truth, scale.mm_per_pt)

        report["by_hazard_level"][hazard_type] = {
            "coverage_radius_m": round(result.coverage_radius_m, 2),
            "suggested_point_count": len(suggested_pts),
            "warnings": result.warnings,
            # For each REAL station, distance to the nearest SUGGESTED point —
            # low values mean the algorithm placed something near every real
            # extinguisher location (no missed coverage).
            "real_station_to_nearest_suggestion_m": [round(d, 2) for d in gt_to_suggested],
            "mean_real_station_to_nearest_suggestion_m": round(
                sum(gt_to_suggested) / len(gt_to_suggested), 2
            ) if gt_to_suggested else None,
            # For each SUGGESTED point, distance to the nearest REAL station —
            # low values mean the algorithm isn't suggesting points far from
            # where a real consultant would put one.
            "mean_suggestion_to_nearest_real_station_m": round(
                sum(suggested_to_gt) / len(suggested_to_gt), 2
            ) if suggested_to_gt else None,
        }

    return report


if __name__ == "__main__":
    print(json.dumps(run_validation(), indent=2, default=str))

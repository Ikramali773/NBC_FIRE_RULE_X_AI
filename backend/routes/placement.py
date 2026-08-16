# backend/routes/placement.py
# POST /api/placement/suggest — Phase 3a: automated fire-extinguisher
# placement suggestion for one page (floor) of an uploaded, plain/unmarked
# vector PDF building plan.
#
# This route does NOT touch engine.py, rule_engine.py, class_a_checker.py,
# hazard_classifier.py, or any rules/*.json — it only imports and calls
# them (via plan_extractor.placement.placement_algorithm, which imports
# class_a_checker.CLASS_A_TABLE read-only).
#
# Scope: fire extinguishers only, dots only, no pipe-routing lines, no DWG
# support, no scanned-file support (see Phase 3a scope doc). The caller
# supplies hazard_type directly — this endpoint reuses the ALREADY-computed
# hazard classification from a normal compliance analysis rather than
# re-deriving it, since hazard_type depends on fields (occupant count,
# height, hazardous-materials volumes) that aren't derivable from geometry.

from __future__ import annotations

import io

import pdfplumber
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse

from class_a_checker import CLASS_A_TABLE
from plan_extractor.placement.geometry_extractor import extract_geometry
from plan_extractor.placement.walkable_graph import build_walkable_graph
from plan_extractor.placement.scale_calibration import calibrate_scale
from plan_extractor.placement.placement_algorithm import suggest_placement

router = APIRouter()

MAX_FILE_SIZE = 20 * 1024 * 1024
LABEL_SEARCH_RADIUS_PT = 200


def _label_words(pdf_bytes: bytes, page_index: int) -> list[dict]:
    """Extract candidate room/space label words once per request (not once
    per point — re-parsing the PDF per point is needlessly slow)."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            words = pdf.pages[page_index].extract_words(keep_blank_chars=False) or []
    except Exception:
        return []
    filtered = []
    for w in words:
        text = w.get("text", "")
        if len(text) < 3:
            continue
        digit_ratio = sum(ch.isdigit() for ch in text) / len(text)
        if digit_ratio > 0.15:  # excludes dimension pairs, elevation markers (LVL+900MM), etc.
            continue
        filtered.append(w)
    return filtered


def _nearest_room_label(words: list[dict], x_pt: float, y_pt: float) -> str:
    """Best-effort plain-language location description for the side table,
    e.g. 'near WAITING / corridor junction'. Purely a text-proximity lookup
    — no semantic understanding, matching this project's existing standard
    for OCR/text-adjacent categorization."""
    best_word, best_dist = None, LABEL_SEARCH_RADIUS_PT
    for w in words:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        dist = ((cx - x_pt) ** 2 + (cy - y_pt) ** 2) ** 0.5
        if dist < best_dist:
            best_word, best_dist = w["text"], dist

    return f"near {best_word}" if best_word else "corridor junction"


@router.post("/api/placement/suggest")
async def suggest_extinguisher_placement(
    file: UploadFile = File(...),
    page_index: int = Form(0),
    hazard_type: str = Form(...),
):
    if hazard_type not in CLASS_A_TABLE:
        return JSONResponse(
            content={"error": f"Invalid hazard_type '{hazard_type}'. Expected one of {list(CLASS_A_TABLE)}."},
            status_code=400,
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse(
            content={"error": "Only .pdf files are accepted for automated placement (Phase 3a)."},
            status_code=400,
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse(
            content={"error": f"File too large ({len(content) / 1024 / 1024:.1f}MB). Maximum is 20MB."},
            status_code=400,
        )

    try:
        geometry = extract_geometry(content, page_index)
    except Exception as err:
        return JSONResponse(
            content={"error": f"Geometry extraction failed: {err}"},
            status_code=422,
        )

    if not geometry.interior_regions:
        return JSONResponse(
            content={
                "error": "No walkable interior geometry found on this page. Automated placement needs "
                         "a CAD-drawn file with real vector line data — scanned/photographed plans "
                         "aren't supported for this feature.",
                "warnings": geometry.warnings,
            },
            status_code=422,
        )

    walkable = build_walkable_graph(geometry)
    scale = calibrate_scale(content, page_index, geometry)

    if not scale.mm_per_pt:
        return JSONResponse(
            content={
                "error": "Could not calibrate a drawing scale automatically. Automated placement "
                         "cannot proceed without a confirmed scale.",
                "scale": scale.to_dict(),
            },
            status_code=422,
        )

    result = suggest_placement(geometry, walkable, scale, hazard_type)
    label_words = _label_words(content, page_index)

    points = []
    for i, p in enumerate(result.points):
        points.append({
            "index": i + 1,
            "xPt": p.x_pt,
            "yPt": p.y_pt,
            "isJunction": p.is_junction,
            "locationDescription": _nearest_room_label(label_words, p.x_pt, p.y_pt),
            "clauseRef": f"IS 2190:2024, Table 1 ({hazard_type} hazard), cl 7.2.1",
        })

    return JSONResponse(content={
        "pageIndex": page_index,
        "pageWidthPt": geometry.page_width_pt,
        "pageHeightPt": geometry.page_height_pt,
        "hazardType": hazard_type,
        "rating": result.rating,
        "maxAreaM2": result.max_area_m2,
        "coverageRadiusM": round(result.coverage_radius_m, 2),
        "scale": scale.to_dict(),
        "points": points,
        "warnings": geometry.warnings + walkable.warnings + result.warnings,
    })

# backend/plan_extractor/confidence_tagger.py
# Stage 8 — Confidence Tagger
#
# Applies green/amber/red confidence consistently across all extraction paths.
#
# Rules:
#   Green: value from explicit dimension/label with no inference (Stage 2/3),
#          or two independent sources agree.
#   Amber: value inferred/calculated, Gemini vision (Stage 5a),
#          OCR keyword match (Stage 5b), keyword-based construction/occupancy guess.
#   Red:   could not be determined, OCR with no keyword context,
#          or LibreDWG conversion with questionable output.
#
# Fields marked "not derivable from a drawing" (building_status) → always red/null.
# Stage 5a (Gemini) results → NEVER green, capped at amber.

from __future__ import annotations


def tag_confidence(mapped_fields: dict) -> dict:
    """
    Apply final confidence tagging to mapped fields.

    Enforces rules like:
    - building_status is always red/null
    - Gemini (5a) results never green, capped at amber
    - Tesseract (5b) results without keyword context stay red
    """
    result = dict(mapped_fields)

    # ── building_status: ALWAYS red/null ──
    if "building_status" in result:
        result["building_status"]["value"] = None
        result["building_status"]["confidence"] = "red"
        result["building_status"]["note"] = "Not derivable from a drawing — always leave for user to select"

    # ── Cap Gemini results at amber ──
    gemini_fields = []
    for key, val in result.items():
        if isinstance(val, dict) and val.get("source_stage", "").startswith("5a_gemini"):
            if val.get("confidence") == "green":
                val["confidence"] = "amber"
                val["note"] = (val.get("note", "") + " (capped at amber — single-source AI read)").strip()
            gemini_fields.append(key)

    # ── Handle per_floor_areas_m2 (list of dicts) ──
    if "per_floor_areas_m2" in result and isinstance(result["per_floor_areas_m2"], list):
        for area_item in result["per_floor_areas_m2"]:
            if isinstance(area_item, dict):
                source = area_item.get("source_stage", "")
                if "gemini" in source and area_item.get("confidence") == "green":
                    area_item["confidence"] = "amber"

    # ── Compute overall extraction quality ──
    field_confidences = []
    for key, val in result.items():
        if key in ("source_file_type", "raw_text_labels", "warnings", "detected_scale", "per_floor_areas_m2"):
            continue
        if isinstance(val, dict) and "confidence" in val:
            field_confidences.append(val["confidence"])

    # Also count per-floor areas
    if isinstance(result.get("per_floor_areas_m2"), list):
        for item in result["per_floor_areas_m2"]:
            if isinstance(item, dict) and "confidence" in item:
                field_confidences.append(item["confidence"])

    green_count = field_confidences.count("green")
    amber_count = field_confidences.count("amber")
    red_count = field_confidences.count("red")
    total = len(field_confidences) or 1

    result["_extraction_quality"] = {
        "green_fields": green_count,
        "amber_fields": amber_count,
        "red_fields": red_count,
        "total_fields": total,
        "quality_score": round((green_count * 100 + amber_count * 50) / total),
        "summary": (
            "Good extraction" if green_count > red_count
            else "Partial extraction — many fields need manual input"
            if amber_count > red_count
            else "Minimal extraction — most fields need manual input"
        ),
    }

    return result

# backend/plan_extractor/field_mapper.py
# Stage 7 — Field Mapper
#
# Maps raw extraction output to the real form field identifiers
# confirmed from the frontend code.

from __future__ import annotations

from typing import Optional


# ── Occupancy keyword → code map (from NBC 2016 classification) ──
OCCUPANCY_KEYWORD_MAP = {
    "hotel": ("A-5", "Hotels"),
    "motel": ("A-1", "Lodging or Rooming Houses"),
    "hostel": ("A-3", "Dormitories"),
    "dormitory": ("A-3", "Dormitories"),
    "apartment": ("A-4", "Apartment Houses (Flats)"),
    "residential": ("A-4", "Apartment Houses (Flats)"),
    "flat": ("A-4", "Apartment Houses (Flats)"),
    "hospital": ("C-1", "Hospitals & Sanatoria"),
    "clinic": ("C-2", "Nursing Homes & Custodial Care"),
    "school": ("D-1", "Schools up to Senior Secondary"),
    "college": ("D-2", "Colleges & Universities"),
    "cinema": ("D-3", "Exhibition Halls, Banquet Halls"),
    "banquet": ("D-3", "Exhibition Halls, Banquet Halls"),
    "exhibition": ("D-3", "Exhibition Halls, Banquet Halls"),
    "restaurant": ("D-4", "Restaurants"),
    "assembly": ("D-5", "Assembly Buildings"),
    "theater": ("D-5", "Assembly Buildings"),
    "theatre": ("D-5", "Assembly Buildings"),
    "office": ("E-1", "Offices, Banks, Professional Establishments"),
    "bank": ("E-1", "Offices, Banks, Professional Establishments"),
    "lab": ("E-2", "Laboratories"),
    "laboratory": ("E-2", "Laboratories"),
    "data center": ("E-3", "Data Centres"),
    "datacenter": ("E-3", "Data Centres"),
    "mall": ("F-2", "Retail Stores, Shops"),
    "shop": ("F-2", "Retail Stores, Shops"),
    "retail": ("F-2", "Retail Stores, Shops"),
    "market": ("F-2", "Retail Stores, Shops"),
    "warehouse": ("G-1", "Low-Hazard Storage"),
    "storage": ("G-1", "Low-Hazard Storage"),
    "factory": ("G-2", "Moderate-Hazard Storage"),
    "industrial": ("J", "Hazardous"),
}


def _map_occupancy_hint(hint_data: Optional[dict]) -> dict:
    """Map occupancy hint to a proposed code and label."""
    field = {
        "value": None,
        "proposed_code": None,
        "confidence": "red",
        "source_stage": "",
        "note": "Not detected — you'll need to enter this manually",
    }

    if not hint_data:
        return field

    if isinstance(hint_data, dict):
        hint_text = hint_data.get("hint") or hint_data.get("occupancy_hint")
        proposed_code = hint_data.get("proposed_code")
        proposed_label = hint_data.get("proposed_label")

        if proposed_code:
            field["value"] = hint_text
            field["proposed_code"] = proposed_code
            field["confidence"] = "amber"
            field["source_stage"] = "keyword_match"
            field["note"] = (
                f"Keyword '{hint_text}' matched → proposed {proposed_label or proposed_code}. "
                "User must confirm via the search dropdown."
            )
        elif hint_text and isinstance(hint_text, str):
            # Try matching against our map
            hint_lower = hint_text.lower()
            for kw, (code, label) in OCCUPANCY_KEYWORD_MAP.items():
                if kw in hint_lower:
                    field["value"] = hint_text
                    field["proposed_code"] = code
                    field["confidence"] = "amber"
                    field["source_stage"] = "keyword_match"
                    field["note"] = f"Keyword '{kw}' → proposed {code} — {label}. User must confirm."
                    break

    return field


def _map_construction_type(ct_data: Optional[dict]) -> dict:
    """Map construction type detection to the binary dropdown."""
    field = {
        "value": None,
        "confidence": "red",
        "source_stage": "",
        "note": "Not detected — you'll need to select this manually",
    }

    if ct_data and isinstance(ct_data, dict):
        val = ct_data.get("value")
        keyword = ct_data.get("keyword", "")
        if val in ("type12", "type34"):
            field["value"] = val
            field["confidence"] = "amber"
            field["source_stage"] = "keyword_match"
            display = ct_data.get("display", val)
            field["note"] = f"Keyword '{keyword}' matched → {display}"

    return field


def _field(value, confidence: str, source_stage: str, note: str = "") -> dict:
    """Create a standard field output dict."""
    return {
        "value": value,
        "confidence": confidence,
        "source_stage": source_stage,
        "note": note,
    }


def map_to_form_fields(
    extraction_data: dict,
    source_file_type: str,
) -> dict:
    """
    Map raw extraction output to the exact form field identifiers.

    Args:
        extraction_data: Output from Stage 2, 3, or 5
        source_file_type: "vector_pdf", "scanned_pdf", or "dwg"

    Returns:
        Structured dict matching the Stage 7 JSON schema.
    """
    data = extraction_data
    source_stage_prefix = {
        "vector_pdf": "stage2_pdfplumber",
        "scanned_pdf": data.get("source_stage", "stage5"),
        "dwg": "stage3_ezdxf",
    }.get(source_file_type, "unknown")

    # ── Project info ──
    project_info = data.get("project_info", {})
    project_name = project_info.get("project_name")
    city = project_info.get("city")
    state = project_info.get("state")

    # ── Height ──
    height_data = data.get("height")
    height_val = None
    height_confidence = "red"
    height_source = source_stage_prefix
    height_note = "Not detected — you'll need to enter this manually"

    if height_data and isinstance(height_data, dict):
        height_val = height_data.get("value")
        if height_val is not None:
            source = height_data.get("source", "")
            if source in ("text_label", "dxf_text"):
                height_confidence = "green"
                height_note = f"Extracted from explicit text label: {height_data.get('raw', '')}"
            elif "gemini" in source:
                height_confidence = "amber"
                height_note = "Detected by Gemini vision — verify this value"
            elif "tesseract" in source:
                height_confidence = "amber"
                height_note = "Detected by OCR keyword match — verify this value"
            else:
                height_confidence = "amber"
                height_note = "Detected from drawing text"
            height_source = source

    # ── Floors ──
    floors_data = data.get("floors")
    floors_val = None
    floors_confidence = "red"
    floors_source = source_stage_prefix
    floors_note = "Not detected — you'll need to enter this manually"

    if floors_data and isinstance(floors_data, dict):
        floors_val = floors_data.get("value")
        if floors_val is not None:
            source = floors_data.get("source", "")
            if source in ("text_label", "dxf_text"):
                floors_confidence = "green"
                floors_note = f"Extracted from text: {floors_data.get('raw', '')}"
            elif "gemini" in source:
                floors_confidence = "amber"
                floors_note = "Detected by Gemini vision — verify"
            else:
                floors_confidence = "amber"
            floors_source = source

    # ── Areas ──
    areas_list = data.get("areas", [])
    per_floor_areas = []
    if areas_list:
        for i, area in enumerate(areas_list[:20]):  # Cap at 20 floors
            if isinstance(area, dict) and area.get("value"):
                floor_label = "GF" if i == 0 else f"F{i}"
                area_source = area.get("source", source_stage_prefix)
                area_conf = "green" if area_source in ("text_label", "dxf_text", "dxf_geometry") else "amber"
                per_floor_areas.append({
                    "floor_label": floor_label,
                    "value": area["value"],
                    "confidence": area_conf,
                    "source_stage": area_source,
                })

    # ── Basement ──
    basement = data.get("basement", {}) or {}
    basement_area = basement.get("area")
    basement_levels = basement.get("levels")

    # ── Kitchen / Sprinklers ──
    kitchen = data.get("kitchen")
    sprinklers = data.get("sprinklers")

    # ── Occupancy ──
    occ_hint_data = data.get("occupancy_hint")
    occupancy_field = _map_occupancy_hint(occ_hint_data)

    # ── Construction type ──
    ct_data = data.get("construction_type")
    construction_field = _map_construction_type(ct_data)

    return {
        "source_file_type": source_file_type,

        "project_name": _field(
            project_name, "amber" if project_name else "red",
            source_stage_prefix,
            "Best-effort from title block" if project_name else "Not detected — you'll need to enter this manually",
        ),

        "city": _field(
            city, "amber" if city else "red",
            source_stage_prefix,
            "Best-effort from title-block address" if city else "Not detected — you'll need to enter this manually",
        ),

        "state": _field(
            state, "amber" if state else "red",
            source_stage_prefix,
            "Best-effort from title-block address" if state else "Not detected — you'll need to enter this manually",
        ),

        "building_status": _field(
            None, "red", "not_applicable",
            "Not derivable from a drawing — always leave for user to select",
        ),

        "primary_occupancy_hint": occupancy_field,

        "height_m": _field(height_val, height_confidence, height_source, height_note),

        "floors_count": _field(floors_val, floors_confidence, floors_source, floors_note),

        "construction_type": construction_field,

        "per_floor_areas_m2": per_floor_areas,

        "basement_area_m2": _field(
            basement_area, "amber" if basement_area else "red",
            source_stage_prefix,
            "Detected from drawing text" if basement_area else "Not detected — you'll need to enter this manually",
        ),

        "basement_levels": _field(
            basement_levels, "amber" if basement_levels else "red",
            source_stage_prefix,
            "Detected from drawing text" if basement_levels else "Not detected — you'll need to enter this manually",
        ),

        "kitchen_present": _field(
            kitchen, "amber" if kitchen is not None else "red",
            source_stage_prefix,
            "Kitchen keyword found in drawing" if kitchen else "Not detected — you'll need to enter this manually",
        ),

        "sprinklers_proposed": _field(
            sprinklers, "amber" if sprinklers is not None else "red",
            source_stage_prefix,
            "Sprinkler keyword found in drawing" if sprinklers else "Not detected — you'll need to enter this manually",
        ),
    }

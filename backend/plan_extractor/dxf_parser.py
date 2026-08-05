# backend/plan_extractor/dxf_parser.py
# Stage 3 — DXF Parser
#
# Uses ezdxf to extract TEXT/MTEXT entities, LWPOLYLINE boundaries,
# and DIMENSION entities from DXF files.

from __future__ import annotations

import re
import math
from pathlib import Path
from typing import Optional

import ezdxf


def _shoelace_area(points: list[tuple[float, float]]) -> float:
    """Compute area of a polygon using the shoelace formula."""
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _is_closed_polyline(entity) -> bool:
    """Check if a LWPOLYLINE entity is closed."""
    try:
        return entity.closed or entity.dxf.flags & 1
    except Exception:
        return False


def extract_from_dxf(dxf_path: str, layer_filter: Optional[list[str]] = None) -> dict:
    """
    Extract building data from a DXF file using ezdxf.

    Args:
        dxf_path: Path to the DXF file
        layer_filter: Optional list of layer names to restrict extraction to

    Returns:
        Dict with extracted text entities, polyline boundaries, dimensions, etc.
    """
    result = {
        "text_entities": [],
        "polylines": [],
        "dimensions": [],
        "layers": [],
        "raw_text_labels": [],
        "header_units": None,
        "warnings": [],
    }

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        result["warnings"].append(f"Failed to open DXF file: {str(e)}")
        return result

    # ── Extract header unit variable ──
    try:
        # INSUNITS: 0=unspecified, 1=inches, 2=feet, 4=mm, 5=cm, 6=m
        insunits = doc.header.get("$INSUNITS", 0)
        unit_map = {0: "unspecified", 1: "inches", 2: "feet", 4: "mm", 5: "cm", 6: "m"}
        result["header_units"] = unit_map.get(insunits, f"code_{insunits}")
    except Exception:
        result["header_units"] = "unknown"

    # ── Collect all layer names ──
    try:
        result["layers"] = [layer.dxf.name for layer in doc.layers]
    except Exception:
        pass

    msp = doc.modelspace()

    for entity in msp:
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else ""

        # Apply layer filter if specified
        if layer_filter and layer not in layer_filter:
            continue

        # ── TEXT entities ──
        if entity.dxftype() == "TEXT":
            try:
                text_val = entity.dxf.text or ""
                insert = entity.dxf.insert
                result["text_entities"].append({
                    "type": "TEXT",
                    "text": text_val,
                    "x": float(insert.x),
                    "y": float(insert.y),
                    "layer": layer,
                    "height": float(entity.dxf.height) if hasattr(entity.dxf, "height") else 0,
                })
                result["raw_text_labels"].append(text_val)
            except Exception as e:
                result["warnings"].append(f"TEXT extraction error: {str(e)}")

        # ── MTEXT entities ──
        elif entity.dxftype() == "MTEXT":
            try:
                text_val = entity.plain_text() if hasattr(entity, "plain_text") else (entity.text or "")
                insert = entity.dxf.insert
                result["text_entities"].append({
                    "type": "MTEXT",
                    "text": text_val,
                    "x": float(insert.x),
                    "y": float(insert.y),
                    "layer": layer,
                })
                result["raw_text_labels"].append(text_val)
            except Exception as e:
                result["warnings"].append(f"MTEXT extraction error: {str(e)}")

        # ── LWPOLYLINE entities (room/floor boundaries) ──
        elif entity.dxftype() == "LWPOLYLINE":
            try:
                # Get vertices as (x, y) tuples
                vertices = [(float(v[0]), float(v[1])) for v in entity.get_points(format="xy")]

                is_closed = _is_closed_polyline(entity)
                area = _shoelace_area(vertices) if is_closed and len(vertices) >= 3 else 0.0

                result["polylines"].append({
                    "layer": layer,
                    "vertices": vertices,
                    "is_closed": is_closed,
                    "area": area,
                    "vertex_count": len(vertices),
                })
            except Exception as e:
                result["warnings"].append(f"LWPOLYLINE extraction error: {str(e)}")

        # ── POLYLINE entities (older format) ──
        elif entity.dxftype() == "POLYLINE":
            try:
                vertices = [(float(v.dxf.location.x), float(v.dxf.location.y))
                            for v in entity.vertices]
                is_closed = entity.is_closed
                area = _shoelace_area(vertices) if is_closed and len(vertices) >= 3 else 0.0

                result["polylines"].append({
                    "layer": layer,
                    "vertices": vertices,
                    "is_closed": is_closed,
                    "area": area,
                    "vertex_count": len(vertices),
                })
            except Exception as e:
                result["warnings"].append(f"POLYLINE extraction error: {str(e)}")

        # ── DIMENSION entities ──
        elif entity.dxftype() in ("DIMENSION", "ARC_DIMENSION", "ALIGNED_DIMENSION"):
            try:
                dim_data = {
                    "type": entity.dxftype(),
                    "layer": layer,
                }
                # Try to get the measurement value
                if hasattr(entity, "get_measurement"):
                    dim_data["measurement"] = float(entity.get_measurement())
                elif hasattr(entity.dxf, "actual_measurement"):
                    dim_data["measurement"] = float(entity.dxf.actual_measurement)

                # Get the text override if present
                if hasattr(entity.dxf, "text"):
                    dim_data["text_override"] = entity.dxf.text

                result["dimensions"].append(dim_data)
            except Exception as e:
                result["warnings"].append(f"DIMENSION extraction error: {str(e)}")

    return result


def analyze_dxf_data(dxf_data: dict) -> dict:
    """
    Analyze raw DXF extraction data to find building parameters.

    Takes the output of extract_from_dxf and returns structured building data.
    """
    analysis = {
        "project_info": {"project_name": None, "city": None, "state": None},
        "height": None,
        "floors": None,
        "areas": [],
        "occupancy_hint": None,
        "construction_type": None,
        "kitchen": None,
        "sprinklers": None,
        "basement": {"area": None, "levels": None},
        "header_units": dxf_data.get("header_units"),
        "warnings": dxf_data.get("warnings", []),
    }

    # Combine all text for analysis
    all_text = "\n".join(dxf_data.get("raw_text_labels", []))

    # ── Project info from text ──
    indian_cities = [
        "Mumbai", "Delhi", "Bangalore", "Bengaluru", "Hyderabad", "Ahmedabad",
        "Chennai", "Kolkata", "Pune", "Jaipur", "Surat", "Vadodara", "Rajkot",
        "Nagpur", "Indore", "Thane", "Bhopal", "Lucknow", "Noida", "Gurugram",
    ]
    indian_states = [
        "Maharashtra", "Gujarat", "Karnataka", "Tamil Nadu", "Telangana",
        "Rajasthan", "Uttar Pradesh", "Madhya Pradesh", "Kerala", "West Bengal",
        "Delhi", "Haryana", "Punjab", "Andhra Pradesh", "Goa",
    ]

    text_upper = all_text.upper()
    for city in indian_cities:
        if city.upper() in text_upper:
            analysis["project_info"]["city"] = city
            break
    for state in indian_states:
        if state.upper() in text_upper:
            analysis["project_info"]["state"] = state
            break

    # Look for project name in text
    name_patterns = [
        r"(?:project|building|tower|complex)\s*[:\-]?\s*(.+?)(?:\n|$)",
    ]
    for pat in name_patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            analysis["project_info"]["project_name"] = m.group(1).strip()[:100]
            break

    # ── Height from text or dimensions ──
    height_patterns = [
        r"(?:building\s+)?height\s*[=:]\s*(\d+\.?\d*)\s*(?:m|mtr)?",
        r"(\d+\.?\d*)\s*m\s*(?:height|ht)",
    ]
    for pat in height_patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 2.0 <= val <= 500.0:
                analysis["height"] = {"value": val, "source": "dxf_text"}
                break

    # ── Floor count ──
    floor_patterns = [
        r"(\d+)\s*(?:floors?|storeys?|stories?)",
        r"G\s*\+\s*(\d+)",
    ]
    for pat in floor_patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if "G" in (m.group(0) or "").upper() and "+" in (m.group(0) or ""):
                val += 1
            if 1 <= val <= 200:
                analysis["floors"] = {"value": val, "source": "dxf_text"}
                break

    # ── Areas from closed polylines ──
    closed_areas = sorted(
        [p["area"] for p in dxf_data.get("polylines", []) if p.get("is_closed") and p.get("area", 0) > 0],
        reverse=True,
    )
    if closed_areas:
        for area_val in closed_areas[:5]:  # Top 5 largest areas
            if area_val > 10.0:  # Skip tiny shapes
                analysis["areas"].append({
                    "value": area_val,
                    "label": "polyline_area",
                    "source": "dxf_geometry",
                    "raw": f"closed polyline area={area_val:.2f}",
                })

    # ── Occupancy hints ──
    keyword_map = {
        "hotel": ("A-5", "Hotels"),
        "hospital": ("C-1", "Hospitals & Sanatoria"),
        "school": ("D-1", "Schools up to Senior Secondary"),
        "office": ("E-1", "Offices, Banks, Professional Establishments"),
        "apartment": ("A-4", "Apartment Houses (Flats)"),
        "residential": ("A-4", "Apartment Houses (Flats)"),
        "mall": ("F-2", "Retail Stores, Shops"),
        "shop": ("F-2", "Retail Stores, Shops"),
        "restaurant": ("D-4", "Restaurants"),
        "warehouse": ("G-1", "Low-Hazard Storage"),
    }

    text_lower = all_text.lower()
    for keyword, (code, label) in keyword_map.items():
        if keyword in text_lower:
            analysis["occupancy_hint"] = {
                "hint": keyword,
                "proposed_code": code,
                "proposed_label": f"{code} — {label}",
            }
            break

    # ── Construction type ──
    fire_resistive_kw = ["rcc", "reinforced concrete", "fire-resistive", "r.c.c"]
    wood_kw = ["wood frame", "timber", "ordinary construction"]

    for kw in fire_resistive_kw:
        if kw in text_lower:
            analysis["construction_type"] = {
                "value": "type12",
                "display": "Type 1 / 2 — fire-resistive",
                "keyword": kw,
            }
            break
    if not analysis["construction_type"]:
        for kw in wood_kw:
            if kw in text_lower:
                analysis["construction_type"] = {
                    "value": "type34",
                    "display": "Type 3 / 4 — ordinary/wood-frame",
                    "keyword": kw,
                }
                break

    # ── Kitchen / sprinkler detection ──
    if re.search(r"\bkitchen\b", all_text, re.IGNORECASE):
        analysis["kitchen"] = True
    if re.search(r"\bsprinkler", all_text, re.IGNORECASE):
        analysis["sprinklers"] = True

    # ── Basement ──
    bsmt_m = re.search(r"(\d+)\s*(?:basement|bsmt)", all_text, re.IGNORECASE)
    if bsmt_m:
        val = int(bsmt_m.group(1))
        if 1 <= val <= 10:
            analysis["basement"]["levels"] = val

    return analysis

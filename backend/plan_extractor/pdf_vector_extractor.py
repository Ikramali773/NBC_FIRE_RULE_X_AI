# backend/plan_extractor/pdf_vector_extractor.py
# Stage 2 — Vector PDF Extractor
#
# Uses pdfplumber to extract text, dimensions, and geometry from vector PDFs.
# This is the highest-value, most reliable extraction path.

from __future__ import annotations

import io
import re
import math
from typing import Optional

import pdfplumber

from plan_extractor.label_categorizer import detect_floor_labels, detect_room_labels


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


def _extract_dimension_values(text: str) -> list[dict]:
    """Extract dimension-like numbers from text (e.g. '12.5 m', '3500 mm')."""
    patterns = [
        # Metric with unit: 12.5 m, 3.5m, 12500 mm
        (r"(\d+\.?\d*)\s*(?:m(?:eter|etre)?s?)\b", "m", 1.0),
        (r"(\d+\.?\d*)\s*(?:mm)\b", "mm", 0.001),
        # Height patterns
        (r"(?:height|ht|h)\s*[=:]\s*(\d+\.?\d*)\s*(?:m|mtr)?\b", "m", 1.0),
        # Area patterns
        (r"(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)\b", "sqm", 1.0),
        # Bare numbers near dimension context (e.g. "15000" near a line)
        (r"\b(\d{4,6})\b", "bare_number", 1.0),
    ]
    results = []
    for pattern, unit, factor in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            val = float(match.group(1)) * factor
            results.append({
                "value": val,
                "unit": unit,
                "raw": match.group(0),
                "start": match.start(),
            })
    return results


def _find_title_block_text(words: list[dict], page_width: float, page_height: float) -> dict:
    """
    Try to find title block text — usually in the bottom-right or right-side strip.
    Title blocks typically contain project name, address, scale, etc.
    """
    title_block_words = []
    # Title block is usually in the right 30% and bottom 30% of the page
    for w in words:
        x0 = float(w.get("x0", 0))
        top = float(w.get("top", 0))
        if x0 > page_width * 0.65 or top > page_height * 0.70:
            title_block_words.append(w)

    return {
        "text": " ".join(w.get("text", "") for w in title_block_words),
        "words": title_block_words,
    }


def _extract_project_info(title_text: str) -> dict:
    """
    Extract project name, city, state from title block text.

    Each found subfield is wrapped with its source ("text_label" — direct,
    unambiguous pdfplumber text) so the field mapper can tag it green,
    matching how height/floors/areas are already tagged.
    """
    result = {"project_name": None, "city": None, "state": None}

    # Common project name patterns
    name_patterns = [
        r"(?:project|building|tower|complex|residence|apartment)\s*[:\-]?\s*(.+?)(?:\n|$)",
        r"(?:name)\s*[:\-]\s*(.+?)(?:\n|$)",
    ]
    for pat in name_patterns:
        m = re.search(pat, title_text, re.IGNORECASE)
        if m:
            result["project_name"] = {"value": m.group(1).strip()[:100], "source": "text_label"}
            break

    # Indian states/cities
    indian_states = [
        "Maharashtra", "Gujarat", "Karnataka", "Tamil Nadu", "Telangana",
        "Rajasthan", "Uttar Pradesh", "Madhya Pradesh", "Kerala", "West Bengal",
        "Delhi", "Haryana", "Punjab", "Andhra Pradesh", "Bihar", "Odisha",
        "Jharkhand", "Chhattisgarh", "Assam", "Goa", "Uttarakhand",
    ]
    indian_cities = [
        "Mumbai", "Delhi", "Bangalore", "Bengaluru", "Hyderabad", "Ahmedabad",
        "Chennai", "Kolkata", "Pune", "Jaipur", "Surat", "Lucknow",
        "Kanpur", "Nagpur", "Indore", "Thane", "Bhopal", "Vadodara",
        "Visakhapatnam", "Patna", "Ghaziabad", "Ludhiana", "Agra",
        "Nashik", "Faridabad", "Meerut", "Rajkot", "Varanasi", "Coimbatore",
        "Noida", "Gurugram", "Chandigarh",
    ]

    text_upper = title_text.upper()
    for city in indian_cities:
        if city.upper() in text_upper:
            result["city"] = {"value": city, "source": "text_label"}
            break

    for state in indian_states:
        if state.upper() in text_upper:
            result["state"] = {"value": state, "source": "text_label"}
            break

    return result


def _detect_height(all_text: str, dimension_vals: list[dict]) -> Optional[dict]:
    """Try to detect building height from text."""
    # Look for explicit height mentions
    height_patterns = [
        r"(?:building\s+)?height\s*[=:]\s*(\d+\.?\d*)\s*(?:m|mtr|meter)?",
        r"(?:total\s+)?ht\.?\s*[=:]\s*(\d+\.?\d*)\s*(?:m|mtr)?",
        r"(\d+\.?\d*)\s*m\s*(?:height|ht)",
    ]
    for pat in height_patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 2.0 <= val <= 500.0:  # Reasonable building height range
                return {"value": val, "source": "text_label", "raw": m.group(0)}

    return None


def _detect_floor_count(all_text: str) -> Optional[dict]:
    """Try to detect number of floors from text."""
    patterns = [
        r"(\d+)\s*(?:floors?|storeys?|stories?)",
        r"(?:floors?|storeys?|stories?)\s*[=:]\s*(\d+)",
        r"(?:G\s*\+\s*)(\d+)",  # "G+4" format common in Indian plans
        r"(?:no\.?\s*of\s+floors?)\s*[=:]\s*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            # G+N means N+1 total floors (ground + upper)
            if "G" in (m.group(0) or "").upper() and "+" in (m.group(0) or ""):
                val += 1
            if 1 <= val <= 200:
                return {"value": val, "source": "text_label", "raw": m.group(0)}

    return None


def _detect_areas(all_text: str) -> list[dict]:
    """
    Detect area values from text labels.

    Patterns are checked most-specific-first, and a span already claimed by
    a more specific label (e.g. "basement_area") is never also counted under
    a broader one (e.g. "generic_area") — otherwise the same printed number
    (like "BASEMENT AREA = 380 sqm") is double-counted into the per-floor
    areas list under two different labels, silently corrupting floor-area
    assignment downstream. A wrongly-duplicated area is worse than a missing
    one, so overlap is actively avoided here rather than left to chance.
    """
    areas = []
    claimed_spans: list[tuple[int, int]] = []

    # Most specific first — basement_area and floor_area claim their span
    # before the generic catch-all pattern gets a chance to re-match it.
    area_patterns = [
        (r"(?:basement\s+area)\s*[=:]\s*(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)?",
         "basement_area"),
        (r"(?:floor\s+area|carpet\s+area|built.?up\s+area|area)\s*[=:]\s*(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)?",
         "floor_area"),
        (r"(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)",
         "generic_area"),
    ]
    for pat, label in area_patterns:
        for m in re.finditer(pat, all_text, re.IGNORECASE):
            span = m.span()
            if any(span[0] < end and start < span[1] for start, end in claimed_spans):
                continue
            val = float(m.group(1))
            if 5.0 <= val <= 100000.0:  # Reasonable area range
                areas.append({
                    "value": val,
                    "label": label,
                    "source": "text_label",
                    "raw": m.group(0),
                })
                claimed_spans.append(span)
    return areas


def _detect_occupancy_hints(all_text: str) -> Optional[dict]:
    """Try to detect occupancy type from text keywords."""
    keyword_map = {
        "hotel": ("A-5", "Hotels"),
        "hospital": ("C-1", "Hospitals & Sanatoria"),
        "school": ("D-1", "Schools up to Senior Secondary"),
        "college": ("D-2", "Colleges & Universities"),
        "office": ("E-1", "Offices, Banks, Professional Establishments"),
        "mall": ("F-2", "Retail Stores, Shops"),
        "shop": ("F-2", "Retail Stores, Shops"),
        "apartment": ("A-4", "Apartment Houses (Flats)"),
        "residential": ("A-4", "Apartment Houses (Flats)"),
        "warehouse": ("G-1", "Low-Hazard Storage"),
        "factory": ("G-2", "Moderate-Hazard Storage"),
        "cinema": ("D-3", "Exhibition Halls, Banquet Halls"),
        "banquet": ("D-3", "Exhibition Halls, Banquet Halls"),
        "restaurant": ("D-4", "Restaurants"),
        "hostel": ("A-3", "Dormitories"),
        "dormitory": ("A-3", "Dormitories"),
        "assembly": ("D-5", "Assembly Buildings"),
        "theater": ("D-5", "Assembly Buildings"),
        "theatre": ("D-5", "Assembly Buildings"),
    }

    text_lower = all_text.lower()
    for keyword, (code, label) in keyword_map.items():
        if keyword in text_lower:
            return {
                "hint": keyword,
                "proposed_code": code,
                "proposed_label": f"{code} — {label}",
            }
    return None


def _detect_construction_type(all_text: str) -> Optional[dict]:
    """Detect construction type from keyword matching."""
    text_lower = all_text.lower()

    fire_resistive_keywords = [
        "rcc", "reinforced concrete", "fire-resistive", "fire resistive",
        "steel frame", "concrete encasement", "r.c.c",
    ]
    wood_keywords = [
        "wood frame", "timber", "ordinary construction", "wood-frame",
    ]

    for kw in fire_resistive_keywords:
        if kw in text_lower:
            return {
                "value": "type12",
                "display": "Type 1 / 2 — fire-resistive",
                "keyword": kw,
            }

    for kw in wood_keywords:
        if kw in text_lower:
            return {
                "value": "type34",
                "display": "Type 3 / 4 — ordinary/wood-frame",
                "keyword": kw,
            }

    return None


def _detect_kitchen(all_text: str) -> Optional[bool]:
    """Detect kitchen presence from text."""
    if re.search(r"\bkitchen\b", all_text, re.IGNORECASE):
        return True
    return None


def _detect_sprinklers(all_text: str) -> Optional[bool]:
    """Detect sprinkler mentions."""
    if re.search(r"\bsprinkler", all_text, re.IGNORECASE):
        return True
    return None


def _detect_basement(all_text: str) -> dict:
    """Detect basement info from text."""
    result = {"area": None, "levels": None}

    level_patterns = [
        r"(\d+)\s*(?:basement|bsmt)\s*(?:level|floor)?s?",
        r"(?:basement|bsmt)\s*(?:level|floor)?s?\s*[=:]\s*(\d+)",
        r"B\s*(\d+)\s*(?:floor|level)",
    ]
    for pat in level_patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 10:
                result["levels"] = val
                break

    area_pat = r"(?:basement\s+area)\s*[=:]\s*(\d+\.?\d*)\s*(?:sq\.?\s*m|m²|sqm)?"
    m = re.search(area_pat, all_text, re.IGNORECASE)
    if m:
        result["area"] = float(m.group(1))

    return result


def extract_from_vector_pdf(file_bytes: bytes, only_pages: Optional[set] = None) -> dict:
    """
    Extract building data from a vector PDF using pdfplumber.

    Args:
        only_pages: 0-indexed page numbers to process. When None (default),
            every page is processed — this is the original, page-router-
            unaware behavior. When provided, pages outside this set are
            skipped entirely, so a mixed vector+scanned document only feeds
            its real-text pages into this (green-confidence) path; the
            router-flagged scanned pages are handled separately by the
            OCR path and merged back in by the pipeline.

    Returns a dict with all extracted fields, raw text labels,
    and geometry information.
    """
    result = {
        "raw_text_labels": [],
        "all_words": [],
        "dimension_values": [],
        "polygons": [],
        "title_block": {},
        "project_info": {},
        "height": None,
        "floors": None,
        "areas": [],
        "occupancy_hint": None,
        "construction_type": None,
        "kitchen": None,
        "sprinklers": None,
        "basement": {"area": None, "levels": None},
        "scale": None,
        "floor_labels": [],
        "room_labels": [],
        "warnings": [],
    }

    try:
        pdf_io = io.BytesIO(file_bytes)
        with pdfplumber.open(pdf_io) as pdf:
            all_text_parts = []

            for page_idx, page in enumerate(pdf.pages):
                if only_pages is not None and page_idx not in only_pages:
                    continue

                page_width = float(page.width)
                page_height = float(page.height)

                # ── Extract words with positions ──
                words = page.extract_words(keep_blank_chars=False) or []
                for w in words:
                    w["page"] = page_idx
                    result["all_words"].append(w)

                page_text = page.extract_text() or ""
                all_text_parts.append(page_text)

                # ── Title block extraction ──
                tb = _find_title_block_text(words, page_width, page_height)
                if tb["text"] and len(tb["text"]) > len(result.get("title_block", {}).get("text", "")):
                    result["title_block"] = tb

                # ── Dimension values from text ──
                dims = _extract_dimension_values(page_text)
                result["dimension_values"].extend(dims)

                # ── Vector geometry: lines, rects, curves ──
                try:
                    lines = page.lines or []
                    rects = page.rects or []
                    curves = page.curves or []

                    # Compute areas from closed rectangles
                    for rect in rects:
                        x0 = float(rect.get("x0", 0))
                        y0 = float(rect.get("top", 0))
                        x1 = float(rect.get("x1", 0))
                        y1 = float(rect.get("bottom", 0))
                        w = abs(x1 - x0)
                        h = abs(y1 - y0)
                        area = w * h
                        if area > 100:  # Skip tiny decoration rects
                            result["polygons"].append({
                                "type": "rect",
                                "page": page_idx,
                                "points": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                                "area_pdf_units": area,
                                "width": w,
                                "height": h,
                            })

                    # Compute areas from closed curves (polylines)
                    for curve in curves:
                        pts = curve.get("pts") or curve.get("points", [])
                        if len(pts) >= 3:
                            points = [(float(p[0]), float(p[1])) for p in pts]
                            area = _shoelace_area(points)
                            if area > 100:
                                result["polygons"].append({
                                    "type": "curve",
                                    "page": page_idx,
                                    "points": points,
                                    "area_pdf_units": area,
                                })
                except Exception as e:
                    result["warnings"].append(
                        f"Page {page_idx}: geometry extraction error: {str(e)}"
                    )

            # ── Combine all text for analysis ──
            all_text = "\n".join(all_text_parts)
            result["raw_text_labels"] = [
                w.get("text", "") for w in result["all_words"]
            ]

            # ── Extract structured fields ──
            if result["title_block"].get("text"):
                result["project_info"] = _extract_project_info(
                    result["title_block"]["text"]
                )

            result["height"] = _detect_height(all_text, result["dimension_values"])
            result["floors"] = _detect_floor_count(all_text)
            result["areas"] = _detect_areas(all_text)
            result["occupancy_hint"] = _detect_occupancy_hints(all_text)
            result["construction_type"] = _detect_construction_type(all_text)
            result["basement"] = _detect_basement(all_text)
            result["floor_labels"] = detect_floor_labels(all_text)
            result["room_labels"] = detect_room_labels(all_text)

            if _detect_kitchen(all_text):
                result["kitchen"] = {"value": True, "source": "text_label"}
            if _detect_sprinklers(all_text):
                result["sprinklers"] = {"value": True, "source": "text_label"}

    except Exception as e:
        result["warnings"].append(f"PDF extraction failed: {str(e)}")

    return result

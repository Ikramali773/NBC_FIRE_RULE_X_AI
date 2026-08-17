# backend/plan_extractor/scale_detector.py
# Stage 6 — Scale/Unit Detection
#
# Detects drawing scale from title-block text, DXF headers, or text labels.
# NEVER silently applies a detected scale — always surfaces it as a separate field.

from __future__ import annotations

import re
from typing import Optional


def detect_scale(
    text_labels: list[str],
    dxf_header_units: Optional[str] = None,
) -> dict:
    """
    Attempt to detect the drawing's scale and unit.

    Returns:
        {
            "value": "1:100" or None,
            "unit": "m" or "mm" or None,
            "confidence": "green" | "amber" | "red",
            "source": "title_block_text" | "dxf_header" | "not_detected",
            "note": str
        }
    """
    result = {
        "value": None,
        "unit": None,
        "confidence": "red",
        "source": "not_detected",
        "note": "Scale not detected — area values may be in drawing units, not real-world units.",
    }

    all_text = " ".join(text_labels).strip()

    # A single sheet legitimately carries multiple scales (e.g. a main site
    # plan, a small-scale key/location plan, and a cross-section detail,
    # each printed at a different scale). Picking whichever one a regex
    # happens to match first is exactly the "confidently wrong" failure
    # this project explicitly warns against — collect every distinct value
    # found and only report high(er) confidence when they agree.
    found_ratios: list[str] = []

    # ── Pattern 1: Explicit ratio scale notation (e.g. "1:100", "SCALE 1:200") ──
    scale_patterns = [
        r"(?:scale|sc)\s*[=:]\s*(1\s*:\s*\d+)",
        r"(1\s*:\s*\d{2,4})\b",
        r"(?:scale|sc)\s*[=:]\s*(\d+\s*:\s*\d+)",
    ]
    for pat in scale_patterns:
        for m in re.finditer(pat, all_text, re.IGNORECASE):
            found_ratios.append(m.group(1).replace(" ", ""))

    # ── Pattern 1b: Civil/site-plan scale notation (e.g. "1 CM = 2.00 MT",
    # "SCALE 1CM=20M") — common on layout/site plans, distinct from the
    # architectural "1:100" ratio convention above. 1cm = N metres means a
    # 1:(N*100) ratio, since 1m = 100cm.
    for m in re.finditer(
        r"1\s*cm\.?\s*=\s*(\d+\.?\d*)\s*m(?:t|tr|eters?)?\b",
        all_text, re.IGNORECASE,
    ):
        metres_per_cm = float(m.group(1))
        if 0 < metres_per_cm < 1000:
            found_ratios.append(f"1:{round(metres_per_cm * 100)}")

    distinct_ratios = list(dict.fromkeys(found_ratios))  # de-dupe, keep order

    if len(distinct_ratios) == 1:
        scale_str = distinct_ratios[0]
        result["value"] = scale_str
        result["confidence"] = "amber"
        result["source"] = "title_block_text"
        result["note"] = f"Scale '{scale_str}' found in drawing text. Verify this matches the actual drawing."
    elif len(distinct_ratios) > 1:
        # This sheet has more than one printed scale — do NOT silently pick
        # one. Surface all candidates and require the user to confirm which
        # applies to the area they're measuring.
        result["value"] = distinct_ratios[0]
        result["confidence"] = "amber"
        result["source"] = "title_block_text"
        result["note"] = (
            f"Multiple different scales found on this sheet: {', '.join(distinct_ratios)} "
            "— likely separate sub-drawings (e.g. main plan, key plan, section detail) at "
            f"different scales. Defaulted to '{distinct_ratios[0]}' — confirm which one "
            "actually applies before trusting any distance/placement calculation."
        )

    # ── Pattern 2: DXF header units ──
    if dxf_header_units and dxf_header_units not in ("unspecified", "unknown"):
        unit_to_scale = {
            "mm": "mm",
            "cm": "cm",
            "m": "m",
            "inches": "inches",
            "feet": "feet",
        }
        if dxf_header_units in unit_to_scale:
            result["unit"] = unit_to_scale[dxf_header_units]
            if not result["value"]:
                result["source"] = "dxf_header"
                result["confidence"] = "amber"
                result["note"] = (
                    f"DXF header unit is '{dxf_header_units}'. "
                    "Coordinates are in this unit. Scale notation not found in text."
                )

    # ── Pattern 3: Unit mentions in text ──
    if not result["unit"]:
        if re.search(r"\b(?:all\s+dimensions?\s+(?:are\s+)?in\s+)(mm|meters?|m)\b", all_text, re.IGNORECASE):
            m = re.search(r"\b(?:all\s+dimensions?\s+(?:are\s+)?in\s+)(mm|meters?|m)\b", all_text, re.IGNORECASE)
            if m:
                unit_text = m.group(1).lower()
                result["unit"] = "mm" if unit_text == "mm" else "m"
                if result["confidence"] == "red":
                    result["confidence"] = "amber"
                    result["source"] = "title_block_text"
                    result["note"] = f"Unit '{result['unit']}' found in drawing text."

    return result

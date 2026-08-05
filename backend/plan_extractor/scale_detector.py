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

    # ── Pattern 1: Explicit scale notation (e.g. "1:100", "SCALE 1:200") ──
    scale_patterns = [
        r"(?:scale|sc)\s*[=:]\s*(1\s*:\s*\d+)",
        r"(1\s*:\s*\d{2,4})\b",
        r"(?:scale|sc)\s*[=:]\s*(\d+\s*:\s*\d+)",
    ]

    for pat in scale_patterns:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            scale_str = m.group(1).replace(" ", "")
            result["value"] = scale_str
            result["confidence"] = "amber"
            result["source"] = "title_block_text"
            result["note"] = f"Scale '{scale_str}' found in drawing text. Verify this matches the actual drawing."
            break

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

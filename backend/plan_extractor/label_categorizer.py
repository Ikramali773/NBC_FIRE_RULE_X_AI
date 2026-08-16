# backend/plan_extractor/label_categorizer.py
# Shared floor/level and room/space label categorization.
#
# Used by both the pdfplumber (text-based) and Tesseract (OCR) extraction
# paths so the two stay consistent. Purely keyword matching — no semantic
# understanding, no confidence decisions (that's Stage 8's job).

from __future__ import annotations

import re

FLOOR_LABEL_PATTERNS = [
    r"\bGROUND\s+FLOOR\b", r"\bFIRST\s+FLOOR\b", r"\bSECOND\s+FLOOR\b",
    r"\bTHIRD\s+FLOOR\b", r"\bFOURTH\s+FLOOR\b", r"\bFIFTH\s+FLOOR\b",
    r"\bTOP\s+FLOOR\b", r"\bBASEMENT\b", r"\bMEZZANINE\b", r"\bTERRACE\b",
    r"\bROOF\s*(?:FLOOR|LEVEL)?\b", r"\bSTILT\s*(?:FLOOR|PARKING)?\b",
    r"\bTYPICAL\s+FLOOR\b", r"\bGF\b", r"\bB\s*\d\b", r"\bF\s*\d{1,2}\b",
]

ROOM_LABEL_PATTERNS = [
    r"\bKITCHEN\b", r"\bBEDROOM\b", r"\bBED\s*ROOM\b", r"\bTOILET\b",
    r"\bBATHROOM\b", r"\bBATH\s*ROOM\b", r"\bLIVING\s+ROOM\b", r"\bDINING\b",
    r"\bPARKING\b", r"\bLOBBY\b", r"\bSTORE\s*(?:ROOM)?\b", r"\bOFFICE\b",
    r"\bSTAIRCASE\b", r"\bSTAIR\s*(?:CASE|WELL)?\b", r"\bLIFT\b",
    r"\bBALCONY\b", r"\bCORRIDOR\b", r"\bHALL\b", r"\bPANTRY\b",
    r"\bWASHROOM\b", r"\bLOUNGE\b",
]


def detect_floor_labels(text: str) -> list[str]:
    """Find floor/level labels (GROUND FLOOR, F1, BASEMENT, ...) in raw text."""
    found = set()
    for pat in FLOOR_LABEL_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.add(re.sub(r"\s+", " ", m.group(0).strip().upper()))
    return sorted(found)


def detect_room_labels(text: str) -> list[str]:
    """Find room/space labels (KITCHEN, BEDROOM, TOILET, PARKING, ...) in raw text."""
    found = set()
    for pat in ROOM_LABEL_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.add(re.sub(r"\s+", " ", m.group(0).strip().upper()))
    return sorted(found)

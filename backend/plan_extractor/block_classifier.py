# backend/plan_extractor/block_classifier.py
# Document block classification (scope §12), scoped down to the block types
# an architectural drawing actually has: TITLE_BLOCK, ROOM_LABEL,
# FLOOR_LABEL, DIMENSION, TABLE, KEY_PLAN, NOTES, UNKNOWN.
#
# Unifies two previously-scattered pieces of logic:
#   - pdf_vector_extractor.py's `_find_title_block_text`, a position-only
#     heuristic (right 30% / bottom 30% of the page).
#   - label_categorizer.py's FLOOR_LABEL_PATTERNS / ROOM_LABEL_PATTERNS,
#     keyword-only, with no position awareness or block-level output.
# Position and keyword classification are combined here: a line sitting in
# the title-block zone is a TITLE_BLOCK even if it also contains a keyword
# like "KITCHEN" (title blocks legitimately reference room names as part of
# a project description) — position wins there. Everywhere else, keyword
# content decides the type.

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from plan_extractor.label_categorizer import FLOOR_LABEL_PATTERNS, ROOM_LABEL_PATTERNS


class BlockType(str, Enum):
    TITLE_BLOCK = "title_block"
    ROOM_LABEL = "room_label"
    FLOOR_LABEL = "floor_label"
    DIMENSION = "dimension"
    TABLE = "table"
    KEY_PLAN = "key_plan"
    NOTES = "notes"
    UNKNOWN = "unknown"


# Matches pdf_vector_extractor._find_title_block_text's existing thresholds
# exactly (kept identical on purpose — this is a unification, not a retune).
TITLE_BLOCK_RIGHT_FRACTION = 0.65
TITLE_BLOCK_BOTTOM_FRACTION = 0.70

_DIMENSION_RE = re.compile(r"^\s*\d+\.?\d*\s*(?:mm|m|sq\.?\s*m|m²|sqm)?\s*$", re.IGNORECASE)
_NOTES_RE = re.compile(r"^\s*NOTES?\s*[:\-]", re.IGNORECASE)
_KEY_PLAN_RE = re.compile(r"\b(?:KEY\s+PLAN|LOCATION\s+PLAN)\b", re.IGNORECASE)


@dataclass
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]  # (x0, top, x1, bottom)
    page_index: int
    block_type: BlockType


def is_in_title_block_zone(bbox: tuple[float, float, float, float], page_width: float, page_height: float) -> bool:
    x0, top, _x1, _bottom = bbox
    return x0 > page_width * TITLE_BLOCK_RIGHT_FRACTION or top > page_height * TITLE_BLOCK_BOTTOM_FRACTION


def classify_block_text(text: str) -> BlockType:
    """Keyword-only classification, position-independent."""
    stripped = text.strip()
    if not stripped:
        return BlockType.UNKNOWN
    if _NOTES_RE.search(stripped):
        return BlockType.NOTES
    if _KEY_PLAN_RE.search(stripped):
        return BlockType.KEY_PLAN
    for pat in FLOOR_LABEL_PATTERNS:
        if re.search(pat, stripped, re.IGNORECASE):
            return BlockType.FLOOR_LABEL
    for pat in ROOM_LABEL_PATTERNS:
        if re.search(pat, stripped, re.IGNORECASE):
            return BlockType.ROOM_LABEL
    if _DIMENSION_RE.match(stripped):
        return BlockType.DIMENSION
    return BlockType.UNKNOWN


def classify_line(
    text: str,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_index: int = 0,
) -> TextBlock:
    if is_in_title_block_zone(bbox, page_width, page_height):
        block_type = BlockType.TITLE_BLOCK
    else:
        block_type = classify_block_text(text)
    return TextBlock(text=text, bbox=tuple(bbox), page_index=page_index, block_type=block_type)


def _bbox_center_in(bbox: tuple[float, float, float, float], container: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    cx, cy = (x0 + x1) / 2, (top + bottom) / 2
    tx0, ttop, tx1, tbottom = container
    return tx0 <= cx <= tx1 and ttop <= cy <= tbottom


def classify_page_blocks(page, page_index: int = 0, tables=None) -> list[TextBlock]:
    """
    Classify every extracted text line on a pdfplumber Page into a
    TextBlock. `tables` (ExtractedTable list from table_extractor,
    already quality-filtered) takes priority: a line whose center falls
    inside a passing table's bbox is classified TABLE rather than being
    misread as a stray room/floor label from the table's cell contents.
    """
    blocks: list[TextBlock] = []
    try:
        lines = page.extract_text_lines()
    except Exception:
        lines = []

    table_bboxes = [t.bbox for t in (tables or [])]

    for line in lines:
        bbox = (line["x0"], line["top"], line["x1"], line["bottom"])
        if any(_bbox_center_in(bbox, tb) for tb in table_bboxes):
            blocks.append(TextBlock(text=line["text"], bbox=bbox, page_index=page_index, block_type=BlockType.TABLE))
            continue
        blocks.append(classify_line(line["text"], bbox, page.width, page.height, page_index))

    return blocks

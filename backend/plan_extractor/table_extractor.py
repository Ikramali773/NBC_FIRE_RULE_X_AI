# backend/plan_extractor/table_extractor.py
# Structured table extraction (scope §10-11) via pdfplumber's native
# find_tables() — no Docling dependency (see plan rationale: Docling pulls
# in torch + a full CUDA toolkit for a CPU-only host).
#
# find_tables() detects a grid from intersecting vector lines, which means
# it can just as easily "detect" a table out of a page dense with non-tabular
# vector clutter (hatching, tree symbols, landscaping) as it can a real one.
# Verified against two real files this session:
#   - A real plot/area-statement table (clean, small, high cell fill) is
#     found correctly alongside 9 other small legitimate tables on the same
#     page.
#   - The SAME page also produces one huge false positive: a 44x11 grid
#     covering 91% of the page that swallows unrelated running text, with
#     only 17% of its cells actually non-empty.
#   - A dense CAD export (ALL_BASIC_DRAWING.pdf) produces "tables" on every
#     page from pure line-intersection noise — every single one at 0% cell
#     fill.
# A quality filter based on cell fill ratio cleanly separates these cases
# (all real tables above measured >=0.75 fill; every noise grid measured
# 0.0-0.17), so that is the primary filter here, not table size or bbox
# area alone.

from __future__ import annotations

from dataclasses import dataclass

MIN_FILL_RATIO = 0.35
MIN_TOTAL_CELLS = 2
# A sanity cap, not a tuned value — guards against a pathological grid (e.g.
# hundreds of rows/cols from misread vector noise) that happens to clear the
# fill-ratio bar by chance. No real architectural-drawing table seen so far
# approaches this size.
MAX_TOTAL_CELLS = 2000


@dataclass
class ExtractedTable:
    page_index: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]
    fill_ratio: float

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def to_markdown(self) -> str:
        if not self.rows:
            return ""
        n_cols = self.n_cols
        lines = []
        for i, row in enumerate(self.rows):
            cells = [(c or "").replace("\n", " ").replace("|", "\\|").strip() for c in row]
            cells += [""] * (n_cols - len(cells))
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("|" + "|".join(["---"] * n_cols) + "|")
        return "\n".join(lines)


def _cell_fill_ratio(rows: list[list[str]]) -> float:
    total = sum(len(r) for r in rows)
    if not total:
        return 0.0
    non_empty = sum(1 for r in rows for c in r if c and c.strip())
    return non_empty / total


def _passes_quality_filter(rows: list[list[str]]) -> bool:
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    total_cells = n_rows * n_cols
    if total_cells < MIN_TOTAL_CELLS or total_cells > MAX_TOTAL_CELLS:
        return False
    return _cell_fill_ratio(rows) >= MIN_FILL_RATIO


def extract_tables(page, page_index: int = 0) -> list[ExtractedTable]:
    """Find tables on `page` (a pdfplumber Page) and drop the noisy false
    positives that a pure line-intersection grid produces on non-tabular
    vector-dense content."""
    results: list[ExtractedTable] = []
    try:
        found = page.find_tables()
    except Exception:
        return results

    for table in found:
        try:
            rows = table.extract()
        except Exception:
            continue
        if not rows or not _passes_quality_filter(rows):
            continue
        results.append(
            ExtractedTable(
                page_index=page_index,
                bbox=tuple(table.bbox),
                rows=rows,
                fill_ratio=_cell_fill_ratio(rows),
            )
        )
    return results

# backend/tests/test_floor_detector.py
# Tests for plan_extractor/placement/floor_detector.py against the two
# real multi-floor fire-safety-layout fixtures — this feature's whole
# premise is per-page floor identification on real files, so synthetic
# PDFs wouldn't meaningfully exercise the font-size tie-break logic.

from __future__ import annotations

from pathlib import Path

from plan_extractor.placement.floor_detector import detect_floors

FIXTURES = Path(__file__).parent / "fixtures"


class TestDetectFloors:
    def test_kasturba_gandhi_all_five_floors_labeled_correctly(self):
        """Regression test for a real ambiguity: page 1's text matches BOTH
        'FIRST FLOOR' (the page's actual big caption) and 'TERRACE' (a small
        room literally named Terrace inside that floor's plan). The bigger-
        font match must win — verified this resolves correctly against the
        real file, not a synthetic one, since the ambiguity only exists
        because of the real drawing's actual room naming."""
        pdf_bytes = (FIXTURES / "KASTURBA_GANDHI.pdf").read_bytes()
        floors = detect_floors(pdf_bytes)
        labels = [f.floor_label for f in floors]
        assert labels == ["GROUND FLOOR", "FIRST FLOOR", "SECOND FLOOR", "THIRD FLOOR", "TERRACE"]

    def test_sot_all_floor_three_floors_labeled_correctly(self):
        pdf_bytes = (FIXTURES / "SOT_ALL_FLOOR_3.pdf").read_bytes()
        floors = detect_floors(pdf_bytes)
        labels = [f.floor_label for f in floors]
        assert labels == ["GROUND FLOOR", "FIRST FLOOR", "SECOND FLOOR"]

    def test_page_indices_are_sequential(self):
        pdf_bytes = (FIXTURES / "SOT_ALL_FLOOR_3.pdf").read_bytes()
        floors = detect_floors(pdf_bytes)
        assert [f.page_index for f in floors] == [0, 1, 2]

# backend/tests/test_placement.py
# Tests for Phase 3a (plan_extractor/placement/) against the real
# KASTURBA_GANDHI.pdf fixture — this feature's whole premise depends on
# real building geometry, so synthetic reportlab PDFs (used in
# test_plan_extractor.py) aren't a meaningful substitute here.

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plan_extractor.placement.geometry_extractor import extract_geometry
from plan_extractor.placement.walkable_graph import build_walkable_graph
from plan_extractor.placement.scale_calibration import calibrate_scale
from plan_extractor.placement.placement_algorithm import suggest_placement
from plan_extractor.placement.validate_kasturba import extract_ground_truth, run_validation
from routes.placement import router as placement_router

FIXTURE = Path(__file__).parent / "fixtures" / "KASTURBA_GANDHI.pdf"
PDF_BYTES = FIXTURE.read_bytes()


class TestGeometryExtraction:
    def test_finds_walkable_interior_on_ground_floor(self):
        geometry = extract_geometry(PDF_BYTES, page_index=0)
        assert not geometry.warnings
        assert len(geometry.interior_regions) > 0
        # The building interior should dominate the page — not a sliver.
        assert geometry.interior_regions[0]["size_px"] > 1_000_000


class TestWalkableGraph:
    def test_builds_single_connected_graph(self):
        geometry = extract_geometry(PDF_BYTES, page_index=0)
        walkable = build_walkable_graph(geometry)
        assert walkable.graph.number_of_nodes() > 0
        # Must be a single connected component (see build_walkable_graph's
        # largest-component filtering) — a placement algorithm relying on
        # graph-distance coverage would silently miscount otherwise.
        import networkx as nx
        assert nx.number_connected_components(walkable.graph) == 1
        assert len(walkable.junction_nodes) > 0


class TestScaleCalibration:
    def test_calibrates_from_real_room_dimensions(self):
        geometry = extract_geometry(PDF_BYTES, page_index=0)
        scale = calibrate_scale(PDF_BYTES, 0, geometry)
        assert scale.mm_per_pt is not None
        assert scale.confidence in ("amber", "green")
        # Sanity bound: a real architectural drawing's scale shouldn't be
        # wildly outside plausible print-scale ranges (roughly 1:20-1:500).
        assert 5 < scale.mm_per_pt < 200


class TestPlacementAlgorithm:
    def test_produces_corridor_biased_coverage(self):
        geometry = extract_geometry(PDF_BYTES, page_index=0)
        walkable = build_walkable_graph(geometry)
        scale = calibrate_scale(PDF_BYTES, 0, geometry)
        result = suggest_placement(geometry, walkable, scale, "moderate")

        assert result.points, "expected at least one suggested point"
        assert result.rating == "3A"
        assert result.max_area_m2 == 150
        # Not "one per room" — this floor has ~20 rooms; a sane coverage
        # placement should land well under that per the corridor-bias rule.
        assert len(result.points) < 60

    def test_rejects_unknown_hazard_type(self):
        geometry = extract_geometry(PDF_BYTES, page_index=0)
        walkable = build_walkable_graph(geometry)
        scale = calibrate_scale(PDF_BYTES, 0, geometry)
        try:
            suggest_placement(geometry, walkable, scale, "extreme")
            assert False, "expected ValueError for unknown hazard_type"
        except ValueError:
            pass


class TestKasturbaGroundTruthValidation:
    def test_finds_three_real_extinguisher_stations(self):
        """Regression test for the Phase 3a Step 6 validation evidence:
        the real drawing has exactly 3 CO2+ABC extinguisher station pairs
        on the ground floor, confirmed by direct visual inspection."""
        stations = extract_ground_truth(PDF_BYTES, page_index=0)
        assert len(stations) == 3

    def test_suggested_points_land_near_every_real_station(self):
        """The core pass/fail evidence: every real station should have a
        suggested point within a small multiple of the coverage radius —
        i.e. the algorithm doesn't miss real equipment locations."""
        report = run_validation()
        moderate = report["by_hazard_level"]["moderate"]
        assert moderate["mean_real_station_to_nearest_suggestion_m"] < moderate["coverage_radius_m"]


class TestPlacementRoute:
    def test_suggest_endpoint_end_to_end(self):
        app = FastAPI()
        app.include_router(placement_router)
        client = TestClient(app)

        resp = client.post(
            "/api/placement/suggest",
            files={"file": ("KASTURBA_GANDHI.pdf", PDF_BYTES, "application/pdf")},
            data={"page_index": "0", "hazard_type": "moderate"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hazardType"] == "moderate"
        assert len(data["points"]) > 0
        assert data["scale"]["mm_per_pt"] is not None
        assert all("locationDescription" in p for p in data["points"])

    def test_rejects_non_pdf(self):
        app = FastAPI()
        app.include_router(placement_router)
        client = TestClient(app)

        resp = client.post(
            "/api/placement/suggest",
            files={"file": ("plan.dwg", b"not a pdf", "application/octet-stream")},
            data={"page_index": "0", "hazard_type": "moderate"},
        )
        assert resp.status_code == 400

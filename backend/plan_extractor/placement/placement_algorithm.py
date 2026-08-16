# backend/plan_extractor/placement/placement_algorithm.py
# Phase 3a, Step 4 — Fire extinguisher placement algorithm.
#
# Reuses the EXISTING IS 2190:2024 Table 1 coverage rule from
# backend/class_a_checker.py (CLASS_A_TABLE: max 300/150/100 m² per
# extinguisher for low/moderate/high hazard) — this codebase has no
# separate "maximum travel distance" figure for fire extinguishers (that
# concept exists only for egress/exit travel distance, a different NBCS
# rule). The area rule is converted to an equivalent coverage radius
# (r = sqrt(max_area_m2 / pi)) and used as the placement algorithm's
# spacing constraint. class_a_checker.py itself is never modified — only
# imported, read-only, exactly like the rest of the rules engine.
#
# Algorithm: greedy set-cover over the walkable graph (walkable_graph.py).
# Candidate points are the graph's significant nodes (junctions and leaf
# dead-ends). Each round, pick the uncovered candidate whose coverage
# radius reaches the most still-uncovered nodes — ties broken in favor of
# junction nodes, biasing placement toward corridor/circulation points
# rather than one dot per room, matching observed real practice. Repeat
# until every walkable node is within radius of a chosen point.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from class_a_checker import CLASS_A_TABLE
from .geometry_extractor import GeometryResult
from .scale_calibration import ScaleCalibration
from .walkable_graph import WalkableGraph


@dataclass
class PlacementPoint:
    row: int
    col: int
    x_pt: float
    y_pt: float
    is_junction: bool
    covers: int  # how many walkable nodes this point covers, at selection time


@dataclass
class PlacementResult:
    hazard_type: str
    rating: str
    max_area_m2: float
    coverage_radius_m: float
    coverage_radius_pt: float
    points: list[PlacementPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _coverage_radius_pt(hazard_type: str, mm_per_pt: float) -> tuple[float, float, float, str]:
    entry = CLASS_A_TABLE[hazard_type]
    max_area_m2 = entry["max_area_m2"]
    radius_m = math.sqrt(max_area_m2 / math.pi)
    radius_mm = radius_m * 1000
    radius_pt = radius_mm / mm_per_pt
    return max_area_m2, radius_m, radius_pt, entry["rating"]


def suggest_placement(
    geometry: GeometryResult,
    walkable: WalkableGraph,
    scale: ScaleCalibration,
    hazard_type: str,
) -> PlacementResult:
    warnings = list(walkable.warnings)

    if hazard_type not in CLASS_A_TABLE:
        raise ValueError(f"Unknown hazard_type '{hazard_type}' — expected one of {list(CLASS_A_TABLE)}.")
    if not scale.mm_per_pt:
        raise ValueError("Scale calibration has no value — cannot place equipment without a confirmed scale.")

    max_area_m2, radius_m, radius_pt, rating = _coverage_radius_pt(hazard_type, scale.mm_per_pt)

    G = walkable.graph
    if G.number_of_nodes() == 0:
        return PlacementResult(
            hazard_type=hazard_type, rating=rating, max_area_m2=max_area_m2,
            coverage_radius_m=radius_m, coverage_radius_pt=radius_pt,
            points=[], warnings=warnings + ["Walkable graph is empty — nothing to place."],
        )

    # All-pairs shortest path in raster px, over the small simplified graph.
    dist = dict(nx.all_pairs_dijkstra_path_length(G, weight="length_px"))
    radius_px = radius_pt * walkable.raster_scale

    all_nodes = set(G.nodes())
    uncovered = set(all_nodes)
    selected: list[PlacementPoint] = []

    # Candidates: junctions first (corridor/circulation bias), then leaves,
    # matching the scope's explicit "prioritize corridor and circulation
    # points... not one per room" rule.
    candidates = list(walkable.junction_nodes) + [n for n in walkable.leaf_nodes if n not in walkable.junction_nodes]

    safety_limit = len(all_nodes) + 10
    while uncovered and safety_limit > 0:
        safety_limit -= 1
        best_node, best_covered, best_is_junction = None, set(), False
        for node in candidates:
            if node not in dist:
                continue
            reachable = {n for n, d in dist[node].items() if d <= radius_px}
            newly_covered = reachable & uncovered
            if len(newly_covered) > len(best_covered) or (
                len(newly_covered) == len(best_covered) and node in walkable.junction_nodes and not best_is_junction
            ):
                best_node, best_covered, best_is_junction = node, newly_covered, node in walkable.junction_nodes

        if best_node is None or not best_covered:
            # No remaining candidate covers any uncovered node within radius —
            # place directly on the nearest still-uncovered node itself.
            fallback = next(iter(uncovered))
            best_node = fallback
            best_covered = {n for n, d in dist.get(fallback, {fallback: 0}).items() if d <= radius_px} & uncovered
            best_covered = best_covered or {fallback}
            best_is_junction = fallback in walkable.junction_nodes

        row, col = best_node
        x_pt, y_pt = geometry.to_pdf_point(row, col)
        selected.append(PlacementPoint(
            row=row, col=col, x_pt=x_pt, y_pt=y_pt,
            is_junction=best_is_junction, covers=len(best_covered),
        ))
        uncovered -= best_covered
        if best_node in uncovered:
            uncovered.discard(best_node)

    if safety_limit <= 0 and uncovered:
        warnings.append(
            f"Coverage loop hit its safety limit with {len(uncovered)} walkable node(s) still "
            "uncovered — placement may be incomplete for this floor."
        )

    return PlacementResult(
        hazard_type=hazard_type, rating=rating, max_area_m2=max_area_m2,
        coverage_radius_m=radius_m, coverage_radius_pt=radius_pt,
        points=selected, warnings=warnings,
    )

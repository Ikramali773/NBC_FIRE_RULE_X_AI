# backend/plan_extractor/placement/walkable_graph.py
# Phase 3a, Step 2 — Walkable-space graph derivation.
#
# From the raster interior mask produced by geometry_extractor.py, derive a
# simplified graph of open, walkable floor space: corridors, room interiors,
# and doorway connections, with walls already subtracted (they're simply not
# part of the interior mask). The placement algorithm (Step 4) works on this
# graph, never on the raw drawing.
#
# Approach: skeletonize (medial axis) the interior mask to get a 1px-wide
# walkable spine, build a pixel-adjacency graph from it, prune short
# spurious branches (artifacts from furniture/fixture-scale mask noise),
# then simplify by contracting straight degree-2 chains into single
# weighted edges between "significant" nodes (junctions and dead-ends) —
# this keeps the graph small enough for repeated shortest-path queries in
# the placement algorithm, instead of operating on tens of thousands of
# individual raster pixels.

from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from skimage.morphology import skeletonize

from .geometry_extractor import GeometryResult

PRUNE_LEN_PX = 40  # spurious-branch length threshold, in raster px (see Step 1's constants note)


@dataclass
class WalkableGraph:
    graph: nx.Graph                 # simplified graph; nodes are (row, col) raster coords,
                                     # edge weight "length_px" is real path length along the skeleton
    junction_nodes: set[tuple[int, int]]   # degree >= 3 — corridor/circulation points
    leaf_nodes: set[tuple[int, int]]       # degree == 1 — room-interior dead ends
    raster_scale: float
    warnings: list[str] = field(default_factory=list)


def _pixel_graph(mask: np.ndarray) -> nx.Graph:
    ys, xs = np.nonzero(mask)
    pixels = set(zip(ys.tolist(), xs.tolist()))
    G = nx.Graph()
    G.add_nodes_from(pixels)
    for y, x in pixels:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                n = (y + dy, x + dx)
                if n in pixels:
                    dist = math.hypot(dy, dx)
                    G.add_edge((y, x), n, length_px=dist)
    return G


def _prune_short_branches(G: nx.Graph, prune_len_px: float) -> nx.Graph:
    """Iteratively strip dead-end paths shorter than prune_len_px — these are
    almost always mask-boundary noise (a fixture corner, a hatch line), not
    real room-entry points, which tend to be longer."""
    G = G.copy()
    changed = True
    rounds = 0
    while changed and rounds < 50:
        changed = False
        rounds += 1
        degrees = dict(G.degree())
        leaf_nodes = [n for n, d in degrees.items() if d == 1]
        to_remove: set = set()
        for leaf in leaf_nodes:
            if leaf in to_remove:
                continue
            path = [leaf]
            cur, prev, length = leaf, None, 0.0
            while True:
                neighbors = [n for n in G.neighbors(cur) if n != prev]
                if len(neighbors) != 1:
                    break
                prev, cur = cur, neighbors[0]
                path.append(cur)
                length += G[path[-2]][path[-1]]["length_px"]
                if length > prune_len_px:
                    break
            if length <= prune_len_px:
                to_remove.update(path[:-1])  # keep the junction/endpoint itself
        if to_remove:
            G.remove_nodes_from(to_remove)
            changed = True
    return G


def _simplify(G: nx.Graph) -> nx.Graph:
    """Contract degree-2 chains into single weighted edges between
    'significant' nodes (degree 1 or >= 3), collapsing tens of thousands of
    pixel nodes down to a small topological graph."""
    degrees = dict(G.degree())
    significant = {n for n, d in degrees.items() if d != 2}
    simplified = nx.Graph()
    simplified.add_nodes_from(significant)

    visited_edges: set = set()
    for start in significant:
        for first_hop in G.neighbors(start):
            edge_key = frozenset((start, first_hop))
            if edge_key in visited_edges:
                continue
            # Walk the degree-2 chain from `start` through `first_hop` until
            # we reach the next significant node.
            length = G[start][first_hop]["length_px"]
            prev, cur = start, first_hop
            visited_edges.add(edge_key)
            while cur not in significant:
                nxt = [n for n in G.neighbors(cur) if n != prev]
                if not nxt:
                    break
                nxt = nxt[0]
                visited_edges.add(frozenset((cur, nxt)))
                length += G[cur][nxt]["length_px"]
                prev, cur = cur, nxt
            if cur in significant and cur != start:
                if simplified.has_edge(start, cur):
                    if simplified[start][cur]["length_px"] <= length:
                        continue
                simplified.add_edge(start, cur, length_px=length)
    return simplified


def build_walkable_graph(
    geometry: GeometryResult,
    prune_len_px: float = PRUNE_LEN_PX,
) -> WalkableGraph:
    warnings = list(geometry.warnings)

    if not geometry.interior_regions:
        return WalkableGraph(
            graph=nx.Graph(), junction_nodes=set(), leaf_nodes=set(),
            raster_scale=geometry.raster_scale,
            warnings=warnings + ["No interior geometry to build a walkable graph from."],
        )

    skeleton = skeletonize(geometry.interior_mask)
    pixel_graph = _pixel_graph(skeleton)
    pruned = _prune_short_branches(pixel_graph, prune_len_px)
    simplified = _simplify(pruned)

    if simplified.number_of_nodes() == 0:
        warnings.append("Walkable graph is empty after pruning — try a smaller prune_len_px.")

    degrees = dict(simplified.degree())
    junctions = {n for n, d in degrees.items() if d >= 3}
    leaves = {n for n, d in degrees.items() if d == 1}

    # Keep only the largest connected component — small disconnected
    # fragments are almost always leftover noise (e.g. an isolated
    # decoration or a region the pruning step split off).
    if simplified.number_of_nodes() > 0:
        components = list(nx.connected_components(simplified))
        components.sort(key=len, reverse=True)
        if len(components) > 1:
            dropped = sum(len(c) for c in components[1:])
            warnings.append(
                f"Dropped {len(components) - 1} disconnected walkable-graph fragment(s) "
                f"({dropped} nodes) — kept the largest connected component."
            )
            simplified = simplified.subgraph(components[0]).copy()
            junctions &= components[0]
            leaves &= components[0]

    return WalkableGraph(
        graph=simplified, junction_nodes=junctions, leaf_nodes=leaves,
        raster_scale=geometry.raster_scale, warnings=warnings,
    )

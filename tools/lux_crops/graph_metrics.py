"""Graph-theoretic and SUMO-network profile of every square window of the LuST network.

Each window is cropped like build_lux_crop.py (see lust_graph.py). Its topology is described with networkx
(degrees, cycles, cuts, centrality, connectivity, paths); traffic lights, motorways and road classes are read
from the SUMO network (sumo_properties).
Notation for one window:
    D  directed road graph of the crop (arc weight = free-flow travel time; parallel arcs merged)
    U  underlying undirected simple graph of D
    V_in   nodes inside the window (the rest are the outer ends of arcs that cross the border)
    junctions  nodes of V_in with degree != 2 in U (degree-2 nodes only split a street)

Usage (from the repository root):
    venv/bin/python tools/lux_crops/graph_metrics.py [--size 900] [--stride 300] [--workers 8]
Writes tools/lux_crops/out/windows_<size>.csv, one row per window.
"""
import argparse
import itertools
import math
import os
from multiprocessing import Pool

import networkx as nx
import numpy as np
import pandas as pd

import lust_graph as lg

OUT_DIR = os.path.join(lg.HERE, "out")
G = None  # full LuST graph, loaded once per worker process


# ----------------------------------------------------------------------------- graphs of a window
def window_graphs(crop):
    """Directed simple graph D (fastest arc kept between two nodes) and its undirected graph U."""
    D = nx.DiGraph()
    D.add_nodes_from(crop.nodes(data=True))
    for u, v, a in crop.edges(data=True):
        if u != v and (not D.has_edge(u, v) or a["time"] < D[u][v]["time"]):
            D.add_edge(u, v, **a)
    return D, nx.Graph(D)


# ----------------------------------------------------------------------------- degree distribution
def degree_profile(U, inner):
    """Degree distribution of the junctions (degree measured in the full crop, so border streets count)."""
    k = np.array([U.degree(v) for v in inner if U.degree(v) != 2])
    return {
        "n_junctions": len(k),
        "mean_degree": k.mean(),
        "dead_end_share": np.mean(k == 1),   # degree-1 junctions: cul-de-sacs
        "four_way_share": np.mean(k >= 4),   # degree >= 4: crossings typical of grids
    }


# ----------------------------------------------------------------------------- cycles
def cycle_profile(U, n_junctions):
    """Cyclomatic number mu = |E| - |V| + c (independent cycles) and meshedness alpha = mu / (2n - 5).

    alpha is the share of the maximum number of independent cycles a planar graph with n junctions can
    have: 0 for a tree, 1 for a maximal planar graph. Degree-2 nodes do not change mu.
    """
    mu = U.number_of_edges() - U.number_of_nodes() + nx.number_connected_components(U)
    return {"cyclomatic_number": mu, "meshedness": mu / max(1, 2 * n_junctions - 5)}


# ----------------------------------------------------------------------------- cuts and bottlenecks
def smooth(H):
    """Contract every degree-2 node of H into a single edge between its two neighbours (MultiGraph).

    SUMO splits a street into several edges wherever an attribute changes (lanes, speed). Those degree-2 nodes
    are not junctions, and their number is arbitrary; contracting them leaves the junction topology only.
    """
    M = nx.MultiGraph(H)
    for v in list(M):
        if M.degree(v) == 2 and len(set(M.neighbors(v))) == 2:
            a, b = M.neighbors(v)
            M.remove_node(v)
            M.add_edge(a, b)
    return M


def bottleneck_width(S, min_side=0.2):
    """Fewest streets whose closure splits the junction graph S into two parts, the smaller holding >= min_side of
    its nodes. Exact for widths 1 to 3 (bridges after removing 0, 1 or 2 edges); a width of 4 or more is the
    smallest such cut found by a sweep over the Fiedler vector, an upper bound."""
    n = S.number_of_nodes()
    splits = lambda H: n - max(map(len, nx.connected_components(H))) >= min_side * n

    def bridge_completes_cut(removed):
        H = S.copy()
        H.remove_edges_from(removed)
        for a, b in nx.bridges(nx.Graph(H)):
            if H.number_of_edges(a, b) == 1:
                H2 = H.copy()
                H2.remove_edge(a, b)
                if splits(H2):
                    return True
        return False

    edges = list(S.edges(keys=True))
    if bridge_completes_cut([]):
        return 1
    if any(bridge_completes_cut([e]) for e in edges):
        return 2
    nodes = list(S)
    vector = nx.fiedler_vector(nx.Graph(S), normalized=True, method="tracemin_lu", seed=0)
    side, sweep = set(), math.inf
    for k, i in enumerate(np.argsort(vector)[:-1], 1):
        side.add(nodes[i])
        if min(k, n - k) >= min_side * n:
            sweep = min(sweep, sum(1 for a, b, _ in S.edges(side, keys=True) if (a in side) != (b in side)))
    if sweep <= 3 or any(bridge_completes_cut([e, f]) for e, f in itertools.combinations(edges, 2)):
        return 3
    return int(sweep)


def bottleneck_profile(U, inner):
    """Bridges and cut vertices of the 2-core, the normalised algebraic connectivity (Fiedler value) and the
    bottleneck width.

    The 2-core removes dead-end trees, so a bridge there is a single street whose closure splits the
    meshed part of the network in two (most bridges cut off small pockets). A small Fiedler value means the graph
    is close to falling apart (a sparse cut relative to the size of the parts). The bottleneck width counts the
    streets of the narrowest cut between two substantial parts. Fiedler value and bottleneck width are computed on
    the junction graph (degree-2 nodes contracted), so that they do not depend on how SUMO split streets into edges.
    """
    core = nx.k_core(U, 2)
    if core.number_of_nodes() < 3:
        return {"bridges": 0, "cut_vertices": 0, "algebraic_connectivity": 0.0, "bottleneck_width": 0}
    giant = smooth(core.subgraph(max(nx.connected_components(core), key=len)))
    return {
        "bridges": sum(1 for u, v in nx.bridges(core) if u in inner or v in inner),
        "cut_vertices": sum(1 for v in nx.articulation_points(core) if v in inner),
        # rounded: the eigensolver differs between runs only in the last floating-point digits
        "algebraic_connectivity": round(nx.algebraic_connectivity(giant, normalized=True, method="tracemin_lu", seed=0), 10),
        "bottleneck_width": bottleneck_width(giant),
    }


def side_cuts(U, box):
    """Edge connectivity between opposite sides of the window (Menger: = number of edge-disjoint paths).

    Border nodes are the outer ends of streets crossing the west/east (south/north) edge of the window.
    A super-source is joined to one side and a super-sink to the other; lambda = minimum edge cut.
    """
    x0, x1, y0, y1 = box
    sides = {"W": [], "E": [], "S": [], "N": []}
    for v in U:
        x, y = U.nodes[v]["x"], U.nodes[v]["y"]
        gaps = {"W": x0 - x, "E": x - x1, "S": y0 - y, "N": y - y1}
        side, gap = max(gaps.items(), key=lambda kv: kv[1])
        if gap > 0:
            sides[side].append(v)

    def lam(a, b):
        if not sides[a] or not sides[b]:
            return 0
        H = U.copy()
        H.add_edges_from(("SOURCE", v) for v in sides[a])
        H.add_edges_from((v, "SINK") for v in sides[b])
        return nx.edge_connectivity(H, "SOURCE", "SINK")

    we, sn = lam("W", "E"), lam("S", "N")
    return {"cut_west_east": we, "cut_south_north": sn, "min_side_cut": min(we, sn)}


# ----------------------------------------------------------------------------- centrality
def gini(values):
    x = np.sort(np.asarray(values, float))
    return float((2 * np.arange(1, len(x) + 1) - len(x) - 1) @ x / (len(x) * x.sum())) if x.sum() else 0.0


def centrality_profile(D):
    """Edge betweenness (shortest paths by travel time). Gini of its distribution = how much the shortest
    paths concentrate on a few arcs: high for a corridor/hub network, low for a uniform grid."""
    eb = np.array(list(nx.edge_betweenness_centrality(D, weight="time").values()))
    return {"betweenness_gini": gini(eb), "betweenness_max": eb.max()}


# ----------------------------------------------------------------------------- reachability and distances
def reachability_profile(D, inner):
    """Share of inside nodes in the largest strongly connected component (every node reaches every other)."""
    scc = max(nx.strongly_connected_components(D.subgraph(inner)), key=len)
    return {"scc_share": len(scc) / len(inner)}


def circuity(D, inner, rng, n_sources=40):
    """Median detour index: shortest-path length / straight-line distance, for inside node pairs > 300 m apart."""
    nodes = sorted(inner)
    ratios = []
    for s in rng.choice(nodes, min(n_sources, len(nodes)), replace=False):
        dist = nx.single_source_dijkstra_path_length(D, s, weight="length")
        for t, d in dist.items():
            if t in inner and t != s:
                straight = math.dist((D.nodes[s]["x"], D.nodes[s]["y"]), (D.nodes[t]["x"], D.nodes[t]["y"]))
                if straight > 300:
                    ratios.append(d / straight)
    return {"circuity": float(np.median(ratios)) if ratios else np.nan}


def route_choice(D, inner, rng, n_pairs=40, slack=1.3, max_overlap=0.5, max_paths=50, motorway_diff=100):
    """Share of border OD pairs that have a choice of route, and share whose choice involves the motorway.

    OD pairs join an entry junction (first junction after a street enters the window) to an exit junction
    (last junction before a street leaves it), > 400 m apart; up to `n_pairs` are sampled. For each pair,
    Yen's algorithm (nx.shortest_simple_paths) lists the simple paths in order of travel time. The pair has a
    choice if, within `slack` x the fastest travel time, there is a path sharing at most `max_overlap` of its
    arcs (Jaccard) with the fastest one. At most `max_paths` paths are listed per pair.
    motorway_choice_share: share of pairs whose alternative differs from the fastest path by at least
    `motorway_diff` metres of motorway, i.e. the choice is between more and less motorway.
    """
    entries = sorted({v for u, v in D.edges if u not in inner and v in inner})
    exits = sorted({u for u, v in D.edges if u in inner and v not in inner})
    xy = lambda v: (D.nodes[v]["x"], D.nodes[v]["y"])
    pairs = [(s, t) for s in entries for t in exits if math.dist(xy(s), xy(t)) > 400 and nx.has_path(D, s, t)]
    out = {"n_entries": len(entries), "n_exits": len(exits), "n_od_pairs": len(pairs)}
    if not pairs:
        return out | {"route_choice_share": np.nan, "motorway_choice_share": np.nan}
    pairs = [pairs[i] for i in rng.choice(len(pairs), min(n_pairs, len(pairs)), replace=False)]
    motorway_m = lambda p: sum(D[a][b]["length"] for a, b in zip(p[:-1], p[1:]) if D[a][b]["type"].startswith("highway.motorway"))
    has_choice, motorway_choice = [], []
    for s, t in pairs:
        paths = nx.shortest_simple_paths(D, s, t, weight="time")
        fastest = next(paths)
        best, first = nx.path_weight(D, fastest, "time"), set(zip(fastest[:-1], fastest[1:]))
        found, via_motorway = False, False
        for path in itertools.islice(paths, max_paths - 1):
            if nx.path_weight(D, path, "time") > slack * best:
                break
            arcs = set(zip(path[:-1], path[1:]))
            if len(arcs & first) / len(arcs | first) <= max_overlap:
                found = True
                via_motorway = abs(motorway_m(path) - motorway_m(fastest)) >= motorway_diff
                break
        has_choice.append(found)
        motorway_choice.append(via_motorway)
    return out | {"route_choice_share": float(np.mean(has_choice)), "motorway_choice_share": float(np.mean(motorway_choice))}


def reciprocity(D):
    """Share of arcs whose opposite arc also exists (1 = every street two-way, low = many one-way streets)."""
    return {"reciprocity": nx.overall_reciprocity(D)}


# ----------------------------------------------------------------------------- geometry and SUMO attributes
def orientation_order(D):
    """Boeing (2019) orientation order: 1 = all streets on a perfect grid, 0 = bearings uniformly spread."""
    hist = np.zeros(36)
    for u, v, shape in nx.Graph(D).edges(data="shape"):
        for (xa, ya), (xb, yb) in zip(shape[:-1], shape[1:]):
            bearing = math.degrees(math.atan2(xb - xa, yb - ya)) % 180
            hist[int(((bearing + 5) % 180) // 10)] += math.hypot(xb - xa, yb - ya)
    p = np.r_[hist[:18], hist[:18]] / (2 * hist[:18].sum())  # both directions of each street
    entropy = -(p[p > 0] * np.log(p[p > 0])).sum()
    return {"orientation_order": 1 - ((entropy - math.log(4)) / (math.log(36) - math.log(4))) ** 2}


def sumo_properties(D, U, inner):
    """Properties read from the SUMO network rather than from the topology.

    Traffic control: traffic-light junctions (SUMO junction type traffic_light*) and their share of the
    junctions; the other LuST junctions are priority junctions.
    Motorway: length share of highway.motorway* arcs, number of ramps (highway.motorway_link arcs) and
    motorway access points (motorway arcs crossing the window border).
    Road hierarchy: length share of primary/secondary roads, mean lanes and speed limit (length-weighted).
    """
    arcs = [a for *_, a in D.edges(data=True)]
    length = sum(a["length"] for a in arcs)
    by_type = lambda prefix: sum(a["length"] for a in arcs if a["type"].startswith(prefix)) / length
    junctions = [v for v in inner if U.degree(v) != 2]
    tls = sum(1 for v in inner if D.nodes[v]["tls"])
    return {
        "tls": tls,
        "tls_share": tls / max(1, len(junctions)),
        "motorway_share": by_type("highway.motorway"),
        "motorway_ramps": sum(1 for a in arcs if a["type"] == "highway.motorway_link"),
        "motorway_access": sum(1 for u, v, t in D.edges(data="type")
                               if t.startswith("highway.motorway") and ((u in inner) != (v in inner))),
        "major_road_share": by_type("highway.primary") + by_type("highway.secondary"),
        "mean_lanes": sum(a["lanes"] * a["length"] for a in arcs) / length,
        "mean_speed_limit": sum(a["speed"] * a["length"] for a in arcs) / length,
        "n_arcs": D.number_of_edges(),
        "road_km": sum(a["length"] for *_, a in U.edges(data=True)) / 1000,
    }


# ----------------------------------------------------------------------------- one window
def profile(box):
    crop = lg.crop(G, box)
    D, U = window_graphs(crop)
    inner = {v for v in D if lg.inside(D, v, box)}
    if len(inner) < 20:
        return None
    rng = np.random.default_rng(int(box[0]) * 100_003 + int(box[2]))  # reproducible sampling per window
    row = {"x0": box[0], "x1": box[1], "y0": box[2], "y1": box[3],
           "place": lg.place_name((box[0] + box[1]) / 2, (box[2] + box[3]) / 2)}
    row.update(degree_profile(U, inner))
    if row["n_junctions"] < 15:
        return None
    row.update(cycle_profile(U, row["n_junctions"]))
    row.update(bottleneck_profile(U, inner))
    row.update(side_cuts(U, box))
    row.update(centrality_profile(D))
    row.update(reachability_profile(D, inner))
    row.update(circuity(D, inner, rng))
    row.update(route_choice(D, inner, rng))
    row.update(reciprocity(D))
    row.update(orientation_order(D))
    row.update(sumo_properties(D, U, inner))
    return row


def _init():
    global G
    G = lg.load_lust()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=float, default=900.0, help="window side in metres")
    ap.add_argument("--stride", type=float, default=300.0, help="distance between window origins in metres")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    xmin, ymin, xmax, ymax = lg.load_lust().graph["bounds"]
    boxes = [(float(x), float(x + args.size), float(y), float(y + args.size))
             for x in np.arange(xmin, xmax - args.size + 1, args.stride)
             for y in np.arange(ymin, ymax - args.size + 1, args.stride)]
    boxes.append(lg.BONNEVOIE[1])
    with Pool(args.workers, initializer=_init) as pool:
        rows = [r for r in pool.map(profile, boxes, chunksize=4) if r]
    df = pd.DataFrame(rows).drop_duplicates(["x0", "y0", "x1"])
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"windows_{int(args.size)}.csv")
    df.to_csv(out, index=False)
    print(f"{len(boxes)} windows, {len(df)} with a street network -> {out}")


if __name__ == "__main__":
    main()

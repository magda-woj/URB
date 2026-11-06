"""Choose a set of LuST windows that together cover the variety of the network, including luxembourg_south_bonnevoie.

1. Keep the usable windows (USABLE): enough junctions, mutually reachable, route choice for at least half of the
   border OD pairs, and no motorway (in LuST windows with a motorway, no route choice involves the motorway except
   at the Gasperich interchange; see motorway_choice_share in graph_metrics.py and REPORT.md).
2. Describe each window by the METRICS below, each turned into its percentile among the usable windows
   (0 = lowest, 1 = highest), so that metrics with different units and skewed distributions are comparable.
3. Compare windows with a weighted Euclidean distance between their percentile profiles (WEIGHTS).
4. Choose K more windows with farthest-point sampling (greedy k-center), starting from Bonnevoie: repeatedly add
   the window that is farthest from its nearest chosen window. The result has two guarantees with the same
   radius r (the distance of the last window added): no two chosen windows are closer than r, and every usable
   window is within r of a chosen one. Every usable window is assigned to its nearest chosen window, so each
   candidate stands for a group of similar windows.
   Windows may overlap; overlap is only reported. evaluate_selection.py shows why these weights, this algorithm
   and this K were chosen over the alternatives.
5. Add the motorway special case (label M) outside the selection: among the windows that pass every usable
   condition except the motorway one, the one whose route choice involves the motorway most often
   (MOTORWAY_CASE; in LuST the Croix de Gasperich interchange). It is described against the usable windows.

Usage (from the repository root):
    venv/bin/python tools/lux_crops/select_candidates.py [--size 900] [--k 7]
Writes tools/lux_crops/out/candidates_<size>.csv and tools/lux_crops/out/groups_<size>.csv (every usable window
with the candidate it is assigned to).
"""
import argparse
import os
import re

import numpy as np
import pandas as pd

import lust_graph as lg

BASE = "n_junctions >= 30 and scc_share >= 0.8 and route_choice_share >= 0.5"
USABLE = BASE + " and motorway_share == 0"
MOTORWAY_CASE = BASE + " and motorway_choice_share > 0"  # special case: the window with most motorway route choice

# metric: (group, short description). See REPORT.md, Section 3, for why these and not others.
METRICS = {
    "meshedness": ("graph", "independent cycles relative to a maximal planar graph"),
    "route_choice_share": ("graph", "share of border OD pairs with a second distinct near-shortest route"),
    "betweenness_gini": ("graph", "concentration of shortest paths on few arcs"),
    "algebraic_connectivity": ("graph", "Fiedler value of the junction graph: how far from splitting in two"),
    "reciprocity": ("graph", "share of arcs with an opposite arc (two-way streets)"),
    "tls": ("traffic lights", "traffic-light junctions"),
}
# Weight of each metric in the distance. evaluate_selection.py compares traffic-light weights 0 to 4.
WEIGHTS = {m: 1.0 for m in METRICS}
K = 7  # candidates besides Bonnevoie; see coverage_vs_k in evaluate_selection.py
METHOD = "k-center"  # or "k-medoids"; compared in evaluate_selection.py


def profiles(windows):
    """Percentile profile of every window (rows) over METRICS (columns)."""
    return windows[list(METRICS)].rank(pct=True)


def distances(P, weights):
    """Weighted Euclidean distance matrix between percentile profiles."""
    Q = P.to_numpy() * np.sqrt([weights[m] for m in P.columns])
    return np.linalg.norm(Q[:, None] - Q[None], axis=2)


def k_center(D, start, k):
    """Farthest-point sampling: repeatedly add the window farthest from its nearest chosen window."""
    chosen = [start]
    for _ in range(k):
        chosen.append(int(np.argmax(D[:, chosen].min(axis=1))))
    return chosen


def k_medoids(D, start, k, max_iter=100):
    """Voronoi-iteration k-medoids, initialised with k_center, with `start` fixed as a medoid."""
    medoids = k_center(D, start, k)
    for _ in range(max_iter):
        labels = D[:, medoids].argmin(axis=1)
        new = []
        for c, m in enumerate(medoids):
            members = np.flatnonzero(labels == c)
            new.append(m if m == start else int(members[D[np.ix_(members, members)].sum(axis=1).argmin()]))
        if new == medoids:
            break
        medoids = new
    return medoids


def select(windows, weights=WEIGHTS, k=K, method=METHOD):
    """Indices (into `windows`) of the chosen windows, Bonnevoie first."""
    D = distances(profiles(windows), weights)
    start = bonnevoie_index(windows)
    return (k_medoids if method == "k-medoids" else k_center)(D, start, k)


def bonnevoie_index(windows):
    return next(i for i, r in enumerate(windows.itertuples()) if (r.x0, r.x1, r.y0, r.y1) == lg.BONNEVOIE[1])


def overlap(a, b):
    """Share of window a's area covered by window b; windows are (x0, x1, y0, y1)."""
    w = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[2], b[2]))
    return w * h / ((a[1] - a[0]) * (a[3] - a[2]))


def differs_most(windows, pct, i, j, n=3):
    """The n metrics on which windows i and j differ most (by percentile), with raw values."""
    diff = (pct.iloc[i] - pct.iloc[j]).abs().sort_values(ascending=False)
    return "; ".join(f"{m} {windows.iloc[i][m]:.3g} vs {windows.iloc[j][m]:.3g} "
                     f"(p{100 * pct.iloc[i][m]:.0f} vs p{100 * pct.iloc[j][m]:.0f})" for m in diff.index[:n])


def distinctive(pct_row, low=0.1, high=0.9):
    """Metrics on which a window is in the top or bottom 10 % of the usable windows."""
    parts = [f"high {m}" for m in METRICS if pct_row[m] >= high] + [f"low {m}" for m in METRICS if pct_row[m] <= low]
    return ", ".join(parts) or "no extreme metric"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def describe(windows, chosen, weights=WEIGHTS):
    """One row per chosen window: metrics, percentiles, group, nearest other candidate and why they differ."""
    pct = profiles(windows)
    D = distances(pct, weights)
    labels = np.asarray(chosen)[D[:, chosen].argmin(axis=1)]
    names, seen = {}, {}
    for i in chosen:
        base = lg.BONNEVOIE[0] if i == chosen[0] else f"luxembourg_{slug(windows.iloc[i].place)}"
        seen[base] = seen.get(base, 0) + 1
        names[i] = base if seen[base] == 1 else f"{base}_{seen[base]}"
    rows = []
    for n, i in enumerate(chosen):
        w = windows.iloc[i]
        others = [j for j in chosen if j != i]
        j = min(others, key=lambda o: D[i, o])
        box = (w.x0, w.x1, w.y0, w.y1)
        rows.append(w.to_dict() | {f"pct_{m}": pct.iloc[i][m] for m in METRICS} | {
            "label": "B" if n == 0 else str(n), "name": names[i],
            "group_size": int((labels == i).sum()),
            "nearest_candidate": names[j], "distance_to_nearest_candidate": D[i, j],
            "differs_from_nearest_on": differs_most(windows, pct, i, j),
            "distinctive": distinctive(pct.iloc[i]),
            "max_overlap_with_candidates": max(overlap(box, tuple(windows.iloc[o][["x0", "x1", "y0", "y1"]])) for o in others),
        })
    groups = windows[["x0", "x1", "y0", "y1", "place"]].assign(candidate=[names[c] for c in labels],
                                                               distance_to_candidate=D[np.arange(len(D)), labels])
    return pd.DataFrame(rows), groups


def motorway_case(all_windows, windows, chosen, cand, weights=WEIGHTS):
    """The motorway special case (label M) as a row like those of describe(), or no row if no window qualifies.

    Its percentiles and distances are computed with the usable windows plus this window.
    """
    pool = all_windows.query(MOTORWAY_CASE)
    if pool.empty:
        return cand.iloc[:0]
    both = pd.concat([windows, pool.loc[[pool.motorway_choice_share.idxmax()]]], ignore_index=True)
    pct = profiles(both)
    D = distances(pct, weights)
    m, w = len(both) - 1, both.iloc[-1]
    j = min(chosen, key=lambda o: D[m, o])
    names = dict(zip(chosen, cand.name))
    box = (w.x0, w.x1, w.y0, w.y1)
    return pd.DataFrame([w.to_dict() | {f"pct_{x}": pct.iloc[m][x] for x in METRICS} | {
        "label": "M", "name": f"luxembourg_{slug(w.place)}", "group_size": np.nan,
        "nearest_candidate": names[j], "distance_to_nearest_candidate": D[m, j],
        "differs_from_nearest_on": differs_most(both, pct, m, j),
        "distinctive": distinctive(pct.iloc[m]),
        "max_overlap_with_candidates": max(overlap(box, tuple(both.iloc[o][["x0", "x1", "y0", "y1"]])) for o in chosen),
    }])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--k", type=int, default=K)
    args = ap.parse_args()

    out_dir = os.path.join(lg.HERE, "out")
    all_windows = pd.read_csv(os.path.join(out_dir, f"windows_{args.size}.csv"))
    windows = all_windows.query(USABLE).reset_index(drop=True)
    chosen = select(windows, k=args.k)
    cand, groups = describe(windows, chosen)
    cand = pd.concat([cand, motorway_case(all_windows, windows, chosen, cand)], ignore_index=True)
    D = distances(profiles(windows), WEIGHTS)
    radius = D[:, chosen].min(axis=1).max()
    closest = min(D[a, b] for a in chosen for b in chosen if a < b)
    print(f"{len(windows)} usable windows ({USABLE})")
    print("weights: " + ", ".join(f"{m} {w:g}" for m, w in WEIGHTS.items()))
    print(f"{METHOD}, K = {args.k}: closest pair of candidates {closest:.2f} apart; "
          f"every usable window within {radius:.2f} of a candidate (weighted distance)\n")
    for r in cand.itertuples():
        role = "special case, outside the selection" if r.label == "M" else f"stands for {r.group_size:.0f} windows"
        print(f"{r.label:>2} {r.name}  x [{r.x0:.0f}, {r.x1:.0f}]  y [{r.y0:.0f}, {r.y1:.0f}]  {role}")
        print(f"   distinctive: {r.distinctive}")
        print(f"   nearest candidate {r.nearest_candidate} (distance {r.distance_to_nearest_candidate:.2f}, "
              f"overlap {r.max_overlap_with_candidates:.0%}); differs on {r.differs_from_nearest_on}")
    cand.to_csv(os.path.join(out_dir, f"candidates_{args.size}.csv"), index=False)
    groups.to_csv(os.path.join(out_dir, f"groups_{args.size}.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print()
    print(cand[["label", "name", "group_size", "n_junctions"] + list(METRICS)].round(3).to_string(index=False))
    print("->", os.path.join(out_dir, f"candidates_{args.size}.csv"))


if __name__ == "__main__":
    main()

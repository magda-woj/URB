"""Evidence for the choices in select_candidates.py: metrics, traffic-light weight, algorithm and number of candidates.

1. Redundancy: Spearman correlations between the metrics and, for each metric, the share of its variance (R^2)
   explained by a linear model of the other metrics (on percentiles).
2. Traffic-light weight and algorithm: for every traffic-light weight in WEIGHT_GRID (graph metrics have weight 1)
   and algorithm (k-center = farthest-point sampling, k-medoids), choose K windows and measure the set in
   unweighted percentile space:
     graph diversity   distance between the two most similar candidates, graph metrics       (higher = better)
     graph radius      largest distance from a usable window to its nearest candidate, same space (lower = better)
     TLS radius        the same on the traffic-light percentile alone                         (lower = better)
     metric span       mean over the selection metrics of the percentile range the set covers (reported only)
   The algorithm is fixed by the goal (sc.METHOD; candidates that differ from each other and span the range of every
   metric); both algorithms are reported for comparison. Within that algorithm, each measure is ranked over the
   weights, and the chosen weight has the smallest sum of ranks (ties: the weight closest to equal weighting).
   Graph structure has two of the three ranked measures, traffic lights one.
3. Number of candidates: the same measures for the chosen setting with K = 2 ... 15.

Usage (from the repository root):
    venv/bin/python tools/lux_crops/evaluate_selection.py [--size 900] [--k 7]
Writes tables and figures to tools/lux_crops/out/evaluation/.
"""
import argparse
import itertools
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import lust_graph as lg
import select_candidates as sc

GRAPH = [m for m, (g, _) in sc.METRICS.items() if g == "graph"]
WEIGHT_GRID = [0, 0.5, 1, 2, 3, 4]
METHODS = ["k-center", "k-medoids"]
# computed but not used for the selection; shown in the correlation figure
EXTRA = ["n_junctions", "cyclomatic_number", "mean_degree", "dead_end_share", "four_way_share", "bridges", "bottleneck_width", "cut_vertices",
         "orientation_order", "circuity", "min_side_cut", "tls_share", "major_road_share"]
MEASURES = {"graph_diversity": False, "graph_radius": True, "tls_radius": True}  # True: lower is better


def r2(P, y, xs):
    """Share of the variance of column y explained by a linear model of columns xs."""
    A = np.c_[np.ones(len(P)), P[xs].to_numpy()]
    coef = np.linalg.lstsq(A, P[y].to_numpy(), rcond=None)[0]
    return 1 - (P[y].to_numpy() - A @ coef).var() / P[y].var(ddof=0)


def to_nearest(P, chosen, cols):
    """Distance from every window to its nearest chosen window, in the space of `cols`."""
    Q = P[cols].to_numpy()
    return np.linalg.norm(Q[:, None] - Q[chosen][None], axis=2).min(axis=1)


def measures(P, chosen):
    Q = P[GRAPH].to_numpy()[chosen]
    pair = np.linalg.norm(Q[:, None] - Q[None], axis=2)
    return {
        "graph_diversity": pair[np.triu_indices(len(chosen), 1)].min(),
        "graph_radius": to_nearest(P, chosen, GRAPH).max(),
        "tls_radius": to_nearest(P, chosen, ["tls"]).max(),
        "graph_mean_distance": to_nearest(P, chosen, GRAPH).mean(),
        "metric_span": (P.iloc[chosen].max() - P.iloc[chosen].min()).mean(),
    }


def choose(D, start, k, method):
    return (sc.k_medoids if method == "k-medoids" else sc.k_center)(D, start, k)


def redundancy(windows, out):
    rho = windows[list(sc.METRICS) + EXTRA].corr(method="spearman")
    rho.to_csv(os.path.join(out, "correlations.csv"))
    P = windows[list(sc.METRICS) + EXTRA].rank(pct=True)
    m = list(sc.METRICS)
    table = pd.DataFrame({
        "max_abs_rho_with_other_selection_metric": [rho.loc[x, [o for o in m if o != x]].abs().max() for x in m],
        "most_correlated_selection_metric": [rho.loc[x, [o for o in m if o != x]].abs().idxmax() for x in m],
        "r2_from_other_selection_metrics": [r2(P, x, [o for o in m if o != x]) for x in m],
        "rho_with_n_junctions": [rho.loc[x, "n_junctions"] for x in m],
    }, index=m)
    table.to_csv(os.path.join(out, "redundancy.csv"))
    print("Redundancy of the selection metrics (usable windows):")
    print(table.round(2).to_string(), "\n")

    fig, ax = plt.subplots(figsize=(11, 9))
    cols = m + EXTRA
    im = ax.imshow(rho.loc[cols, cols], cmap="RdBu_r", vmin=-1, vmax=1)
    for i, j in itertools.product(range(len(cols)), repeat=2):
        ax.text(j, i, f"{rho.loc[cols[i], cols[j]]:.2f}", ha="center", va="center", fontsize=6.5,
                color="white" if abs(rho.loc[cols[i], cols[j]]) > 0.6 else "black")
    ax.set_xticks(range(len(cols)), cols, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(cols)), cols, fontsize=8)
    ax.axhline(len(m) - 0.5, color="black", lw=1.2)
    ax.axvline(len(m) - 0.5, color="black", lw=1.2)
    fig.colorbar(im, ax=ax, fraction=0.04, label="Spearman ρ")
    ax.set_title(f"Spearman correlation over usable windows (top-left block: the {len(m)} selection metrics)", fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "correlations.png"), dpi=120)
    plt.close(fig)


def weight_grid(windows, k, out):
    P = sc.profiles(windows)
    start = sc.bonnevoie_index(windows)
    rows, sets = [], {}
    for method, w_tls in itertools.product(METHODS, WEIGHT_GRID):
        chosen = choose(sc.distances(P, sc.WEIGHTS | {"tls": w_tls}), start, k, method)
        sets[method, w_tls] = set(chosen)
        rows.append({"method": method, "w_tls": w_tls} | measures(P, chosen))
    grid = pd.DataFrame(rows)
    grid["rank_sum"] = sum(grid.groupby("method")[m].rank(ascending=low) for m, low in MEASURES.items())
    grid["distance_from_equal_weights"] = (grid.w_tls - 1).abs()
    best = grid[grid.method == sc.METHOD].sort_values(["rank_sum", "distance_from_equal_weights"]).iloc[0]
    grid["shared_with_chosen"] = [len(sets[r.method, r.w_tls] & sets[best.method, best.w_tls]) - 1 for r in grid.itertuples()]
    grid.to_csv(os.path.join(out, "weights_grid.csv"), index=False)
    print(f"Traffic-light weight and algorithm (K = {k}); rank_sum = sum of the ranks of {list(MEASURES)} within the "
          f"algorithm; shared_with_chosen = candidates besides Bonnevoie in common with the chosen setting")
    print(grid.round(3).to_string(index=False))
    print("\nchosen:", {k_: (round(v, 3) if isinstance(v, float) else v) for k_, v in best.items()}, "\n")

    panels = [(m, f"{m} ({'lower' if low else 'higher'} = better)") for m, low in MEASURES.items()] + \
             [("metric_span", "metric_span (higher = wider range)"), ("rank_sum", "sum of ranks within algorithm (lower = better)")]
    fig, axes = plt.subplots(1, len(panels), figsize=(4.6 * len(panels), 3.8))
    for ax, (metric, title) in zip(axes, panels):
        for method, style in zip(METHODS, ("-o", "--s")):
            g = grid[grid.method == method]
            ax.plot(g.w_tls, g[metric], style, ms=4, label=method)
        ax.plot(best.w_tls, best[metric], "o", ms=11, mfc="none", mec="red", mew=1.8, label="chosen")
        ax.set_xlabel("traffic-light weight")
        ax.set_title(title, fontsize=9.5)
    axes[0].legend(fontsize=8)
    fig.suptitle(f"Traffic-light weight and algorithm, K = {k} (graph metrics have weight 1)", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "weights_grid.png"), dpi=120)
    plt.close(fig)
    return best


def coverage_curve(windows, best, out):
    P = sc.profiles(windows)
    start = sc.bonnevoie_index(windows)
    D = sc.distances(P, sc.WEIGHTS | {"tls": best.w_tls})
    curve = pd.DataFrame([{"k": k} | measures(P, choose(D, start, k, best.method)) for k in range(2, 16)])
    curve.to_csv(os.path.join(out, "coverage_vs_k.csv"), index=False)
    print("Coverage of the chosen setting against the number of candidates K:")
    print(curve.round(3).to_string(index=False))
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for col, style in [("graph_diversity", "-o"), ("graph_radius", "-s"), ("graph_mean_distance", "-^"), ("tls_radius", ":")]:
        ax.plot(curve.k, curve[col], style, label=col, ms=4)
    ax.axvline(sc.K, color="0.5", lw=0.8)
    ax.set_xlabel("K (candidates besides Bonnevoie)")
    ax.set_ylabel("distance in percentile space")
    ax.set_title(f"{best.method}, traffic-light weight {best.w_tls:g}", fontsize=10, loc="left")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "coverage_vs_k.png"), dpi=120)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--k", type=int, default=sc.K)
    args = ap.parse_args()
    out = os.path.join(lg.HERE, "out", "evaluation")
    os.makedirs(out, exist_ok=True)
    windows = pd.read_csv(os.path.join(lg.HERE, "out", f"windows_{args.size}.csv")).query(sc.USABLE).reset_index(drop=True)
    print(f"{len(windows)} usable windows ({sc.USABLE})\n")
    redundancy(windows, out)
    best = weight_grid(windows, args.k, out)
    coverage_curve(windows, best, out)
    print("->", out)


if __name__ == "__main__":
    main()

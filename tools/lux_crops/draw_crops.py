"""Draw the chosen crops and compare them.

out/crops/<label>_<name>.png  one per candidate, in the style of
                              networks/luxembourg_south_bonnevoie/luxembourg_south_bonnevoie.png: left the whole
                              LuST network with the crop highlighted, right a zoom on the crop, footer with the
                              metrics and how the crop relates to the other candidates.
out/crops_overview.png        all crops side by side (zoom panels with their key numbers).
out/map_overview.png          the crops on the LuST network.
out/comparison.png            the candidates side by side: every selection metric as raw value, coloured by percentile.
out/metric_space.png          every usable window (2-D projection of its percentile profile), joined to the candidate
                              it is assigned to.

Usage (from the repository root):
    venv/bin/python tools/lux_crops/draw_crops.py [--size 900]
Reads out/windows_<size>.csv, out/candidates_<size>.csv and out/groups_<size>.csv.
"""
import argparse
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

import lust_graph as lg
from select_candidates import METRICS, USABLE

HIGHWAY, CROP, TLS, BACKGROUND, ZOOM_BACKGROUND = "steelblue", "crimson", "darkorange", "0.45", "0.82"
MARGIN = 200  # metres around the crop in the zoom panels


def streets(n):
    return f"{int(n)} street" + ("" if int(n) == 1 else "s")


def box_color(label):
    """Bonnevoie black, the motorway special case in the motorway colour, the other candidates red."""
    return {"B": "black", "M": HIGHWAY}.get(label, CROP)


def is_highway(arc):
    return arc["type"].startswith("highway.motorway")


def draw_lines(ax, arcs, shape_key, **style):
    ax.add_collection(LineCollection([a[shape_key] for a in arcs], **style))


def draw_network(ax, G, lw=0.6):
    arcs = [a for *_, a in G.edges(data=True)]
    draw_lines(ax, [a for a in arcs if not is_highway(a)], "shape", colors=BACKGROUND, linewidths=lw, zorder=1)
    draw_lines(ax, [a for a in arcs if is_highway(a)], "shape", colors=HIGHWAY, linewidths=2.2, zorder=2)
    xmin, ymin, xmax, ymax = G.graph["bounds"]
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")


def draw_zoom(ax, G, crop, row, tls_size=110, lw=1.6):
    view = (row.x0 - MARGIN, row.x1 + MARGIN, row.y0 - MARGIN, row.y1 + MARGIN)
    nearby = [a for *_, a in G.edges(data=True) if lg.shape_touches_box(a["lane_shape"], view)]
    crop_arcs = [a for *_, a in crop.edges(data=True)]
    draw_lines(ax, nearby, "lane_shape", colors=ZOOM_BACKGROUND, linewidths=lw * 0.6, zorder=1)
    draw_lines(ax, [a for a in crop_arcs if not is_highway(a)], "lane_shape", colors=CROP, linewidths=lw, zorder=3)
    draw_lines(ax, [a for a in crop_arcs if is_highway(a)], "lane_shape", colors=HIGHWAY, linewidths=lw * 1.5, zorder=3)
    box = (row.x0, row.x1, row.y0, row.y1)
    tls = [(crop.nodes[v]["x"], crop.nodes[v]["y"]) for v in crop if crop.nodes[v]["tls"] and lg.inside(crop, v, box)]
    if tls:
        ax.scatter(*zip(*tls), marker="^", s=tls_size, c=TLS, edgecolors="black", linewidths=0.8, zorder=4)
    ax.set_xlim(view[0], view[1])
    ax.set_ylim(view[2], view[3])
    ax.set_aspect("equal")


def legend(ax, **kw):
    ax.legend(handles=[Line2D([], [], color=HIGHWAY, lw=2.2, label="highway"),
                       Line2D([], [], color=CROP, lw=1.4, label="urban (in crop)"),
                       Line2D([], [], marker="^", ls="", ms=8, mfc=TLS, mec="black", label="traffic light")],
              fontsize=9, framealpha=0.9, **kw)


def stats(row):
    return (f"{int(row.n_junctions)} junctions  |  {int(row.n_arcs)} arcs  |  {int(row.tls)} TLS  |  "
            f"{int(row.motorway_access)} hwy access  |  {int(row.motorway_ramps)} ramps")


def draw_candidate(G, row, path):
    crop = lg.crop(G, (row.x0, row.x1, row.y0, row.y1))
    fig, (left, right) = plt.subplots(1, 2, figsize=(20, 12))
    draw_network(left, G)
    draw_lines(left, [a for *_, a in crop.edges(data=True)], "shape", colors=CROP, linewidths=1.0, zorder=3)
    left.add_patch(Rectangle((row.x0, row.y0), row.x1 - row.x0, row.y1 - row.y0, fc=CROP, ec=CROP, alpha=0.15, zorder=2))
    tls = [(d["x"], d["y"]) for _, d in G.nodes(data=True) if d["tls"]]
    left.scatter(*zip(*tls), marker="^", s=22, c=TLS, edgecolors="black", linewidths=0.4, zorder=4)
    left.set_title(f"Full LuST — '{row.name}'  |  {stats(row)}", fontsize=11)
    draw_zoom(right, G, crop, row)
    right.set_title(f"Zoom '{row.name}' ({int(row.x1 - row.x0)}x{int(row.y1 - row.y0)} m)  |  {stats(row)}\n"
                    f"{row.label} · {row.place} — {row.distinctive}", fontsize=11)
    for ax in (left, right):
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        legend(ax, loc="upper right")
    role = "motorway special case, outside the selection  ·  " if row.label == "M" else ""
    fig.text(0.01, 0.01,
             f"cycles & degrees:  meshedness α {row.meshedness:.2f}  ·  independent cycles μ {int(row.cyclomatic_number)}  ·  "
             f"mean degree {row.mean_degree:.2f}  ·  dead ends {row.dead_end_share:.0%}  ·  4-way {row.four_way_share:.0%}  ·  "
             f"reciprocity {row.reciprocity:.2f}\n"
             f"cuts & paths:      bridges {int(row.bridges)}  ·  cut vertices {int(row.cut_vertices)}  ·  "
             f"bottleneck width {streets(row.bottleneck_width)}  ·  Fiedler {row.algebraic_connectivity:.3f}  ·  "
             f"betweenness Gini {row.betweenness_gini:.2f}  ·  OD pairs with route choice {row.route_choice_share:.0%}\n"
             f"context:           grid order φ {row.orientation_order:.2f}  ·  circuity {row.circuity:.2f}  ·  "
             f"min side cut λ {int(row.min_side_cut)}  ·  bbox x [{row.x0:.0f}, {row.x1:.0f}]  y [{row.y0:.0f}, {row.y1:.0f}]\n"
             f"SUMO network:      traffic-light junctions {int(row.tls)} ({row.tls_share:.0%})  ·  motorway {row.motorway_share:.0%} of length  ·  "
             f"OD pairs choosing more or less motorway {row.motorway_choice_share:.0%}  ·  major roads {row.major_road_share:.0%}  ·  "
             f"mean lanes {row.mean_lanes:.2f}  ·  mean speed limit {row.mean_speed_limit * 3.6:.0f} km/h\n"
             f"in the set:        {role}nearest candidate {row.nearest_candidate} "
             f"(distance {row.distance_to_nearest_candidate:.2f}, max overlap with candidates {row.max_overlap_with_candidates:.0%})\n"
             f"differs from it:   {row.differs_from_nearest_on}",
             fontsize=9.5, family="monospace", va="bottom")
    fig.tight_layout(rect=(0, 0.12, 1, 0.98))
    fig.savefig(path, dpi=120)
    plt.close(fig)


def draw_crops_overview(G, cand, path):
    cols = 4 if len(cand) <= 8 else 3
    rows = math.ceil(len(cand) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 6.6 * rows))
    for ax in axes.flat[len(cand):]:
        ax.axis("off")
    for ax, r in zip(axes.flat, cand.itertuples()):
        draw_zoom(ax, G, lg.crop(G, (r.x0, r.x1, r.y0, r.y1)), r, tls_size=45, lw=1.1)
        ax.add_patch(Rectangle((r.x0, r.y0), r.x1 - r.x0, r.y1 - r.y0, fill=False, ec="0.6", lw=0.8, ls="--", zorder=2))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f"{r.label} · {r.name}", fontsize=10.5, loc="left", weight="bold")
        ax.text(0, -0.02,
                f"{int(r.n_junctions)} junctions · {int(r.tls)} TLS ({r.tls_share:.0%} of junctions)\n"
                f"cycles μ {int(r.cyclomatic_number)} · meshedness α {r.meshedness:.2f}\n"
                f"route choice {r.route_choice_share:.0%} of OD pairs · reciprocity {r.reciprocity:.2f}\n"
                f"Fiedler {r.algebraic_connectivity:.3f} · betweenness Gini {r.betweenness_gini:.2f}\n"
                f"bottleneck {streets(r.bottleneck_width)} · motorway {r.motorway_share:.0%}",
                transform=ax.transAxes, va="top", fontsize=8.5, family="monospace")
    legend(fig, loc="upper right", ncol=3)
    fig.suptitle("LuST crop candidates (B = existing luxembourg_south_bonnevoie, M = motorway special case)",
                 x=0.01, ha="left", fontsize=13)
    fig.tight_layout(rect=(0, 0.06, 1, 0.97), h_pad=9)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def draw_map_overview(G, cand, path):
    fig, ax = plt.subplots(figsize=(12, 10.5))
    draw_network(ax, G, lw=0.5)
    tls = [(d["x"], d["y"]) for _, d in G.nodes(data=True) if d["tls"]]
    ax.scatter(*zip(*tls), marker="^", s=12, c=TLS, edgecolors="black", linewidths=0.3, zorder=2)
    for r in cand.itertuples():
        color = box_color(r.label)
        ax.add_patch(Rectangle((r.x0, r.y0), r.x1 - r.x0, r.y1 - r.y0, fc=color, ec=color, alpha=0.12, zorder=3))
        ax.add_patch(Rectangle((r.x0, r.y0), r.x1 - r.x0, r.y1 - r.y0, fill=False, ec=color, lw=1.6, zorder=3))
        ax.text(r.x0 + 30, r.y1 - 40, r.label, fontsize=11, va="top", weight="bold", zorder=4,
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
        ax.text(r.x0, r.y0 - 60, r.name.replace("luxembourg_", ""), fontsize=8, va="top", zorder=4,
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.5))
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    legend(ax, loc="upper right")
    ax.set_title("LuST — crop candidates (black: existing luxembourg_south_bonnevoie, blue: motorway special case)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# shown uncoloured: not selection metrics
CONTEXT = {"n_junctions": "junctions", "cyclomatic_number": "cycles μ", "bottleneck_width": "bottleneck width",
           "motorway_share": "motorway"}


def draw_comparison(cand, path):
    cols = list(CONTEXT) + list(METRICS)
    pct = np.ma.masked_invalid(np.c_[np.full((len(cand), len(CONTEXT)), np.nan), cand[[f"pct_{m}" for m in METRICS]].to_numpy()])
    fig, ax = plt.subplots(figsize=(15, 0.5 * len(cand) + 2.4))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad("white")
    im = ax.imshow(pct, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(cand.itertuples()):
        for j, m in enumerate(cols):
            v = getattr(row, m)
            text = (f"{v:.0%}" if m in ("route_choice_share", "motorway_share") else f"{v:.0f}" if m in ("bridges", "tls", *CONTEXT)
                    else f"{v:.3f}" if m == "algebraic_connectivity" else f"{v:.2f}")
            dark = not np.ma.is_masked(pct[i, j]) and abs(pct[i, j] - 0.5) > 0.35
            ax.text(j, i, text, ha="center", va="center", fontsize=9, color="white" if dark else "black")
    ax.axvline(len(CONTEXT) - 0.5, color="0.3", lw=1)
    ax.set_yticks(range(len(cand)), [f"{r.label} · {r.name}" for r in cand.itertuples()], fontsize=9.5)
    if (cand.label == "M").any():
        ax.axhline(int(np.flatnonzero(cand.label == "M")[0]) - 0.5, color="0.3", lw=1)
    groups = {m: g for m, (g, _) in METRICS.items()} | {m: "context" for m in CONTEXT}
    ax.set_xticks(range(len(cols)), [f"{CONTEXT.get(m, m)}\n[{groups[m]}]" for m in cols], fontsize=9, rotation=25, ha="right")
    fig.colorbar(im, ax=ax, fraction=0.02, pad=0.01, label="percentile among usable windows")
    ax.set_title("Candidates side by side: raw value in each cell, colour = percentile among the usable LuST windows",
                 fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def draw_metric_space(windows, cand, groups, path):
    """First two principal components of the percentile profiles; each window joined to its candidate."""
    usable = windows.query(USABLE).reset_index(drop=True)
    P = usable[list(METRICS)].rank(pct=True).to_numpy()
    mean = P.mean(axis=0)
    _, s, vt = np.linalg.svd(P - mean, full_matrices=False)
    xy = (P - mean) @ vt[:2].T
    explained = s[:2] ** 2 / (s ** 2).sum()
    index = {(r.x0, r.y0, r.x1): i for i, r in enumerate(usable.itertuples())}
    # the motorway special case is not a usable window: project its percentile profile (computed with the usable windows)
    cand_xy = {r.name: xy[index[(r.x0, r.y0, r.x1)]] if (r.x0, r.y0, r.x1) in index else
               (np.array([getattr(r, f"pct_{m}") for m in METRICS]) - mean) @ vt[:2].T for r in cand.itertuples()}
    fig, ax = plt.subplots(figsize=(11.5, 9.5))
    segs = [(xy[index[(g.x0, g.y0, g.x1)]], cand_xy[g.candidate]) for g in groups.itertuples()]
    ax.add_collection(LineCollection(segs, colors="0.8", linewidths=0.7, zorder=1))
    ax.scatter(xy[:, 0], xy[:, 1], s=14, c="0.55", zorder=2, label="usable window (line: to its candidate)")
    for r in cand.itertuples():
        p = cand_xy[r.name]
        ax.scatter(*p, s=90, c=box_color(r.label), marker="D" if r.label == "M" else "o", zorder=3)
        ax.annotate(f"{r.label} {r.name.replace('luxembourg_', '')}", p, xytext=(5, 5), textcoords="offset points",
                    fontsize=9, weight="bold")
    for j, m in enumerate(METRICS):
        ax.annotate("", xy=(vt[0, j] * 0.9, vt[1, j] * 0.9), xytext=(0, 0), arrowprops=dict(arrowstyle="->", color="0.35", lw=0.8))
        ax.text(vt[0, j] * 0.95, vt[1, j] * 0.95, m, fontsize=8, color="0.3")
    ax.set_xlabel(f"PC1 ({explained[0]:.0%} of variance)")
    ax.set_ylabel(f"PC2 ({explained[1]:.0%} of variance)")
    ax.set_title("Usable windows in metric space (percentile profiles, first two principal components)\n"
                 "red: candidates, black: Bonnevoie, blue diamond: motorway special case; "
                 "arrows: direction in which each metric grows", fontsize=10, loc="left")
    ax.legend(loc="lower left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=900)
    args = ap.parse_args()
    out = os.path.join(lg.HERE, "out")
    windows = pd.read_csv(os.path.join(out, f"windows_{args.size}.csv"))
    cand = pd.read_csv(os.path.join(out, f"candidates_{args.size}.csv"), dtype={"label": str})
    groups = pd.read_csv(os.path.join(out, f"groups_{args.size}.csv"))

    G = lg.load_lust()
    crops_dir = os.path.join(out, "crops")
    os.makedirs(crops_dir, exist_ok=True)
    for old in os.listdir(crops_dir):
        if old.endswith(".png"):
            os.remove(os.path.join(crops_dir, old))
    for row in cand.itertuples():
        prefix = {"B": "00", "M": "M"}.get(row.label, row.label.zfill(2))
        draw_candidate(G, row, os.path.join(crops_dir, f"{prefix}_{row.name}.png"))
    draw_crops_overview(G, cand, os.path.join(out, "crops_overview.png"))
    draw_map_overview(G, cand, os.path.join(out, "map_overview.png"))
    draw_comparison(cand, os.path.join(out, "comparison.png"))
    draw_metric_space(windows, cand, groups, os.path.join(out, "metric_space.png"))
    print("figures ->", out)


if __name__ == "__main__":
    main()

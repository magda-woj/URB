# Choosing LuST crops

These scripts choose parts of the LuST (Luxembourg) network to crop for URB, so that the crops differ from `networks/luxembourg_south_bonnevoie` and from each other in the properties that shape a route-choice problem: alternative routes, where routes meet, one-way streets and traffic lights. Windows with a motorway are excluded, because their motorway offers no route choice; the one window where it does (the Gasperich interchange) is added as a special case, label M. [REPORT.md](REPORT.md) describes the method, the metrics and the result in full.

They choose bounding boxes only. Building a crop (demand, `agents.csv`, routes) is still done with `build_lux_crop.py`. No traffic is simulated here.

Run from the repository root:

```bash
venv/bin/python tools/lux_crops/graph_metrics.py        # profile every 900 x 900 m window  -> out/windows_900.csv
venv/bin/python tools/lux_crops/evaluate_selection.py   # evidence for metrics, weights, K  -> out/evaluation/
venv/bin/python tools/lux_crops/select_candidates.py    # choose the candidates             -> out/candidates_900.csv, out/groups_900.csv
venv/bin/python tools/lux_crops/draw_crops.py           # drawings                          -> out/crops/, out/*.png
```

The first run downloads `lust.net.xml` (11 MB) from the [LuST repository](https://github.com/lcodeca/LuSTScenario) into `tools/lux_crops/data/`, which git ignores. `graph_metrics.py` takes `--size` and `--stride` (metres, default 900 and 300) and `--workers`; a full run takes about 1.5 min on 12 cores. The other scripts take a few seconds each.

| File | Role |
|---|---|
| `lust_graph.py` | LuST as a networkx graph; window cropping identical to `build_lux_crop.py` |
| `graph_metrics.py` | graph metrics (networkx) and SUMO network metrics for every window |
| `select_candidates.py` | metric set, weights, usable-window filter and the selection (farthest-point sampling) |
| `evaluate_selection.py` | redundancy of the metrics, comparison of weights and algorithms, choice of the number of candidates |
| `draw_crops.py` | one drawing per candidate in the style of `luxembourg_south_bonnevoie.png`, plus overviews |

Outputs in `out/`:

| File | Content |
|---|---|
| `windows_900.csv` | every window with a street network and all its metrics |
| `candidates_900.csv` | the chosen windows with metrics, percentiles, group size and nearest other candidate |
| `groups_900.csv` | every usable window with the candidate it is closest to |
| `crops/NN_<name>.png` | one drawing per candidate |
| `crops_overview.png`, `map_overview.png` | all candidates side by side; all candidates on the LuST map |
| `comparison.png`, `metric_space.png` | candidates compared metric by metric; all usable windows in metric space |
| `evaluation/` | correlations, redundancy, weight grid and coverage-versus-K tables and figures |

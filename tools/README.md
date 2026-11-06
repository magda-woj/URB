# Experiment tools

These tools reuse and organize experiment directories under `results/`. Run them from the repository root with the same Python environment used for URB.

## Rerun an experiment

`rerun.py` starts a new run from an existing experiment's saved script and configuration. Options on the command line override the saved values. It refuses to overwrite an existing result.

```bash
venv/bin/python tools/rerun.py old_exp new_exp --env-seed 43
venv/bin/python tools/rerun.py old_exp new_exp --net provins --task-conf selfish_40
```

Supported overrides are `--alg-conf`, `--env-conf`, `--task-conf`, `--net`, `--env-seed`, `--torch-seed`, `--model`, `--route-set`, `--shuffle`, `--skip-metrics`, `--save-model-every`, and `--project`.

## Rename an experiment

`rename.py` renames one result directory and refuses to overwrite another. If its `exp_config.json` contains an `exp_id` field, that field is updated too.

```bash
venv/bin/python tools/rename.py old_exp new_exp
```

## Choose LuST crops

`lux_crops/` profiles every 900 × 900 m window of the LuST network with graph properties (networkx) and SUMO network properties (traffic lights, motorways), chooses the street windows whose route-choice structure differs most from `luxembourg_south_bonnevoie` and from each other, and draws them like `networks/luxembourg_south_bonnevoie/luxembourg_south_bonnevoie.png`. See [lux_crops/README.md](lux_crops/README.md) and the method report [lux_crops/REPORT.md](lux_crops/REPORT.md).

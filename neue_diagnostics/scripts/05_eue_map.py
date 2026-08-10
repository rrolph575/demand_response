#!/usr/bin/env python
"""Stage 05 (standalone): choropleth map of mean EUE per region.

Colors each ReEDS "p" region by its mean EUE over the whole timeseries
(total EUE / n_timesteps, MWh per hour) for a chosen case, one map per system.

Needs only stage 00 + 01 output (cache/registry.csv, cache/rollups/*_region.csv)
plus the ReEDS PCA shapefile. Reads no .pras files. Runs in a few seconds on a
login node; a slurm wrapper is provided if you prefer to batch it.

    python scripts/05_eue_map.py                       # all systems, default case
    python scripts/05_eue_map.py --system pjm
    python scripts/05_eue_map.py --case shed_16h_all_1.00
    python scripts/05_eue_map.py --metric neue_ppm     # or total_eue_mwh

Default case is each system's high-DC, no-DR reference
(baseline_with_load_added) -- the reliability signal DR is trying to reduce.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag import mapping  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

# ReEDS power-control-area shapefile; `rb` column holds region ids (p99, p60...).
DEFAULT_SHAPEFILE = (
    Path(__file__).resolve().parents[2] / "ReEDS" / "inputs" / "shapefiles"
    / "US_PCA" / "US_PCA.shp"
)
REGION_FIELD = "rb"


def resolve_case(registry: pd.DataFrame, system: str, case: str | None) -> str:
    reg = registry[registry["system"] == system]
    if case:
        if case not in set(reg["case_id"]):
            raise SystemExit(
                f"case {case!r} not found in {system}; available e.g. "
                f"{sorted(reg['case_id'])[:5]}..."
            )
        return case
    # Default: the high-DC, no-DR reference.
    ref = reg[(reg["is_reference"]) & (reg["dc_scenario"] == "high")]
    if not len(ref):
        raise SystemExit(f"no high-DC no-DR reference for {system}; pass --case")
    return ref.iloc[0]["case_id"]


def region_values(cfg, system: str, case: str, metric: str) -> pd.DataFrame:
    roll = pd.read_csv(cfg.cache_path("rollups", f"{system}_region.csv"))
    roll = roll[roll["case_id"] == case].copy()
    if not len(roll):
        raise SystemExit(f"no rollup rows for {system}/{case}; run stage 01")

    n_ts = int(
        pd.read_csv(cfg.cache_path("registry.csv"))
        .query("system == @system")["n_timesteps"].iloc[0]
    )
    roll["mean_eue_mwh"] = roll["eue_mwh"] / n_ts

    load = pd.read_csv(cfg.table_path(f"{system}_where.csv"))[["region", "load_mwh"]]
    roll = roll.merge(load, on="region", how="left")
    roll["neue_ppm"] = 1e6 * roll["eue_mwh"] / roll["load_mwh"]
    roll = roll.rename(columns={"eue_mwh": "total_eue_mwh"})

    if metric not in roll.columns:
        raise SystemExit(f"unknown --metric {metric!r}")
    return roll[["region", "mean_eue_mwh", "total_eue_mwh", "neue_ppm"]]


METRIC_LABELS = {
    "mean_eue_mwh": "mean EUE (MWh / hour)",
    "total_eue_mwh": "total EUE (MWh over timeseries)",
    "neue_ppm": "NEUE (ppm)",
}


def make_map(cfg, system, case, metric, shapefile: Path, suffix: str = "",
             edges=None):
    label = cfg.system(system).get("label", system.upper())
    vals = region_values(cfg, system, case, metric)

    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left"
    )
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))

    if edges is None:
        edges = mapping.decade_edges(ours[metric])

    metric_label = METRIC_LABELS.get(metric, metric)
    fig, ax = plt.subplots(figsize=(11, 8.5))
    minx, miny, maxx, maxy = mapping.draw_binned(
        fig, ax, ours, gdf, metric, edges, cmap_name="YlOrRd",
        legend_title=metric_label,
    )
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)

    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        val = r[metric]
        txt = f"{r['region']}\n{val:.3g}" if val and val > 0 else f"{r['region']}\n0"
        ax.annotate(txt, (c.x, c.y), ha="center", va="center", fontsize=9,
                    color="black", fontweight="bold")

    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = f"{label} — {metric_label} by region\ncase: {case}"
    if missing:
        title += f"\n(no polygon for: {', '.join(missing)})"
    ax.set_title(title, fontsize=13)
    fig.tight_layout()

    out = cfg.figure_path(f"{system}_eue_map{suffix}.png")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)

    tbl = cfg.table_path(f"{system}_region_mean_eue{suffix}.csv")
    vals.sort_values("mean_eue_mwh", ascending=False).to_csv(tbl, index=False)
    return out, tbl, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--case", default=None,
                    help="case_id; default = high-DC no-DR reference")
    ap.add_argument("--metric", default="mean_eue_mwh",
                    choices=["mean_eue_mwh", "total_eue_mwh", "neue_ppm"])
    ap.add_argument("--shapefile", default=str(DEFAULT_SHAPEFILE))
    ap.add_argument("--bins", default=None,
                    help="comma-separated bin edges, e.g. '0,0.001,0.01,0.1,1,10'; "
                         "default = automatic decade bins. Pass the same value to "
                         "several maps to put them on one shared set of bins.")
    args = ap.parse_args()
    edges = mapping.parse_bins(args.bins)

    cfg = load_config(paths_yaml=args.config)
    shapefile = Path(args.shapefile)
    if not shapefile.exists():
        raise SystemExit(f"shapefile not found: {shapefile} (pass --shapefile)")

    registry = pd.read_csv(cfg.cache_path("registry.csv"))
    systems = [args.system] if args.system else cfg.system_names()

    for system in systems:
        case = resolve_case(registry, system, args.case)
        # Keep the canonical filename ({system}_eue_map.png) for the default
        # high-DC no-DR map; suffix any other case or non-default metric so maps
        # never overwrite each other.
        default_case = resolve_case(registry, system, None)
        parts = []
        if case != default_case:
            parts.append(case)
        if args.metric != "mean_eue_mwh":
            parts.append(args.metric)
        suffix = ("_" + "_".join(parts)) if parts else ""
        print(f"\n=== {system} ===  case={case}  metric={args.metric}")
        out, tbl, missing = make_map(cfg, system, case, args.metric, shapefile,
                                     suffix, edges=edges)
        print(f"  figure: {out}")
        print(f"  table : {tbl}")
        if missing:
            print(f"  note  : no polygon for {missing} (excluded from map)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

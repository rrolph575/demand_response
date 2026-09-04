#!/usr/bin/env python
"""Stage 12 (standalone): EUE-per-year choropleth for the always-on shed case.

Maps residual EUE per region (MWh/yr, = total EUE / n_weather_years) for the
always-on shed (shed_1h_timeseries), reading the file named by config
(systems.<sys>.always_on_shed_h5). This is needed for ERCOT because its shed_1h
lives only in ercot_neue1_samples/ and is NOT in the main stage-01 cache that
scripts/05_eue_map.py uses. Same metric/colors/bins as stage 05 so it's directly
comparable to the no-DR {system}_eue_map.png.

    python scripts/12_shed_eue_map.py --system ercot
    python scripts/12_shed_eue_map.py --system pjm --bins=10,100,1000,10000,100000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag import io_results, mapping  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

DEFAULT_SHAPEFILE = (
    Path(__file__).resolve().parents[2] / "ReEDS" / "inputs" / "shapefiles"
    / "US_PCA" / "US_PCA.shp"
)
REGION_FIELD = "rb"


def region_eue_per_year(cfg, system):
    """Per-region EUE/yr (MWh) for the always-on shed, from its .h5 directly."""
    rel = cfg.system(system).get("always_on_shed_h5")
    if not rel:
        raise SystemExit(f"no always_on_shed_h5 configured for {system}")
    path = cfg.sweep_root / rel
    arr = io_results.read_arrays(path)
    eue = np.asarray(arr["eue"], float)                 # (T, R)
    regions = list(arr["regions"])
    n_ts = eue.shape[0]
    n_years = max(n_ts / cfg.analysis.get("hours_per_weather_year", 8760), 1)
    return pd.DataFrame({
        "region": regions,
        "eue_mwh_per_year": eue.sum(axis=0) / n_years,
    }), str(path)


def region_neue_diff(cfg, system):
    """Per-region ΔNEUE (ppm) = NEUE_shed - NEUE_base vs the no-DR high-DC
    baseline. Negative = DR lowered NEUE (same convention as stage 07's
    make_neue_diff_map). Load (same for both) from {system}_where.csv."""
    reg = pd.read_csv(cfg.cache_path("registry.csv"))
    ref = reg[(reg.system == system) & reg.is_reference
              & (reg.dc_scenario == "high")].iloc[0]["case_id"]
    roll = pd.read_csv(cfg.cache_path("rollups", f"{system}_region.csv"))
    base = (roll[roll.case_id == ref][["region", "eue_mwh"]]
            .rename(columns={"eue_mwh": "eue_base"}))
    load = pd.read_csv(cfg.table_path(f"{system}_where.csv"))[["region", "load_mwh"]]
    arr = io_results.read_arrays(cfg.sweep_root / cfg.system(system)["always_on_shed_h5"])
    shed = pd.DataFrame({"region": list(arr["regions"]),
                         "eue_shed": np.asarray(arr["eue"], float).sum(axis=0)})
    d = base.merge(shed, on="region").merge(load, on="region").fillna(0.0)
    d["dneue_ppm"] = np.where(
        d.load_mwh > 0, 1e6 * (d.eue_shed - d.eue_base) / d.load_mwh, np.nan)
    d["category"] = np.where(
        d.load_mwh <= 0, "no_load",
        np.where((d.eue_base <= 0) & (d.eue_shed <= 0), "no_eue", "value"))
    return d[["region", "dneue_ppm", "category"]], str(
        cfg.sweep_root / cfg.system(system)["always_on_shed_h5"]), ref


def make_reduction_map(cfg, system, shapefile: Path, edges=None):
    """ΔNEUE map matching stage 07: signed ppm, RdBu_r, shared diverging bins."""
    from matplotlib.patches import Patch
    label = cfg.system(system).get("label", system.upper())
    vals, path, ref = region_neue_diff(cfg, system)
    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left")
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))
    minx, miny, maxx, maxy = ours.total_bounds
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)
    valued = ours[ours["category"] == "value"]
    grey = ours[ours["category"] != "value"]
    if edges is None:   # shared with stage 07 for cross-case/system comparability
        edges = [-1000.0, -100.0, -10.0, -1.0, 0.0, 1.0, 10.0, 100.0]

    fig, ax = plt.subplots(figsize=(12, 9.5))
    gdf.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.4)
    if len(grey):
        grey.plot(ax=ax, color="#d9d9d9", edgecolor="#888888", linewidth=0.6)
    handles = []
    if len(valued):
        listed, norm, colors = mapping.bin_cmap(edges, "RdBu_r")
        valued.plot(ax=ax, column="dneue_ppm", cmap=listed, norm=norm,
                    edgecolor="#555555", linewidth=0.7)
        handles.extend(mapping.bin_patches(edges, colors, unit=" ppm"))
    handles.append(Patch(facecolor="#d9d9d9", edgecolor="#888888",
                         label="no EUE / no load"))
    ax.legend(handles=handles, title="ΔNEUE  (NEUE_shed − NEUE_noDR)",
              loc="lower right", fontsize=9, title_fontsize=10, framealpha=0.9)
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        txt = (f"{r['region']}\n{r['dneue_ppm']:+.2f} ppm"
               if r["category"] == "value" else f"{r['region']}\nno EUE")
        ax.annotate(txt, (c.x, c.y), ha="center", va="center", fontsize=9,
                    color="black", fontweight="bold")
    ax.set_xlim(minx - mx, maxx + mx); ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — regional NEUE change from always-on shed vs no-DR\n"
             f"case: shed_1h_timeseries   ·   NEUE_shed − NEUE({ref})  "
             "[ppm; negative = DR lowered NEUE]")
    if missing:
        title += f"\nno polygon: {', '.join(missing)}"
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    # Organized subfolder, matching the stage-07 layout
    # (outputs/figures/<sys>_neue_diff_maps/shed_1h_alwayson/).
    out_dir = (cfg.figure_path("_").parent / f"{system}_neue_diff_maps"
               / "shed_1h_alwayson")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{system}_neue_diff_map_shed_1h_timeseries.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    tbl = cfg.table_path(f"{system}_region_neue_diff_shed_1h.csv")
    vals.sort_values("dneue_ppm").to_csv(tbl, index=False)
    return out, tbl, missing, path


def region_per_mw(cfg, system):
    """(EUE_shed - EUE_noDR) / peak-added-MW per region [MWh EUE per MW added],
    matching stage 07's per_mw_added. Denominator = peak added datacenter load
    per region (= the always-on shed's borrow capacity)."""
    reg = pd.read_csv(cfg.cache_path("registry.csv"))
    ref = reg[(reg.system == system) & reg.is_reference
              & (reg.dc_scenario == "high")].iloc[0]["case_id"]
    roll = pd.read_csv(cfg.cache_path("rollups", f"{system}_region.csv"))
    nodr = (roll[roll.case_id == ref][["region", "eue_mwh"]]
            .rename(columns={"eue_mwh": "nodr_eue"}))
    added = pd.read_csv(cfg.table_path(f"{system}_added_load_summary.csv"))[
        ["region", "added_peak_mw"]]
    arr = io_results.read_arrays(cfg.sweep_root / cfg.system(system)["always_on_shed_h5"])
    shed = pd.DataFrame({"region": list(arr["regions"]),
                         "case_eue": np.asarray(arr["eue"], float).sum(axis=0)})
    d = nodr.merge(shed, on="region").merge(added, on="region").fillna(0.0)
    d["delta_eue"] = d.case_eue - d.nodr_eue
    d["per_mw"] = np.where(d.added_peak_mw > 0,
                           d.delta_eue / d.added_peak_mw, np.nan)
    d["category"] = np.where(
        d.added_peak_mw <= 0, "no_added",
        np.where((d.nodr_eue <= 0) & (d.case_eue <= 0), "no_eue", "value"))
    return d[["region", "per_mw", "delta_eue", "category"]], str(
        cfg.sweep_root / cfg.system(system)["always_on_shed_h5"]), ref


def make_per_mw_map(cfg, system, shapefile: Path, edges=None):
    """EUE change per MW of added load, matching stage 07's make_per_mw_map."""
    from matplotlib.patches import Patch
    label = cfg.system(system).get("label", system.upper())
    vals, path, ref = region_per_mw(cfg, system)
    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left")
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))
    minx, miny, maxx, maxy = ours.total_bounds
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)
    valued = ours[ours["category"] == "value"]
    grey = ours[ours["category"] != "value"]
    if edges is None:
        edges = [-1000.0, -100.0, -10.0, -1.0, 0.0, 1.0, 10.0, 100.0]

    fig, ax = plt.subplots(figsize=(12, 9.5))
    gdf.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.4)
    if len(grey):
        grey.plot(ax=ax, color="#d9d9d9", edgecolor="#888888", linewidth=0.6)
    handles = []
    if len(valued):
        listed, norm, colors = mapping.bin_cmap(edges, "RdBu_r")
        valued.plot(ax=ax, column="per_mw", cmap=listed, norm=norm,
                    edgecolor="#555555", linewidth=0.7)
        handles.extend(mapping.bin_patches(edges, colors, unit=" MWh/MW"))
    handles.append(Patch(facecolor="#d9d9d9", edgecolor="#888888",
                         label="no EUE / no added load"))
    ax.legend(handles=handles, title="ΔEUE per MW of added load",
              loc="lower right", fontsize=9, title_fontsize=10, framealpha=0.9)

    def _mwh(x):
        a = abs(x)
        return f"{x:+,.0f} MWh" if a >= 1 else (f"{x:+.2g} MWh" if a > 0 else "0 MWh")
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        txt = (f"{r['region']}\n{r['per_mw']:+.1f} MWh/MW\n"
               f"(ΔEUE {_mwh(r['delta_eue'])})") if r["category"] == "value" \
            else f"{r['region']}\nno EUE"
        ax.annotate(txt, (c.x, c.y), ha="center", va="center", fontsize=9,
                    color="black", fontweight="bold")
    ax.set_xlim(minx - mx, maxx + mx); ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — EUE change per MW of added load\n"
             f"case: shed_1h_timeseries   ·   (EUE_shed − EUE_noDR) / peak-added-MW"
             "   [negative = DR removed EUE]")
    if missing:
        title += f"\nno polygon: {', '.join(missing)}"
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    out_dir = (cfg.figure_path("_").parent / f"{system}_per_mw_maps"
               / "shed_1h_alwayson")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{system}_per_mw_map_shed_1h_timeseries.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    tbl = cfg.table_path(f"{system}_per_mw_shed_1h.csv")
    vals.sort_values("per_mw").to_csv(tbl, index=False)
    return out, tbl, missing, path


def make_map(cfg, system, shapefile: Path, edges=None):
    label = cfg.system(system).get("label", system.upper())
    vals, path = region_eue_per_year(cfg, system)
    metric = "eue_mwh_per_year"

    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left")
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))
    if edges is None:
        edges = mapping.decade_edges(ours[metric])

    fig, ax = plt.subplots(figsize=(11, 8.5))
    minx, miny, maxx, maxy = mapping.draw_binned(
        fig, ax, ours, gdf, metric, edges, cmap_name="YlOrRd",
        legend_title="EUE (MWh / year)")
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        v = r[metric]
        txt = f"{r['region']}\n{v:.3g}" if v and v > 0 else f"{r['region']}\n0"
        ax.annotate(txt, (c.x, c.y), ha="center", va="center", fontsize=9,
                    color="black", fontweight="bold")
    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — EUE (MWh / year) by region\n"
             "case: shed_1h_timeseries (always-on 100% shed)")
    if missing:
        title += f"\n(no polygon for: {', '.join(missing)})"
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    out = cfg.figure_path(f"{system}_eue_map_shed_1h_timeseries.png")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    tbl = cfg.table_path(f"{system}_region_eue_per_year_shed_1h.csv")
    vals.sort_values(metric, ascending=False).to_csv(tbl, index=False)
    return out, tbl, missing, path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default="ercot")
    ap.add_argument("--metric", default="eue",
                    choices=["eue", "ppm_removed", "per_mw"],
                    help="eue = EUE (MWh/yr) with the shed; ppm_removed = ΔNEUE "
                         "(ppm) vs no-DR baseline; per_mw = ΔEUE per MW of added "
                         "load, vs no-DR baseline")
    ap.add_argument("--shapefile", default=str(DEFAULT_SHAPEFILE))
    ap.add_argument("--bins", default=None,
                    help="comma-separated bin edges (use --bins=... form); "
                         "default = automatic decades")
    args = ap.parse_args()
    cfg = load_config(paths_yaml=args.config)
    shapefile = Path(args.shapefile)
    if not shapefile.exists():
        raise SystemExit(f"shapefile not found: {shapefile}")
    fn = {"ppm_removed": make_reduction_map, "per_mw": make_per_mw_map,
          "eue": make_map}[args.metric]
    out, tbl, missing, path = fn(cfg, args.system, shapefile,
                                 edges=mapping.parse_bins(args.bins))
    print(f"  source: {path}")
    print(f"  figure: {out}")
    print(f"  table : {tbl}")
    if missing:
        print(f"  note  : no polygon for {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

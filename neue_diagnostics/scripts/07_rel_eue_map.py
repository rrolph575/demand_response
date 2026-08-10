#!/usr/bin/env python
"""Stage 07 (standalone): map relative EUE change per region vs a baseline.

For each region, colors by the fractional change

    rel = (EUE_case - EUE_baseline) / EUE_baseline

so you can see whether a region that already had EUE ("pre-existing") gets a
large or small proportional increase once datacenter load (and DR) is applied.

  * baseline  = the pre-existing reference (default `baseline` = base demand,
                no DR). Set with --baseline.
  * case      = the scenario(s) to compare against it (default = the high-DC
                no-DR reference; pass --case one or more times, or --all-dr for
                every DR scenario -> one map each).

Three region categories are drawn distinctly, because the ratio is only defined
where the baseline is nonzero:

  * baseline > 0            -> colored by `rel` (log scale)
  * baseline == 0, case > 0 -> "NEW" (EUE that did not exist pre-load; rel is
                               infinite) -- drawn in a flat highlight color
  * both == 0               -> no EUE (grey)

Needs stage 00/01 output (registry, rollups). No .pras reads. Fast.

    python scripts/07_rel_eue_map.py --system pjm
    python scripts/07_rel_eue_map.py --system pjm --case shed_1h_timeseries
    python scripts/07_rel_eue_map.py --system pjm --all-dr
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

from neue_diag import mapping  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

DEFAULT_SHAPEFILE = (
    Path(__file__).resolve().parents[2] / "ReEDS" / "inputs" / "shapefiles"
    / "US_PCA" / "US_PCA.shp"
)
REGION_FIELD = "rb"

FS_LABEL = 11
FS_TITLE = 14
LABEL_COLOR = "#00b3ff"      # bright bold labels, as on the worst-event map
# Flat category fills, kept pale so the bright-blue labels stay readable.
NEW_COLOR = "#e6d5f5"        # pale purple: EUE that did not exist at baseline
BELOW_COLOR = "#cdeccd"      # pale green: DR pushed EUE BELOW the baseline
ZERO_COLOR = "#d9d9d9"       # grey: no EUE at all
WORSE_COLOR = "#d62728"      # red: DR INCREASED a region's EUE (vs-nodr mode)
NOEUE_COLOR = "#d9d9d9"      # grey: no EUE to reduce (vs-nodr mode)


def region_eue(cfg, system, case):
    roll = pd.read_csv(cfg.cache_path("rollups", f"{system}_region.csv"))
    r = roll[roll["case_id"] == case]
    if not len(r):
        raise SystemExit(f"no rollup rows for {system}/{case}; run stage 01")
    return r.set_index("region")["eue_mwh"]


def region_load_high(cfg, system):
    """Per-region total load (MWh) in the high-DC scenario, from stage-02 features."""
    z = np.load(cfg.cache_path("features", f"{system}.npz"), allow_pickle=True)
    regions = list(z["regions"])
    return pd.Series(z["feat__load_high_mw"].sum(axis=0), index=regions)


def nodr_stderr(cfg, system, nodr):
    """Monte-Carlo stderr (MWh) of the no-DR case's system EUE (the noise yardstick)."""
    reg = pd.read_csv(cfg.cache_path("registry.csv"))
    row = reg[(reg["system"] == system) & (reg["case_id"] == nodr)]
    return float(row["eue_stderr_mwh"].iloc[0]) if len(row) else 0.0


def reduction_vs_nodr(cfg, system, case, nodr):
    """Per-region DR effect vs the high-DC no-DR case.

        reduction  = (EUE_noDR - EUE_case) / EUE_noDR   (for coloring, 0..1)
        delta_eue  = EUE_case - EUE_noDR   (MWh, signed change; - = improved)
        delta_neue = 1e6 * delta_eue / load  (ppm NEUE change; - = improved)

    Categories:
        no_eue  -- no-DR case already had zero EUE (nothing to reduce)
        noise   -- |delta_eue| < 1x the MC stderr (not distinguishable from noise)
        worse   -- DR increased EUE beyond the noise floor
        reduced -- DR decreased EUE beyond the noise floor
    """
    noDR = region_eue(cfg, system, nodr)
    cur = region_eue(cfg, system, case)
    load = region_load_high(cfg, system)
    stderr = nodr_stderr(cfg, system, nodr)

    df = pd.DataFrame({"nodr_eue": noDR, "case_eue": cur, "load": load}).fillna(0.0)
    df["reduction"] = np.where(
        df["nodr_eue"] > 0, (df["nodr_eue"] - df["case_eue"]) / df["nodr_eue"],
        np.nan,
    )
    df["delta_eue"] = df["case_eue"] - df["nodr_eue"]
    df["delta_neue_ppm"] = np.where(
        df["load"] > 0, 1e6 * df["delta_eue"] / df["load"], np.nan)

    def _cat(r):
        if r["nodr_eue"] <= 0:
            return "no_eue"
        if abs(r["delta_eue"]) < stderr:      # within Monte-Carlo noise
            return "noise"
        return "worse" if r["case_eue"] > r["nodr_eue"] else "reduced"

    df["category"] = df.apply(_cat, axis=1)
    df.attrs["stderr"] = stderr
    return df.reset_index().rename(columns={"index": "region"})


def rel_change(cfg, system, case, baseline):
    base = region_eue(cfg, system, baseline)
    cur = region_eue(cfg, system, case)
    df = pd.DataFrame({"base_eue": base, "case_eue": cur}).fillna(0.0)
    df["rel"] = np.where(df["base_eue"] > 0,
                         (df["case_eue"] - df["base_eue"]) / df["base_eue"],
                         np.nan)
    # Four categories, because the ratio is only well-defined and bin-plottable
    # where base>0 and case>=base:
    #   ratio -> base>0, case>=base  (rel>=0)   colored by discrete bins
    #   below -> base>0, case<base   (rel<0)    DR pushed EUE below pre-existing
    #   new   -> base==0, case>0                EUE that did not exist at baseline
    #   none  -> base==0, case==0               no EUE either way
    def _cat(row):
        if row["base_eue"] > 0:
            return "ratio" if row["case_eue"] >= row["base_eue"] else "below"
        return "new" if row["case_eue"] > 0 else "none"

    df["category"] = df.apply(_cat, axis=1)
    return df.reset_index().rename(columns={"index": "region"})


def make_map(cfg, system, case, baseline, shapefile, suffix,
             edges=None, label_color=LABEL_COLOR, label_pos=None):
    # label_pos is accepted for API parity with the vs-nodr / per-mw maps but
    # not applied here: the base-DC ratio map labels regions in place.
    from matplotlib.patches import Patch

    label = cfg.system(system).get("label", system.upper())
    vals = rel_change(cfg, system, case, baseline)

    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left"
    )
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))

    minx, miny, maxx, maxy = ours.total_bounds
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)

    ratio = ours[ours["category"] == "ratio"]
    below = ours[ours["category"] == "below"]
    new = ours[ours["category"] == "new"]
    none = ours[ours["category"] == "none"]

    if edges is None:
        edges = mapping.decade_edges(ratio["rel"]) if len(ratio) else [0, 1, 10]

    fig, ax = plt.subplots(figsize=(12, 9.5))
    gdf.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.4)

    # Flat categories first, then the binned ratio regions on top.
    for sub, col in ((none, ZERO_COLOR), (below, BELOW_COLOR), (new, NEW_COLOR)):
        if len(sub):
            sub.plot(ax=ax, color=col, edgecolor="#555555", linewidth=0.7)

    handles = []
    if len(ratio):
        listed, norm, colors = mapping.bin_cmap(edges, "YlOrRd")
        ratio.plot(ax=ax, column="rel", cmap=listed, norm=norm,
                   edgecolor="#555555", linewidth=0.7)
        handles.extend(mapping.bin_patches(edges, colors, unit="×"))
    if len(below):
        handles.append(Patch(facecolor=BELOW_COLOR, edgecolor="#555555",
                             label="below baseline (DR helped past it)"))
    if len(new):
        handles.append(Patch(facecolor=NEW_COLOR, edgecolor="#555555",
                             label="NEW (no EUE at baseline)"))
    if len(none):
        handles.append(Patch(facecolor=ZERO_COLOR, edgecolor="#888888",
                             label="no EUE either way"))
    ax.legend(handles=handles, title="(EUE_case − EUE_base) / EUE_base",
              loc="lower left", fontsize=10, title_fontsize=10, framealpha=0.9)

    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        if r["category"] == "ratio":
            txt = f"{r['region']}\n+{r['rel']:.1f}×"
        elif r["category"] == "below":
            txt = f"{r['region']}\n{r['rel']:.2f}×"
        elif r["category"] == "new":
            txt = f"{r['region']}\nNEW\n{r['case_eue']:,.0f} MWh"
        else:
            txt = f"{r['region']}\n0"
        ax.annotate(txt, (c.x, c.y), ha="center", va="center",
                    fontsize=FS_LABEL, color=label_color, fontweight="bold")

    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — relative EUE change vs {baseline}\n"
             f"case: {case}   ·   value = (EUE_case − EUE_base) / EUE_base")
    if missing:
        title += f"\nno polygon: {', '.join(missing)}"
    ax.set_title(title, fontsize=FS_TITLE)
    fig.tight_layout()

    out = cfg.figure_path(f"{system}_rel_eue_map{suffix}.png")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)

    tbl = cfg.table_path(f"{system}_rel_eue{suffix}.csv")
    vals.sort_values("case_eue", ascending=False).to_csv(tbl, index=False)
    return out, tbl, missing


def make_reduction_map(cfg, system, case, nodr, shapefile, suffix,
                       edges=None, label_color=LABEL_COLOR, label_pos=None):
    """DR-effect map: % of each region's EUE removed by DR vs the no-DR case."""
    from matplotlib.patches import Patch

    label = cfg.system(system).get("label", system.upper())
    vals = reduction_vs_nodr(cfg, system, case, nodr)

    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left"
    )
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))
    minx, miny, maxx, maxy = ours.total_bounds
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)

    reduced = ours[ours["category"] == "reduced"]
    worse = ours[ours["category"] == "worse"]
    noeue = ours[ours["category"] == "no_eue"]
    # Reduction fraction 0..1 in 20-point bins; 1.0 (fully eliminated) sits in
    # the top bin. Greens: pale = little removed, dark = most removed.
    if edges is None:
        edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0001]

    fig, ax = plt.subplots(figsize=(12, 9.5))
    gdf.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.4)
    for sub, col in ((noeue, NOEUE_COLOR), (worse, WORSE_COLOR)):
        if len(sub):
            sub.plot(ax=ax, color=col, edgecolor="#555555", linewidth=0.7)

    handles = []
    if len(reduced):
        listed, norm, colors = mapping.bin_cmap(edges, "Greens")
        reduced.plot(ax=ax, column="reduction", cmap=listed, norm=norm,
                     edgecolor="#555555", linewidth=0.7)
        handles.extend(mapping.bin_patches(
            edges, colors, fmt=lambda x: f"{x * 100:.0f}%"))
    if len(worse):
        handles.append(Patch(facecolor=WORSE_COLOR, edgecolor="#555555",
                             label="DR increased EUE"))
    if len(noeue):
        handles.append(Patch(facecolor=NOEUE_COLOR, edgecolor="#888888",
                             label="no EUE to reduce"))
    ax.legend(handles=handles, title="% of EUE removed by DR",
              loc="lower right", fontsize=10, title_fontsize=10, framealpha=0.9)

    def _mwh(x):
        # Signed MWh removed (noDR - case): +ve = removed, -ve = added.
        ax = abs(x)
        if ax >= 1:
            return f"{x:,.0f} MWh"
        if ax > 0:
            return f"{x:.2g} MWh"
        return "0 MWh"

    items = []
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        removed = r["nodr_eue"] - r["case_eue"]   # MWh of EUE removed
        if r["category"] == "reduced":
            txt = (f"{r['region']}\n{r['reduction'] * 100:.0f}% removed\n"
                   f"({_mwh(removed)})")
        elif r["category"] == "worse":
            txt = (f"{r['region']}\n{r['reduction'] * 100:.0f}% (worse)\n"
                   f"({_mwh(removed)})")
        else:
            txt = f"{r['region']}\nno EUE"
        items.append({"xy": (c.x, c.y), "area": r.geometry.area, "text": txt,
                      "region": r["region"]})
    label_xy = mapping.smart_labels(ax, items, color=label_color,
                                    fontsize=FS_LABEL, overrides=label_pos)
    if label_xy:
        lxs = [p[0] for p in label_xy] + [minx, maxx]
        lys = [p[1] for p in label_xy] + [miny, maxy]
        minx, maxx, miny, maxy = min(lxs), max(lxs), min(lys), max(lys)
        mx, my = 0.06 * (maxx - minx), 0.06 * (maxy - miny)

    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — EUE removed by DR (vs no-DR high-DC case)\n"
             f"case: {case}   ·   value = (EUE_noDR − EUE_case) / EUE_noDR")
    if missing:
        title += f"\nno polygon: {', '.join(missing)}"
    ax.set_title(title, fontsize=FS_TITLE)
    fig.tight_layout()

    out = cfg.figure_path(f"{system}_dr_effect_map{suffix}.png")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    tbl = cfg.table_path(f"{system}_dr_effect{suffix}.csv")
    vals.sort_values("reduction", ascending=False).to_csv(tbl, index=False)
    return out, tbl, missing


def region_added_peak(cfg, system):
    """Peak added datacenter load (MW) per region, from stage-02's summary."""
    a = pd.read_csv(cfg.table_path(f"{system}_added_load_summary.csv"))
    return a.set_index("region")["added_peak_mw"]


def per_mw_added(cfg, system, case, nodr):
    """(EUE_case - EUE_noDR) / peak-added-MW per region  [MWh EUE per MW added].

    Negative = DR removed EUE per MW of that region's added load (good);
    positive = DR worsened it. The denominator (peak added load) is fixed per
    region, so maps are comparable across cases. NOTE: shed_1h is always-on, so
    its per-MW effect is not apples-to-apples with the windowed shed cases.
    """
    noDR = region_eue(cfg, system, nodr)
    cur = region_eue(cfg, system, case)
    added = region_added_peak(cfg, system)
    df = pd.DataFrame({"nodr_eue": noDR, "case_eue": cur, "added_peak_mw": added})
    df = df.fillna(0.0)
    df["delta_eue"] = df["case_eue"] - df["nodr_eue"]
    df["per_mw"] = np.where(df["added_peak_mw"] > 0,
                            df["delta_eue"] / df["added_peak_mw"], np.nan)
    df["category"] = np.where(
        df["added_peak_mw"] <= 0, "no_added",
        np.where((df["nodr_eue"] <= 0) & (df["case_eue"] <= 0), "no_eue", "value"),
    )
    return df.reset_index().rename(columns={"index": "region"})


def make_per_mw_map(cfg, system, case, nodr, shapefile, suffix,
                    edges=None, label_color=LABEL_COLOR, label_pos=None):
    """Map of EUE change per MW of added load (diverging: blue=removed, red=worse)."""
    from matplotlib.patches import Patch

    label = cfg.system(system).get("label", system.upper())
    vals = per_mw_added(cfg, system, case, nodr)
    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left")
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))
    minx, miny, maxx, maxy = ours.total_bounds
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)

    valued = ours[ours["category"] == "value"]
    grey = ours[ours["category"] != "value"]
    # Signed diverging decade bins; blue (RdBu_r low) = EUE removed per MW,
    # red = EUE increased per MW, near-white at 0.
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

    items = []
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        if r["category"] == "value":
            txt = (f"{r['region']}\n{r['per_mw']:+.1f} MWh/MW\n"
                   f"(ΔEUE {_mwh(r['delta_eue'])})")
        else:
            txt = f"{r['region']}\nno EUE"
        items.append({"xy": (c.x, c.y), "area": r.geometry.area, "text": txt,
                      "region": r["region"]})
    label_xy = mapping.smart_labels(ax, items, color=label_color,
                                    fontsize=FS_LABEL, overrides=label_pos)
    if label_xy:
        lxs = [p[0] for p in label_xy] + [minx, maxx]
        lys = [p[1] for p in label_xy] + [miny, maxy]
        minx, maxx, miny, maxy = min(lxs), max(lxs), min(lys), max(lys)
        mx, my = 0.06 * (maxx - minx), 0.06 * (maxy - miny)

    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — EUE change per MW of added load\n"
             f"case: {case}   ·   (EUE_case − EUE_noDR) / peak-added-MW  "
             f"[negative = DR removed EUE]")
    if missing:
        title += f"\nno polygon: {', '.join(missing)}"
    ax.set_title(title, fontsize=FS_TITLE)
    fig.tight_layout()

    out = cfg.figure_path(f"{system}_per_mw_map{suffix}.png")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    tbl = cfg.table_path(f"{system}_per_mw{suffix}.csv")
    vals.sort_values("per_mw").to_csv(tbl, index=False)
    return out, tbl, missing


def neue_diff(cfg, system, case, nodr):
    """Per-region NEUE change vs the no-DR case: NEUE_case - NEUE_noDR  [ppm].

        NEUE = 1e6 * EUE / load   (high-DC load per region)

    Negative = DR lowered the region's NEUE (good); positive = raised it.
    """
    noDR = region_eue(cfg, system, nodr)
    cur = region_eue(cfg, system, case)
    load = region_load_high(cfg, system)
    df = pd.DataFrame({"nodr_eue": noDR, "case_eue": cur, "load": load}).fillna(0.0)
    df["dneue_ppm"] = np.where(
        df["load"] > 0, 1e6 * (df["case_eue"] - df["nodr_eue"]) / df["load"], np.nan)
    df["category"] = np.where(
        df["load"] <= 0, "no_load",
        np.where((df["nodr_eue"] <= 0) & (df["case_eue"] <= 0), "no_eue", "value"))
    return df.reset_index().rename(columns={"index": "region"})


def make_neue_diff_map(cfg, system, case, nodr, shapefile, suffix,
                       edges=None, label_color=LABEL_COLOR, label_pos=None):
    """Map of regional NEUE change vs no-DR (ppm; diverging blue=lower, red=higher)."""
    from matplotlib.patches import Patch

    label = cfg.system(system).get("label", system.upper())
    vals = neue_diff(cfg, system, case, nodr)
    gdf = mapping.load_pca(shapefile).merge(
        vals, left_on=REGION_FIELD, right_on="region", how="left")
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(vals["region"]) - set(gdf[REGION_FIELD]))
    minx, miny, maxx, maxy = ours.total_bounds
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)

    valued = ours[ours["category"] == "value"]
    grey = ours[ours["category"] != "value"]
    # Fixed diverging bins (shared across all cases/systems for comparability).
    if edges is None:
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
    ax.legend(handles=handles, title="ΔNEUE  (NEUE_case − NEUE_noDR)",
              loc="lower right", fontsize=9, title_fontsize=10, framealpha=0.9)

    def _ppm(x):
        a = abs(x)
        return f"{x:+.2f} ppm" if a >= 0.01 else (f"{x:+.2g} ppm" if a > 0 else "0 ppm")

    items = []
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        if r["category"] == "value":
            txt = f"{r['region']}\n{_ppm(r['dneue_ppm'])}"
        else:
            txt = f"{r['region']}\nno EUE"
        items.append({"xy": (c.x, c.y), "area": r.geometry.area, "text": txt,
                      "region": r["region"]})
    label_xy = mapping.smart_labels(ax, items, color=label_color,
                                    fontsize=FS_LABEL, overrides=label_pos)
    if label_xy:
        lxs = [p[0] for p in label_xy] + [minx, maxx]
        lys = [p[1] for p in label_xy] + [miny, maxy]
        minx, maxx, miny, maxy = min(lxs), max(lxs), min(lys), max(lys)
        mx, my = 0.06 * (maxx - minx), 0.06 * (maxy - miny)

    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    title = (f"{label} — regional NEUE change vs no-DR high-DC case\n"
             f"case: {case}   ·   NEUE_case − NEUE_noDR  [ppm; negative = DR lowered NEUE]")
    if missing:
        title += f"\nno polygon: {', '.join(missing)}"
    ax.set_title(title, fontsize=FS_TITLE)
    fig.tight_layout()

    out = cfg.figure_path(f"{system}_neue_diff_map{suffix}.png")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    tbl = cfg.table_path(f"{system}_neue_diff{suffix}.csv")
    vals.sort_values("dneue_ppm").to_csv(tbl, index=False)
    return out, tbl, missing


def resolve_cases(registry, system, cases, all_dr):
    reg = registry[registry["system"] == system]
    if all_dr:
        dr = reg[(~reg["is_reference"]) & (reg["dc_scenario"] == "high")]
        return sorted(dr["case_id"])
    if cases:
        bad = [c for c in cases if c not in set(reg["case_id"])]
        if bad:
            raise SystemExit(f"{system}: unknown case(s) {bad}")
        return cases
    ref = reg[(reg["is_reference"]) & (reg["dc_scenario"] == "high")]
    if not len(ref):
        raise SystemExit(f"no high-DC no-DR reference for {system}; pass --case")
    return [ref.iloc[0]["case_id"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--baseline", default="baseline",
                    help="pre-existing reference case (default: base demand, no DR)")
    ap.add_argument("--case", action="append", default=None,
                    help="scenario case_id; repeatable. Default = high-DC no-DR ref")
    ap.add_argument("--all-dr", action="store_true",
                    help="one map for every high-DC DR scenario")
    ap.add_argument("--vs-nodr", action="store_true",
                    help="DR-effect mode: baseline = high-DC no-DR case, and the "
                         "map shows % of EUE each DR case removes (green=helped, "
                         "red=worsened) instead of ratio-above-base-DC")
    ap.add_argument("--per-mw", action="store_true",
                    help="per-MW mode: (EUE_case - EUE_noDR) / peak-added-MW per "
                         "region [MWh/MW], diverging blue(removed)/red(worse)")
    ap.add_argument("--neue-diff", action="store_true",
                    help="NEUE-diff mode: NEUE_case - NEUE_noDR per region [ppm], "
                         "diverging blue(lower)/red(higher)")
    ap.add_argument("--shapefile", default=str(DEFAULT_SHAPEFILE))
    ap.add_argument("--bins", default=None,
                    help="comma-separated bin edges; default = automatic decades")
    ap.add_argument("--label-color", default=LABEL_COLOR)
    ap.add_argument("--label-pos", default=None,
                    help="manual label placement in axes fractions, e.g. "
                         "'p113:0.08,0.50'; leader line links back to the polygon")
    args = ap.parse_args()
    edges = mapping.parse_bins(args.bins)

    label_pos = {}
    if args.label_pos:
        for part in args.label_pos.split(";"):
            if part.strip():
                reg, xy = part.split(":")
                x, y = xy.split(",")
                label_pos[reg.strip()] = (float(x), float(y))

    cfg = load_config(paths_yaml=args.config)
    shapefile = Path(args.shapefile)
    if not shapefile.exists():
        raise SystemExit(f"shapefile not found: {shapefile}")

    registry = pd.read_csv(cfg.cache_path("registry.csv"))
    systems = [args.system] if args.system else cfg.system_names()

    vs_nodr = args.vs_nodr or args.per_mw or args.neue_diff  # baseline = no-DR case
    for system in systems:
        baseline = (resolve_cases(registry, system, None, False)[0]
                    if vs_nodr else args.baseline)
        if baseline not in set(registry[registry["system"] == system]["case_id"]):
            print(f"  {system}: baseline {baseline!r} not found; skipping")
            continue
        cases = resolve_cases(registry, system, args.case, args.all_dr)
        if len(cases) > 10:
            print(f"  {system}: generating {len(cases)} maps (one per case)...")
        for case in cases:
            if case == baseline:
                continue
            suffix = f"_{case}"
            mode = ("neue-diff" if args.neue_diff else "per-mw" if args.per_mw
                    else "vs-nodr" if args.vs_nodr else "")
            print(f"\n=== {system} ===  baseline={baseline}  case={case}"
                  f"{'  [' + mode + ']' if mode else ''}")
            if args.neue_diff:
                out, tbl, missing = make_neue_diff_map(
                    cfg, system, case, baseline, shapefile, suffix,
                    edges=edges, label_color=args.label_color, label_pos=label_pos,
                )
            elif args.per_mw:
                out, tbl, missing = make_per_mw_map(
                    cfg, system, case, baseline, shapefile, suffix,
                    edges=edges, label_color=args.label_color, label_pos=label_pos,
                )
            elif args.vs_nodr:
                out, tbl, missing = make_reduction_map(
                    cfg, system, case, baseline, shapefile, suffix,
                    edges=edges, label_color=args.label_color, label_pos=label_pos,
                )
            else:
                # default (single, unsuffixed) case keeps the canonical name
                default_case = resolve_cases(registry, system, None, False)[0]
                s = "" if case == default_case else suffix
                out, tbl, missing = make_map(
                    cfg, system, case, baseline, shapefile, s,
                    edges=edges, label_color=args.label_color, label_pos=label_pos,
                )
            print(f"  figure: {out}")
            print(f"  table : {tbl}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

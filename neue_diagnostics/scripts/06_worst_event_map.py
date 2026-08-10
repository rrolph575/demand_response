#!/usr/bin/env python
"""Stage 06 (standalone): map each region's single worst EUE event, with date.

For a chosen case, finds the largest EUE *event* (a contiguous unserved-energy
episode) in each region, colors the region by that event's total EUE, and labels
it with the region id, the event's start date, and the magnitude.

"Worst event" = the episode with the greatest total EUE summed over its hours --
the same definition `pjm_worst_event.png` uses for its single overall worst event.

Needs stage 00/01/03 output (registry, timeindex, and the per-case events table
from stage 03). Reads no .pras files. Fast; a few seconds.

    python scripts/06_worst_event_map.py                    # all systems, default case
    python scripts/06_worst_event_map.py --system pjm
    python scripts/06_worst_event_map.py --case shed_1h_timeseries
    python scripts/06_worst_event_map.py --color peak_eue_mwh   # size by worst single hour
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

DEFAULT_SHAPEFILE = (
    Path(__file__).resolve().parents[2] / "ReEDS" / "inputs" / "shapefiles"
    / "US_PCA" / "US_PCA.shp"
)
REGION_FIELD = "rb"

# Bigger fonts than the mean-EUE map, per request.
FS_LABEL = 11
FS_TITLE = 15
# Bright bold label color that reads over the YlOrRd fills (override with
# --label-color). Cyan-blue pops hardest on the dark-red / orange regions where
# the big-number labels sit.
LABEL_COLOR = "#00b3ff"


def resolve_case(registry, system, case):
    reg = registry[registry["system"] == system]
    if case:
        if case not in set(reg["case_id"]):
            raise SystemExit(f"case {case!r} not in {system}")
        return case
    ref = reg[(reg["is_reference"]) & (reg["dc_scenario"] == "high")]
    if not len(ref):
        raise SystemExit(f"no high-DC no-DR reference for {system}; pass --case")
    return ref.iloc[0]["case_id"]


RANK_COL = {"peak": "peak_eue_mwh", "total": "total_eue_mwh"}


def worst_per_region(cfg, system, case, rank_by):
    """Each region's single worst event, selected by `rank_by` ('peak'|'total').

    Also flags `peak_total_mismatch`: True where the region's biggest-total
    outage is a *different* event than its worst-peak-hour event. Both maps
    color by peak-hour EUE; the two differ only in which event they select
    (hence which date/values are shown).
    """
    ev = pd.read_csv(cfg.table_path(f"{system}_events.csv"))
    ev = ev[ev["case_id"] == case]
    if not len(ev):
        raise SystemExit(
            f"no events for {system}/{case}. Run stage 03 (03_attribute.py) first, "
            f"and note only a few cases have an events table."
        )
    ti = pd.read_csv(cfg.cache_path("timeindex", f"{system}.csv"),
                     parse_dates=["timestamp_utc"])
    offset = cfg.system(system).get("local_utc_offset", 0)
    tsmap = ti.set_index("hour_idx")["timestamp_utc"]

    by_total = ev.loc[ev.groupby("region")["total_eue_mwh"].idxmax()].set_index("region")
    by_peak = ev.loc[ev.groupby("region")["peak_eue_mwh"].idxmax()].set_index("region")
    mismatch = by_total["start_hour_idx"] != by_peak["start_hour_idx"]

    chosen = (by_total if rank_by == "total" else by_peak).copy()
    chosen["peak_total_mismatch"] = mismatch
    # Date year uses the event's (relabeled) weather_year so it matches the
    # weather-year convention (e.g. a PRAS-2015 block reads 2017); month-day
    # comes from the timestamp.
    start_local = chosen["start_hour_idx"].map(tsmap) + pd.Timedelta(hours=offset)
    chosen["date"] = [f"{int(wy):04d}-{d:%m-%d}"
                      for wy, d in zip(chosen["weather_year"], start_local)]
    return chosen.reset_index()[
        ["region", "date", "duration_h", "total_eue_mwh", "peak_eue_mwh",
         "peak_total_mismatch"]
    ]


def make_map(cfg, system, case, rank_by, shapefile, suffix, edges=None,
             label_color=LABEL_COLOR, label_pos=None, fmt="png"):
    from matplotlib.patches import Patch

    label = cfg.system(system).get("label", system.upper())
    worst = worst_per_region(cfg, system, case, rank_by)
    color = "peak_eue_mwh"   # both maps are colored by peak-hour intensity

    gdf = mapping.load_pca(shapefile).merge(
        worst, left_on=REGION_FIELD, right_on="region", how="left"
    )
    ours = gdf[gdf["region"].notna()].copy()
    missing = sorted(set(worst["region"]) - set(gdf[REGION_FIELD]))

    if edges is None:
        edges = mapping.decade_edges(ours[color])
    metric_name = "worst-event peak-hour EUE (MWh)"

    # Hatch regions (only on the total-ranked map) where the biggest-total
    # outage is a different event than the worst-peak-hour one.
    hatch = ours[ours["peak_total_mismatch"].fillna(False)] if rank_by == "total" \
        else ours.iloc[0:0]
    extra = None
    if len(hatch):
        extra = [Patch(facecolor="#f0f0f0", edgecolor="#333333", hatch="////",
                       label="biggest outage ≠ worst peak hour")]

    fig, ax = plt.subplots(figsize=(12, 9.5))
    minx, miny, maxx, maxy = mapping.draw_binned(
        fig, ax, ours, gdf, color, edges, cmap_name="YlOrRd", unit=" MWh",
        zero_label="no event", legend_title=metric_name, extra_patches=extra,
        legend_loc="lower right",
    )
    if len(hatch):
        hatch.plot(ax=ax, facecolor="none", edgecolor=(0.15, 0.15, 0.15, 0.55),
                   hatch="////", linewidth=0.0)
    mx, my = 0.12 * (maxx - minx), 0.12 * (maxy - miny)

    # Region label: "region; date", then worst single-hour EUE with the whole
    # event's total EUE in parentheses. Small, crowd-prone regions are fanned
    # out on leader lines (mapping.smart_labels) so the dense cluster is legible.
    items = []
    for _, r in ours.iterrows():
        c = r.geometry.representative_point()
        txt = (f"{r['region']}; {r['date']}\n"
               f"{r['peak_eue_mwh']:,.0f} MWh EUE (peak hr)\n"
               f"({r['total_eue_mwh']:,.0f} MWh event total)")
        items.append({"xy": (c.x, c.y), "area": r.geometry.area, "text": txt,
                      "region": r["region"]})
    label_xy = mapping.smart_labels(ax, items, color=label_color,
                                    fontsize=FS_LABEL, overrides=label_pos)
    # Widen the view so any fanned-out labels stay on-canvas.
    if label_xy:
        lxs = [p[0] for p in label_xy] + [minx, maxx]
        lys = [p[1] for p in label_xy] + [miny, maxy]
        minx, maxx = min(lxs), max(lxs)
        miny, maxy = min(lys), max(lys)
        mx, my = 0.06 * (maxx - minx), 0.06 * (maxy - miny)

    ax.set_xlim(minx - mx, maxx + mx)
    ax.set_ylim(miny - my, maxy + my)
    ax.set_axis_off()
    rank_desc = ("biggest total-energy outage" if rank_by == "total"
                 else "worst single peak hour")
    title = (f"{label} — worst EUE event per region  (ranked by {rank_desc})\n"
             f"colored by peak-hour EUE  ·  case: {case}")
    if missing:
        title += f"\n(no polygon: {', '.join(missing)})"
    ax.set_title(title, fontsize=FS_TITLE)
    fig.tight_layout()

    out = cfg.figure_path(f"{system}_worst_event_map{suffix}.{fmt}")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)

    tbl = cfg.table_path(f"{system}_worst_event_per_region{suffix}.csv")
    worst.sort_values(color, ascending=False).to_csv(tbl, index=False)
    return out, tbl, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--case", default=None)
    ap.add_argument("--rank-by", default="both",
                    choices=["peak", "total", "both"],
                    help="which event is each region's 'worst': peak-hour, "
                         "biggest total outage, or both maps (default)")
    ap.add_argument("--shapefile", default=str(DEFAULT_SHAPEFILE))
    ap.add_argument("--bins", default=None,
                    help="comma-separated bin edges; default = automatic decades")
    ap.add_argument("--label-color", default=LABEL_COLOR,
                    help="label text color (e.g. '#00b3ff' blue, '#00e676' green)")
    ap.add_argument("--label-pos", default=None,
                    help="manual label placement in axes fractions (0-1), e.g. "
                         "'p120:0.30,0.63;p100:0.52,0.50'. Left/bottom=0, "
                         "right/top=1. A leader line links back to the polygon.")
    ap.add_argument("--format", default="png", choices=["png", "svg", "pdf"],
                    help="output format; svg/pdf are vector-editable in Inkscape")
    args = ap.parse_args()
    edges = mapping.parse_bins(args.bins)

    # Keep SVG/PDF text as real, selectable text objects (not outlined paths)
    # so labels can be moved individually in a vector editor.
    if args.format in ("svg", "pdf"):
        matplotlib.rcParams["svg.fonttype"] = "none"
        matplotlib.rcParams["pdf.fonttype"] = 42

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
    rankings = ["peak", "total"] if args.rank_by == "both" else [args.rank_by]

    for system in systems:
        case = resolve_case(registry, system, args.case)
        default_case = resolve_case(registry, system, None)
        for rank_by in rankings:
            parts = []
            if case != default_case:
                parts.append(case)
            # peak-ranked keeps the canonical filename; total-ranked is suffixed.
            if rank_by == "total":
                parts.append("by_total_outage")
            suffix = ("_" + "_".join(parts)) if parts else ""
            print(f"\n=== {system} ===  case={case}  rank_by={rank_by}")
            try:
                out, tbl, missing = make_map(cfg, system, case, rank_by, shapefile,
                                             suffix, edges=edges,
                                             label_color=args.label_color,
                                             label_pos=label_pos, fmt=args.format)
            except SystemExit as e:
                print(f"  skipped: {e}")
                continue
            print(f"  figure: {out}")
            print(f"  table : {tbl}")
            if missing:
                print(f"  note  : no polygon for {missing}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

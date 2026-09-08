#!/usr/bin/env python
"""Stage 10 (standalone, WIP): 4-panel load + generation dashboard.

Layout (iterating -- start with PJM):
  top row:    [ Total Load ] [ Solar Generation ] [ Wind Generation ]
  bottom row: [ panel 4 -- TBD ]

The three top panels are month x hour-of-day heatmaps (mean over 15 weather
years, true local time), with the always-on shed's DR-dispatch windows boxed
(same per-system windows as scripts/08). Middle/right reuse stage 08's solar and
wind panels (just retitled "Solar/Wind Generation").

    python scripts/10_load_gen_panels.py --system pjm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"font.size": 16})   # bigger fonts throughout
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from neue_diag import io_results  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WIN_C = "#00c000"   # winter box: green (more visible than blue on the wind panel)
SUM_C = "#d62728"
DR_WINTER_MONTHS = (1, 2)
DR_SUMMER_MONTHS = (6, 8)
_TZ_BY_OFFSET = {-2: "Pacific", -1: "Mountain", 0: "Central", 1: "Eastern"}


def tz_label(cfg, system):
    off = int(cfg.system(system).get("local_utc_offset", 0))
    return _TZ_BY_OFFSET.get(off, f"CST{off:+d}h")


def _win_lbl(hours):
    lo, hi = hours
    return f"{lo:02d}:00" if lo == hi else f"{lo:02d}:00–{hi:02d}:00"


def load_series(cfg, system):
    """System-total load / solar / wind (GW) per hour + month/hour (true local)."""
    z = np.load(cfg.cache_path("features", f"{system}.npz"), allow_pickle=True)
    ti = pd.read_csv(cfg.cache_path("timeindex", f"{system}.csv"))
    load = z["feat__load_high_mw"].sum(axis=1) / 1000.0
    solar = z["feat__cap_solar_mw"].sum(axis=1) / 1000.0
    wind = z["feat__cap_wind_mw"].sum(axis=1) / 1000.0
    df = pd.DataFrame({
        "hour_idx": np.arange(len(load)),
        "load_gw": load,
        "solar_gw": solar,
        "wind_gw": wind,
        "net_load_gw": load - solar - wind,   # net load = load - solar - wind
    }).merge(ti[["hour_idx", "month", "hour_local"]], on="hour_idx", how="left")
    return df


def _grid(df, col):
    g = df.groupby(["month", "hour_local"])[col].mean().reset_index()
    grid = np.full((12, 24), np.nan)
    for _, r in g.iterrows():
        grid[int(r["month"]) - 1, int(r["hour_local"])] = r[col]
    return grid




def shed_data(cfg, system, frac=0.5):
    """One read of the shed file -> (dr_grid[12,24] mean MW, windows dict).

    windows: per-season contiguous hours whose mean dispatch >= frac*season peak.
    """
    rel = cfg.system(system).get("always_on_shed_h5")
    fallback = {"winter": (5, 8), "summer": (18, 21)}
    if not rel or not (cfg.sweep_root / rel).exists():
        return None, fallback
    arr = io_results.read_arrays(cfg.sweep_root / rel)
    dr = np.asarray(arr["dr_energy"], float).sum(axis=1)
    ts = [t.decode() if isinstance(t, (bytes, bytearray)) else str(t)
          for t in arr["timestamps"]]
    off = int(cfg.system(system).get("local_utc_offset", 0))
    month = np.array([int(s[5:7]) for s in ts])
    hour = (np.array([int(s[11:13]) for s in ts]) + off) % 24
    d = pd.DataFrame({"month": month, "hour": hour, "dr": dr})
    grid = np.zeros((12, 24))
    for (m, h), v in d.groupby(["month", "hour"])["dr"].mean().items():
        grid[int(m) - 1, int(h)] = v
    windows = dict(fallback)
    for name, months in (("winter", DR_WINTER_MONTHS), ("summer", DR_SUMMER_MONTHS)):
        s = d[d["month"].between(*months)].groupby("hour")["dr"].mean()
        if len(s) and s.max() > 0:
            hot = s[s >= frac * s.max()].index
            windows[name] = (int(hot.min()), int(hot.max()))
    return grid, windows


def _draw_heatmap(fig, ax, grid, cmap, title, cbar_label, windows,
                  vmin=None, vmax=None):
    im = ax.imshow(grid, aspect="auto", origin="upper", cmap=cmap,
                   extent=[-0.5, 23.5, 11.5, -0.5], vmin=vmin, vmax=vmax)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label(cbar_label, fontsize=15)
    ax.set_yticks(range(12)); ax.set_yticklabels(MONTHS)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("hour of day")
    ax.set_title(title, fontsize=19)
    for hrs, months, c in ((windows["winter"], DR_WINTER_MONTHS, WIN_C),
                           (windows["summer"], DR_SUMMER_MONTHS, SUM_C)):
        ax.add_patch(Rectangle(
            (hrs[0] - 0.5, months[0] - 1 - 0.5),
            hrs[1] - hrs[0] + 1, months[1] - months[0] + 1,
            fill=False, edgecolor=c, lw=2.2, zorder=5))


def make_fig(cfg, system):
    df = load_series(cfg, system)
    _, windows = shed_data(cfg, system)

    # Layout: Total Load / Solar / Wind stacked as equal-size rows in a left
    # column, with a bigger Net Load panel on the right spanning all three rows.
    fig = plt.figure(figsize=(15, 12))
    gs = fig.add_gridspec(3, 2, width_ratios=[1, 1.35], hspace=0.4, wspace=0.28)

    _draw_heatmap(fig, fig.add_subplot(gs[0, 0]), _grid(df, "load_gw"), "Greys",
                  "Total Load", "mean load (GW)", windows)
    _draw_heatmap(fig, fig.add_subplot(gs[1, 0]), _grid(df, "solar_gw"),
                  "YlOrBr", "Solar Generation", "mean available solar (GW)",
                  windows)
    _draw_heatmap(fig, fig.add_subplot(gs[2, 0]), _grid(df, "wind_gw"),
                  "Blues", "Wind Generation", "mean available wind (GW)",
                  windows)
    _draw_heatmap(fig, fig.add_subplot(gs[0:3, 1]), _grid(df, "net_load_gw"),
                  "Purples", "Net Load  (load − solar − wind)",
                  "mean net load (GW)", windows)

    handles = [
        Patch(facecolor="none", edgecolor=WIN_C, lw=2.2,
              label=f"winter DR window (Jan–Feb, {_win_lbl(windows['winter'])})"),
        Patch(facecolor="none", edgecolor=SUM_C, lw=2.2,
              label=f"summer DR window (Jun–Aug, {_win_lbl(windows['summer'])})"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=15,
               frameon=True, bbox_to_anchor=(0.5, 0.005))
    # System name in the upper-right corner (same size as subpanel titles).
    label = cfg.system(system).get("label", system.upper())
    fig.text(0.995, 0.995, label, ha="right", va="top", fontsize=19,
             fontweight="bold")
    out = cfg.figure_path(f"{system}_load_gen_panels.png")
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default="pjm")
    args = ap.parse_args()
    cfg = load_config(paths_yaml=args.config)
    print(f"  figure: {make_fig(cfg, args.system)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Stage 08 (standalone): solar & wind generation availability, aggregated years.

Motivation: the always-on shed is dispatched hardest in two windows (in true
local time) -- Jan-Feb early mornings (~05:00-08:00) and Jun-Aug early evenings
(~18:00-21:00, the solar-dropoff ramp). These plots show what solar and wind
*availability* looks like across the year and the day (system total available
MW, meaned over all 15 weather years) so those DR windows can be read against
the generation picture. Hour axis is each system's own local time (data is
Central; PJM shifted +1 h to Eastern -- see load_availability).

Two figures per system:
  {system}_gen_availability_heatmap.png   month x hour-of-day heatmaps (solar,
                                          wind); the two DR windows are boxed.
  {system}_gen_availability_profiles.png  monthly profile + diurnal profile
                                          (winter DR window vs summer DR window).

"Availability" = the hourly available capacity the adequacy model could draw on
(feat__cap_solar_mw / feat__cap_wind_mw), summed over regions -> system GW. Not
a capacity factor and not actual dispatch.

Needs only stage 01 (timeindex) + stage 02 (features npz). Reads no .pras files.
Fast; login-node safe.

    python scripts/08_gen_availability.py                 # all systems
    python scripts/08_gen_availability.py --system pjm
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
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from neue_diag import io_results  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

SOLAR_C = "#E8912A"   # solar: warm orange
WIND_C = "#3C8C40"    # wind: green
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# DR-dispatch windows are computed PER SYSTEM from the shed file (dr_windows()),
# in each system's own local hours, so the PJM and ERCOT boxes reflect their own
# timing. The *_HOURS values below are only fallbacks if the shed file is absent.
# Months are fixed (winter=Jan-Feb, summer=Jun-Aug); only the hour span is
# data-driven.
WIN_C = "#1f77ff"   # winter shading/box color
SUM_C = "#d62728"   # summer shading/box color
DR_WINTER_MONTHS = (1, 2)
DR_SUMMER_MONTHS = (6, 8)
DR_WINTER_HOURS = (5, 8)     # fallback only
DR_SUMMER_HOURS = (18, 21)   # fallback only


def _win_lbl(hours):
    lo, hi = hours
    return f"{lo:02d}:00" if lo == hi else f"{lo:02d}:00–{hi:02d}:00"


# Data is Central; local_utc_offset shifts CST -> each system's local zone.
_TZ_BY_OFFSET = {-2: "Pacific", -1: "Mountain", 0: "Central", 1: "Eastern"}


def tz_label(cfg, system):
    off = int(cfg.system(system).get("local_utc_offset", 0))
    return _TZ_BY_OFFSET.get(off, f"CST{off:+d}h")


def dr_windows(cfg, system, frac=0.5):
    """Per-system DR-dispatch windows, read from the always-on shed file so the
    boxes reflect THIS system's real timing (in its own local hours) rather than
    a shared hardcoded guess. Returns {'winter': (lo, hi), 'summer': (lo, hi)},
    each the contiguous span of hours whose mean dispatch is >= `frac` of that
    season's peak hour. Falls back to the module defaults if the file is absent.
    """
    rel = cfg.system(system).get("always_on_shed_h5")
    out = {"winter": DR_WINTER_HOURS, "summer": DR_SUMMER_HOURS}
    if not rel or not (cfg.sweep_root / rel).exists():
        return out
    arr = io_results.read_arrays(cfg.sweep_root / rel)
    dr = np.asarray(arr["dr_energy"], float).sum(axis=1)
    ts = [t.decode() if isinstance(t, (bytes, bytearray)) else str(t)
          for t in arr["timestamps"]]
    off = int(cfg.system(system).get("local_utc_offset", 0))
    month = np.array([int(s[5:7]) for s in ts])
    hour = (np.array([int(s[11:13]) for s in ts]) + off) % 24
    d = pd.DataFrame({"month": month, "hour": hour, "dr": dr})
    for name, months in (("winter", DR_WINTER_MONTHS), ("summer", DR_SUMMER_MONTHS)):
        s = d[d["month"].between(*months)].groupby("hour")["dr"].mean()
        if len(s) and s.max() > 0:
            hot = s[s >= frac * s.max()].index
            out[name] = (int(hot.min()), int(hot.max()))
    return out


def load_availability(cfg, system):
    """System-total available solar/wind (GW) per hour, joined to month/hour.

    Time convention: the PRAS timestamps are stamped +00:00 but the data is
    really Central Standard Time (ReEDS tz_out='Etc/GMT+6' = UTC-6). The
    timeindex `hour_local` column applies each system's CST->local offset
    (config: local_utc_offset -- ERCOT 0 since it IS Central, PJM +1 for
    Eastern), so we group by hour_local and it is true local time.
    """
    z = np.load(cfg.cache_path("features", f"{system}.npz"), allow_pickle=True)
    solar_gw = z["feat__cap_solar_mw"].sum(axis=1) / 1000.0
    wind_gw = z["feat__cap_wind_mw"].sum(axis=1) / 1000.0

    ti = pd.read_csv(cfg.cache_path("timeindex", f"{system}.csv"))
    df = pd.DataFrame({
        "hour_idx": np.arange(len(solar_gw)),
        "solar_gw": solar_gw,
        "wind_gw": wind_gw,
    }).merge(ti[["hour_idx", "month", "hour_local", "weather_year"]],
             on="hour_idx", how="left")
    return df


def _month_hour_grid(df, col):
    """12x24 grid of the mean of `col` per (month, hour), meaned over years."""
    g = df.groupby(["month", "hour_local"])[col].mean().reset_index()
    grid = np.full((12, 24), np.nan)
    for _, r in g.iterrows():
        grid[int(r["month"]) - 1, int(r["hour_local"])] = r[col]
    return grid


def fig_heatmap(cfg, system, df, windows):
    label = cfg.system(system).get("label", system.upper())
    wh, sh = windows["winter"], windows["summer"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    for ax, col, cmap, name in (
        (axes[0], "solar_gw", "YlOrBr", "solar"),
        # Blue, DARK = high wind, light = low wind (standard sequential).
        (axes[1], "wind_gw", "Blues", "wind"),
    ):
        grid = _month_hour_grid(df, col)
        im = ax.imshow(grid, aspect="auto", origin="upper", cmap=cmap,
                       extent=[-0.5, 23.5, 11.5, -0.5])
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.set_label(f"mean available {name} (GW)")
        ax.set_yticks(range(12))
        ax.set_yticklabels(MONTHS)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xlabel(f"hour of day ({tz_label(cfg, system)} local)")
        ax.set_title(f"{name} availability")

        # DR-usage windows (boxes; imshow cell (m,h) spans +/-0.5). Hours are
        # this system's own dispatch window (see dr_windows()).
        for hrs, months, c in ((wh, DR_WINTER_MONTHS, WIN_C),
                               (sh, DR_SUMMER_MONTHS, SUM_C)):
            ax.add_patch(Rectangle(
                (hrs[0] - 0.5, months[0] - 1 - 0.5),
                hrs[1] - hrs[0] + 1, months[1] - months[0] + 1,
                fill=False, edgecolor=c, lw=2.2, zorder=5))

    # Legend explaining the two boxes (unfilled rectangles as proxies).
    handles = [
        Patch(facecolor="none", edgecolor=WIN_C, lw=2.2,
              label=f"winter DR window (Jan–Feb, {_win_lbl(wh)})"),
        Patch(facecolor="none", edgecolor=SUM_C, lw=2.2,
              label=f"summer DR window (Jun–Aug, {_win_lbl(sh)})"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=10,
               frameon=True, bbox_to_anchor=(0.5, -0.03))
    fig.suptitle(
        f"{label} — solar & wind availability by month and hour "
        "(mean over 15 weather years)\nboxes = when the always-on shed is "
        "dispatched (true local time)",
        fontsize=12)
    fig.tight_layout(rect=[0, 0.03, 1, 0.96])
    out = cfg.figure_path(f"{system}_gen_availability_heatmap.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_profiles(cfg, system, df, windows):
    label = cfg.system(system).get("label", system.upper())
    wh, sh = windows["winter"], windows["summer"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))

    # --- monthly profile (mean over all hours & years) ---
    ax = axes[0]
    m = df.groupby("month")[["solar_gw", "wind_gw"]].mean()
    ax.plot(m.index, m["solar_gw"], "-o", color=SOLAR_C, lw=1.8, ms=4,
            label="solar")
    ax.plot(m.index, m["wind_gw"], "-s", color=WIND_C, lw=1.8, ms=4,
            label="wind")
    ax.axvspan(DR_WINTER_MONTHS[0] - 0.5, DR_WINTER_MONTHS[1] + 0.5,
               color=WIN_C, alpha=0.12)
    ax.axvspan(DR_SUMMER_MONTHS[0] - 0.5, DR_SUMMER_MONTHS[1] + 0.5,
               color=SUM_C, alpha=0.12)
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(MONTHS, rotation=45, fontsize=8)
    ax.set_ylabel("mean available generation (GW)")
    ax.set_title("Monthly availability")
    ax.grid(alpha=0.25)
    # Line legend + shaded-band legend, combined.
    h, l = ax.get_legend_handles_labels()
    h += [Patch(facecolor=WIN_C, alpha=0.3, label="winter DR months"),
          Patch(facecolor=SUM_C, alpha=0.3, label="summer DR months")]
    ax.legend(handles=h, fontsize=8)

    # --- diurnal profiles: winter DR months vs summer DR months ---
    winter = df[df["month"].between(*DR_WINTER_MONTHS)]
    summer = df[df["month"].between(*DR_SUMMER_MONTHS)]
    for ax, col, name, c in (
        (axes[1], "solar_gw", "solar", SOLAR_C),
        (axes[2], "wind_gw", "wind", WIND_C),
    ):
        w = winter.groupby("hour_local")[col].mean()
        s = summer.groupby("hour_local")[col].mean()
        ax.plot(w.index, w.values, "-o", color=WIN_C, lw=1.8, ms=3.5,
                label="winter (Jan–Feb)")
        ax.plot(s.index, s.values, "-o", color=SUM_C, lw=1.8, ms=3.5,
                label="summer (Jun–Aug)")
        # Shade each season's DR-dispatch window (when the shed actually fires).
        ax.axvspan(wh[0], wh[1], color=WIN_C, alpha=0.12)
        ax.axvspan(sh[0], sh[1], color=SUM_C, alpha=0.12)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel(f"hour of day ({tz_label(cfg, system)} local)")
        ax.set_ylabel(f"mean available {name} (GW)")
        ax.set_title(f"{name.capitalize()} — diurnal profile")
        ax.grid(alpha=0.25)
        h, l = ax.get_legend_handles_labels()
        h += [Patch(facecolor=WIN_C, alpha=0.3,
                    label=f"winter DR window ({_win_lbl(wh)})"),
              Patch(facecolor=SUM_C, alpha=0.3,
                    label=f"summer DR window ({_win_lbl(sh)})")]
        ax.legend(handles=h, fontsize=7.5)

    fig.suptitle(
        f"{label} — solar & wind availability profiles (mean over 15 weather years)",
        fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = cfg.figure_path(f"{system}_gen_availability_profiles.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    systems = [args.system] if args.system else cfg.system_names()
    for system in systems:
        print(f"\n=== {system} ===")
        df = load_availability(cfg, system)
        windows = dr_windows(cfg, system)
        print(f"  DR windows ({tz_label(cfg, system)} local): "
              f"winter {windows['winter']}  summer {windows['summer']}")
        print(f"  figure: {fig_heatmap(cfg, system, df, windows)}")
        print(f"  figure: {fig_profiles(cfg, system, df, windows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

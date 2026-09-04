#!/usr/bin/env python
"""Stage 09 (standalone): WHEN is the always-on shed dispatched?

For the always-on shed case (shed_1h_timeseries, the only DR case analyzed as of
2026-09), reads the DR energy actually dispatched each hour (/dr_energy) straight
from the *_samples/ result file named by config (systems.<sys>.always_on_shed_h5),
sums it over regions, and aggregates over all 15 weather years to show WHEN the
shed fires -- by month and by hour of day.

TIME CONVENTION: the PRAS timestamps are stamped +00:00 but the data is really
Central Standard Time (ReEDS tz_out='Etc/GMT+6' = UTC-6). We add each system's
CST->local offset (config: local_utc_offset -- ERCOT 0 since it IS Central, PJM
+1 for Eastern) so the hour axis is true local time. Read against
scripts/08_gen_availability.py (same convention) to see the shed firing during
the evening solar-dropoff ramp.

Reads the shed_1h .h5 directly (not the cached registry) so ERCOT -- whose shed_1h
lives only in ercot_neue1_samples/ -- is included. Fast; login-node safe.

    python scripts/09_dr_dispatch_timing.py
    python scripts/09_dr_dispatch_timing.py --system pjm
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

from neue_diag import io_results  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Data is Central; local_utc_offset shifts CST -> each system's local zone.
_TZ_BY_OFFSET = {-2: "Pacific", -1: "Mountain", 0: "Central", 1: "Eastern"}


def tz_label(cfg, system):
    off = int(cfg.system(system).get("local_utc_offset", 0))
    return _TZ_BY_OFFSET.get(off, f"CST{off:+d}h")


DR_C = "#7B3FA0"   # always-on shed: purple, matching the when-plot's shed_1h
WINTER_MONTHS = (1, 2)
SUMMER_MONTHS = (6, 8)


def shed_dispatch(cfg, system):
    """System-total DR dispatched (MW) per hour + month/hour (true local)."""
    rel = cfg.system(system).get("always_on_shed_h5")
    if not rel:
        raise SystemExit(f"no always_on_shed_h5 configured for {system}")
    path = cfg.sweep_root / rel
    if not path.exists():
        raise SystemExit(f"always-on shed file not found: {path}")

    arrays = io_results.read_arrays(path)
    dr = np.asarray(arrays["dr_energy"], dtype=float)      # (T, R) MWh/h == MW
    ts = np.asarray(arrays["timestamps"])
    ts = np.array([t.decode() if isinstance(t, (bytes, bytearray)) else str(t)
                   for t in ts])
    # The stored hour is Central Standard Time (ReEDS tz_out='Etc/GMT+6' = UTC-6);
    # add each system's CST->local offset (config: local_utc_offset -- ERCOT 0,
    # PJM +1 for Eastern) to reach true local time.
    offset = int(cfg.system(system).get("local_utc_offset", 0))
    month = np.array([int(s[5:7]) for s in ts])
    hour = (np.array([int(s[11:13]) for s in ts]) + offset) % 24
    return pd.DataFrame({
        "month": month, "hour_local": hour,
        "dr_mw": dr.sum(axis=1),                    # system-total dispatched MW
        "any_dispatched": (dr > 0).any(axis=1),     # any region shedding?
    }), str(path)


def _month_hour_grid(df, col):
    g = df.groupby(["month", "hour_local"])[col].mean().reset_index()
    grid = np.full((12, 24), np.nan)
    for _, r in g.iterrows():
        grid[int(r["month"]) - 1, int(r["hour_local"])] = r[col]
    return grid


def make_fig(cfg, system, df):
    label = cfg.system(system).get("label", system.upper())
    fig = plt.figure(figsize=(16, 5))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.4, 1, 1])

    # --- month x hour heatmap of mean dispatched DR ---
    ax0 = fig.add_subplot(gs[0])
    grid = _month_hour_grid(df, "dr_mw") / 1000.0   # GW
    im = ax0.imshow(grid, aspect="auto", origin="upper", cmap="Purples",
                    extent=[-0.5, 23.5, 11.5, -0.5])
    cb = fig.colorbar(im, ax=ax0, fraction=0.046, pad=0.04)
    cb.set_label("mean DR dispatched (GW)")
    ax0.set_yticks(range(12)); ax0.set_yticklabels(MONTHS)
    ax0.set_xticks(range(0, 24, 2)); ax0.set_xlabel(f"hour of day ({tz_label(cfg, system)} local)")
    ax0.set_title("When is the always-on shed dispatched?")

    # --- diurnal: winter vs summer ---
    ax1 = fig.add_subplot(gs[1])
    for months, name, c in ((WINTER_MONTHS, "winter (Jan–Feb)", "#1f77ff"),
                            (SUMMER_MONTHS, "summer (Jun–Aug)", "#d62728")):
        s = df[df["month"].between(*months)].groupby("hour_local")["dr_mw"].mean() / 1000
        ax1.plot(s.index, s.values, "-o", color=c, lw=1.8, ms=3.5, label=name)
    ax1.set_xticks(range(0, 24, 3)); ax1.set_xlabel(f"hour of day ({tz_label(cfg, system)} local)")
    ax1.set_ylabel("mean DR dispatched (GW)")
    ax1.set_title("Diurnal DR dispatch")
    ax1.grid(alpha=0.25); ax1.legend(fontsize=8)

    # --- monthly total dispatched energy ---
    ax2 = fig.add_subplot(gs[2])
    # total GWh per month = mean MW * hours-in-that-month-bin / 1000, but a simple
    # comparative view is the summed dispatched energy per month over all years.
    mo = df.groupby("month")["dr_mw"].sum() / 1000.0   # GWh over the record
    ax2.bar(mo.index, mo.values, color=DR_C)
    ax2.set_xticks(range(1, 13)); ax2.set_xticklabels(MONTHS, rotation=45,
                                                       fontsize=8)
    ax2.set_ylabel("total DR dispatched (GWh, all years)")
    ax2.set_title("DR dispatch by month")
    ax2.grid(alpha=0.25, axis="y")

    fig.suptitle(
        f"{label} — always-on shed (shed_1h) dispatch timing, mean/total over 15 "
        f"weather years  ·  true local time", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = cfg.figure_path(f"{system}_dr_dispatch_timing.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def make_prob_heatmap(cfg, system, df):
    """P(any region dispatched) by month x hour of day, on the TRUE-LOCAL axis.

    Same view as ssundar's shed_1h heatmap, but with the hour axis corrected to
    true local time (data is Central; ERCOT already local, PJM +1 h to Eastern),
    so the summer peak sits in the early evening instead of the mislabeled 13:00.
    """
    label = cfg.system(system).get("label", system.upper())
    # 24x12 grid: P(any region shedding) as a percentage, mean over all years.
    g = (df.groupby(["hour_local", "month"])["any_dispatched"].mean() * 100
         ).reset_index()
    grid = np.full((24, 12), np.nan)
    for _, r in g.iterrows():
        grid[int(r["hour_local"]), int(r["month"]) - 1] = r["any_dispatched"]

    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(grid, aspect="auto", cmap="Blues", origin="upper",
                   extent=[-0.5, 11.5, 23.5, -0.5])
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("P(dispatch) %")
    ax.set_xticks(range(12)); ax.set_xticklabels(MONTHS)
    ax.set_yticks(range(0, 24)); ax.set_yticklabels(range(0, 24), fontsize=7)
    ax.set_xlabel("month")
    ax.set_ylabel(f"hour of day ({tz_label(cfg, system)} local)")
    # annotate each cell
    vmax = np.nanmax(grid)
    for i in range(24):
        for j in range(12):
            v = grid[i, j]
            if np.isfinite(v) and v >= 0.05:
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=6,
                        color="white" if v > 0.55 * vmax else "#222")
    ax.set_title(
        f"{label} — always-on shed: P(any region dispatched) by month & hour\n"
        "true local time (summer peak early evening, NOT the mislabeled 13:00)",
        fontsize=12)
    fig.tight_layout()
    out = cfg.figure_path(f"{system}_dr_dispatch_prob.png")
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
        df, path = shed_dispatch(cfg, system)
        print(f"  file: {path}")
        tot = df["dr_mw"].sum()
        # Report the single busiest (month, hour) cells to confirm the windows.
        cell = (df.groupby(["month", "hour_local"])["dr_mw"].mean()
                .sort_values(ascending=False).head(5))
        print(f"  total DR dispatched: {tot:,.0f} MWh over the record")
        print("  busiest (month, hour_local) cells by mean MW:")
        for (m, h), v in cell.items():
            print(f"    {MONTHS[m-1]} {h:02d}:00  {v:,.0f} MW")
        print(f"  figure: {make_fig(cfg, system, df)}")
        print(f"  figure: {make_prob_heatmap(cfg, system, df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

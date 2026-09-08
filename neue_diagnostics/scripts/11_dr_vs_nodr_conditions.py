#!/usr/bin/env python
"""Stage 11 (standalone, WIP): per-region conditions when DR is used vs not.

For one region and season, compares the diurnal profile of net load / solar /
wind between the hours the always-on shed WAS dispatched (dr_energy > 0) and the
hours it was NOT (dr_energy == 0) -- at the same hour-of-day and same season, so
the only difference is whether DR fired. Isolates what conditions trigger DR.

Layout (per region): rows = winter (Jan-Feb) / summer (Jun-Aug),
                     cols = Net Load / Solar / Wind.
Each panel: x = hour of day (true local); solid line = DR used, dashed = DR not.

    python scripts/11_dr_vs_nodr_conditions.py --system pjm            # top-DR region
    python scripts/11_dr_vs_nodr_conditions.py --system pjm --region p99
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"font.size": 14})   # bigger fonts throughout
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from neue_diag import io_results  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

USED_C = "#d62728"   # DR used
NODR_C = "#555555"   # DR not used
BAR_C = "#9ecae1"    # % of days DR on (secondary-axis bars)
BAR_EDGE = "#2b6ca3"
SEASON_C = "#00008b"   # dark blue for the winter/summer row labels
_TZ = {-2: "Pacific", -1: "Mountain", 0: "Central", 1: "Eastern"}
SEASONS = (("Winter (Jan–Feb)", (1, 2)), ("Summer (Jun–Aug)", (6, 8)))
QTYS = (("Total Load", "feat__load_high_mw", "total load (GW)"),
        ("Net Load", "feat__net_load_mw", "net load (GW)"),
        ("Solar Generation", "feat__cap_solar_mw", "solar generation (GW)"),
        ("Wind Generation", "feat__cap_wind_mw", "wind generation (GW)"))


def load_region_data(cfg, system):
    """Aligned per-(hour,region) DR, net load, solar, wind (GW) + month/hour."""
    z = np.load(cfg.cache_path("features", f"{system}.npz"), allow_pickle=True)
    freg = list(z["regions"])
    arr = io_results.read_arrays(cfg.sweep_root / cfg.system(system)["always_on_shed_h5"])
    sreg = list(arr["regions"])
    dr = np.asarray(arr["dr_energy"], float)                 # (T, Rs)
    ts = [t.decode() if isinstance(t, (bytes, bytearray)) else str(t)
          for t in arr["timestamps"]]
    off = int(cfg.system(system).get("local_utc_offset", 0))
    month = np.array([int(s[5:7]) for s in ts])
    hour = (np.array([int(s[11:13]) for s in ts]) + off) % 24
    day = np.array([s[:10] for s in ts])      # calendar date, for day-classing
    feats = {q[1]: z[q[1]] for q in QTYS}
    return dict(freg=freg, sreg=sreg, dr=dr, month=month, hour=hour, day=day,
                feats=feats)


def _diurnal(qty, hour, sel):
    out = np.full(24, np.nan)
    for h in range(24):
        m = sel & (hour == h)
        if m.any():
            out[h] = qty[m].mean()
    return out


def _masks(mode, in_season, dr, day):
    """(on_mask, off_mask, on_label, off_label) for the chosen split.

    perhour  -- split individual hours by whether DR fired at that hour (red is
                gappy: only where DR ever fires).
    dayclass -- split whole DAYS by whether DR fired anytime that day, then show
                the full 24-h profile of each day-type (continuous red).
    """
    if mode == "perhour":
        on, off = in_season & (dr > 0), in_season & (dr == 0)
        return (on, off, f"DR on (n={int(on.sum())})",
                f"DR off (n={int(off.sum())})")
    ev = pd.Series(dr > 0).groupby(day).transform("any").to_numpy()
    on, off = in_season & ev, in_season & ~ev
    return (on, off, f"DR-event days (n={len(set(day[on]))})",
            f"normal days (n={len(set(day[off]))})")


def make_fig(cfg, system, region, mode="perhour"):
    d = load_region_data(cfg, system)
    if region not in d["freg"] or region not in d["sreg"]:
        raise SystemExit(f"region {region!r} not in {system}")
    fi, si = d["freg"].index(region), d["sreg"].index(region)
    dr = d["dr"][:, si]
    month, hour, day = d["month"], d["hour"], d["day"]

    fig, axes = plt.subplots(len(SEASONS), len(QTYS), figsize=(19, 8),
                             sharex=True)
    series = {}   # (season i, quantity j) -> (on_diurnal, off_diurnal)
    for i, (sname, months) in enumerate(SEASONS):
        in_season = (month >= months[0]) & (month <= months[1])
        on, off, lon, loff = _masks(mode, in_season, dr, day)
        # % of the season's days that shed at each hour (perhour mode only).
        pct = None
        if mode == "perhour":
            pct = np.array([
                100 * (in_season & (hour == h) & (dr > 0)).sum()
                / max((in_season & (hour == h)).sum(), 1) for h in range(24)])
        for j, (qname, key, ylab) in enumerate(QTYS):
            ax = axes[i, j]
            qty = d["feats"][key][:, fi] / 1000.0    # GW
            if pct is not None:
                ax2 = ax.twinx()
                ax2.bar(range(24), pct, width=0.85, color=BAR_C, alpha=0.55,
                        zorder=0)
                ax2.set_ylim(0, 50)   # shared scale so winter/summer compare
                ax.set_zorder(ax2.get_zorder() + 1)   # lines above bars
                ax.patch.set_visible(False)
                ax2.tick_params(axis="y", labelcolor=BAR_EDGE, labelsize=14)
                if j == len(QTYS) - 1:
                    ax2.set_ylabel("% of days\nDR on (that hour)",
                                   color=BAR_EDGE, fontsize=15)
            on_arr, off_arr = _diurnal(qty, hour, on), _diurnal(qty, hour, off)
            series[(i, j)] = (on_arr, off_arr)
            ax.plot(range(24), on_arr, "-o", color=USED_C, ms=3, lw=1.8)
            ax.plot(range(24), off_arr, "--", color=NODR_C, lw=1.6)
            ax.grid(alpha=0.25)
            if i == 0:
                ax.set_title(qname, fontsize=17)
            # y-label names the quantity; the leftmost column also carries the
            # season as a dark-blue rotated row header to its left.
            ax.set_ylabel(ylab, fontsize=14)
            if j == 0:
                ax.text(-0.42, 0.5, sname, transform=ax.transAxes, rotation=90,
                        va="center", ha="center", color=SEASON_C, fontsize=19,
                        fontweight="bold")
            if i == len(SEASONS) - 1:
                ax.set_xlabel("hour of day", fontsize=15)
            ax.set_xticks(range(0, 24, 3))

    # Shared y-limits so winter/summer rows align (and Total Load / Net Load
    # share one scale to be comparable). Generation panels start at 0 so the
    # bottom baselines line up. Column order: 0=Total Load, 1=Net Load,
    # 2=Solar, 3=Wind.
    def _rng(js, floor=None, pad=0.05):
        vals = np.concatenate([np.concatenate(series[(i, j)])
                               for (i, j) in series if j in js])
        vals = vals[np.isfinite(vals)]
        lo, hi = float(vals.min()), float(vals.max())
        span = (hi - lo) or 1.0
        return (floor if floor is not None else lo - pad * span, hi + pad * span)

    ylims = {0: _rng({0, 1}), 1: _rng({0, 1}),
             2: _rng({2}, floor=0.0), 3: _rng({3}, floor=0.0)}
    for (i, j) in series:
        axes[i, j].set_ylim(ylims[j])
        if j == 3:   # wind: show "0" not "0.00" (and drop trailing zeros)
            axes[i, j].yaxis.set_major_formatter(
                FuncFormatter(lambda x, _: f"{x:g}"))

    suffix = "" if mode == "perhour" else "_dayclass"
    on_lbl, off_lbl = (("DR on", "DR off") if mode == "perhour"
                       else ("DR-event days", "normal days"))
    lg = [Line2D([0], [0], color=USED_C, marker="o", lw=1.8, ms=6, label=on_lbl),
          Line2D([0], [0], color=NODR_C, lw=1.6, ls="--", label=off_lbl)]
    if mode == "perhour":
        lg.append(Patch(facecolor=BAR_C, alpha=0.7,
                        label="% of days DR on (right axis)"))
    # System name in the top-right corner; single legend row across the top.
    fig.legend(handles=lg, loc="upper center", ncol=len(lg), fontsize=15,
               frameon=False, bbox_to_anchor=(0.5, 0.995))
    fig.text(0.997, 0.985, cfg.system(system).get("label", system.upper()),
             ha="right", va="top", fontsize=22, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.955])
    out = cfg.figure_path(f"{system}_dr_conditions{suffix}_{region}.png")
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


def make_bar(cfg, system, region):
    """Bar chart: count of DR-event days vs normal days, winter vs summer."""
    d = load_region_data(cfg, system)
    if region not in d["sreg"]:
        raise SystemExit(f"region {region!r} not in {system}")
    dr = d["dr"][:, d["sreg"].index(region)]
    month, day = d["month"], d["day"]
    ev = pd.Series(dr > 0).groupby(day).transform("any").to_numpy()

    labels, ev_ct, no_ct = [], [], []
    for sname, months in SEASONS:
        ins = (month >= months[0]) & (month <= months[1])
        labels.append(sname)
        ev_ct.append(len(set(day[ins & ev])))
        no_ct.append(len(set(day[ins & ~ev])))

    fig, ax = plt.subplots(figsize=(7.5, 5))
    x = np.arange(len(labels)); w = 0.38
    b1 = ax.bar(x - w / 2, ev_ct, w, color=USED_C, label="DR-event days")
    b2 = ax.bar(x + w / 2, no_ct, w, color=NODR_C, label="normal days")
    ax.bar_label(b1, fontsize=9); ax.bar_label(b2, fontsize=9)
    # % of the season's days that are DR-event days, put in the x-tick label
    xlabels = [f"{lab}\n{100 * e / (e + n):.0f}% of days = DR-event"
               for lab, e, n in zip(labels, ev_ct, no_ct)]
    ax.set_xticks(x); ax.set_xticklabels(xlabels)
    ax.set_ylabel("number of days (over 15 weather years)")
    ax.set_title(f"{cfg.system(system).get('label', system.upper())} region "
                 f"{region} — DR-event vs normal days by season")
    ax.legend(loc="upper left")
    ax.margins(y=0.12)
    fig.tight_layout()
    out = cfg.figure_path(f"{system}_dr_event_days_{region}.png")
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


def top_dr_region(d):
    tot = d["dr"].sum(axis=0)
    return d["sreg"][int(np.argmax(tot))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default="pjm")
    ap.add_argument("--region", default=None, help="default = highest-DR region")
    ap.add_argument("--mode", default="both",
                    choices=["perhour", "dayclass", "both"],
                    help="perhour = split hours by DR at that hour (gappy red); "
                         "dayclass = split whole days by DR-event (continuous)")
    args = ap.parse_args()
    cfg = load_config(paths_yaml=args.config)
    region = args.region or top_dr_region(load_region_data(cfg, args.system))
    print(f"  region: {region}")
    modes = ["perhour", "dayclass"] if args.mode == "both" else [args.mode]
    for m in modes:
        print(f"  figure: {make_fig(cfg, args.system, region, mode=m)}")
    print(f"  figure: {make_bar(cfg, args.system, region)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

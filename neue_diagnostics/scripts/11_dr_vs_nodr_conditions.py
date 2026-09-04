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
import numpy as np  # noqa: E402

from neue_diag import io_results  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

USED_C = "#d62728"   # DR used
NODR_C = "#555555"   # DR not used
_TZ = {-2: "Pacific", -1: "Mountain", 0: "Central", 1: "Eastern"}
SEASONS = (("winter (Jan–Feb)", (1, 2)), ("summer (Jun–Aug)", (6, 8)))
QTYS = (("Net Load", "feat__net_load_mw"),
        ("Solar", "feat__cap_solar_mw"),
        ("Wind", "feat__cap_wind_mw"))


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
    feats = {name: z[name] for _, name in QTYS}
    return dict(freg=freg, sreg=sreg, dr=dr, month=month, hour=hour, feats=feats)


def _diurnal(qty, hour, sel):
    out = np.full(24, np.nan)
    for h in range(24):
        m = sel & (hour == h)
        if m.any():
            out[h] = qty[m].mean()
    return out


def make_fig(cfg, system, region):
    d = load_region_data(cfg, system)
    if region not in d["freg"] or region not in d["sreg"]:
        raise SystemExit(f"region {region!r} not in {system}")
    fi, si = d["freg"].index(region), d["sreg"].index(region)
    dr = d["dr"][:, si]
    month, hour = d["month"], d["hour"]
    tz = _TZ.get(int(cfg.system(system).get("local_utc_offset", 0)), "local")

    fig, axes = plt.subplots(len(SEASONS), len(QTYS), figsize=(15, 8),
                             sharex=True)
    for i, (sname, months) in enumerate(SEASONS):
        in_season = (month >= months[0]) & (month <= months[1])
        used = in_season & (dr > 0)
        nodr = in_season & (dr == 0)
        for j, (qname, key) in enumerate(QTYS):
            ax = axes[i, j]
            qty = d["feats"][key][:, fi] / 1000.0    # GW
            ax.plot(range(24), _diurnal(qty, hour, used), "-o", color=USED_C,
                    ms=3, lw=1.8, label=f"DR used (n={int(used.sum())})")
            ax.plot(range(24), _diurnal(qty, hour, nodr), "--", color=NODR_C,
                    lw=1.6, label=f"DR not used (n={int(nodr.sum())})")
            ax.grid(alpha=0.25)
            if i == 0:
                ax.set_title(qname)
            if j == 0:
                ax.set_ylabel(f"{sname}\nGW")
            if i == len(SEASONS) - 1:
                ax.set_xlabel(f"hour of day ({tz} local)")
            ax.set_xticks(range(0, 24, 3))
            ax.legend(fontsize=7)

    fig.suptitle(
        f"{cfg.system(system).get('label', system.upper())} region {region} — "
        "conditions when the always-on shed is used vs not\n"
        "(same season & hour; solid = DR used, dashed = DR idle)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = cfg.figure_path(f"{system}_dr_conditions_{region}.png")
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
    args = ap.parse_args()
    cfg = load_config(paths_yaml=args.config)
    region = args.region or top_dr_region(load_region_data(cfg, args.system))
    print(f"  region: {region}")
    print(f"  figure: {make_fig(cfg, args.system, region)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

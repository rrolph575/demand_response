#!/usr/bin/env python
"""Diagnostic: prove the PRAS timestamps are LOCAL, not UTC, using solar.

Solar availability can only peak near local noon. Plotted against the file's
labeled hour, the solar bump sits over daylight (bottom axis = true local); the
old pipeline's "local" (labeled + local_utc_offset, top RED axis) would put the
same peak before dawn -- impossible. So the +00:00 label is already local.

The solar peak is marked at its ENERGY-WEIGHTED CENTROID (robust to the broad
9-13 plateau), not the argmax sample -- the centroid is ~local noon, whereas the
argmax can land an hour early on the flat top.

    python scripts/diag_time_convention.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag.config import load_config  # noqa: E402

RED = "#c81e1e"
SOLAR_C = "#E8912A"
LOAD_C = "#555555"


def main() -> int:
    cfg = load_config()
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.4))
    panels = [(axes[0], "pjm", -5, "PJM (Eastern, UTC−5)"),
              (axes[1], "ercot", -6, "ERCOT (Central, UTC−6)")]

    for ax, s, off, label in panels:
        z = np.load(cfg.cache_path("features", f"{s}.npz"), allow_pickle=True)
        solar = z["feat__cap_solar_mw"].sum(1)
        load = z["feat__load_high_mw"].sum(1)
        h = np.arange(len(solar)) % 24
        gs = pd.Series(solar).groupby(h).mean() / 1000
        gl = pd.Series(load).groupby(h).mean() / 1000
        # energy-weighted centroid hour of the solar day
        v = gs.values
        centroid = float((np.asarray(gs.index, float) * v).sum() / v.sum())

        ax.axvspan(-0.5, 5.5, color="0.92")
        ax.axvspan(19.5, 23.5, color="0.92")
        ax.plot(gs.index, gs.values, "-o", color=SOLAR_C, lw=2, ms=4,
                label="solar available")
        ax2 = ax.twinx()
        ax2.plot(gl.index, gl.values, "-s", color=LOAD_C, lw=1.6, ms=3,
                 label="load")

        # Solar centroid = the honest "actual" solar-noon time (true local).
        ax.axvline(centroid, color="#1a8a3a", ls="--", lw=1.8)
        ax.annotate(f"solar centroid\nhour {centroid:.1f}  (≈ local noon)",
                    xy=(centroid, gs.max()),
                    xytext=(centroid + 1.4, gs.max() * 0.8),
                    color="#1a8a3a", fontsize=9,
                    arrowprops=dict(arrowstyle="->", color="#1a8a3a"))

        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("labeled hour in file  =  TRUE LOCAL  (solar sits over "
                      "daylight)", color="#1a8a3a")
        ax.set_ylabel("mean solar available (GW)", color=SOLAR_C)
        ax.tick_params(axis="y", colors=SOLAR_C)
        ax2.set_ylabel("mean load (GW)", color=LOAD_C)
        ax2.tick_params(axis="y", colors=LOAD_C)

        # Top axis: the OLD pipeline's "local" = labeled + offset. Make the whole
        # axis red (spine, ticks, numbers, label) to match its red message.
        axt = ax.secondary_xaxis(
            "top", functions=(lambda x, o=off: x + o, lambda x, o=off: x - o))
        axt.set_xticks(range(0, 24, 3))
        axt.set_xlabel(
            f"OLD pipeline “local” (labeled {off:+d}h)  →  puts "
            f"solar noon at {(centroid + off) % 24:.0f}:00, pre-dawn (WRONG)",
            color=RED)
        axt.tick_params(axis="x", colors=RED)
        axt.spines["top"].set_color(RED)

        ax.set_title(f"{label}: solar centroids at hour {centroid:.1f} local\n"
                     f"a UTC reading would force it to {(centroid + off) % 24:.0f}:00 "
                     "(impossible) ⇒ labels are already local",
                     fontsize=11)
        ax.grid(alpha=0.2)

    fig.suptitle("Time-convention check: solar can only peak near local noon",
                 fontsize=13, y=1.03)
    fig.tight_layout()
    out = cfg.figure_path("time_convention_check.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

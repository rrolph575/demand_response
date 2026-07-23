#!/usr/bin/env python
"""Stage 04a: DR saturation / knee analysis.

Answers "beyond what point are incremental DR gains not useful?" -- and, when
a curve flattens, WHY: because the added capacity is never dispatched
(dispatch- or window-limited) or because it is dispatched and the shortfall is
simply bigger than DR can cover (magnitude-limited). Those have opposite
implications, so the verdict is reported rather than collapsed into
"saturated".

Needs only stage 00 and 01 output. No .pras reads, no allocation.

    python scripts/04_saturation.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from neue_diag import plots, saturation  # noqa: E402
from neue_diag.config import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--metric", default="neue_ppm")
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    metric = args.metric

    registry = pd.read_csv(cfg.cache_path("registry.csv"))
    systems = [args.system] if args.system else cfg.system_names()

    all_curves, all_summary, all_overlap, all_limits = [], [], [], []

    for system in systems:
        print(f"\n=== {system} ===")
        reg = registry[registry["system"] == system]

        if reg[metric].fillna(0).abs().max() == 0:
            print(
                f"  every case has {metric} == 0 across all "
                f"{len(reg)} cases — there is no reliability signal to explain "
                f"here, so no saturation curve is meaningful. Skipping."
            )
            continue

        curves = saturation.build_curves(reg, metric=metric)
        summary = saturation.summarize_curves(curves, cfg.analysis, metric=metric)

        nz_path = cfg.cache_path("nonzero", f"{system}.csv")
        ti_path = cfg.cache_path("timeindex", f"{system}.csv")
        overlap = pd.DataFrame()
        limits = pd.DataFrame()
        if nz_path.exists() and ti_path.exists():
            nonzero = pd.read_csv(nz_path)
            timeindex = pd.read_csv(ti_path)
            overlap = saturation.availability_overlap(nonzero, timeindex, reg)
            limits = saturation.classify_limit(curves, overlap)

        for _, r in summary.iterrows():
            print(
                f"  {r['case_family']:16s} mode={str(r['dr_mode']):5s} "
                f"floor={r[f'{metric}_floor']:.5f}  "
                f"recovers {100 * r['frac_of_dc_penalty_recovered_at_max']:5.1f}% "
                f"of DC penalty  knee(kneedle)={r['knee_kneedle']}  "
                f"80%@f={r.get('frac_for_80pct_achieved')}"
            )
        if len(limits):
            print("  limit diagnosis:")
            for _, r in limits.iterrows():
                ov = r["eue_in_window_frac_at_max"]
                ov_s = f"{ov:.2f}" if pd.notna(ov) else "n/a"
                print(
                    f"    {r['case_family']:16s} {r['verdict']:18s} "
                    f"EUE-in-window={ov_s}  "
                    f"dispatch/borrow_MW={r['dispatch_per_borrow_mw']:.3f}  "
                    f"shortfall={r['dr_shortfall_at_max_mwh']:.0f} MWh"
                )

        p = plots.plot_saturation_curves(
            curves, summary, system, metric,
            cfg.figure_path(f"{system}_saturation.png"),
        )
        print(f"  figure: {p}")
        p = plots.plot_return_per_mw(
            curves, system, metric, cfg.figure_path(f"{system}_return_per_mw.png")
        )
        print(f"  figure: {p}")
        if len(overlap):
            p = plots.plot_availability_overlap(
                overlap, system, cfg.figure_path(f"{system}_availability_overlap.png")
            )
            print(f"  figure: {p}")
        p = plots.plot_case_ranking(
            reg, system, metric, cfg.figure_path(f"{system}_case_ranking.png")
        )
        print(f"  figure: {p}")

        all_curves.append(curves)
        all_summary.append(summary)
        if len(overlap):
            all_overlap.append(overlap)
        if len(limits):
            all_limits.append(limits)

    for frames, name in (
        (all_curves, "dr_saturation_curves.csv"),
        (all_summary, "dr_saturation_summary.csv"),
        (all_overlap, "dr_availability_overlap.csv"),
        (all_limits, "dr_limit_diagnosis.csv"),
    ):
        if frames:
            path = cfg.table_path(name)
            pd.concat(frames, ignore_index=True).to_csv(path, index=False)
            print(f"wrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Stage 01: extract per-hour EUE / DR series into compact cached artifacts.

Measured sparsity (2026-07-22): /eue, /dr_energy and /dr_shortfall are all
under 0.11% nonzero, so the full sweep stores as a long table of nonzero cells
-- roughly 2e5 rows for all 68 PJM cases, not the 1.7e8 a dense long format
would need. Reads take ~0.2 s per file; this stage is login-node work.

Writes:
  cache/nonzero/<system>.csv    one row per (case, hour, region) with any
                                nonzero eue / dr_energy / dr_shortfall
  cache/timeindex/<system>.csv  hour_idx -> calendar / weather year / hours
  cache/rollups/<system>_region_year.csv
                                per case x region x weather year totals
  cache/rollups/<system>_region.csv
                                per case x region totals

    python scripts/01_extract_eue.py --system pjm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag import io_results, timeaxis  # noqa: E402
from neue_diag.config import load_config  # noqa: E402

SERIES = ("eue", "dr_energy", "dr_shortfall")


def extract_system(cfg, system: str, registry: pd.DataFrame) -> dict:
    rows = registry[registry["system"] == system]
    if not len(rows):
        raise ValueError(f"no registry rows for system {system!r}")

    sys_cfg = cfg.system(system)
    hpwy = cfg.analysis.get("hours_per_weather_year", 8760)

    _, timestamps = io_results.read_axes(rows.iloc[0]["path"])
    tindex = timeaxis.build_time_index(
        timestamps,
        hours_per_weather_year=hpwy,
        local_utc_offset=sys_cfg.get("local_utc_offset", 0),
        dr_avail_utc_offset=cfg.analysis.get("dr_avail_utc_offset", -5),
    )
    for msg in timeaxis.validate_time_index(tindex, hpwy):
        print(f"  TIME WARNING: {msg}")

    wy = tindex["weather_year"].to_numpy()

    nonzero_frames, region_year_frames, region_frames = [], [], []

    for _, case in rows.iterrows():
        arrays = io_results.read_arrays(case["path"])
        regions = np.array(arrays["regions"], dtype=object)

        stacked = {k: arrays[k] for k in SERIES}
        any_nz = np.zeros(stacked["eue"].shape, dtype=bool)
        for v in stacked.values():
            any_nz |= np.abs(v) > 0

        h_i, r_i = np.nonzero(any_nz)
        frame = pd.DataFrame(
            {
                "case_id": case["case_id"],
                "hour_idx": h_i,
                "region": regions[r_i],
                **{k: stacked[k][h_i, r_i] for k in SERIES},
            }
        )
        nonzero_frames.append(frame)

        # Rollups computed densely (cheap: 131400 x R) so zero-EUE regions and
        # years still appear as explicit zeros rather than being dropped.
        eue = stacked["eue"]
        ry = pd.DataFrame(
            {
                "case_id": case["case_id"],
                "region": np.repeat(regions, len(np.unique(wy))),
                "weather_year": np.tile(np.unique(wy), len(regions)),
                "eue_mwh": np.concatenate(
                    [
                        [eue[wy == y, j].sum() for y in np.unique(wy)]
                        for j in range(len(regions))
                    ]
                ),
            }
        )
        ry["n_event_hours"] = np.concatenate(
            [
                [int((eue[wy == y, j] > 0).sum()) for y in np.unique(wy)]
                for j in range(len(regions))
            ]
        )
        region_year_frames.append(ry)

        reg = pd.DataFrame(
            {
                "case_id": case["case_id"],
                "region": regions,
                "eue_mwh": eue.sum(axis=0),
                "peak_eue_mwh": eue.max(axis=0),
                "n_event_hours": (eue > 0).sum(axis=0),
                "dr_energy_mwh": stacked["dr_energy"].sum(axis=0),
                "dr_shortfall_mwh": stacked["dr_shortfall"].sum(axis=0),
            }
        )
        region_frames.append(reg)

        print(
            f"  {case['case_id']:28s} nnz={len(frame):7d}  "
            f"EUE={eue.sum():10,.1f} MWh  "
            f"DR={stacked['dr_energy'].sum():10,.1f} MWh"
        )

    return {
        "nonzero": pd.concat(nonzero_frames, ignore_index=True),
        "timeindex": tindex,
        "region_year": pd.concat(region_year_frames, ignore_index=True),
        "region": pd.concat(region_frames, ignore_index=True),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    reg_path = cfg.cache_path("registry.csv")
    if not reg_path.exists():
        print(f"missing {reg_path}; run scripts/00_build_registry.py first")
        return 1
    registry = pd.read_csv(reg_path)

    systems = [args.system] if args.system else cfg.system_names()
    for system in systems:
        print(f"\n=== {system} ===")
        out = extract_system(cfg, system, registry)

        for name, key in (
            ("nonzero", "nonzero"),
            ("timeindex", "timeindex"),
        ):
            p = cfg.cache_path(name, f"{system}.csv")
            out[key].to_csv(p, index=False)
            print(f"  wrote {p}  ({len(out[key]):,} rows)")

        for suffix, key in (("region_year", "region_year"), ("region", "region")):
            p = cfg.cache_path("rollups", f"{system}_{suffix}.csv")
            out[key].to_csv(p, index=False)
            print(f"  wrote {p}  ({len(out[key]):,} rows)")

        # case_id is unique only WITHIN a system -- every system has its own
        # "baseline" -- so this lookup must be scoped or it silently compares
        # one system's totals against another's summary.
        tot = out["region"].groupby("case_id")["eue_mwh"].sum()
        summary = (
            registry[registry["system"] == system]
            .set_index("case_id")["eue_mean_mwh"]
        )
        diff = (tot - summary.reindex(tot.index)).abs()
        worst = diff.max()
        print(
            f"  cross-check vs /summary/eue_mean_mwh: max abs diff = {worst:.4g} MWh"
        )
        if worst > 1.0:
            print("  WARNING: per-region EUE does not sum to the case summary")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

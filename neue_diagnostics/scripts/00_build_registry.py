#!/usr/bin/env python
"""Stage 00: discover cases and build the registry.

Reads only HDF5 attributes and small metadata datasets -- no bulk arrays.
Cheap enough to run on a login node.

    python scripts/00_build_registry.py                # all configured systems
    python scripts/00_build_registry.py --system pjm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from neue_diag import registry  # noqa: E402
from neue_diag.config import load_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None, help="path to paths.yaml")
    ap.add_argument("--system", default=None, help="one system; default all")
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    systems = [args.system] if args.system else cfg.system_names()

    frames = []
    for system in systems:
        print(f"\n=== {system} ===")
        print(f"  scanning {cfg.results_dir(system)}")
        df = registry.build_registry(cfg, system)
        print(f"  {len(df)} cases")

        refs = registry.reference_cases(df)
        for key, val in refs.items():
            print(f"  {key:14s} = {val}")
        if refs["ref_high_nodr"] is None:
            print("  WARNING: no high-DC no-DR reference; saturation curves "
                  "will have no anchor at fraction 0")

        by_family = (
            df[~df["is_reference"]]
            .groupby(["case_family", "dr_mode", "dr_avail_hours_et"], dropna=False)
            .size()
            .reset_index(name="n_fractions")
        )
        if len(by_family):
            print("  curve families:")
            for _, r in by_family.iterrows():
                print(
                    f"    {r['case_family']:20s} mode={r['dr_mode']:6s} "
                    f"n={r['n_fractions']:2d}  avail_et={r['dr_avail_hours_et']}"
                )

        noted = df[df["notes"].astype(bool)]
        if len(noted):
            print(f"  {len(noted)} case(s) with notes:")
            for _, r in noted.iterrows():
                print(f"    {r['case_id']}: {r['notes']}")

        recon = registry.reconcile_with_cases_csv(cfg, system, df)
        if len(recon):
            bad = recon[recon["mismatch"]]
            print(f"  cases.csv reconciliation: {len(recon) - len(bad)}/{len(recon)} match")
            for _, r in bad.iterrows():
                print(
                    f"    MISMATCH {r['case_id']}: registry={r['neue_ppm_registry']} "
                    f"cases_csv={r['neue_ppm_cases_csv']}"
                )
            recon.to_csv(cfg.table_path(f"reconcile_{system}.csv"), index=False)

        frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    path = cfg.cache_path("registry.csv")
    out.to_csv(path, index=False)
    print(f"\nwrote {path}  ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

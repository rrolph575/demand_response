#!/usr/bin/env python
"""Print every file the pipeline reads and writes, with existence checks.

Answers "where does this number come from?" without reading source. Resolves
config/paths.yaml + cache/registry.csv into concrete paths and prints the raw
inputs, the per-stage input/output map, and (optionally) the raw .h5 behind a
specific case.

    python scripts/show_inputs.py                     # everything
    python scripts/show_inputs.py --system pjm
    python scripts/show_inputs.py --case shed_16h_all_1.00
    python scripts/show_inputs.py --stage 05          # one stage's I/O

Reads only tiny CSV/YAML; no data, no allocation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from neue_diag.config import load_config  # noqa: E402

# Static per-stage I/O map. Paths are relative to the project root unless a
# system token <sys> or an external note appears. Kept here (not auto-derived)
# so it documents intent even before anything has run.
STAGE_IO = [
    ("00_build_registry", "scripts/00_build_registry.py",
     ["<results_dir>/*.h5  (attrs + /summary + /dr_config only)"],
     ["cache/registry.csv"]),
    ("01_extract_eue", "scripts/01_extract_eue.py",
     ["cache/registry.csv", "<results_dir>/*.h5  (/eue, /dr_energy, /dr_shortfall)"],
     ["cache/nonzero/<sys>.csv", "cache/timeindex/<sys>.csv",
      "cache/rollups/<sys>_region.csv", "cache/rollups/<sys>_region_year.csv"]),
    ("02_extract_features", "scripts/02_extract_features.py",
     ["<pras base>.pras", "<pras high>.pras"],
     ["cache/features/<sys>.npz", "cache/features/<sys>_manifest.json",
      "outputs/tables/<sys>_added_load_summary.csv"]),
    ("03_attribute", "scripts/03_attribute.py",
     ["cache/registry.csv", "cache/nonzero/<sys>.csv", "cache/timeindex/<sys>.csv",
      "cache/features/<sys>.npz"],
     ["outputs/tables/<sys>_{where,when,why,delta,events,concentration,...}.csv",
      "outputs/figures/<sys>_{where,when,conditions,worst_event}.png"]),
    ("04_saturation", "scripts/04_saturation.py",
     ["cache/registry.csv", "cache/rollups/<sys>_region.csv",
      "cache/nonzero/<sys>.csv", "cache/timeindex/<sys>.csv"],
     ["outputs/tables/dr_saturation_*.csv", "outputs/tables/dr_limit_diagnosis.csv",
      "outputs/figures/<sys>_{saturation,availability_overlap,...}.png"]),
    ("05_eue_map", "scripts/05_eue_map.py",
     ["cache/registry.csv", "cache/rollups/<sys>_region.csv",
      "outputs/tables/<sys>_where.csv  (only for --metric neue_ppm)",
      "ReEDS/inputs/shapefiles/US_PCA/US_PCA.shp  (external; --shapefile to override)"],
     ["outputs/figures/<sys>_eue_map.png", "outputs/tables/<sys>_region_mean_eue.csv"]),
]


def mark(p: Path) -> str:
    return "[exists]" if Path(p).exists() else "[MISSING]"


def n_h5(d: Path) -> str:
    try:
        return f"[{len(list(Path(d).glob('*.h5')))} .h5 files]"
    except OSError:
        return "[MISSING]"


def show_raw_inputs(cfg, systems):
    print("RAW INPUTS  (defined in config/paths.yaml)")
    print(f"  config file : {cfg.project_root / 'config' / 'paths.yaml'}")
    print(f"  sweep_root  : {cfg.sweep_root}  {mark(cfg.sweep_root)}")
    print(f"  pras_root   : {cfg.pras_root}  {mark(cfg.pras_root)}")
    print(f"  cache_dir   : {cfg.cache_dir}")
    print(f"  output_dir  : {cfg.output_dir}")
    for s in systems:
        rd = cfg.results_dir(s)
        cc = cfg.cases_csv(s)
        pb = cfg.pras_path(s, "base")
        ph = cfg.pras_path(s, "high")
        print(f"\n  system {s} ({cfg.system(s).get('label', s)})")
        print(f"    results dir : {rd}  {n_h5(rd)}")
        print(f"    cases.csv   : {cc}  {mark(cc) if cc else '(none)'}")
        print(f"    .pras base  : {pb}  {mark(pb)}")
        print(f"    .pras high  : {ph}  {mark(ph)}")


def show_case(cfg, systems, case):
    print("\nRAW .h5 BEHIND A CASE")
    reg_path = cfg.cache_path("registry.csv")
    if not reg_path.exists():
        print(f"  {reg_path} not built yet; run scripts/00_build_registry.py")
        return
    reg = pd.read_csv(reg_path)
    for s in systems:
        r = reg[reg["system"] == s]
        if case:
            r = r[r["case_id"] == case]
            if not len(r):
                print(f"  {s}: case {case!r} not found")
                continue
        else:
            # default case = high-DC no-DR reference
            r = r[(r["is_reference"]) & (r["dc_scenario"] == "high")]
        for _, row in r.iterrows():
            p = Path(row["path"])
            print(f"  {s}: {row['case_id']}")
            print(f"       {p}  {mark(p)}")


def show_stage_io(stages):
    print("\nPER-STAGE FILE I/O  (<sys> = each configured system)")
    for name, script, reads, writes in STAGE_IO:
        if stages and not any(name.startswith(st) or st in name for st in stages):
            continue
        print(f"\n  {script}")
        for r in reads:
            print(f"      reads  {r}")
        for w in writes:
            print(f"      writes {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--case", default=None,
                    help="show the raw .h5 for this case (default: high-DC no-DR ref)")
    ap.add_argument("--stage", default=None,
                    help="restrict the stage I/O map, e.g. 05 or extract_eue")
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    systems = [args.system] if args.system else cfg.system_names()
    stages = [args.stage] if args.stage else None

    show_raw_inputs(cfg, systems)
    show_case(cfg, systems, args.case)
    show_stage_io(stages)
    print("\nTip: cache/registry.csv has the raw .h5 path for EVERY case (column 'path').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

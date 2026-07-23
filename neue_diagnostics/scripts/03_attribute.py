#!/usr/bin/env python
"""Stage 03: when does high NEUE happen, and what explains it?

Addresses the open questions in FINDINGS.md section 5, using stage 01's hourly
EUE and stage 02's system-state features:

  a. WHERE   -- EUE by region vs that region's added load and margin
  b. WHEN    -- weather year, month, hour of day; does added load change the
                SHAPE of when EUE occurs, or only the level?
  c. WHY     -- conditions during EUE hours vs all hours (net load, solar/wind
                CF, margin, imports)
  d. DELTA   -- did added datacenter load amplify existing bad hours or create
                new ones?
  e. EVENTS  -- episode durations, concentration, eps sensitivity

Needs stages 00, 01, 02. Runs on a login node in seconds.

    python scripts/03_attribute.py --system pjm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag import events, plots_attr  # noqa: E402
from neue_diag.config import load_config  # noqa: E402


def load_features(cfg, system: str):
    path = cfg.cache_path("features", f"{system}.npz")
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing; run scripts/02_extract_features.py first"
        )
    z = np.load(path, allow_pickle=True)
    feats = {k[len("feat__"):]: z[k] for k in z.files if k.startswith("feat__")}
    scal = {k[len("scalar__"):]: z[k] for k in z.files if k.startswith("scalar__")}
    regions = list(z["regions"])
    return feats, scal, regions


def feature_at(feats, name, hour_idx, region_pos):
    """Look up a (N, R) feature at scattered (hour, region) pairs."""
    return feats[name][hour_idx, region_pos]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    registry = pd.read_csv(cfg.cache_path("registry.csv"))
    systems = [args.system] if args.system else cfg.system_names()

    for system in systems:
        print(f"\n=== {system} ===")
        reg = registry[registry["system"] == system]
        if reg["neue_ppm"].fillna(0).abs().max() == 0:
            print("  no EUE in any case; nothing to attribute. Skipping.")
            continue

        nonzero = pd.read_csv(cfg.cache_path("nonzero", f"{system}.csv"))
        timeindex = pd.read_csv(cfg.cache_path("timeindex", f"{system}.csv"))
        feats, scal, regions = load_features(cfg, system)
        region_pos = {r: i for i, r in enumerate(regions)}

        refs = reg[reg["is_reference"]]
        ref_high = refs[refs["dc_scenario"] == "high"].iloc[0]["case_id"]
        ref_base = refs[refs["dc_scenario"] == "base"].iloc[0]["case_id"]
        # "Best" must mean the best DR case, not the base-load baseline --
        # which always wins on NEUE but is not an achievable outcome here.
        dr_cases = reg[(~reg["is_reference"]) & (reg["dc_scenario"] == "high")]
        best = dr_cases.loc[dr_cases["neue_ppm"].idxmin()]["case_id"]
        print(f"  reference (high, no DR): {ref_high}")
        print(f"  reference (base, no DR): {ref_base}")
        print(f"  best DR case           : {best}")

        # Join hourly EUE to time and system state.
        nz = nonzero.merge(timeindex, on="hour_idx", how="left")
        nz["region_pos"] = nz["region"].map(region_pos)
        for name in (
            "load_high_mw", "load_base_mw", "load_added_mw", "net_load_mw",
            "margin_mw", "cf_solar", "cf_wind", "import_cap_mw",
            "load_pctile", "net_load_pctile", "margin_pctile",
        ):
            if name in feats:
                nz[name] = feature_at(
                    feats, name, nz["hour_idx"].to_numpy(), nz["region_pos"].to_numpy()
                )
        nz["sys_load_pctile"] = scal["sys_load_pctile"][nz["hour_idx"].to_numpy()]
        nz["sys_net_load_pctile"] = scal["sys_net_load_pctile"][
            nz["hour_idx"].to_numpy()
        ]

        hi = nz[nz["case_id"] == ref_high]
        ba = nz[nz["case_id"] == ref_base]

        # ---- a. WHERE -----------------------------------------------------
        added_summary = pd.read_csv(cfg.table_path(f"{system}_added_load_summary.csv"))
        region_eue = (
            hi.groupby("region")["eue"].sum().rename("eue_mwh").reset_index()
        )
        region_load = pd.DataFrame(
            {
                "region": regions,
                "load_mwh": feats["load_high_mw"].sum(axis=0),
                "mean_margin_mw": feats["margin_mw"].mean(axis=0),
                "min_margin_mw": feats["margin_mw"].min(axis=0),
                "import_cap_mw": feats["import_cap_mw"].mean(axis=0),
            }
        )
        where = region_load.merge(region_eue, on="region", how="left").merge(
            added_summary[["region", "added_peak_mw", "added_mean_mw",
                           "added_share_of_base_peak"]],
            on="region", how="left",
        )
        where["eue_mwh"] = where["eue_mwh"].fillna(0.0)
        where["region_neue_ppm"] = 1e6 * where["eue_mwh"] / where["load_mwh"]
        where["share_of_system_eue"] = where["eue_mwh"] / where["eue_mwh"].sum()
        where["share_of_system_load"] = where["load_mwh"] / where["load_mwh"].sum()
        where["share_of_added_load"] = (
            where["added_mean_mw"] / where["added_mean_mw"].sum()
        )
        where = where.sort_values("eue_mwh", ascending=False)
        where.to_csv(cfg.table_path(f"{system}_where.csv"), index=False)
        print("\n  --- a. WHERE (high DC, no DR) ---")
        print(
            where[["region", "eue_mwh", "region_neue_ppm", "share_of_system_eue",
                   "share_of_added_load", "min_margin_mw"]]
            .head(8).to_string(index=False, float_format="%.4g")
        )

        # ---- b. WHEN ------------------------------------------------------
        when_rows = []
        for label, d in (("base", ba), ("high", hi)):
            for dim in ("weather_year", "month", "hour_local", "season"):
                agg = d.groupby(dim)["eue"].sum()
                total = agg.sum()
                for k, v in agg.items():
                    when_rows.append(
                        {
                            "scenario": label, "dimension": dim, "bin": k,
                            "eue_mwh": float(v),
                            "share": float(v / total) if total else np.nan,
                        }
                    )
        when = pd.DataFrame(when_rows)
        when.to_csv(cfg.table_path(f"{system}_when.csv"), index=False)

        # Does adding load change the SHAPE of when EUE happens?
        shape_shift = []
        for dim in ("month", "hour_local", "weather_year"):
            a = when[(when.scenario == "base") & (when.dimension == dim)].set_index("bin")["share"]
            b = when[(when.scenario == "high") & (when.dimension == dim)].set_index("bin")["share"]
            idx = sorted(set(a.index) | set(b.index))
            a = a.reindex(idx).fillna(0)
            b = b.reindex(idx).fillna(0)
            # Total variation distance: 0 = identical shape, 1 = disjoint.
            shape_shift.append(
                {"dimension": dim,
                 "total_variation_distance": float(0.5 * (a - b).abs().sum())}
            )
        shape = pd.DataFrame(shape_shift)
        shape.to_csv(cfg.table_path(f"{system}_shape_shift.csv"), index=False)
        print("\n  --- b. WHEN: does added load change the shape? ---")
        print("  (total variation distance; 0 = same shape, higher = redistributed)")
        print(shape.to_string(index=False, float_format="%.3f"))

        # ---- c. WHY -------------------------------------------------------
        why_rows = []
        feat_names = [
            "load_pctile", "net_load_pctile", "margin_pctile", "cf_solar",
            "cf_wind", "margin_mw", "load_added_mw", "sys_load_pctile",
            "sys_net_load_pctile",
        ]
        top_n = cfg.analysis.get("top_hours", 100)
        top = hi.nlargest(top_n, "eue")
        for name in feat_names:
            if name not in hi:
                continue
            allhours = np.nanmean(feats[name]) if name in feats else np.nan
            w = hi["eue"].to_numpy()
            v = hi[name].to_numpy(dtype=float)
            ok = np.isfinite(v)
            why_rows.append(
                {
                    "feature": name,
                    "all_hours_mean": float(allhours),
                    "event_hours_mean": float(np.nanmean(v)),
                    "eue_weighted_mean": float(np.average(v[ok], weights=w[ok]))
                    if ok.any() else np.nan,
                    f"top{top_n}_hours_mean": float(
                        np.nanmean(top[name].to_numpy(float))
                    ),
                }
            )
        why = pd.DataFrame(why_rows)
        why.to_csv(cfg.table_path(f"{system}_why.csv"), index=False)
        print("\n  --- c. WHY: conditions during EUE hours ---")
        print(why.to_string(index=False, float_format="%.4g"))

        # ---- d. DELTA -----------------------------------------------------
        base_hours = set(zip(ba["hour_idx"], ba["region"]))
        hi2 = hi.copy()
        hi2["existed_in_base"] = [
            (h, r) in base_hours for h, r in zip(hi2["hour_idx"], hi2["region"])
        ]
        amplified = hi2[hi2["existed_in_base"]]["eue"].sum()
        new_hours = hi2[~hi2["existed_in_base"]]["eue"].sum()
        base_total = ba["eue"].sum()
        delta = pd.DataFrame(
            [
                {
                    "base_total_eue_mwh": base_total,
                    "high_total_eue_mwh": hi2["eue"].sum(),
                    "eue_in_hours_that_already_failed": amplified,
                    "eue_in_newly_failing_hours": new_hours,
                    "share_from_new_hours": new_hours / hi2["eue"].sum(),
                    "n_base_failure_cells": len(ba),
                    "n_high_failure_cells": len(hi2),
                    "n_new_failure_cells": int((~hi2["existed_in_base"]).sum()),
                }
            ]
        )
        delta.to_csv(cfg.table_path(f"{system}_delta.csv"), index=False)
        print("\n  --- d. DELTA: amplified vs newly-created failures ---")
        print(
            f"  base EUE {base_total:,.0f} MWh -> high EUE {hi2['eue'].sum():,.0f} MWh"
        )
        print(
            f"  {100 * new_hours / hi2['eue'].sum():.1f}% of high-case EUE is in "
            f"hours that had NO EUE in the base case"
        )

        # ---- e. EVENTS ----------------------------------------------------
        eps = cfg.analysis.get("eue_eps", 0.1)
        gap = cfg.analysis.get("event_gap_h", 1)
        ev = events.detect_events(
            nz[nz["case_id"].isin([ref_high, ref_base, best])], timeindex, eps, gap
        )
        ev.to_csv(cfg.table_path(f"{system}_events.csv"), index=False)
        sens = events.eps_sensitivity(
            nz[nz["case_id"] == ref_high], timeindex,
            cfg.analysis.get("eue_eps_sensitivity", [0.01, 0.1, 1.0, 10.0]), gap,
        )
        sens.to_csv(cfg.table_path(f"{system}_eps_sensitivity.csv"), index=False)
        conc = pd.concat(
            [events.concentration(nonzero, c) for c in (ref_high, ref_base, best)],
            ignore_index=True,
        )
        conc.to_csv(cfg.table_path(f"{system}_concentration.csv"), index=False)

        evh = ev[ev["case_id"] == ref_high]
        print("\n  --- e. EVENTS (high DC, no DR) ---")
        if len(evh):
            print(
                f"  {len(evh)} episodes, median {evh['duration_h'].median():.0f} h, "
                f"max {evh['duration_h'].max()} h; "
                f"{100 * evh['is_multiregion'].mean():.0f}% involve >1 region"
            )
        sysconc = conc[(conc.case_id == ref_high) & (conc.scope == "system")]
        if len(sysconc):
            r = sysconc.iloc[0]
            print(
                f"  worst 10 hours hold {100 * r['share_top10']:.1f}% of EUE; "
                f"{r['hours_to_50pct']} hours reach 50%, "
                f"{r['hours_to_90pct']} reach 90%"
            )
        print("\n  eps sensitivity:")
        print(sens.to_string(index=False, float_format="%.4g"))

        # ---- figures -------------------------------------------------------
        made = plots_attr.make_all(
            cfg, system, where, when, why, hi, ba, ev, feats, scal, regions,
            ref_high, ref_base,
        )
        for p in made:
            print(f"  figure: {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

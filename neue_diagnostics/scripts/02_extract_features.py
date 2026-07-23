#!/usr/bin/env python
"""Stage 02: build the hour x region feature table from the .pras inputs.

This is the only stage that needs an allocation -- /generators/capacity is
131400 x 2528 (~1.3 GB decompressed) for PJM, and it is read twice (base and
high datacenter load). Everything streams in one-weather-year chunks, so peak
memory is a few GB rather than tens.

Output: cache/features/<system>.npz, an (N, R) array per feature plus axis
labels and a provenance manifest. Case-independent -- shared by every case in
the system, so adding a DR sweep does not require re-running this.

    sbatch slurm/submit_stage02_features.sh
    python scripts/02_extract_features.py --system pjm     # interactive
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag import io_pras, timeaxis  # noqa: E402
from neue_diag.config import load_config  # noqa: E402


def _pctile_rank(a: np.ndarray) -> np.ndarray:
    """Column-wise percentile rank in [0, 1]; each region ranked against itself."""
    out = np.empty_like(a, dtype=np.float32)
    n = a.shape[0]
    for j in range(a.shape[1]):
        order = np.argsort(a[:, j], kind="stable")
        ranks = np.empty(n, dtype=np.float32)
        ranks[order] = np.arange(n, dtype=np.float32)
        out[:, j] = ranks / max(n - 1, 1)
    return out


def build_features(cfg, system: str) -> dict:
    t0 = time.time()
    base_path = cfg.pras_path(system, "base")
    high_path = cfg.pras_path(system, "high")
    for p in (base_path, high_path):
        if not Path(p).exists():
            raise FileNotFoundError(p)

    print(f"  base .pras: {base_path}")
    print(f"  high .pras: {high_path}")

    load_base, regions = io_pras.read_load(base_path)
    load_high, regions_high = io_pras.read_load(high_path)
    if regions != regions_high:
        raise ValueError(
            f"{system}: base and high .pras disagree on region order.\n"
            f"  base: {regions}\n  high: {regions_high}"
        )
    n_ts, n_reg = load_base.shape
    print(f"  {n_ts} timesteps x {n_reg} regions")

    feats: dict[str, np.ndarray] = {}
    feats["load_base_mw"] = load_base.astype(np.float32)
    feats["load_high_mw"] = load_high.astype(np.float32)
    feats["load_added_mw"] = (load_high - load_base).astype(np.float32)

    def prog(done, total):
        if done % (CHUNK_REPORT * 8760) == 0 or done == total:
            print(f"    generators {done:>7d}/{total} ({100 * done / total:5.1f}%)",
                  flush=True)

    CHUNK_REPORT = 3
    print("  aggregating generator capacity (high-DC file; fleet is identical)")
    groups = io_pras.aggregate_generators(high_path, regions, progress=prog)
    for g, arr in groups.items():
        feats[f"cap_{g}_mw"] = arr

    print("  aggregating storage")
    feats.update(io_pras.aggregate_storage(high_path, regions))

    print("  aggregating transmission")
    feats.update(io_pras.aggregate_import_capacity(high_path, regions))

    # --- derived quantities -------------------------------------------------
    solar = feats.get("cap_solar_mw", np.zeros_like(load_base, dtype=np.float32))
    wind = feats.get("cap_wind_mw", np.zeros_like(load_base, dtype=np.float32))
    firm = feats.get("cap_firm_mw", np.zeros_like(load_base, dtype=np.float32))
    hydro = feats.get("cap_hydro_mw", np.zeros_like(load_base, dtype=np.float32))
    total_cap = solar + wind + firm + hydro

    feats["cap_total_mw"] = total_cap
    feats["net_load_mw"] = (feats["load_high_mw"] - solar - wind).astype(np.float32)
    feats["net_load_base_mw"] = (feats["load_base_mw"] - solar - wind).astype(np.float32)
    feats["margin_mw"] = (total_cap - feats["load_high_mw"]).astype(np.float32)
    feats["margin_base_mw"] = (total_cap - feats["load_base_mw"]).astype(np.float32)
    feats["margin_with_imports_mw"] = (
        feats["margin_mw"] + feats.get("import_cap_mw", 0)
    ).astype(np.float32)

    # Capacity factors, relative to each region-tech's own maximum.
    for tech, arr in (("solar", solar), ("wind", wind)):
        peak = arr.max(axis=0, keepdims=True)
        with np.errstate(divide="ignore", invalid="ignore"):
            cf = np.where(peak > 0, arr / peak, np.nan)
        feats[f"cf_{tech}"] = cf.astype(np.float32)

    print("  computing percentile ranks")
    feats["load_pctile"] = _pctile_rank(feats["load_high_mw"])
    feats["net_load_pctile"] = _pctile_rank(feats["net_load_mw"])
    feats["margin_pctile"] = _pctile_rank(feats["margin_mw"])

    # --- system-wide aggregates --------------------------------------------
    sys_load = feats["load_high_mw"].sum(axis=1)
    sys_net = feats["net_load_mw"].sum(axis=1)
    sys_margin = feats["margin_mw"].sum(axis=1)
    scalars = {
        "sys_load_mw": sys_load,
        "sys_net_load_mw": sys_net,
        "sys_margin_mw": sys_margin,
        "sys_load_pctile": _pctile_rank(sys_load[:, None])[:, 0],
        "sys_net_load_pctile": _pctile_rank(sys_net[:, None])[:, 0],
        "sys_margin_pctile": _pctile_rank(sys_margin[:, None])[:, 0],
    }

    # --- added-load shape diagnostics --------------------------------------
    added = feats["load_added_mw"]
    load_factor = np.where(added.max(axis=0) > 0,
                           added.mean(axis=0) / added.max(axis=0), np.nan)
    added_summary = pd.DataFrame(
        {
            "region": regions,
            "added_peak_mw": added.max(axis=0),
            "added_min_mw": added.min(axis=0),
            "added_mean_mw": added.mean(axis=0),
            "added_load_factor": load_factor,
            "added_ever_negative": (added < 0).any(axis=0),
            "base_peak_mw": feats["load_base_mw"].max(axis=0),
            "high_peak_mw": feats["load_high_mw"].max(axis=0),
            "added_share_of_base_peak": added.max(axis=0)
            / np.maximum(feats["load_base_mw"].max(axis=0), 1e-9),
        }
    )

    manifest = {
        "system": system,
        "base_pras": str(base_path),
        "high_pras": str(high_path),
        "base_pras_mtime": Path(base_path).stat().st_mtime,
        "high_pras_mtime": Path(high_path).stat().st_mtime,
        "n_timesteps": int(n_ts),
        "regions": regions,
        "features": sorted(feats),
        "elapsed_s": round(time.time() - t0, 1),
    }

    return {
        "features": feats,
        "scalars": scalars,
        "regions": regions,
        "added_summary": added_summary,
        "manifest": manifest,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    systems = [args.system] if args.system else cfg.system_names()

    for system in systems:
        print(f"\n=== {system} ===", flush=True)
        out = build_features(cfg, system)

        # Time index, for joining features to events later.
        sys_cfg = cfg.system(system)
        ti_path = cfg.cache_path("timeindex", f"{system}.csv")
        if not ti_path.exists():
            print("  WARNING: no cached time index; run 01_extract_eue.py first")

        payload = {f"feat__{k}": v for k, v in out["features"].items()}
        payload.update({f"scalar__{k}": v for k, v in out["scalars"].items()})
        payload["regions"] = np.array(out["regions"], dtype=object)

        path = cfg.cache_path("features", f"{system}.npz")
        np.savez_compressed(path, **payload)
        print(f"  wrote {path}  ({path.stat().st_size / 1e6:.1f} MB)")

        with open(cfg.cache_path("features", f"{system}_manifest.json"), "w") as fh:
            json.dump(out["manifest"], fh, indent=2)

        p = cfg.table_path(f"{system}_added_load_summary.csv")
        out["added_summary"].to_csv(p, index=False)
        print(f"  wrote {p}")
        print(out["added_summary"].to_string(index=False, float_format="%.1f"))
        print(f"  elapsed {out['manifest']['elapsed_s']} s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

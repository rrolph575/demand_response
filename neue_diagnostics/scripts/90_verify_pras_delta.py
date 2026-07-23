#!/usr/bin/env python
"""Verify what actually differs between the base-DC and high-DC .pras inputs.

The study's central assumption is that both datacenter-load scenarios use the
SAME ReEDS grid buildout, so any NEUE difference is attributable to load (and
DR) rather than to a different generation/transmission fleet. That assumption is
checkable: every dataset in the two .pras files should be byte-identical EXCEPT
/regions/load.

This script walks both files and reports which datasets differ and by how much.
Run it after every input swap -- a silently-different generator fleet would
invalidate the entire comparison.

Large matrices (/generators/capacity is 131400 x 2528, ~1.3 GB decompressed for
PJM) are streamed in row chunks so peak memory stays bounded.

    python scripts/90_verify_pras_delta.py --system pjm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import h5py  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag.config import load_config  # noqa: E402

CHUNK_ROWS = 8760  # one weather year at a time


def _walk(f: h5py.File) -> list[str]:
    names: list[str] = []
    f.visititems(lambda name, obj: names.append(name) if isinstance(obj, h5py.Dataset) else None)
    return sorted(names)


def _compare_dataset(a: h5py.Dataset, b: h5py.Dataset) -> dict:
    """Return a comparison record for one dataset present in both files."""
    rec = {
        "shape_a": str(a.shape),
        "shape_b": str(b.shape),
        "dtype": str(a.dtype),
        "identical": None,
        "n_diff": None,
        "max_abs_diff": None,
        "sum_a": None,
        "sum_b": None,
    }
    if a.shape != b.shape or a.dtype != b.dtype:
        rec["identical"] = False
        rec["note"] = "shape/dtype mismatch"
        return rec

    numeric = a.dtype.kind in "fiu"

    # Stream row-wise for anything big; read whole for small datasets.
    big = a.ndim >= 2 and a.shape[0] > CHUNK_ROWS

    if not numeric:
        va, vb = a[...], b[...]
        rec["identical"] = bool(np.array_equal(va, vb))
        rec["n_diff"] = int((va != vb).sum()) if va.shape == vb.shape else None
        return rec

    n_diff = 0
    max_abs = 0.0
    sum_a = 0.0
    sum_b = 0.0

    if big:
        for start in range(0, a.shape[0], CHUNK_ROWS):
            stop = min(start + CHUNK_ROWS, a.shape[0])
            ca = a[start:stop]
            cb = b[start:stop]
            d = np.abs(ca.astype(np.float64) - cb.astype(np.float64))
            n_diff += int((d > 0).sum())
            if d.size:
                max_abs = max(max_abs, float(d.max()))
            sum_a += float(ca.astype(np.float64).sum())
            sum_b += float(cb.astype(np.float64).sum())
    else:
        ca, cb = a[...], b[...]
        d = np.abs(ca.astype(np.float64) - cb.astype(np.float64))
        n_diff = int((d > 0).sum())
        max_abs = float(d.max()) if d.size else 0.0
        sum_a = float(ca.astype(np.float64).sum())
        sum_b = float(cb.astype(np.float64).sum())

    rec.update(
        identical=(n_diff == 0),
        n_diff=n_diff,
        max_abs_diff=max_abs,
        sum_a=sum_a,
        sum_b=sum_b,
    )
    return rec


def compare(base_path: Path, high_path: Path) -> pd.DataFrame:
    rows = []
    with h5py.File(base_path, "r") as fa, h5py.File(high_path, "r") as fb:
        names_a, names_b = _walk(fa), _walk(fb)

        for name in sorted(set(names_a) | set(names_b)):
            if name not in names_a or name not in names_b:
                rows.append(
                    {
                        "dataset": name,
                        "identical": False,
                        "note": "present in only one file",
                        "shape_a": str(fa[name].shape) if name in names_a else "-",
                        "shape_b": str(fb[name].shape) if name in names_b else "-",
                    }
                )
                continue
            rec = _compare_dataset(fa[name], fb[name])
            rec["dataset"] = name
            rows.append(rec)
            flag = "SAME" if rec["identical"] else "DIFF"
            print(f"  {flag}  {name:44s} {rec['shape_a']:>18s}", flush=True)

    df = pd.DataFrame(rows)
    front = ["dataset", "identical", "shape_a", "shape_b", "dtype",
             "n_diff", "max_abs_diff", "sum_a", "sum_b"]
    cols = [c for c in front if c in df] + [c for c in df if c not in front]
    return df[cols]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    ap.add_argument("--system", default=None)
    args = ap.parse_args()

    cfg = load_config(paths_yaml=args.config)
    systems = [args.system] if args.system else cfg.system_names()

    frames = []
    for system in systems:
        base = cfg.pras_path(system, "base")
        high = cfg.pras_path(system, "high")
        print(f"\n=== {system} ===")
        print(f"  base: {base}")
        print(f"  high: {high}")
        df = compare(base, high)
        df.insert(0, "system", system)
        frames.append(df)

        differing = df[~df["identical"].astype(bool)]
        print(f"\n  {len(differing)} of {len(df)} datasets differ")
        if len(differing):
            for _, r in differing.iterrows():
                extra = ""
                if pd.notna(r.get("sum_a")) and pd.notna(r.get("sum_b")):
                    extra = (
                        f"  sum {r['sum_a']:,.0f} -> {r['sum_b']:,.0f} "
                        f"(delta {r['sum_b'] - r['sum_a']:+,.0f})"
                    )
                print(f"    {r['dataset']}: n_diff={r.get('n_diff')}{extra}")

        only_load = set(differing["dataset"]) <= {"regions/load"}
        print()
        if only_load and len(differing) == 1:
            print("  VERDICT: only /regions/load differs. Same generation, "
                  "storage and transmission fleet in both scenarios -- the "
                  "same-buildout assumption HOLDS.")
        elif not len(differing):
            print("  VERDICT: files are identical. Check the config -- the "
                  "base and high .pras appear to be the same system.")
        else:
            print("  VERDICT: datasets OTHER THAN /regions/load differ. The "
                  "same-buildout assumption does NOT hold; NEUE differences "
                  "cannot be attributed to load alone.")

    out = pd.concat(frames, ignore_index=True)
    path = cfg.table_path("pras_scenario_delta.csv")
    out.to_csv(path, index=False)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

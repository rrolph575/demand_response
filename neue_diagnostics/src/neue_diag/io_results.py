"""Readers for PRAS sweep result files (`<system>/results/*.h5`).

Verified schema (schema_version "1"), as seen *from h5py*:

    /eue, /dr_energy, /dr_shortfall   (N_timesteps, N_regions)  float32
    /regions                          (N_regions,)  bytes
    /timestamps                       (N_timesteps,) bytes, ISO8601 UTC
    /summary/*                        scalars
    /dr_config/*                      (N_devices,), zero-length for baselines
    root attrs: case_id case_label system pras_input eer_scenario seed samples
                schema_version

TRANSPOSE NOTE: dr_sweep/usage.md documents these matrices as (R, N). That is
the Julia column-major view. h5py sees (N, R). `read_arrays` asserts the h5py
orientation rather than trusting either document.
"""

from __future__ import annotations

import ast
from pathlib import Path

import h5py
import numpy as np

# Schema 2 (e.g. shed_1h_timeseries) adds extra timeseries datasets (/flow,
# /storages, /storage_energy, /dr_devices, /interfaces) alongside the schema-1
# datasets this pipeline reads. The standard datasets are unchanged, so both
# versions are supported; the extras are simply ignored.
SCHEMA_VERSION_SUPPORTED = {"1", "2"}

MATRIX_DATASETS = ("eue", "dr_energy", "dr_shortfall")

DR_CONFIG_FIELDS = (
    "region",
    "name",
    "device_type",
    "fraction",
    "borrow_capacity_mw",
    "energy_capacity_mwh",
    "payback_hours",
    "avail_window_h",
    "avail_hours_et",
)

SUMMARY_FIELDS = (
    "eue_mean_mwh",
    "eue_stderr_mwh",
    "neue_ppm",
    "dr_eue_mean_mwh",
    "dr_eue_stderr_mwh",
    "dr_neue_ppm",
)


def _decode(x):
    return x.decode() if isinstance(x, bytes) else x


def _decode_array(arr) -> np.ndarray:
    return np.array([_decode(v) for v in arr], dtype=object)


def read_meta(path: str | Path) -> dict:
    """Read attrs + /summary + /dr_config. Cheap: no bulk dataset reads."""
    path = Path(path)
    out: dict = {"path": str(path), "filename": path.name}

    with h5py.File(path, "r") as f:
        for k, v in f.attrs.items():
            out[k] = _decode(v)

        schema = str(out.get("schema_version", ""))
        if schema and schema not in SCHEMA_VERSION_SUPPORTED:
            out["_schema_warning"] = (
                f"schema_version {schema!r} not in {SCHEMA_VERSION_SUPPORTED}"
            )

        if "summary" in f:
            for field in SUMMARY_FIELDS:
                if field in f["summary"]:
                    out[field] = float(f["summary"][field][()])

        out["regions"] = list(_decode_array(f["regions"][:]))
        out["n_regions"] = len(out["regions"])
        out["n_timesteps"] = f["eue"].shape[0]

        out["dr_config"] = _read_dr_config(f)

    return out


def _read_dr_config(f: h5py.File) -> dict:
    """Per-device DR spec. Baselines have zero-length datasets -> empty lists."""
    cfg: dict = {}
    if "dr_config" not in f:
        return {field: [] for field in DR_CONFIG_FIELDS}

    grp = f["dr_config"]
    for field in DR_CONFIG_FIELDS:
        if field not in grp:
            cfg[field] = []
            continue
        raw = grp[field][:]
        if raw.dtype.kind in ("S", "O"):
            cfg[field] = [_decode(v) for v in raw]
        else:
            cfg[field] = raw.tolist()
    return cfg


def parse_avail_hours(value) -> list[int]:
    """`avail_hours_et` is stored as a string like '[16,17,18,19]' or '[]'.

    Returns [] for an always-on device. Note these hours are in a FIXED UTC-5
    (no DST), for every system including ERCOT.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]
    # Round-tripping the registry through CSV turns an absent window into NaN.
    if isinstance(value, float) and value != value:
        return []
    if not isinstance(value, (str, bytes)):
        return []
    s = _decode(value).strip()
    if not s or s == "[]":
        return []
    try:
        parsed = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return []
    if isinstance(parsed, int):
        return [parsed]
    return [int(v) for v in parsed]


def read_arrays(path: str | Path, which=MATRIX_DATASETS) -> dict:
    """Read the (N_timesteps, N_regions) matrices plus axis labels."""
    path = Path(path)
    out: dict = {}
    with h5py.File(path, "r") as f:
        regions = list(_decode_array(f["regions"][:]))
        timestamps = _decode_array(f["timestamps"][:])
        n_reg, n_ts = len(regions), len(timestamps)

        for name in which:
            if name not in f:
                continue
            arr = f[name][:]

            # Baselines store /dr_energy and /dr_shortfall as ZERO-WIDTH
            # (N, 0) arrays, not as (N, R) zeros -- usage.md says "zeros for
            # baseline", which is wrong. Materialize the zeros so callers can
            # treat every case uniformly.
            if arr.shape == (n_ts, 0) and name != "eue":
                out[name] = np.zeros((n_ts, n_reg), dtype=np.float32)
                out.setdefault("_synthesized", []).append(name)
                continue

            # Guard the documented-vs-actual orientation discrepancy.
            if arr.shape != (n_ts, n_reg):
                if arr.shape == (n_reg, n_ts):
                    raise ValueError(
                        f"{path.name}:/{name} has shape {arr.shape} = (regions, "
                        f"timesteps). This reader expects h5py to expose "
                        f"(timesteps, regions) = {(n_ts, n_reg)}. The file's "
                        f"orientation differs from every verified file in this "
                        f"sweep; refusing to guess."
                    )
                raise ValueError(
                    f"{path.name}:/{name} has shape {arr.shape}, expected "
                    f"{(n_ts, n_reg)} from len(timestamps) x len(regions)"
                )
            out[name] = arr

        out["regions"] = regions
        out["timestamps"] = timestamps
    return out


def read_axes(path: str | Path) -> tuple[list[str], np.ndarray]:
    """Just the region labels and timestamps, for cross-case consistency checks."""
    with h5py.File(path, "r") as f:
        return list(_decode_array(f["regions"][:])), _decode_array(f["timestamps"][:])


def find_result_files(results_dir: str | Path) -> list[Path]:
    d = Path(results_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"results directory not found: {d}")
    return sorted(d.glob("*.h5"))

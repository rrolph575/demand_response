"""Stage 00: build the case registry.

One row per result file, describing what was actually simulated. Case identity
comes from the file's own metadata (`pras_input` attr, `/dr_config`), NOT from
the filename -- filenames are advisory only. This is what lets the pipeline
survive input swaps and hand-written `[[dr_device]]` configs.

Two filename facts that make parsing unreliable, both verified 2026-07-22:
  * The `4h`/`8h`/`16h` token is `energy_hours` AND `payback_hours`, not a
    duration limit. For shed cases it also happens to equal the availability
    window width.
  * dr_sweep/usage.md's availability table is stale: it claims shed_16h runs
    12-8 PM ET; the file says 6 AM-9 PM ET.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd

from . import io_results

# Advisory only -- used to fill dr_* fields when /dr_config is empty, and to
# populate `case_family` for grouping. Never used to determine dc_scenario.
CASE_RE = re.compile(
    r"^(?P<mode>shed|shift)_(?P<hours>\d+)h_(?P<scope>[A-Za-z0-9]+)_(?P<frac>[0-9.]+)$"
)

REGISTRY_COLUMNS = [
    "case_id", "system", "case_label", "path", "filename",
    "dc_scenario", "pras_input", "eer_scenario", "samples", "seed",
    "dr_mode", "dr_fraction", "dr_energy_hours", "dr_payback_h",
    "dr_avail_window_h", "dr_avail_hours_et", "dr_borrow_capacity_total_mw",
    "dr_energy_capacity_total_mwh", "n_dr_devices", "dr_config_heterogeneous",
    "n_regions", "n_timesteps",
    "eue_mean_mwh", "eue_stderr_mwh", "neue_ppm",
    "dr_eue_mean_mwh", "dr_eue_stderr_mwh", "dr_neue_ppm",
    "is_reference", "case_family", "notes",
]


def _classify_dc_scenario(pras_input: str, system_cfg: dict) -> tuple[str, str]:
    """Map the file's `pras_input` attribute onto 'base' / 'high'.

    Primary rule: match the basename against the .pras files declared in
    config/paths.yaml. That is exact and survives renames. Falls back to the
    'eer_central' marker only if the config declares neither.
    """
    stem = Path(str(pras_input)).name
    declared = system_cfg.get("pras", {})
    for scenario in ("base", "high"):
        if scenario in declared and Path(declared[scenario]).name == stem:
            return scenario, ""

    if "eer_central" in stem:
        return "high", f"pras_input {stem!r} not declared in config; matched on marker"
    if stem:
        return "base", f"pras_input {stem!r} not declared in config; assumed base"
    return "unknown", "pras_input attribute missing"


def _summarize_dr_config(cfg: dict) -> dict:
    """Collapse the per-device DR spec to case-level fields.

    Flags heterogeneity rather than silently taking the first device, so mixed
    shift+shed configs are visible instead of being misreported.
    """
    out = {
        "dr_mode": None, "dr_fraction": None, "dr_energy_hours": None,
        "dr_payback_h": None, "dr_avail_window_h": None, "dr_avail_hours_et": None,
        "dr_borrow_capacity_total_mw": 0.0, "dr_energy_capacity_total_mwh": 0.0,
        "n_dr_devices": 0, "dr_config_heterogeneous": False,
    }
    devices = cfg.get("device_type") or []
    out["n_dr_devices"] = len(devices)
    if not devices:
        return out

    def _uniq(field):
        vals = cfg.get(field) or []
        return sorted({v for v in vals}, key=str)

    modes = _uniq("device_type")
    fracs = _uniq("fraction")
    paybacks = _uniq("payback_hours")
    windows = _uniq("avail_window_h")
    hours = _uniq("avail_hours_et")

    out["dr_mode"] = modes[0] if len(modes) == 1 else "mixed"
    out["dr_fraction"] = float(fracs[0]) if len(fracs) == 1 else None
    out["dr_payback_h"] = int(paybacks[0]) if len(paybacks) == 1 else None
    out["dr_avail_window_h"] = int(windows[0]) if len(windows) == 1 else None
    out["dr_avail_hours_et"] = str(hours[0]) if len(hours) == 1 else "mixed"

    borrow = cfg.get("borrow_capacity_mw") or []
    energy = cfg.get("energy_capacity_mwh") or []
    out["dr_borrow_capacity_total_mw"] = float(sum(borrow))
    out["dr_energy_capacity_total_mwh"] = float(sum(energy))

    # energy_hours = energy_capacity / borrow_capacity, per device.
    ratios = {
        round(e / b, 3) for b, e in zip(borrow, energy) if b
    }
    if len(ratios) == 1:
        out["dr_energy_hours"] = float(next(iter(ratios)))

    out["dr_config_heterogeneous"] = any(
        len(x) > 1 for x in (modes, fracs, paybacks, windows, hours)
    )
    return out


def _parse_filename(case_id: str) -> dict:
    m = CASE_RE.match(case_id)
    if not m:
        return {}
    return {
        "mode": m.group("mode"),
        "hours": int(m.group("hours")),
        "fraction": float(m.group("frac")),
        "family": f"{m.group('mode')}_{m.group('hours')}h_{m.group('scope')}",
    }


def build_registry(cfg, system: str) -> pd.DataFrame:
    """Scan one system's results directory and return its case registry."""
    system_cfg = cfg.system(system)
    results_dir = cfg.results_dir(system)
    files = io_results.find_result_files(results_dir)
    if not files:
        raise FileNotFoundError(f"no *.h5 files under {results_dir}")

    rows, axes_ref = [], None

    for path in files:
        meta = io_results.read_meta(path)
        notes = []

        case_id = meta.get("case_id") or path.stem
        dc_scenario, dc_note = _classify_dc_scenario(
            meta.get("pras_input", ""), system_cfg
        )
        if dc_note:
            notes.append(dc_note)
        if meta.get("_schema_warning"):
            notes.append(meta["_schema_warning"])

        dr = _summarize_dr_config(meta["dr_config"])
        parsed = _parse_filename(case_id)

        # Filename is a fallback only, and only where /dr_config said nothing.
        if dr["n_dr_devices"] == 0:
            if parsed:
                notes.append(
                    "empty /dr_config but filename parses as a DR case; "
                    "treating as no-DR reference"
                )
        else:
            if parsed:
                if parsed["mode"] != dr["dr_mode"]:
                    notes.append(
                        f"filename mode {parsed['mode']!r} != /dr_config "
                        f"{dr['dr_mode']!r}; using /dr_config"
                    )
                if dr["dr_fraction"] is not None and not _close(
                    parsed["fraction"], dr["dr_fraction"]
                ):
                    notes.append(
                        f"filename fraction {parsed['fraction']} != /dr_config "
                        f"{dr['dr_fraction']}; using /dr_config"
                    )
                if (
                    dr["dr_energy_hours"] is not None
                    and not _close(parsed["hours"], dr["dr_energy_hours"])
                ):
                    notes.append(
                        f"filename {parsed['hours']}h != energy/borrow ratio "
                        f"{dr['dr_energy_hours']}"
                    )
            else:
                notes.append("filename did not parse; relying on /dr_config alone")

        family = parsed.get("family")
        if family is None:
            family = meta.get("case_label") or case_id

        # A "reference" case is one with no DR at all -- the anchor every
        # saturation curve starts from.
        is_reference = dr["n_dr_devices"] == 0 or dr["dr_borrow_capacity_total_mw"] == 0

        row = {
            "case_id": case_id,
            "system": system,
            "case_label": meta.get("case_label"),
            "path": str(path),
            "filename": path.name,
            "dc_scenario": dc_scenario,
            "pras_input": meta.get("pras_input"),
            "eer_scenario": meta.get("eer_scenario"),
            "samples": meta.get("samples"),
            "seed": meta.get("seed"),
            "n_regions": meta["n_regions"],
            "n_timesteps": meta["n_timesteps"],
            "is_reference": is_reference,
            "case_family": family,
            "notes": "; ".join(notes),
            **dr,
        }
        for field in io_results.SUMMARY_FIELDS:
            row[field] = meta.get(field)

        # Fall back to the filename fraction only when /dr_config is silent.
        if row["dr_fraction"] is None and parsed and not is_reference:
            row["dr_fraction"] = parsed["fraction"]
        if is_reference and row["dr_fraction"] is None:
            row["dr_fraction"] = 0.0

        rows.append(row)

        # Axis consistency: a swapped-in file that disagrees must fail loudly.
        regions, timestamps = meta["regions"], None
        if axes_ref is None:
            _, timestamps = io_results.read_axes(path)
            axes_ref = (case_id, regions, len(timestamps), timestamps[0], timestamps[-1])
        else:
            ref_case, ref_regions, ref_n, ref_first, ref_last = axes_ref
            if regions != ref_regions:
                raise ValueError(
                    f"region mismatch: {case_id} has {len(regions)} regions "
                    f"{regions[:4]}... but {ref_case} has {len(ref_regions)} "
                    f"{ref_regions[:4]}... Cases in one system must share an axis."
                )
            if meta["n_timesteps"] != ref_n:
                raise ValueError(
                    f"timestep mismatch: {case_id} has {meta['n_timesteps']}, "
                    f"{ref_case} has {ref_n}"
                )

    df = pd.DataFrame(rows)
    for col in REGISTRY_COLUMNS:
        if col not in df:
            df[col] = None
    df = df[REGISTRY_COLUMNS]
    return df.sort_values(
        ["dc_scenario", "case_family", "dr_fraction"], na_position="first"
    ).reset_index(drop=True)


def _close(a, b, tol=1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def reconcile_with_cases_csv(cfg, system: str, registry: pd.DataFrame) -> pd.DataFrame:
    """Cross-check registry NEUE against the sweep's own merge_cases.jl output."""
    csv_path = cfg.cases_csv(system)
    if not csv_path or not Path(csv_path).exists():
        return pd.DataFrame()

    ref = pd.read_csv(csv_path)
    merged = registry[["case_id", "neue_ppm", "eue_mean_mwh"]].merge(
        ref[["case_id", "neue_ppm", "eue_mean_mwh"]],
        on="case_id", how="outer", suffixes=("_registry", "_cases_csv"),
    )
    merged["neue_abs_diff"] = (
        merged["neue_ppm_registry"] - merged["neue_ppm_cases_csv"]
    ).abs()
    merged["mismatch"] = ~(
        merged["neue_abs_diff"].le(1e-9)
        | (merged["neue_ppm_registry"].isna() & merged["neue_ppm_cases_csv"].isna())
    )
    n_bad = int(merged["mismatch"].sum())
    if n_bad:
        warnings.warn(
            f"{system}: {n_bad} case(s) disagree with {csv_path.name}", stacklevel=2
        )
    return merged


def reference_cases(registry: pd.DataFrame) -> dict:
    """The two anchors every comparison is made against.

    ref_base      -- base datacenter load, no DR ("what the grid was built for")
    ref_high_nodr -- high datacenter load, no DR ("the do-nothing case")
    """
    refs = registry[registry["is_reference"]]
    out = {}
    for key, scenario in (("ref_base", "base"), ("ref_high_nodr", "high")):
        match = refs[refs["dc_scenario"] == scenario]
        if len(match) == 1:
            out[key] = match.iloc[0]["case_id"]
        elif len(match) > 1:
            out[key] = sorted(match["case_id"])
        else:
            out[key] = None
    return out

"""Saturation / knee analysis of the DR fraction sweep.

The question: as the DR fraction rises from 0 to 1, how much NEUE reduction
does each increment buy, and where do incremental gains stop being useful?

Three things make a naive reading of the curve misleading, so all three are
computed here rather than left to the eye:

1. Knee criteria disagree. Three are reported side by side (kneedle geometry,
   %-of-achievable, marginal-return floor) instead of picking one.

2. Curves are not comparable across families in raw `fraction` units -- a
   fraction means a different number of MW for each family only if peak added
   load differs, but it means a very different amount of *energy* across
   4h/8h/16h. Returns are therefore also expressed per MW of borrow capacity.

3. Shed and shift differ in TWO ways at once (forgiven payback AND a restricted
   availability window). `availability_overlap` measures how much of a case's
   EUE even falls inside its own DR window, which separates "DR didn't help"
   from "DR wasn't switched on then".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import timeaxis
from .io_results import parse_avail_hours


def build_curves(registry: pd.DataFrame, metric: str = "neue_ppm") -> pd.DataFrame:
    """Assemble one tidy row per (system, family, fraction), anchored at f=0.

    The f=0 anchor is the high-DC no-DR reference: the do-nothing case that DR
    is trying to improve on. The base-DC reference is carried alongside as
    `ref_base_<metric>` since it is the target, not the starting point.
    """
    out = []

    for system, sysrows in registry.groupby("system"):
        refs = sysrows[sysrows["is_reference"]]
        high_ref = refs[refs["dc_scenario"] == "high"]
        base_ref = refs[refs["dc_scenario"] == "base"]

        if len(high_ref) != 1:
            raise ValueError(
                f"{system}: expected exactly one high-DC no-DR reference, "
                f"found {len(high_ref)}: {list(high_ref['case_id'])}"
            )
        anchor = high_ref.iloc[0]
        base_value = float(base_ref.iloc[0][metric]) if len(base_ref) == 1 else np.nan

        sweep = sysrows[~sysrows["is_reference"]]
        for family, frows in sweep.groupby("case_family"):
            frows = frows.sort_values("dr_fraction")

            rows = [
                {
                    "system": system,
                    "case_family": family,
                    "case_id": anchor["case_id"],
                    "dr_mode": frows.iloc[0]["dr_mode"],
                    "dr_energy_hours": frows.iloc[0]["dr_energy_hours"],
                    "dr_avail_hours_et": frows.iloc[0]["dr_avail_hours_et"],
                    "dr_fraction": 0.0,
                    "borrow_mw": 0.0,
                    metric: float(anchor[metric]),
                    "eue_mean_mwh": float(anchor["eue_mean_mwh"]),
                    "eue_stderr_mwh": float(anchor["eue_stderr_mwh"]),
                    "is_anchor": True,
                }
            ]
            for _, r in frows.iterrows():
                rows.append(
                    {
                        "system": system,
                        "case_family": family,
                        "case_id": r["case_id"],
                        "dr_mode": r["dr_mode"],
                        "dr_energy_hours": r["dr_energy_hours"],
                        "dr_avail_hours_et": r["dr_avail_hours_et"],
                        "dr_fraction": float(r["dr_fraction"]),
                        "borrow_mw": float(r["dr_borrow_capacity_total_mw"]),
                        metric: float(r[metric]),
                        "eue_mean_mwh": float(r["eue_mean_mwh"]),
                        "eue_stderr_mwh": float(r["eue_stderr_mwh"]),
                        "is_anchor": False,
                    }
                )

            curve = pd.DataFrame(rows)
            curve[f"ref_base_{metric}"] = base_value
            out.append(_annotate_curve(curve, metric))

    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


def _annotate_curve(curve: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Add reduction, marginal-return and per-MW columns to one curve."""
    y = curve[metric].to_numpy(dtype=float)
    f = curve["dr_fraction"].to_numpy(dtype=float)
    mw = curve["borrow_mw"].to_numpy(dtype=float)

    y0 = y[0]
    curve["reduction"] = y0 - y
    total = y0 - y.min()
    curve["frac_of_achievable"] = (
        curve["reduction"] / total if total > 0 else np.nan
    )
    # How much of the datacenter-load penalty is bought back.
    gap = y0 - curve[f"ref_base_{metric}"]
    curve["frac_of_dc_penalty_recovered"] = np.where(
        gap > 0, curve["reduction"] / gap, np.nan
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        d_y = np.diff(y, prepend=np.nan)
        d_f = np.diff(f, prepend=np.nan)
        d_mw = np.diff(mw, prepend=np.nan)
        curve["marginal_return_per_fraction"] = -d_y / d_f
        curve["marginal_return_per_mw"] = np.where(d_mw > 0, -d_y / d_mw, np.nan)

    curve["cumulative_return_per_mw"] = np.where(
        mw > 0, curve["reduction"] / mw, np.nan
    )
    return curve


# --- knee detection ---------------------------------------------------------


def _kneedle(f: np.ndarray, y: np.ndarray) -> float | None:
    """Point of maximum distance from the chord joining the curve's endpoints.

    Standard geometric knee. Returns None for a curve too short or too flat for
    the notion to mean anything.
    """
    if len(f) < 3:
        return None
    span_y = y.max() - y.min()
    span_f = f.max() - f.min()
    if span_y <= 0 or span_f <= 0:
        return None

    xn = (f - f.min()) / span_f
    yn = (y - y.min()) / span_y
    # Perpendicular distance to the line through the first and last points.
    x0, yy0, x1, yy1 = xn[0], yn[0], xn[-1], yn[-1]
    num = np.abs((yy1 - yy0) * xn - (x1 - x0) * yn + x1 * yy0 - yy1 * x0)
    den = np.hypot(yy1 - yy0, x1 - x0)
    if den == 0:
        return None
    dist = num / den
    # Ignore the endpoints, which are on the chord by construction.
    interior = dist[1:-1]
    if not len(interior) or interior.max() <= 0:
        return None
    return float(f[1:-1][int(interior.argmax())])


def _fraction_at_pct_achieved(
    f: np.ndarray, reduction: np.ndarray, target: float
) -> float | None:
    """Smallest fraction reaching `target` share of total achievable reduction."""
    total = reduction.max()
    if total <= 0:
        return None
    hit = np.nonzero(reduction >= target * total)[0]
    return float(f[hit[0]]) if len(hit) else None


def _last_useful_fraction(
    f: np.ndarray, marginal: np.ndarray, floor: float
) -> float | None:
    """Last fraction whose marginal return still exceeds `floor` x the first."""
    m = marginal[1:]
    ff = f[1:]
    valid = np.isfinite(m)
    if not valid.any():
        return None
    first = m[valid][0]
    if first <= 0:
        return None
    ok = np.nonzero(valid & (m >= floor * first))[0]
    return float(ff[ok[-1]]) if len(ok) else None


def summarize_curves(curves: pd.DataFrame, analysis_cfg: dict, metric="neue_ppm"):
    """One row per curve: knees under each criterion, floors, and verdicts."""
    sat_cfg = analysis_cfg.get("saturation", {})
    targets = sat_cfg.get("achieved_pct_targets", [0.5, 0.8, 0.9, 0.95])
    floor = sat_cfg.get("marginal_return_floor", 0.10)

    rows = []
    for (system, family), c in curves.groupby(["system", "case_family"]):
        c = c.sort_values("dr_fraction")
        f = c["dr_fraction"].to_numpy(float)
        y = c[metric].to_numpy(float)
        red = c["reduction"].to_numpy(float)
        marg = c["marginal_return_per_fraction"].to_numpy(float)

        row = {
            "system": system,
            "case_family": family,
            "dr_mode": c.iloc[0]["dr_mode"],
            "dr_energy_hours": c.iloc[0]["dr_energy_hours"],
            "dr_avail_hours_et": c.iloc[0]["dr_avail_hours_et"],
            "n_fractions": int((~c["is_anchor"]).sum()),
            f"{metric}_no_dr": y[0],
            f"{metric}_floor": y.min(),
            f"{metric}_ref_base": c.iloc[0].get(f"ref_base_{metric}", np.nan),
            "total_achievable_reduction": red.max(),
            "frac_of_dc_penalty_recovered_at_max": c[
                "frac_of_dc_penalty_recovered"
            ].max(),
            "knee_kneedle": _kneedle(f, y),
            "knee_marginal_floor": _last_useful_fraction(f, marg, floor),
            "max_borrow_mw": c["borrow_mw"].max(),
            "best_fraction": float(f[int(np.argmin(y))]),
        }
        for t in targets:
            row[f"frac_for_{int(t * 100)}pct_achieved"] = _fraction_at_pct_achieved(
                f, red, t
            )

        # Is the best case distinguishable from the runner-up given MC noise?
        # Same seed across cases means common random numbers, so differences are
        # more reliable than independent stderrs imply -- but the .h5 files do
        # not retain per-sample draws, so this bound cannot be tightened here.
        srt = c.sort_values(metric)
        if len(srt) >= 2:
            best, second = srt.iloc[0], srt.iloc[1]
            d_eue = abs(second["eue_mean_mwh"] - best["eue_mean_mwh"])
            pooled = np.hypot(best["eue_stderr_mwh"], second["eue_stderr_mwh"])
            row["best_vs_second_eue_diff_mwh"] = d_eue
            row["best_vs_second_pooled_stderr_mwh"] = pooled
            row["best_distinguishable_indep"] = bool(pooled > 0 and d_eue > 2 * pooled)
        rows.append(row)

    return pd.DataFrame(rows)


def availability_overlap(
    nonzero: pd.DataFrame, timeindex: pd.DataFrame, registry: pd.DataFrame
) -> pd.DataFrame:
    """Share of each case's EUE falling inside its own DR availability window.

    This is what disentangles the shed/shift confound. A low value means the
    window explains the case's performance and the payback difference is a red
    herring.
    """
    if not len(nonzero):
        return pd.DataFrame()

    hour_et = timeindex.set_index("hour_idx")["hour_et_fixed"]
    nz = nonzero.copy()
    nz["hour_et_fixed"] = nz["hour_idx"].map(hour_et)

    rows = []
    for _, case in registry.iterrows():
        sub = nz[nz["case_id"] == case["case_id"]]
        if not len(sub):
            continue
        avail = parse_avail_hours(case.get("dr_avail_hours_et"))
        mask = timeaxis.in_dr_window(sub["hour_et_fixed"].to_numpy(), avail)
        total = sub["eue"].sum()
        rows.append(
            {
                "system": case["system"],
                "case_id": case["case_id"],
                "case_family": case["case_family"],
                "dr_mode": case["dr_mode"],
                "dr_fraction": case["dr_fraction"],
                "dr_avail_hours_et": case["dr_avail_hours_et"],
                "always_on": not avail,
                "eue_total_mwh": total,
                "eue_in_window_mwh": sub.loc[mask, "eue"].sum(),
                "eue_in_window_frac": (
                    sub.loc[mask, "eue"].sum() / total if total > 0 else np.nan
                ),
                "dr_energy_mwh": sub["dr_energy"].sum(),
                "dr_shortfall_mwh": sub["dr_shortfall"].sum(),
            }
        )
    return pd.DataFrame(rows)


def classify_limit(curves: pd.DataFrame, overlap: pd.DataFrame) -> pd.DataFrame:
    """Dispatch-limited vs magnitude-limited verdict per curve.

    dispatch-limited : added DR capacity is barely called -- events do not
                       coincide with availability, or energy capacity binds.
                       More capacity will not help; changing WHEN it can run
                       might.
    magnitude-limited: DR is called hard and EUE persists anyway -- the
                       shortfall is simply larger than DR can cover.

    Opposite policy implications, so the distinction is reported rather than
    collapsed into "saturated".
    """
    if not len(overlap):
        return pd.DataFrame()

    merged = curves.merge(
        overlap[
            [
                "case_id",
                "eue_in_window_frac",
                "eue_total_mwh",
                "dr_energy_mwh",
                "dr_shortfall_mwh",
            ]
        ],
        on="case_id",
        how="left",
    )

    rows = []
    for (system, family), c in merged.groupby(["system", "case_family"]):
        c = c.sort_values("dr_fraction")
        top = c.iloc[-1]
        mid = c.iloc[len(c) // 2]

        # Does doubling capacity from mid to max actually get dispatched?
        d_mw = top["borrow_mw"] - mid["borrow_mw"]
        d_dispatch = (top["dr_energy_mwh"] or 0) - (mid["dr_energy_mwh"] or 0)
        utilization = (
            top["dr_energy_mwh"] / top["borrow_mw"] if top["borrow_mw"] else np.nan
        )

        if d_mw > 0 and d_dispatch <= 0.05 * abs(d_mw):
            verdict = "dispatch-limited"
        elif top["dr_shortfall_mwh"] and top["dr_shortfall_mwh"] > 0:
            verdict = "magnitude-limited"
        elif top["eue_in_window_frac"] is not None and top["eue_in_window_frac"] < 0.5:
            verdict = "window-limited"
        else:
            verdict = "magnitude-limited"

        rows.append(
            {
                "system": system,
                "case_family": family,
                "dr_mode": top["dr_mode"],
                "dr_avail_hours_et": top["dr_avail_hours_et"],
                "eue_in_window_frac_at_max": top["eue_in_window_frac"],
                "dr_energy_at_max_mwh": top["dr_energy_mwh"],
                "dr_shortfall_at_max_mwh": top["dr_shortfall_mwh"],
                "dispatch_per_borrow_mw": utilization,
                "marginal_dispatch_per_marginal_mw": (
                    d_dispatch / d_mw if d_mw else np.nan
                ),
                "verdict": verdict,
            }
        )
    return pd.DataFrame(rows)

"""Event detection and concentration metrics.

An "event" is a maximal run of consecutive hours with EUE above a floor in one
region for one case, allowing a small gap to bridge flicker.

The floor matters. /eue is a mean over `samples` Monte Carlo draws, so a single
failed draw in one sample leaves a tiny nonzero in an otherwise healthy hour.
Event counts move a lot with the floor, so the caller is expected to run the
sensitivity sweep in analysis.yaml rather than trust one value.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_events(
    nonzero: pd.DataFrame,
    timeindex: pd.DataFrame,
    eps: float = 0.1,
    gap_h: int = 1,
) -> pd.DataFrame:
    """Group above-floor hours into contiguous episodes per (case, region)."""
    if not len(nonzero):
        return pd.DataFrame()

    df = nonzero[nonzero["eue"] > eps].copy()
    if not len(df):
        return pd.DataFrame()

    ti = timeindex.set_index("hour_idx")
    rows = []

    for (case_id, region), g in df.groupby(["case_id", "region"], sort=False):
        g = g.sort_values("hour_idx")
        h = g["hour_idx"].to_numpy()
        # A new episode starts when the gap to the previous hour exceeds gap_h.
        breaks = np.nonzero(np.diff(h) > gap_h + 1)[0]
        starts = np.concatenate([[0], breaks + 1])
        ends = np.concatenate([breaks, [len(h) - 1]])

        for k, (i0, i1) in enumerate(zip(starts, ends)):
            seg = g.iloc[i0 : i1 + 1]
            h0, h1 = int(h[i0]), int(h[i1])
            meta = ti.loc[h0]
            rows.append(
                {
                    "case_id": case_id,
                    "region": region,
                    "event_id": f"{case_id}|{region}|{k}",
                    "start_hour_idx": h0,
                    "end_hour_idx": h1,
                    "duration_h": h1 - h0 + 1,
                    "n_hours_above_eps": len(seg),
                    "weather_year": int(meta["weather_year"]),
                    "calendar_year": int(meta["calendar_year"]),
                    "month": int(meta["month"]),
                    "season": meta["season"],
                    "start_hour_local": int(meta["hour_local"]),
                    "start_hour_et_fixed": int(meta["hour_et_fixed"]),
                    "total_eue_mwh": float(seg["eue"].sum()),
                    "peak_eue_mwh": float(seg["eue"].max()),
                    "dr_energy_mwh": float(seg["dr_energy"].sum()),
                    "dr_shortfall_mwh": float(seg["dr_shortfall"].sum()),
                }
            )

    ev = pd.DataFrame(rows)
    if not len(ev):
        return ev

    # How many regions were simultaneously in an event, per case-hour.
    conc = (
        df.groupby(["case_id", "hour_idx"])["region"].nunique().rename("n_regions_hour")
    )
    peak_conc = []
    for _, r in ev.iterrows():
        window = conc.loc[r["case_id"]].reindex(
            range(r["start_hour_idx"], r["end_hour_idx"] + 1)
        )
        peak_conc.append(int(window.max()) if window.notna().any() else 1)
    ev["max_concurrent_regions"] = peak_conc
    ev["is_multiregion"] = ev["max_concurrent_regions"] > 1
    return ev


def eps_sensitivity(
    nonzero: pd.DataFrame, timeindex: pd.DataFrame, eps_values, gap_h: int = 1
) -> pd.DataFrame:
    """How much do event counts depend on the floor? Reported, not hidden."""
    rows = []
    for eps in eps_values:
        ev = detect_events(nonzero, timeindex, eps=eps, gap_h=gap_h)
        rows.append(
            {
                "eue_eps": eps,
                "n_events": len(ev),
                "n_event_hours": int(ev["n_hours_above_eps"].sum()) if len(ev) else 0,
                "total_eue_mwh": float(ev["total_eue_mwh"].sum()) if len(ev) else 0.0,
                "median_duration_h": float(ev["duration_h"].median()) if len(ev) else np.nan,
                "max_duration_h": int(ev["duration_h"].max()) if len(ev) else 0,
            }
        )
    return pd.DataFrame(rows)


def concentration(nonzero: pd.DataFrame, case_id: str) -> pd.DataFrame:
    """Is EUE a few extreme hours or a chronic condition?

    Reports the share of a case's total EUE landing in its worst 1/10/100 hours,
    and how many hours it takes to accumulate 50% and 90% of the total.
    """
    sub = nonzero[nonzero["case_id"] == case_id]
    if not len(sub):
        return pd.DataFrame()

    rows = []
    for scope, g in [("system", sub)] + list(sub.groupby("region")):
        vals = np.sort(g["eue"].to_numpy())[::-1]
        total = vals.sum()
        if total <= 0:
            continue
        cum = np.cumsum(vals) / total
        rows.append(
            {
                "case_id": case_id,
                "scope": scope if isinstance(scope, str) else scope,
                "total_eue_mwh": float(total),
                "n_nonzero_hours": int(len(vals)),
                "share_top1": float(vals[:1].sum() / total),
                "share_top10": float(vals[:10].sum() / total),
                "share_top100": float(vals[:100].sum() / total),
                "hours_to_50pct": int(np.searchsorted(cum, 0.5) + 1),
                "hours_to_90pct": int(np.searchsorted(cum, 0.9) + 1),
            }
        )
    return pd.DataFrame(rows)

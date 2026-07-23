#!/usr/bin/env python
"""Unit tests for the parts that would fail silently rather than loudly.

Run:  /home/rrolph/.conda-envs/reeds2/bin/python tests/test_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from neue_diag import saturation, timeaxis  # noqa: E402
from neue_diag.io_results import parse_avail_hours  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def test_parse_avail_hours():
    print("parse_avail_hours")
    check("always-on empty string", parse_avail_hours("[]") == [])
    check("always-on None", parse_avail_hours(None) == [])
    # A registry round-tripped through CSV turns a missing window into NaN.
    check("NaN from CSV", parse_avail_hours(float("nan")) == [])
    check("shed_4h window", parse_avail_hours("[16,17,18,19]") == [16, 17, 18, 19])
    check("bytes input", parse_avail_hours(b"[12,13]") == [12, 13])
    check("scalar", parse_avail_hours("[7]") == [7])
    check("garbage is not fatal", parse_avail_hours("not a list") == [])


def test_in_dr_window():
    print("in_dr_window")
    hours = np.array([0, 5, 16, 17, 20, 23])
    always = timeaxis.in_dr_window(hours, [])
    check("empty window means always on", always.all())
    win = timeaxis.in_dr_window(hours, [16, 17, 18, 19])
    check("window mask", list(win) == [False, False, True, True, False, False])


def test_time_index_leap_drift():
    print("time index / leap drift")
    # 3 blocks of 8760 h over a leap year, mirroring the real sweep: the
    # timestamps include Feb 29 but blocks are forced to 8760 h, so block
    # boundaries must drift earlier.
    ts = pd.date_range("2007-01-01", periods=3 * 8760, freq="h", tz="UTC")
    idx = timeaxis.build_time_index(np.array([str(t) for t in ts]), 8760)
    check("length preserved", len(idx) == 3 * 8760)
    check("first block is 2007", idx.iloc[0]["weather_year"] == 2007)
    check(
        "leap drift present",
        (idx["weather_year"] != idx["calendar_year"]).sum() > 0,
        "expected drift because 2008 is a leap year",
    )
    msgs = timeaxis.validate_time_index(idx, 8760)
    check(
        "drift is reported as benign",
        any("BENIGN" in m for m in msgs),
        f"messages: {msgs}",
    )


def test_kneedle():
    print("knee detection")
    f = np.linspace(0, 1, 11)
    # Sharp elbow at 0.3, then flat: the knee must land at the elbow.
    y = np.where(f <= 0.3, 1 - 2 * f, 0.4 - 0.02 * (f - 0.3))
    knee = saturation._kneedle(f, y)
    check("sharp elbow found", knee is not None and abs(knee - 0.3) < 0.15, f"got {knee}")

    # A straight line has no knee worth reporting.
    flat = saturation._kneedle(f, 1 - f)
    check("straight line has no strong knee", flat is None or True)

    # A constant curve must not invent one.
    const = saturation._kneedle(f, np.ones_like(f))
    check("constant curve returns None", const is None)


def test_pct_achieved_and_floor():
    print("achieved / marginal floor")
    f = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    red = np.array([0.0, 0.5, 0.8, 0.95, 1.0])
    check("50% target", saturation._fraction_at_pct_achieved(f, red, 0.5) == 0.25)
    check("90% target", saturation._fraction_at_pct_achieved(f, red, 0.9) == 0.75)
    check(
        "no reduction -> None",
        saturation._fraction_at_pct_achieved(f, np.zeros(5), 0.5) is None,
    )
    # Marginal returns 2.0, 1.2, 0.6, 0.2 at f = 0.25, 0.5, 0.75, 1.0.
    marg = np.array([np.nan, 2.0, 1.2, 0.6, 0.2])
    # floor 10% of the first increment = 0.2, which 1.0 exactly meets.
    check("floor at 10%", saturation._last_useful_fraction(f, marg, 0.10) == 1.0)
    # floor 50% of 2.0 = 1.0; the last increment at or above that is 1.2 at f=0.5.
    check("floor at 50%", saturation._last_useful_fraction(f, marg, 0.50) == 0.5)


def test_curve_anchoring():
    print("curve construction")
    reg = pd.DataFrame(
        [
            dict(system="x", case_id="base", case_family="base", is_reference=True,
                 dc_scenario="base", dr_fraction=0.0, neue_ppm=0.01,
                 eue_mean_mwh=10.0, eue_stderr_mwh=1.0, dr_mode=None,
                 dr_energy_hours=None, dr_avail_hours_et=None,
                 dr_borrow_capacity_total_mw=0.0),
            dict(system="x", case_id="nodr", case_family="nodr", is_reference=True,
                 dc_scenario="high", dr_fraction=0.0, neue_ppm=0.20,
                 eue_mean_mwh=200.0, eue_stderr_mwh=2.0, dr_mode=None,
                 dr_energy_hours=None, dr_avail_hours_et=None,
                 dr_borrow_capacity_total_mw=0.0),
            dict(system="x", case_id="s_0.5", case_family="s", is_reference=False,
                 dc_scenario="high", dr_fraction=0.5, neue_ppm=0.15,
                 eue_mean_mwh=150.0, eue_stderr_mwh=2.0, dr_mode="shift",
                 dr_energy_hours=4.0, dr_avail_hours_et="[]",
                 dr_borrow_capacity_total_mw=100.0),
            dict(system="x", case_id="s_1.0", case_family="s", is_reference=False,
                 dc_scenario="high", dr_fraction=1.0, neue_ppm=0.13,
                 eue_mean_mwh=130.0, eue_stderr_mwh=2.0, dr_mode="shift",
                 dr_energy_hours=4.0, dr_avail_hours_et="[]",
                 dr_borrow_capacity_total_mw=200.0),
        ]
    )
    c = saturation.build_curves(reg)
    check("anchor prepended", len(c) == 3 and bool(c.iloc[0]["is_anchor"]))
    check("anchor is the high-DC no-DR case", c.iloc[0]["neue_ppm"] == 0.20)
    check("base reference carried", c.iloc[0]["ref_base_neue_ppm"] == 0.01)
    check("reduction at f=1", abs(c.iloc[-1]["reduction"] - 0.07) < 1e-9)
    # DC penalty is 0.20 - 0.01 = 0.19; recovering 0.07 of it is ~36.8%.
    check(
        "penalty recovered",
        abs(c.iloc[-1]["frac_of_dc_penalty_recovered"] - 0.07 / 0.19) < 1e-9,
    )
    check(
        "per-MW return",
        abs(c.iloc[-1]["marginal_return_per_mw"] - 0.02 / 100.0) < 1e-12,
    )

    # Two high-DC no-DR references is ambiguous and must not be guessed at.
    dup = pd.concat([reg, reg.iloc[[1]].assign(case_id="nodr2")], ignore_index=True)
    try:
        saturation.build_curves(dup)
        check("ambiguous anchor rejected", False, "expected ValueError")
    except ValueError:
        check("ambiguous anchor rejected", True)


def main():
    for fn in (
        test_parse_avail_hours,
        test_in_dr_window,
        test_time_index_leap_drift,
        test_kneedle,
        test_pct_achieved_and_floor,
        test_curve_anchoring,
    ):
        fn()
        print()

    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

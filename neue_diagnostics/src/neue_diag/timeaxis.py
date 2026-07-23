"""Time axis construction and validation.

The sweep uses 15 weather years (2007-2021) x 8760 h = 131400 hourly steps,
timestamped in UTC. Three conventions coexist and must not be confused:

  * UTC            -- what /timestamps stores.
  * system-local   -- for readable "when did it happen" framing; per-system
                      offset from config (paths.yaml: local_utc_offset).
  * DR-availability-- a FIXED UTC-5 with no DST, for EVERY system including
                      ERCOT. This is the convention /dr_config/avail_hours_et
                      is expressed in. Comparing an event hour against a DR
                      window in any other convention is wrong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_time_index(
    timestamps: np.ndarray,
    hours_per_weather_year: int = 8760,
    local_utc_offset: int = 0,
    dr_avail_utc_offset: int = -5,
) -> pd.DataFrame:
    """Build the hour_idx -> calendar/weather-year lookup, with validation."""
    ts = pd.to_datetime(pd.Series([str(t) for t in timestamps]), utc=True, format="ISO8601")
    n = len(ts)

    hour_idx = np.arange(n, dtype=np.int64)
    wy_index = hour_idx // hours_per_weather_year

    local = ts + pd.Timedelta(hours=local_utc_offset)
    dr_local = ts + pd.Timedelta(hours=dr_avail_utc_offset)

    df = pd.DataFrame(
        {
            "hour_idx": hour_idx,
            "timestamp_utc": ts.values,
            "weather_year_index": wy_index,
            "weather_year": _weather_year_labels(ts, wy_index),
            "calendar_year": ts.dt.year.values,
            "month": ts.dt.month.values,
            "day_of_year": ts.dt.dayofyear.values,
            "hour_utc": ts.dt.hour.values,
            "hour_local": local.dt.hour.values,
            "hour_et_fixed": dr_local.dt.hour.values,
            "is_weekend": (ts.dt.dayofweek >= 5).values,
            "season": _season(ts.dt.month.values),
        }
    )
    return df


def _weather_year_labels(ts: pd.Series, wy_index: np.ndarray) -> np.ndarray:
    """Label each weather year by the calendar year that dominates its block.

    Derived positionally from hour_idx, then cross-checked against the parsed
    timestamps -- neither source is trusted alone.
    """
    years = ts.dt.year.values
    labels = np.zeros_like(years)
    for wy in np.unique(wy_index):
        mask = wy_index == wy
        vals, counts = np.unique(years[mask], return_counts=True)
        labels[mask] = vals[counts.argmax()]
    return labels


def _season(month: np.ndarray) -> np.ndarray:
    out = np.empty(len(month), dtype=object)
    out[np.isin(month, [12, 1, 2])] = "winter"
    out[np.isin(month, [3, 4, 5])] = "spring"
    out[np.isin(month, [6, 7, 8])] = "summer"
    out[np.isin(month, [9, 10, 11])] = "fall"
    return out


def validate_time_index(df: pd.DataFrame, hours_per_weather_year: int = 8760) -> list[str]:
    """Return a list of human-readable warnings; empty means clean."""
    warnings_out = []
    n = len(df)

    if n % hours_per_weather_year:
        warnings_out.append(
            f"{n} timesteps is not a whole multiple of {hours_per_weather_year}; "
            f"weather-year blocks will be ragged "
            f"(remainder {n % hours_per_weather_year} h)"
        )

    # Positional weather year vs. the year actually in the timestamps.
    #
    # These disagree by construction whenever the timestamps contain leap days
    # but weather years are forced to exactly 8760 h: each leap day pushes every
    # later block one day earlier. Verified in this sweep -- 96 leap hours
    # present, blocks drifting from Jan 1 (2007) to Dec 28 (2020 start of the
    # 2021 block), 672 h disagreeing, all at year boundaries in late December.
    disagree = int((df["weather_year"] != df["calendar_year"]).sum())
    if disagree:
        frac = 100 * disagree / n
        leap_hours = int(
            (
                (pd.Series(df["timestamp_utc"]).dt.month == 2)
                & (pd.Series(df["timestamp_utc"]).dt.day == 29)
            ).sum()
        )
        bad = df[df["weather_year"] != df["calendar_year"]]
        months = sorted(bad["month"].unique().tolist())
        detail = (
            f"{disagree} h ({frac:.2f}%) where positional weather year != "
            f"timestamp calendar year"
        )
        if leap_hours and months in ([12], [1], [1, 12]):
            detail += (
                f" -- BENIGN: {leap_hours} leap hours are present while weather "
                f"years are forced to {hours_per_weather_year} h, so block "
                f"boundaries drift ~1 day earlier per leap year. All affected "
                f"hours are at year boundaries (months {months}). Use "
                f"`weather_year` to align with ReEDS' positional convention and "
                f"`calendar_year`/`month` for meteorological framing"
            )
        else:
            detail += (
                f" -- affected months {months}, {leap_hours} leap hours. NOT the "
                f"expected leap-drift pattern; investigate before trusting "
                f"weather_year"
            )
        warnings_out.append(detail)

    gaps = pd.Series(df["timestamp_utc"]).diff().dropna().unique()
    if len(gaps) > 1:
        warnings_out.append(
            f"non-uniform timestep spacing: {sorted(pd.to_timedelta(gaps))[:5]}"
        )

    counts = df.groupby("weather_year").size()
    odd = counts[counts != hours_per_weather_year]
    if len(odd):
        warnings_out.append(
            f"weather years without exactly {hours_per_weather_year} h: "
            f"{odd.to_dict()}"
        )
    return warnings_out


def in_dr_window(hour_et_fixed: np.ndarray, avail_hours: list[int]) -> np.ndarray:
    """Boolean mask: was DR allowed to operate in this hour?

    An empty `avail_hours` means always-on (window = 0 in /dr_config).
    """
    if not avail_hours:
        return np.ones(len(hour_et_fixed), dtype=bool)
    return np.isin(hour_et_fixed, list(avail_hours))

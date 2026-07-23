"""Attribution figures for stage 03."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

BASE_C = "#4C72B0"
HIGH_C = "#C44E52"


def make_all(cfg, system, where, when, why, hi, ba, ev, feats, scal, regions,
             ref_high, ref_base):
    made = []
    for fn in (
        _fig_where, _fig_when, _fig_conditions, _fig_worst_event,
    ):
        try:
            p = fn(cfg, system, where, when, why, hi, ba, ev, feats, scal,
                   regions, ref_high, ref_base)
            if p:
                made.append(p)
        except Exception as exc:  # a broken figure must not kill the analysis
            print(f"  WARNING: {fn.__name__} failed: {exc}")
    return made


def _fig_where(cfg, system, where, when, why, hi, ba, ev, feats, scal, regions,
               ref_high, ref_base):
    w = where.sort_values("eue_mwh", ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))

    ax = axes[0]
    y = np.arange(len(w))
    ax.barh(y - 0.2, w["share_of_system_eue"], height=0.38, color=HIGH_C,
            label="share of system EUE")
    ax.barh(y + 0.2, w["share_of_added_load"], height=0.38, color=BASE_C,
            label="share of added DC load")
    ax.set_yticks(y)
    ax.set_yticklabels(w["region"], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("share")
    ax.set_title(f"{system.upper()} — where EUE lands vs where load was added")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="x")

    ax = axes[1]
    m = w[w["eue_mwh"] > 0]
    ax.scatter(m["added_mean_mw"], m["region_neue_ppm"], s=46, color=HIGH_C,
               zorder=3)
    for _, r in m.iterrows():
        ax.annotate(r["region"], (r["added_mean_mw"], r["region_neue_ppm"]),
                    fontsize=7.5, xytext=(4, 3), textcoords="offset points")
    zero = w[w["eue_mwh"] <= 0]
    if len(zero):
        ax.scatter(zero["added_mean_mw"], np.zeros(len(zero)), s=26,
                   facecolors="none", edgecolors="0.55", zorder=2,
                   label=f"{len(zero)} regions with zero EUE")
        ax.legend(fontsize=8)
    ax.set_xlabel("mean added datacenter load (MW)")
    ax.set_ylabel("region NEUE (ppm)")
    ax.set_title("Region reliability vs added load\n(not a clean relationship ⇒ margin matters more)")
    ax.grid(alpha=0.25)

    fig.tight_layout()
    p = cfg.figure_path(f"{system}_where.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def _fig_when(cfg, system, where, when, why, hi, ba, ev, feats, scal, regions,
              ref_high, ref_base):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))

    for ax, dim, xlabel in (
        (axes[0], "weather_year", "weather year"),
        (axes[1], "month", "month"),
        (axes[2], "hour_local", "hour of day (local)"),
    ):
        b = when[(when.scenario == "base") & (when.dimension == dim)]
        h = when[(when.scenario == "high") & (when.dimension == dim)]
        idx = sorted(set(b["bin"]) | set(h["bin"]))
        bs = b.set_index("bin")["share"].reindex(idx).fillna(0)
        hs = h.set_index("bin")["share"].reindex(idx).fillna(0)
        x = np.arange(len(idx))
        ax.bar(x - 0.2, bs, width=0.38, color=BASE_C, label="base DC load")
        ax.bar(x + 0.2, hs, width=0.38, color=HIGH_C, label="high DC load")
        ax.set_xticks(x)
        ax.set_xticklabels(idx, fontsize=7, rotation=90 if len(idx) > 13 else 0)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("share of that scenario's EUE")
        ax.grid(alpha=0.25, axis="y")
    axes[0].legend(fontsize=8)
    axes[1].set_title(
        f"{system.upper()} — WHEN does EUE occur? (each scenario normalized to 1)\n"
        "similar bars ⇒ added load scales the problem; different bars ⇒ it moves it"
    )

    fig.tight_layout()
    p = cfg.figure_path(f"{system}_when.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def _fig_conditions(cfg, system, where, when, why, hi, ba, ev, feats, scal,
                    regions, ref_high, ref_base):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

    # Net-load percentile distribution, EUE-weighted vs all hours.
    ax = axes[0]
    bins = np.linspace(0, 1, 21)
    ax.hist(feats["net_load_pctile"].ravel(), bins=bins, density=True,
            color="0.75", label="all hours × regions")
    ax.hist(hi["net_load_pctile"], bins=bins, weights=hi["eue"], density=True,
            histtype="step", lw=2.2, color=HIGH_C, label="EUE-weighted")
    ax.set_xlabel("regional net-load percentile")
    ax.set_ylabel("density")
    ax.set_title("EUE happens at extreme net load")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    # Solar CF during EUE hours.
    ax = axes[1]
    v = hi["cf_solar"].to_numpy(float)
    ok = np.isfinite(v)
    ax.hist(feats["cf_solar"][np.isfinite(feats["cf_solar"])], bins=20,
            density=True, color="0.75", label="all hours")
    if ok.any():
        ax.hist(v[ok], bins=20, weights=hi["eue"].to_numpy()[ok], density=True,
                histtype="step", lw=2.2, color="#DD8452", label="EUE-weighted")
    ax.set_xlabel("regional solar capacity factor")
    ax.set_title("Solar output during EUE hours")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    # EUE by hour of day and season.
    ax = axes[2]
    piv = hi.pivot_table(index="hour_local", columns="season", values="eue",
                         aggfunc="sum").fillna(0)
    order = [s for s in ("winter", "spring", "summer", "fall") if s in piv.columns]
    bottom = np.zeros(len(piv))
    colors = {"winter": "#4C72B0", "spring": "#55A868", "summer": "#C44E52",
              "fall": "#DD8452"}
    for s in order:
        ax.bar(piv.index, piv[s], bottom=bottom, color=colors[s], label=s,
               width=0.85)
        bottom += piv[s].to_numpy()
    ax.set_xlabel("hour of day (local)")
    ax.set_ylabel("total EUE (MWh)")
    ax.set_title("EUE by hour and season")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")

    fig.suptitle(f"{system.upper()} — conditions during EUE hours (high DC load, no DR)",
                 y=1.02, fontsize=11)
    fig.tight_layout()
    p = cfg.figure_path(f"{system}_conditions.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


def _fig_worst_event(cfg, system, where, when, why, hi, ba, ev, feats, scal,
                     regions, ref_high, ref_base):
    """Hourly traces around the single largest event, to make stats legible."""
    e = ev[ev["case_id"] == ref_high]
    if not len(e):
        return None
    worst = e.loc[e["total_eue_mwh"].idxmax()]
    region = worst["region"]
    j = regions.index(region)

    pad = 36
    lo = max(0, int(worst["start_hour_idx"]) - pad)
    hi_i = min(feats["load_high_mw"].shape[0], int(worst["end_hour_idx"]) + pad)
    sl = slice(lo, hi_i)
    x = np.arange(lo, hi_i)

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)

    ax = axes[0]
    ax.plot(x, feats["load_high_mw"][sl, j], color=HIGH_C, lw=1.5, label="load (high DC)")
    ax.plot(x, feats["load_base_mw"][sl, j], color=BASE_C, lw=1.2, ls="--", label="load (base DC)")
    ax.set_ylabel("MW")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.25)
    ax.set_title(
        f"{system.upper()} — largest EUE event: {region}, "
        f"{worst['weather_year']}-{worst['month']:02d}, "
        f"{worst['duration_h']} h, {worst['total_eue_mwh']:,.0f} MWh"
    )

    ax = axes[1]
    ax.plot(x, feats["cap_solar_mw"][sl, j], color="#DD8452", lw=1.3, label="solar available")
    ax.plot(x, feats["cap_wind_mw"][sl, j], color="#55A868", lw=1.3, label="wind available")
    ax.plot(x, feats["margin_mw"][sl, j], color="0.35", lw=1.3, label="margin (cap − load)")
    ax.axhline(0, color="k", lw=0.8, ls=":")
    ax.set_ylabel("MW")
    ax.legend(fontsize=8, ncol=3)
    ax.grid(alpha=0.25)

    ax = axes[2]
    sub = hi[(hi["region"] == region) & (hi["hour_idx"] >= lo) & (hi["hour_idx"] < hi_i)]
    ax.bar(sub["hour_idx"], sub["eue"], color=HIGH_C, width=1.0, label="EUE")
    ax.set_ylabel("EUE (MWh)")
    ax.set_xlabel("hour index")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")

    fig.tight_layout()
    p = cfg.figure_path(f"{system}_worst_event.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def plot_critical_region(cfg, system, nonzero, feats, regions, ref_high,
                         region=None):
    """Why the dominant EUE region fails: VRE output vs the firm+import floor.

    For systems whose EUE concentrates in one region, this is the single most
    explanatory figure -- it shows that shortfalls occupy only the low tail of
    the VRE distribution, and how far below the serving floor the deficit runs.
    """
    e = nonzero[(nonzero["case_id"] == ref_high)]
    if not len(e):
        return None
    if region is None:
        region = e.groupby("region")["eue"].sum().idxmax()
    e = e[e["region"] == region]
    if not len(e):
        return None

    j = regions.index(region)
    wind = feats["cap_wind_mw"][:, j]
    load = feats["load_high_mw"][:, j]
    firm = feats["cap_firm_mw"][:, j]
    imp = feats["import_cap_mw"][:, j]
    h = e["hour_idx"].to_numpy()
    w = e["eue"].to_numpy()

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

    ax = axes[0]
    bins = np.linspace(0, max(wind.max(), 1), 60)
    ax.hist(wind, bins=bins, color="0.78", label="all hours")
    ax.hist(wind[h], bins=bins, color=HIGH_C, label="EUE hours")
    ax.set_yscale("log")
    ax.set_xlabel(f"{region} wind output (MW)")
    ax.set_ylabel("hours (log)")
    ax.set_title(f"EUE occupies only the low tail\nmax wind in any EUE hour: {wind[h].max():.0f} MW")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1]
    lo = max(1.0, wind.max() * 0.06)
    b2 = np.linspace(0, lo, 40)
    ax.hist(wind[h], bins=b2, weights=w, color=HIGH_C)
    ax.set_xlabel(f"{region} wind output (MW) — zoomed to low tail")
    ax.set_ylabel("EUE (MWh)")
    ax.set_title(f"Median wind during EUE hours: {np.median(wind[h]):.0f} MW\n(capacity {wind.max():.0f} MW)")
    ax.grid(alpha=0.25)

    ax = axes[2]
    floor = firm + imp
    # Split the EUE hours by whether DETERMINISTIC capacity was short. The
    # hours below the line are not a contradiction: /eue is a mean over many
    # Monte Carlo samples, so a minority of draws losing the small firm fleet
    # or the tie yields a small positive expectation even when nameplate
    # capacity covers load.
    serve = firm[h] + imp[h] + wind[h]
    short = load[h] > serve
    ax.scatter(wind[h][~short], load[h][~short], s=np.clip(w[~short] * 8, 4, 120),
               color="#DD8452", alpha=0.45, edgecolors="none",
               label=f"outage-driven ({100 * (~short).mean():.0f}% of hours, "
                     f"{100 * w[~short].sum() / w.sum():.0f}% of EUE)")
    ax.scatter(wind[h][short], load[h][short], s=np.clip(w[short] * 8, 4, 120),
               color=HIGH_C, alpha=0.55, edgecolors="none",
               label=f"capacity-short ({100 * short.mean():.0f}% of hours, "
                     f"{100 * w[short].sum() / w.sum():.0f}% of EUE)")
    xs = np.linspace(0, max(wind[h].max() * 1.25, 1), 100)
    ax.plot(xs, floor.mean() + xs, color="k", lw=1.4, ls="--",
            label=f"serving limit: firm+import ({floor.mean():.0f} MW) + wind")
    ax.set_xlabel(f"{region} wind output (MW)")
    ax.set_ylabel("load (MW)")
    ax.set_title("Above the line = capacity short; below = forced-outage tail\n"
                 "(size ∝ EUE; storage covers the gap until it drains)")
    ax.legend(fontsize=6.8, loc="lower right")
    ax.grid(alpha=0.25)

    fig.suptitle(
        f"{system.upper()} — {region} carries "
        f"{100 * w.sum() / nonzero[nonzero.case_id == ref_high]['eue'].sum():.1f}% "
        f"of all EUE (high DC load, no DR)", y=1.03, fontsize=11)
    fig.tight_layout()
    p = cfg.figure_path(f"{system}_critical_region.png")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p

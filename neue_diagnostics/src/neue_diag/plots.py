"""Figure helpers.

Deliberately plain matplotlib: no seaborn, no style packages, nothing that
would add a dependency to the one conda env verified to run this pipeline.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# Mode -> line style, so shed and shift stay distinguishable in greyscale.
MODE_STYLE = {"shed": "--", "shift": "-", "mixed": ":"}
HOURS_COLOR = {4.0: "#4C72B0", 8.0: "#DD8452", 16.0: "#55A868"}
FALLBACK_COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]


def _style_for(row, idx: int):
    ls = MODE_STYLE.get(str(row.get("dr_mode")), "-")
    hours = row.get("dr_energy_hours")
    try:
        color = HOURS_COLOR.get(float(hours))
    except (TypeError, ValueError):
        color = None
    if color is None:
        color = FALLBACK_COLORS[idx % len(FALLBACK_COLORS)]
    return ls, color


def plot_saturation_curves(
    curves, summary, system: str, metric: str, path, annotate_knees: bool = True
):
    """NEUE vs DR fraction, one line per family, with knees marked."""
    c_sys = curves[curves["system"] == system]
    s_sys = summary[summary["system"] == system].set_index("case_family")
    if not len(c_sys):
        return None

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    ax, ax2 = axes

    families = sorted(c_sys["case_family"].unique())
    for i, family in enumerate(families):
        c = c_sys[c_sys["case_family"] == family].sort_values("dr_fraction")
        ls, color = _style_for(c.iloc[0], i)
        ax.plot(
            c["dr_fraction"], c[metric], ls, color=color, marker="o", ms=3.5,
            lw=1.6, label=family,
        )
        ax2.plot(
            c["dr_fraction"].iloc[1:],
            c["marginal_return_per_fraction"].iloc[1:],
            ls, color=color, marker="o", ms=3.5, lw=1.6, label=family,
        )
        if annotate_knees and family in s_sys.index:
            knee = s_sys.loc[family, "knee_kneedle"]
            if knee is not None and np.isfinite(knee):
                yk = np.interp(knee, c["dr_fraction"], c[metric])
                ax.plot([knee], [yk], marker="v", ms=9, color=color, mec="k", mew=0.5)

    anchor = c_sys[c_sys["is_anchor"]][metric].iloc[0]
    ax.axhline(anchor, color="0.35", lw=1.1, ls=":", zorder=0)
    ax.annotate(
        f"no DR (high DC load): {anchor:.4f}",
        xy=(0.02, anchor), xytext=(0.02, anchor), fontsize=8, color="0.25",
        va="bottom",
    )
    base = c_sys[f"ref_base_{metric}"].iloc[0]
    if np.isfinite(base):
        ax.axhline(base, color="#C44E52", lw=1.1, ls="-.", zorder=0)
        ax.annotate(
            f"base DC load (target): {base:.4f}",
            xy=(0.02, base), xytext=(0.02, base), fontsize=8, color="#C44E52",
            va="bottom",
        )
        ax.set_ylim(bottom=min(base * 0.85, c_sys[metric].min() * 0.95))

    ax.set_xlabel("DR fraction of added datacenter load")
    ax.set_ylabel(metric)
    ax.set_title(f"{system.upper()} — saturation curve\n▼ = kneedle knee")
    ax.legend(fontsize=7.5, ncol=2)
    ax.grid(alpha=0.25)

    ax2.set_xlabel("DR fraction")
    ax2.set_ylabel(f"marginal Δ{metric} per unit fraction")
    ax2.set_title("Marginal return\n(flat ⇒ saturated)")
    ax2.grid(alpha=0.25)
    ax2.legend(fontsize=7.5, ncol=2)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_return_per_mw(curves, system: str, metric: str, path):
    """Comparable across families: reduction bought per MW of borrow capacity."""
    c_sys = curves[(curves["system"] == system) & (~curves["is_anchor"])]
    if not len(c_sys):
        return None

    fig, ax = plt.subplots(figsize=(7.2, 5))
    for i, family in enumerate(sorted(c_sys["case_family"].unique())):
        c = c_sys[c_sys["case_family"] == family].sort_values("borrow_mw")
        ls, color = _style_for(c.iloc[0], i)
        ax.plot(
            c["borrow_mw"], c["reduction"], ls, color=color, marker="o", ms=3.5,
            lw=1.6, label=family,
        )
    ax.set_xlabel("DR borrow capacity deployed (MW)")
    ax.set_ylabel(f"{metric} reduction vs no-DR")
    ax.set_title(f"{system.upper()} — return per MW deployed\n(same x-axis ⇒ families comparable)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_availability_overlap(overlap, system: str, path):
    """Share of EUE inside each case's own DR window — the confound diagnostic."""
    # Drop the no-DR references: they have no window, so they sit at 1.0 and
    # only add colliding colors to the legend.
    o = overlap[
        (overlap["system"] == system)
        & (overlap["eue_total_mwh"] > 0)
        & overlap["dr_mode"].notna()
    ]
    if not len(o):
        return None

    fig, ax = plt.subplots(figsize=(7.6, 5))
    for i, family in enumerate(sorted(o["case_family"].unique())):
        sub = o[o["case_family"] == family].sort_values("dr_fraction")
        ls, color = _style_for(sub.iloc[0], i)
        ax.plot(
            sub["dr_fraction"], sub["eue_in_window_frac"], ls, color=color,
            marker="o", ms=3.5, lw=1.6, label=family,
        )
    ax.axhline(1.0, color="0.4", lw=1.0, ls=":")
    ax.set_ylim(-0.03, 1.08)
    ax.set_xlabel("DR fraction")
    ax.set_ylabel("share of EUE occurring while DR was available")
    ax.set_title(
        f"{system.upper()} — availability overlap\n"
        "low ⇒ the window, not the payback rule, explains the result"
    )
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_case_ranking(registry, system: str, metric: str, path):
    """Every case ranked, with Monte Carlo error bars."""
    r = registry[registry["system"] == system].copy()
    if not len(r):
        return None
    r = r.sort_values(metric)

    # Convert EUE stderr into the metric's units via the EUE->NEUE ratio.
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(
            r["eue_mean_mwh"] > 0, r[metric] / r["eue_mean_mwh"], np.nan
        )
    err = r["eue_stderr_mwh"].to_numpy() * scale

    colors = [
        "#C44E52" if ref else ("#DD8452" if m == "shed" else "#4C72B0")
        for ref, m in zip(r["is_reference"], r["dr_mode"].astype(str))
    ]

    fig, ax = plt.subplots(figsize=(8, max(4, 0.17 * len(r))))
    y = np.arange(len(r))
    ax.barh(y, r[metric], xerr=err, color=colors, height=0.72,
            error_kw=dict(lw=0.7, ecolor="0.3"))
    ax.set_yticks(y)
    ax.set_yticklabels(r["case_id"], fontsize=6.5)
    ax.invert_yaxis()
    ax.set_xlabel(metric)
    ax.set_title(
        f"{system.upper()} — all cases ranked (error bars = MC stderr)\n"
        "red = no-DR reference, blue = shift, orange = shed"
    )
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path

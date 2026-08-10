"""Shared choropleth helpers: discrete binned coloring + a plain legend.

The EUE fields are heavily skewed (one region orders of magnitude above the
rest), so continuous scales either wash out everything but the hotspot (linear)
or need an unreadable 10^-3 axis (log). Discrete decade bins are the standard
fix: each region falls in a labeled range with a distinct color, and the legend
reads plainly ("0.1-1"). Exact values are still printed on each region by the
calling script.

Bins are given as ascending edges, e.g. [0, 1e-3, 1e-2, 1e-1, 1, inf]. Each
consecutive pair (lo, hi] is one color drawn from `cmap`. Use inf as the last
edge so the largest region is never clipped.
"""

from __future__ import annotations

import math

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch


def load_pca(shapefile, region_field="rb"):
    """Read the ReEDS PCA shapefile (region ids in `region_field`)."""
    return gpd.read_file(shapefile)


def fmt_num(x) -> str:
    """Compact number format for legend labels."""
    if x == 0:
        return "0"
    if math.isinf(x):
        return "∞"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    if abs(x) >= 1:
        return f"{x:g}"
    return f"{x:g}"


def decade_edges(values, n_bins=5):
    """Clean decade bin edges ending just above the data max.

    e.g. data max 7.1 -> [0, 0.001, 0.01, 0.1, 1, 10]; everything below the
    fourth-from-top decade lumps into the first (0, ...] bin so the count stays
    fixed regardless of how tiny the smallest value is.
    """
    pos = [float(v) for v in values if v is not None and v > 0]
    if not pos:
        return [0.0, 1.0, float("inf")]
    hi = 10.0 ** math.ceil(math.log10(max(pos)))
    return [0.0] + [hi / 10.0 ** i for i in range(n_bins - 1, -1, -1)]


def parse_bins(spec):
    """Parse a comma-separated --bins string into ascending float edges."""
    if not spec:
        return None
    edges = [float("inf") if s.strip() in ("inf", "∞") else float(s)
             for s in spec.split(",")]
    return edges


def bin_cmap(edges, cmap_name):
    """Return (ListedColormap, BoundaryNorm, [colors]) for the given edges."""
    cmap = plt.get_cmap(cmap_name)
    n = len(edges) - 1
    colors = [cmap((i + 0.5) / n) for i in range(n)]
    listed = ListedColormap(colors)
    # BoundaryNorm needs finite boundaries; map the open-ended top edge to a
    # large finite sentinel above the data so inf-topped bins still color.
    finite = list(edges)
    if math.isinf(finite[-1]):
        finite[-1] = max(finite[-2] * 1e6, finite[-2] + 1)
    return listed, BoundaryNorm(finite, n), colors


def bin_patches(edges, colors, unit="", fmt=fmt_num):
    """Legend handles for each bin, labeled 'lo-hi' (or '>lo' for an inf top)."""
    out = []
    for i, c in enumerate(colors):
        lo, hi = edges[i], edges[i + 1]
        if math.isinf(hi):
            label = f">{fmt(lo)}{unit}"
        elif lo == 0 and i == 0:            # genuine bottom bin only
            label = f"≤{fmt(hi)}{unit}"
        else:
            label = f"{fmt(lo)}-{fmt(hi)}{unit}"
        out.append(Patch(facecolor=c, edgecolor="#555555", linewidth=0.5,
                         label=label))
    return out


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def smart_labels(ax, items, *, color, fontsize, area_pct=40, ring_frac=1.28,
                 min_sep_deg=17, overrides=None):
    """Place region labels, fanning small (crowd-prone) regions out on leaders.

    `items` is a list of dicts: {"xy": (x, y) centroid, "area": float, "text":
    str, "region": str}. Regions with area at/above the `area_pct` percentile
    are labeled in place; smaller ones are pushed onto a ring outside the
    cluster (radius `ring_frac` x half-extent) at their own bearing, nudged
    apart by `min_sep_deg`, with a thin line back to the polygon.

    `overrides` maps region -> (x_frac, y_frac) in AXES-fraction coordinates
    (0-1); those labels are placed exactly there with a leader back to the
    polygon, bypassing the automatic layout. Returns the data-coord label
    positions used by the automatic labels, so the caller can widen the axes.
    """
    overrides = overrides or {}
    if overrides:
        forced = [it for it in items if it.get("region") in overrides]
        items = [it for it in items if it.get("region") not in overrides]
        for it in forced:
            ax.annotate(
                it["text"], xy=it["xy"], xycoords="data",
                xytext=overrides[it["region"]], textcoords="axes fraction",
                ha="center", va="center", color=color, fontsize=fontsize,
                fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=color, lw=0.9, alpha=0.85,
                                shrinkA=0, shrinkB=2),
            )
    if not items:
        return []
    xs = [it["xy"][0] for it in items]
    ys = [it["xy"][1] for it in items]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    half = 0.5 * max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    R = ring_frac * half

    areas = sorted(it["area"] for it in items)
    thresh = areas[min(int(area_pct / 100 * len(areas)), len(areas) - 1)]
    large = [it for it in items if it["area"] >= thresh]
    small = [it for it in items if it["area"] < thresh]

    for it in large:
        ax.annotate(it["text"], it["xy"], ha="center", va="center",
                    color=color, fontsize=fontsize, fontweight="bold")

    small.sort(key=lambda it: math.atan2(it["xy"][1] - cy, it["xy"][0] - cx))
    used_angles = []
    positions = [it["xy"] for it in large]
    sep = math.radians(min_sep_deg)
    for it in small:
        a = math.atan2(it["xy"][1] - cy, it["xy"][0] - cx)
        guard = 0
        while any(abs(_wrap(a - p)) < sep for p in used_angles) and guard < 60:
            a += sep * 0.6
            guard += 1
        used_angles.append(a)
        lx, ly = cx + R * math.cos(a), cy + R * math.sin(a)
        positions.append((lx, ly))
        ax.annotate(
            it["text"], xy=it["xy"], xytext=(lx, ly), ha="center", va="center",
            color=color, fontsize=fontsize, fontweight="bold",
            arrowprops=dict(arrowstyle="-", color=color, lw=0.9, alpha=0.85,
                            shrinkA=0, shrinkB=2),
        )
    return positions


def draw_binned(fig, ax, gdf, context_gdf, value_col, edges, *, cmap_name,
                unit="", zero_color="#d9d9d9", zero_label="0 (no EUE)",
                extra_patches=None, legend_title="", legend_loc="lower left",
                legend_fontsize=10):
    """Plot a discrete-binned choropleth with a categorical legend.

    `gdf` is the in-system regions (with value_col); `context_gdf` the full set
    of polygons drawn pale-grey underneath for geographic context. Regions with
    value <= 0 are drawn in `zero_color`. `extra_patches` are appended to the
    legend (e.g. special categories the caller drew itself).
    Returns the map extent (minx, miny, maxx, maxy) of `gdf`.
    """
    context_gdf.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.4)

    listed, norm, colors = bin_cmap(edges, cmap_name)
    pos = gdf[gdf[value_col] > 0]
    zero = gdf[gdf[value_col] <= 0]

    if len(zero):
        zero.plot(ax=ax, color=zero_color, edgecolor="#888888", linewidth=0.6)
    if len(pos):
        pos.plot(ax=ax, column=value_col, cmap=listed, norm=norm,
                 edgecolor="#555555", linewidth=0.7)

    handles = list(bin_patches(edges, colors, unit=unit))
    if len(zero):
        handles.append(Patch(facecolor=zero_color, edgecolor="#888888",
                             linewidth=0.5, label=zero_label))
    if extra_patches:
        handles.extend(extra_patches)
    ax.legend(handles=handles, title=legend_title, loc=legend_loc,
              fontsize=legend_fontsize, title_fontsize=legend_fontsize,
              framealpha=0.9)

    return gdf.total_bounds

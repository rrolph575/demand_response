"""Readers for PRAS *input* systems (`.pras` files).

These are the large files: PJM's /generators/capacity is 131400 x 2528, ~1.3 GB
decompressed. Everything here streams in row chunks so peak memory stays
bounded regardless of system size.

Verified structure (2026-07-22):

    /regions/_core              (R,)   compound (name,)
    /regions/load               (N, R) float
    /generators/_core           (G,)   compound (name, category, region)
    /generators/capacity        (N, G) float   -- available capacity per hour
    /storages/_core             (S,)   compound (name, category, region)
    /storages/{energycapacity, dischargecapacity, chargecapacity}   (N, S)
    /generatorstorages/_core    (GS,)  compound (name, category, region)
    /lines/_core                (L,)   compound (name, category, region_from,
                                                 region_to)
    /lines/{forward,backward}capacity   (N, L)
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

CHUNK_ROWS = 8760  # one weather year per chunk

# ReEDS technology categories grouped into what matters for adequacy.
SOLAR_CATEGORIES = {"upv", "distpv", "csp", "pvb"}
WIND_CATEGORIES = {"wind-ons", "wind-ofs"}
HYDRO_CATEGORIES = {"hydend", "hydund", "hydnpnd", "hydro", "hyded", "hydud"}


def _dec(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _onehot(col: np.ndarray, n_regions: int) -> np.ndarray:
    """(n_items, n_regions) indicator matrix mapping items to their region.

    Used to scatter per-device columns into per-region sums with a matmul,
    which BLAS does far faster than np.add.at's unbuffered accumulation.
    """
    mat = np.zeros((len(col), n_regions), dtype=np.float32)
    mat[np.arange(len(col)), col] = 1.0
    return mat


def read_regions(path: str | Path) -> list[str]:
    with h5py.File(path, "r") as f:
        return [_dec(r["name"]) for r in f["regions/_core"][:]]


def read_load(path: str | Path) -> tuple[np.ndarray, list[str]]:
    """(N, R) load matrix plus its region labels."""
    with h5py.File(path, "r") as f:
        return f["regions/load"][:].astype(np.float64), read_regions(path)


def classify_category(category: str) -> str:
    """Map a ReEDS technology category onto a supply group."""
    c = category.lower()
    if c in SOLAR_CATEGORIES:
        return "solar"
    if c in WIND_CATEGORIES:
        return "wind"
    if c in HYDRO_CATEGORIES:
        return "hydro"
    return "firm"


def aggregate_generators(
    path: str | Path, regions: list[str], progress=None
) -> dict[str, np.ndarray]:
    """Sum hourly available generator capacity into (N, R) arrays per group.

    Streams /generators/capacity in row chunks; peak memory is one chunk
    (8760 x G), not the whole 1.3 GB matrix.
    """
    region_pos = {r: i for i, r in enumerate(regions)}

    with h5py.File(path, "r") as f:
        core = f["generators/_core"][:]
        cats = np.array([classify_category(_dec(c["category"])) for c in core])
        gen_region = np.array([_dec(c["region"]) for c in core])

        unknown = sorted(set(gen_region) - set(region_pos))
        if unknown:
            raise ValueError(
                f"{Path(path).name}: generators reference regions not in "
                f"/regions/_core: {unknown[:5]}"
            )
        col = np.array([region_pos[r] for r in gen_region])

        dset = f["generators/capacity"]
        n_ts = dset.shape[0]
        groups = sorted(set(cats))
        out = {g: np.zeros((n_ts, len(regions)), dtype=np.float32) for g in groups}

        # Scatter generators to regions with a one-hot matmul rather than
        # np.add.at: BLAS handles (chunk x G) @ (G x R) far faster than
        # unbuffered index accumulation over hundreds of millions of elements.
        onehot = {}
        for g in groups:
            m = cats == g
            if not m.any():
                continue
            mat = np.zeros((int(m.sum()), len(regions)), dtype=np.float32)
            mat[np.arange(int(m.sum())), col[m]] = 1.0
            onehot[g] = (m, mat)

        for start in range(0, n_ts, CHUNK_ROWS):
            stop = min(start + CHUNK_ROWS, n_ts)
            chunk = dset[start:stop].astype(np.float32)
            for g, (m, mat) in onehot.items():
                out[g][start:stop] = chunk[:, m] @ mat
            if progress:
                progress(stop, n_ts)

    return out


def aggregate_storage(path: str | Path, regions: list[str]) -> dict[str, np.ndarray]:
    """Per-region storage energy and discharge power, (N, R).

    Covers both /storages and /generatorstorages; the latter are hybrid
    resources (mostly hydro with reservoirs here) and are counted separately so
    they can be included or excluded downstream.
    """
    region_pos = {r: i for i, r in enumerate(regions)}
    out: dict[str, np.ndarray] = {}

    with h5py.File(path, "r") as f:
        for grp, tag in (("storages", "storage"), ("generatorstorages", "genstor")):
            if grp not in f:
                continue
            core = f[grp]["_core"][:]
            if not len(core):
                continue
            col = np.array([region_pos[_dec(c["region"])] for c in core])

            for field, label in (
                ("energycapacity", "energy_mwh"),
                ("dischargecapacity", "power_mw"),
            ):
                if field not in f[grp]:
                    continue
                dset = f[grp][field]
                n_ts = dset.shape[0]
                acc = np.zeros((n_ts, len(regions)), dtype=np.float32)
                scatter = _onehot(col, len(regions))
                for start in range(0, n_ts, CHUNK_ROWS):
                    stop = min(start + CHUNK_ROWS, n_ts)
                    acc[start:stop] = dset[start:stop].astype(np.float32) @ scatter
                out[f"{tag}_{label}"] = acc
    return out


def aggregate_import_capacity(
    path: str | Path, regions: list[str]
) -> dict[str, np.ndarray]:
    """Total transmission capacity into and out of each region, (N, R).

    A line from A to B contributes its forward capacity to B's import limit and
    its backward capacity to A's import limit. This is a nameplate ceiling, not
    a flow -- PRAS decides actual flows internally. It bounds how much help a
    region could receive.
    """
    region_pos = {r: i for i, r in enumerate(regions)}

    with h5py.File(path, "r") as f:
        if "lines" not in f or not len(f["lines/_core"]):
            n_ts = f["regions/load"].shape[0]
            z = np.zeros((n_ts, len(regions)), dtype=np.float32)
            return {"import_cap_mw": z, "export_cap_mw": z.copy()}

        core = f["lines/_core"][:]
        r_from = np.array([region_pos[_dec(c["region_from"])] for c in core])
        r_to = np.array([region_pos[_dec(c["region_to"])] for c in core])

        fwd, bwd = f["lines/forwardcapacity"], f["lines/backwardcapacity"]
        n_ts = fwd.shape[0]
        imp = np.zeros((n_ts, len(regions)), dtype=np.float32)
        exp = np.zeros((n_ts, len(regions)), dtype=np.float32)

        to_scatter = _onehot(r_to, len(regions))
        from_scatter = _onehot(r_from, len(regions))

        for start in range(0, n_ts, CHUNK_ROWS):
            stop = min(start + CHUNK_ROWS, n_ts)
            cf = fwd[start:stop].astype(np.float32)
            cb = bwd[start:stop].astype(np.float32)

            # forward capacity flows from -> to, so it is an import for `to`
            # and an export for `from`; backward capacity is the reverse.
            imp[start:stop] = cf @ to_scatter + cb @ from_scatter
            exp[start:stop] = cf @ from_scatter + cb @ to_scatter

    return {"import_cap_mw": imp, "export_cap_mw": exp}

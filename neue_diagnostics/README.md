# NEUE diagnostics pipeline

Explains *when* and *why* high NEUE occurs in PRAS demand-response sweeps, and
where incremental DR stops paying off.

- **[PROJECT_PLAN.md](PROJECT_PLAN.md)** — architecture, data facts, staging
- **[FINDINGS.md](FINDINGS.md)** — results so far (read this first)
- **[slurm/README.md](slurm/README.md)** — how to run; what needs an allocation

## Quick start

```bash
PY=/home/rrolph/.conda-envs/reeds2/bin/python
$PY scripts/00_build_registry.py     # ~2 s   case registry from HDF5 attrs
$PY scripts/01_extract_eue.py        # ~2 min hourly EUE/DR -> cache
$PY scripts/04_saturation.py         # ~3 s   knee analysis + figures
$PY tests/test_pipeline.py           # unit tests
```

## Swapping inputs

Edit `config/paths.yaml` (`sweep_root`, per-system `pras.base`/`pras.high`) and
re-run from stage 00. Case identity is read from each file's own metadata
(`pras_input` attribute, `/dr_config`), not parsed from filenames, so renamed or
restructured sweeps still work. Stage 00 fails loudly on region/timestep
mismatches within a system rather than silently misaligning.

## Status

| Stage | Script | State |
|---|---|---|
| 00 registry | `scripts/00_build_registry.py` | done |
| 01 EUE extraction | `scripts/01_extract_eue.py` | done |
| 02 `.pras` features | `scripts/02_extract_features.py` | **not built** (needs allocation) |
| 03 event detection | `scripts/03_detect_events.py` | **not built** |
| 04a saturation | `scripts/04_saturation.py` | done |
| 04b–g attribution | `scripts/04_attribute.py` | **not built** (needs stage 02) |

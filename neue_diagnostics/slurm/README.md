# Running the pipeline

## Does this need an allocation?

Mostly no. Measured on the login node, 2026-07-22:

| Stage | What it reads | Runtime | Needs a node? |
|---|---|---|---|
| `00_build_registry.py` | HDF5 attributes only | ~2 s | no |
| `01_extract_eue.py` | 92 result files, ~8 MB each | ~2 min | no |
| `02_extract_features.py` | `.pras` inputs, **~1.3 GB decompressed** | minutes | **yes** |
| `03_detect_events.py` | cached CSVs | seconds | no |
| `04_saturation.py` | cached CSVs | ~3 s | no |

The EUE data is far smaller than it looks. `/eue` is under 0.1 % nonzero, so all
68 PJM cases reduce to ~139 000 nonzero rows — a 6 MB CSV. Only the `.pras`
generator-capacity matrix (131 400 × 2528) is genuinely large.

## Interactive

```bash
PY=/home/rrolph/.conda-envs/reeds2/bin/python   # set in config/paths.yaml

$PY scripts/00_build_registry.py
$PY scripts/01_extract_eue.py
$PY scripts/04_saturation.py
```

## Batch

Set `account` and `partition` under `slurm:` in `config/paths.yaml` for your own
reference, then pass them to `sbatch` (they are deliberately not baked into any
script):

```bash
sbatch --account=<acct> --partition=<part> --time=02:00:00 --mem=80G \
       slurm/run_stage.sh scripts/02_extract_features.py --system pjm
```

Chaining with dependencies:

```bash
j1=$(sbatch --parsable --account=<acct> --partition=<part> \
     slurm/run_stage.sh scripts/00_build_registry.py)
j2=$(sbatch --parsable --dependency=afterok:$j1 --account=<acct> --partition=<part> \
     slurm/run_stage.sh scripts/01_extract_eue.py)
sbatch --dependency=afterok:$j2 --account=<acct> --partition=<part> \
     slurm/run_stage.sh scripts/04_saturation.py
```

## Swapping input files

Edit `config/paths.yaml` — `sweep_root`, and the per-system `pras.base` /
`pras.high` entries — then re-run from stage 00. Nothing downstream hardcodes a
path, case name, region list, or sweep design.

Stage 00 will **fail loudly** if the swapped-in files disagree on region set or
timestep count within a system. That is intentional: silent axis misalignment is
the easiest way to produce confident nonsense here.

#!/bin/bash
#SBATCH --job-name=neue_features
#SBATCH --output=slurm/logs/%x-%j.out
#SBATCH --error=slurm/logs/%x-%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#
# Stage 02: extract per-region hourly features from the .pras input files.
#
# This is the ONE stage that needs an allocation. It reads
# /generators/capacity, which is ~1.3 GB decompressed for PJM (131400 x 2528).
# Every other stage runs comfortably on a login node -- see slurm/README.md.
#
# Set account/partition/time/mem in config/paths.yaml, then:
#     sbatch slurm/stage02_features.sh            # all systems
#     sbatch slurm/stage02_features.sh --system pjm
#
# The account and partition are read from config at submit time by
# slurm/submit.sh; if you sbatch this file directly, pass them yourself:
#     sbatch --account=<acct> --partition=<part> slurm/stage02_features.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p slurm/logs

CONDA_PREFIX_CFG=$(
  "${PYTHON:-python3}" - <<'PY' 2>/dev/null || echo ""
import yaml, sys
try:
    cfg = yaml.safe_load(open("config/paths.yaml"))
    print(cfg.get("env", {}).get("conda_prefix", ""))
except Exception:
    print("")
PY
)
PY_BIN="${CONDA_PREFIX_CFG:+$CONDA_PREFIX_CFG/bin/python}"
PY_BIN="${PY_BIN:-python3}"

echo "host      : $(hostname)"
echo "python    : $PY_BIN"
echo "started   : $(date -Is)"

"$PY_BIN" scripts/02_extract_features.py "$@"

echo "finished  : $(date -Is)"

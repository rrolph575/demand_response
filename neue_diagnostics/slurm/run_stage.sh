#!/bin/bash
#SBATCH --job-name=neue_stage
#SBATCH --output=slurm/logs/%x-%j.out
#SBATCH --error=slurm/logs/%x-%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#
# Generic runner: submits any pipeline stage to a compute node.
#
#   sbatch --account=<acct> --partition=<part> \
#          slurm/run_stage.sh scripts/02_extract_features.py --system pjm
#
# Only stage 02 (.pras feature extraction) actually needs an allocation --
# it reads /generators/capacity, ~1.3 GB decompressed for PJM. Stages 00, 01,
# 03 and 04 finish in seconds to a couple of minutes on a login node. See
# slurm/README.md.
#
# Resource defaults live in config/paths.yaml under `slurm:`; pass them on the
# sbatch command line (or add #SBATCH lines here once you've settled on values).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p slurm/logs

if [[ $# -lt 1 ]]; then
    echo "usage: sbatch slurm/run_stage.sh <script.py> [args...]" >&2
    exit 2
fi

# Read the interpreter straight out of the YAML with sed -- the login node's
# bare python3 has no pyyaml, so parsing the config in Python here would fail
# before the job ever reaches the configured env.
CONDA_PREFIX_CFG=$(sed -n 's/^[[:space:]]*conda_prefix:[[:space:]]*//p' \
    config/paths.yaml | tr -d '"'"'" | head -1)

if [[ -n "$CONDA_PREFIX_CFG" && -x "$CONDA_PREFIX_CFG/bin/python" ]]; then
    PY_BIN="$CONDA_PREFIX_CFG/bin/python"
else
    echo "WARNING: env.conda_prefix in config/paths.yaml is unset or has no" >&2
    echo "         bin/python; falling back to whatever python3 is on PATH." >&2
    PY_BIN="$(command -v python3)"
fi

echo "host     : $(hostname)"
echo "job      : ${SLURM_JOB_ID:-<interactive>}"
echo "python   : $PY_BIN"
echo "command  : $*"
echo "started  : $(date -Is)"
echo

"$PY_BIN" "$@"
rc=$?

echo
echo "finished : $(date -Is)  (exit $rc)"
exit $rc

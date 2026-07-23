#!/bin/bash

#SBATCH --account=reedsweto
#SBATCH --partition=debug
#SBATCH --time=0-00:30:00 # whole pipeline runs in ~3 min; 30 min is ample headroom
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=rebecca.fuchs@nlr.gov
#SBATCH --mail-type=FAIL,END
#SBATCH --mem=16000 # RAM in MB; stage 02 streams the big .pras, peak ~1-2 GB
#SBATCH --job-name=neue_pipeline
#SBATCH --output=logs/slurm-%j.out

# Run the whole NEUE diagnostics pipeline end to end, in order, on one node.
# Use this after swapping input files in config/paths.yaml:
#
#     sbatch slurm/run_all.sh
#
# Each stage writes to cache/ or outputs/ for the next; a failure stops the
# chain (set -e) so you never analyze a half-written cache.
#
#   00 build_registry  -> cache/registry.csv           (reads .h5 attrs)
#   01 extract_eue     -> cache/{nonzero,rollups}/*.csv (reads .h5 EUE)
#   02 extract_features-> cache/features/*.npz          (reads .pras -- the heavy one)
#   03 attribute       -> outputs/tables + figures      (the "why")
#   04 saturation      -> outputs/tables + figures      (DR knee curves)

# Source bashrc / activate conda BEFORE strict mode: the system /etc/bashrc
# references unset variables (BASHRCSOURCED), which `set -u` would treat as a
# fatal error. Turn on fail-fast only once the environment is ready.
. $HOME/.bashrc
conda activate reeds2

set -euo pipefail

cd /projects/reedsweto/bfuchs/Demand_Response/neue_diagnostics
mkdir -p logs

echo "host    : $(hostname)"
echo "started : $(date -Is)"
echo

for stage in \
    scripts/00_build_registry.py \
    scripts/01_extract_eue.py \
    scripts/02_extract_features.py \
    scripts/03_attribute.py \
    scripts/04_saturation.py
do
    echo "=================================================================="
    echo ">>> $stage    $(date -Is)"
    echo "=================================================================="
    python "$stage"
    echo
done

echo "finished: $(date -Is)"

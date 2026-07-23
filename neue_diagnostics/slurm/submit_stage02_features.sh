#!/bin/bash

#SBATCH --account=reedsweto
#SBATCH --partition=standard
#SBATCH --time=0-00:30:00 # walltime; measured ~10 s ERCOT / ~30 s PJM, 30 min is headroom
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=rebecca.fuchs@nlr.gov
#SBATCH --mail-type=FAIL
#SBATCH --mem=16000 # RAM in MB; peak is ~1-2 GB because /generators/capacity
                    # is streamed in 8760-row chunks rather than read whole
#SBATCH --job-name=neue_features
#SBATCH --output=logs/slurm-%j.out

#load your default settings
. $HOME/.bashrc

conda activate reeds2

cd /kfs2/projects/reedsweto/bfuchs/Demand_Response/neue_diagnostics
python scripts/02_extract_features.py

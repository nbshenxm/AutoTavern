#!/usr/bin/env bash
# More pairs for a finished gate, on the cluster's CPUs from $ROOT/gaterules: the same gate under
# another seed (new pairs, pooled with the first by hand); several seeds run side by side. The
# gate keeps each round, so an array with %1 carries it past the 1-hour limit:
#
#   module load slurm/star/21.08.8 && sbatch --array=1-5%1 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/gaterules/scripts/hpc/gate_seed.sh \
#       data/models/archive/act1_end.pt 51000000
#SBATCH --job-name=bg-gate
#SBATCH --nice=10000
#SBATCH --cpus-per-task=64
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/gaterules"
CAND=$1 SEED=$2
echo "$(date '+%F %T') $(hostname): gate $CAND vs best.pt, seed $SEED"
"$PY" -X utf8 -m advisor.gate --rounds 3 --fresh-games 512 --workers 60 --seed "$SEED" --no-recheck \
    "$CAND" data/models/best.pt | tee -a "data/gate/seed_$(basename "$CAND" .pt)_$SEED.log"
echo "$(date '+%F %T') done"

#!/usr/bin/env bash
# A gate between any two checkpoints on the cluster's CPUs (from $ROOT/gaterules): an experiment
# against the mainline at the same iteration, say. The gate keeps each round, so an array with %1
# carries it past the 1-hour limit:
#
#   module load slurm/star/21.08.8 && sbatch --array=1-6%1 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/gate_vs.sh \
#       data/models/archive/comp2_c1301.pt data/models/archive/main1_it1301.pt comp2_c1301_vs_main1
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
CAND=$1 CHAMP=$2 NAME=$3 SEED=${4:-41000000}
echo "$(date '+%F %T') $(hostname): gate $CAND vs $CHAMP, seed $SEED"
"$PY" -X utf8 -m advisor.gate --rounds 3 --fresh-games "${FRESH:-512}" --workers 60 --seed "$SEED" --no-recheck \
    "$CAND" "$CHAMP" | tee -a "data/gate/$NAME.log"
echo "$(date '+%F %T') done"

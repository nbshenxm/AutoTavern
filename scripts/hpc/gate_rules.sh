#!/usr/bin/env bash
# Opening lines on the champion through the gate (advisor.gate --rules), on the cluster's CPUs,
# from its own code folder ($ROOT/gaterules: a running training's repo is never touched; data/
# links to the repo's, the gate only adds its own files there). Fresh games only (the rules act in
# rounds 1-4; your logged starts are mostly later and would only add zero differences). The gate
# keeps each round, so an array with %1 carries it past the 1-hour limit:
#
#   module load slurm/star/21.08.8 && sbatch --array=1-6%1 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/gaterules/scripts/hpc/gate_rules.sh busker,level,nofreeze
#SBATCH --job-name=bg-rules
#SBATCH --nice=10000
#SBATCH --cpus-per-task=64
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/gaterules"
RULES=$1
echo "$(date '+%F %T') $(hostname): gate R3 + rules $RULES vs R3"
"$PY" -X utf8 -m advisor.gate --rounds 4 --fresh-games 1024 --starts 1 --workers 60 --rules "$RULES" \
    data/models/best.pt data/models/best.pt | tee -a "data/gate/rules_${RULES//,/-}_vs_r3.log"
echo "$(date '+%F %T') done"

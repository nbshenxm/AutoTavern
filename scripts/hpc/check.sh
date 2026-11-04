#!/usr/bin/env bash
# A cluster run's check against R3 (as scripts/office/run_checks.sh): its last.pt frozen once as
# data/models/archive/RUN_TAG.pt, then advisor.gate on the CPUs. The gate keeps each round, so an
# array with %1 carries it past the 1-hour limit:
#
#   module load slurm/star/21.08.8 && sbatch --array=1-4%1 --begin=18:25 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/check.sh late1 4h
#SBATCH --job-name=bg-check
#SBATCH --nice=10000
#SBATCH --cpus-per-task=64
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/repo"
RUN=$1
TAG=$2
CK=data/models/archive/${RUN}_${TAG}.pt
mkdir -p data/models/archive data/gate
if [ ! -f "$CK" ]; then
    cp "data/train/$RUN/last.pt" "$CK.tmp" && mv "$CK.tmp" "$CK"
fi
echo "$(date '+%F %T') $(hostname): gate $CK vs data/models/best.pt"
"$PY" -X utf8 -m advisor.gate --rounds 4 --fresh-games 128 --no-recheck --workers 60 \
    "$CK" data/models/best.pt | tee -a "data/gate/${RUN}_${TAG}_vs_r3.log"
echo "$(date '+%F %T') done"

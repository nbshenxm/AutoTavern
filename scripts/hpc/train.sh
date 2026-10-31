#!/usr/bin/env bash
# A training run on the cluster, one GPU, resumed from data/train/$RUN/last.pt (or $START the
# first time). As a job array with %1, each task continues the last:
#
#   module load slurm/star/21.08.8 && sbatch --array=1-4%1 --export=ALL,RUN=solo1,START=data/models/start.pt,HOURS=23 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/train.sh --solo ...
#
#SBATCH --job-name=bg-train
#SBATCH --nice=10000
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --qos=long
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/repo"
RESUME="data/train/$RUN/last.pt"
[ -f "$RESUME" ] || RESUME="$START"
echo "$(date '+%F %T') $(hostname) $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1), $SLURM_CPUS_PER_TASK CPUs: $RUN from $RESUME"
"$PY" -X utf8 -m advisor.train --run "$RUN" --resume "$RESUME" --hours "${HOURS:-23}" \
    --threads "$SLURM_CPUS_PER_TASK" "$@"
echo "$(date '+%F %T') done"

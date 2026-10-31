#!/usr/bin/env bash
# A training run on the cluster, one GPU, resumed from data/train/$RUN/last.pt (or $START the
# first time). As a job array with %1, each task continues the last. QOS normal (its GPUs are
# free; "long" is capped cluster-wide and usually full) allows 1 hour: tasks of 0.9 hours.
# A failed task leaves data/train/$RUN/FAILED and the ones after it stop (the cluster rule).
#
#   module load slurm/star/21.08.8 && sbatch --array=1-48%1 --export=ALL,RUN=solo1,START=data/models/start.pt,HOURS=0.9 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/train.sh --solo ...
#
#SBATCH --job-name=bg-train
#SBATCH --nice=10000
#SBATCH --gres=gpu:1
# The A100 nodes: others queue for the H100s (gpu3-gpu7)
#SBATCH --exclude=gpu[3-7]
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/repo"
mkdir -p "data/train/$RUN"
if [ -f "data/train/$RUN/FAILED" ]; then
    echo "an earlier task failed (data/train/$RUN/FAILED): stopping"
    exit 1
fi
trap 'echo "task $SLURM_ARRAY_TASK_ID failed $(date "+%F %T")" > "data/train/$RUN/FAILED"' ERR
RESUME="data/train/$RUN/last.pt"
[ -f "$RESUME" ] || RESUME="$START"
echo "$(date '+%F %T') $(hostname) $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1), $SLURM_CPUS_PER_TASK CPUs: $RUN from $RESUME"
"$PY" -X utf8 -m advisor.train --run "$RUN" --resume "$RESUME" --hours "${HOURS:-0.9}" \
    --threads "$SLURM_CPUS_PER_TASK" "$@"
echo "$(date '+%F %T') done"

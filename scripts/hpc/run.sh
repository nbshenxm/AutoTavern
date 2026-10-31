#!/usr/bin/env bash
# Any advisor module as a CPU-only cluster job (no GPU), in $ROOT/repo with the job environment:
#
#   module load slurm/star/21.08.8 && sbatch /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/run.sh \
#       advisor.teacher_test data/models/best.pt --workers 60 --from-round 10
#
# QOS normal allows 1 hour; a resumable job (teacher_test --out) can run as an array with %1.
#SBATCH --job-name=bg-run
#SBATCH --nice=10000
#SBATCH --cpus-per-task=64
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/repo"
echo "$(date '+%F %T') $(hostname), $SLURM_CPUS_PER_TASK CPUs: $*"
"$PY" -X utf8 -m "$@"
echo "$(date '+%F %T') done"

#!/usr/bin/env bash
# Apply a staged update once the running training is over (a running run is never changed: its
# hourly tasks reload the code and the library). scripts/hpc/sync.sh --stage puts code.tar,
# data.tar and a wheel in $ROOT/staging; this job, queued after the run, unpacks them into
# $ROOT/repo as sync.sh would and installs the wheel.
#
#   module load slurm/star/21.08.8 && sbatch --dependency=afterany:RUNJOB \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/stage_apply.sh
#
#SBATCH --job-name=bg-stage
#SBATCH --nice=10000
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%j.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
S="$ROOT/staging"
cd "$ROOT"
tar -xf "$S/code.tar" -C repo
tar -xf "$S/data.tar" -C repo
rm -rf repo/python/taverngym
cp "$S/SYNCED" repo/SYNCED
if ls "$S"/taverngym-*.whl > /dev/null 2>&1; then
    cp "$S"/taverngym-*.whl wheels/
    "$PY" -m pip install --force-reinstall --no-deps "$S"/taverngym-*.whl
fi
"$PY" -c "import taverngym; print('taverngym', dict(taverngym.layout())['OBS_VERSION'])"
cat repo/SYNCED
rm -rf "$S"

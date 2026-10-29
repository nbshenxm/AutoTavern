#!/usr/bin/env bash
# Hourly on the office machine (user crontab): gate every run's best checkpoint and promote a
# clearly better one to data/models/best.pt (advisor.promote); the home PC copies that file
# (scripts/sync_model.ps1). Output: data/models/promote.log.
set -euo pipefail
REPO=${REPO:-$HOME/autotavern}
CONDA=$(command -v conda || true)
for c in "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda"; do
    [ -z "$CONDA" ] && [ -x "$c" ] && CONDA=$c
done
PY=$(dirname "$(dirname "$CONDA")")/envs/taverngym/bin/python
cd "$REPO"
mkdir -p data/models
exec 9> data/models/promote.lock
flock -n 9 || exit 0  # the previous hour's gate is still running
nice -n 10 "$PY" -X utf8 -m advisor.promote data/train/*/best.pt >> data/models/promote.log 2>&1

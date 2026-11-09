#!/usr/bin/env bash
# Start (or continue) a PPO run on the office machine, detached; output in data/train/RUN.
#   ssh office "RUN=office2 HOURS=12 THREADS=20 EXTRA='--arch entity' bash -s" < scripts/office/train.sh
# EXTRA: more advisor.train options (a new run's --arch, --lr, --ent, --games...). Since
# 2026-10-29 the office was this track's alone; since Nov 8 it is shared: BG on CPUs 0-11, the constructed track on 12-23;
# check `nvidia-smi` for anything else running first.
set -euo pipefail
REPO=${REPO:-$HOME/autotavern}
RUN=${RUN:-office1}
HOURS=${HOURS:-4}
THREADS=${THREADS:-8}
CONDA=$(command -v conda || true)
for c in "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda"; do
    [ -z "$CONDA" ] && [ -x "$c" ] && CONDA=$c
done
PY=$("$CONDA" run -n taverngym which python)
cd "$REPO"
RESUME=""
[ -f "data/train/$RUN/last.pt" ] && RESUME="--resume data/train/$RUN/last.pt"
mkdir -p "data/train/$RUN"
# nice: whatever else runs on the box (a desktop session) keeps priority
# CPUs 0-11 only (Nov 8: the constructed track uses 12-23 on this box; BG_CPUS overrides)
setsid nohup taskset -c "${BG_CPUS:-0-11}" nice -n 10 "$PY" -X utf8 -m advisor.train --run "$RUN" --hours "$HOURS" --threads "$THREADS" $RESUME ${EXTRA:-} \
    >> "data/train/$RUN/stdout.log" 2>&1 < /dev/null &
echo "started $RUN (pid $!)"

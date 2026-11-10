#!/usr/bin/env bash
# Start (or continue) a PPO run on the office machine, detached; output in data/train/RUN.
#   ssh office "RUN=office2 HOURS=12 THREADS=20 EXTRA='--arch entity' bash -s" < scripts/office/train.sh
# EXTRA: more advisor.train options (a new run's --arch, --lr, --ent, --games...). Since
# 2026-10-29 the office was this track's alone; since Nov 8 it is shared: BG on CPUs 0-11 (0-7 from Nov 12 20:00: bg_cpus.sh), the constructed track on the rest;
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
. "$REPO/scripts/office/bg_cpus.sh"  # (by path: this script also runs as "bash -s" < train.sh)
# never more training threads than BG has CPUs
[ "$THREADS" -gt "$BG_NCPU" ] && THREADS=$BG_NCPU
cd "$REPO"
RESUME=""
[ -f "data/train/$RUN/last.pt" ] && RESUME="--resume data/train/$RUN/last.pt"
mkdir -p "data/train/$RUN"
# nice: whatever else runs on the box (a desktop session) keeps priority
# BG's CPUs only (bg_cpus.sh: the office is shared with the constructed track; BG_CPUS overrides)
setsid nohup taskset -c "$BG_CPUS" nice -n 10 "$PY" -X utf8 -m advisor.train --run "$RUN" --hours "$HOURS" --threads "$THREADS" $RESUME ${EXTRA:-} \
    >> "data/train/$RUN/stdout.log" 2>&1 < /dev/null &
echo "started $RUN (pid $!)"

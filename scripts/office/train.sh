#!/usr/bin/env bash
# Start (or continue) a PPO run on the office machine, detached; output in data/train/RUN.
#   ssh office 'bash -s' < scripts/office/train.sh            # RUN=office1 HOURS=4 THREADS=8
# The constructed track's PPO service shares this GPU and CPU: keep THREADS modest and check
# `nvidia-smi` and `systemctl --user status hsadvisor-ppo` first.
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
# nice: the constructed track's PPO service keeps priority on the shared CPU
setsid nohup nice -n 10 "$PY" -X utf8 -m advisor.train --run "$RUN" --hours "$HOURS" --threads "$THREADS" $RESUME \
    >> "data/train/$RUN/stdout.log" 2>&1 < /dev/null &
echo "started $RUN (pid $!)"

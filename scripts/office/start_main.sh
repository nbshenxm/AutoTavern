#!/usr/bin/env bash
# The mainline (docs/TRAINING_PLAN.md): once AFTER has ended, the office's code and TavernGym
# updated (the simulator's fixes go in at the mainline's start, not into a running run), then
# RUN from data/models/best.pt with the fixed setup FLAGS, listed in data/overnight.conf (the
# supervisor restarts it), and its checks (run_checks.sh: the gate and the engine exam at +4 h).
#   setsid nohup bash scripts/office/start_main.sh AFTER "AFTER_END" RUN "RUN_END" "FLAGS" > /dev/null 2>&1 &
# (a script file: its command line doesn't hold the pattern it waits on)
AFTER=$1; AFTER_END=$2; RUN=$3; END=$4; FLAGS=$5
cd ~/autotavern
LOG=data/gate/${RUN}_checks.log
say() { echo "$(date +%F_%H:%M) $*" >> $LOG; }
until [ "$(date +%s)" -ge "$(date -d "$AFTER_END" +%s)" ]; do sleep 120; done
while pgrep -f "advisor.train --run $AFTER " > /dev/null; do sleep 60; done
sed -i "s/^$AFTER|/#$AFTER|/" data/overnight.conf
# AFTER's end checks start within two minutes and load the module first
sleep 300
say "updating the code and TavernGym"
git pull -q >> $LOG 2>&1
env -u VIRTUAL_ENV CONDA_PREFIX=$HOME/anaconda3/envs/taverngym PATH=$HOME/.cargo/bin:$HOME/anaconda3/envs/taverngym/bin:$PATH \
    nice -n 10 maturin develop --release >> $LOG 2>&1
say "TavernGym $(git log --oneline -1 | cut -c1-60): build exit $?"
mkdir -p data/train/$RUN
[ -f data/train/$RUN/last.pt ] || cp data/models/best.pt data/train/$RUN/last.pt
echo "$RUN|$END|10|$FLAGS" >> data/overnight.conf
say "start $RUN from $(md5sum data/train/$RUN/last.pt | cut -c1-8)"
HOURS=$(awk "BEGIN { printf \"%.2f\", ($(date -d "$END" +%s) - $(date +%s)) / 3600 }")
RUN=$RUN HOURS=$HOURS THREADS=10 EXTRA="$FLAGS" bash scripts/office/train.sh >> $LOG 2>&1
exec bash scripts/office/run_checks.sh "$RUN" "$END"

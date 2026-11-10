#!/usr/bin/env bash
# The checks of a run against R3: at +4 h and at its end, the gate and the engine exam.
#   setsid nohup bash data/gate/run_checks.sh RUN "END" > /dev/null 2>&1 &
# (a script file: its command line doesn't hold the pattern it waits on, unlike a bash -c)
RUN=$1
END=$2  # the run's planned end (a supervisor restart in between isn't its end)
cd ~/autotavern
. scripts/office/bg_cpus.sh
PY=~/anaconda3/envs/taverngym/bin/python
LOG=data/gate/${RUN}_checks.log
say() { echo "$(date +%F_%H:%M) $*" >> $LOG; }
check() {
    local tag=$1
    cp data/train/$RUN/last.pt data/models/archive/${RUN}_${tag}.tmp && mv data/models/archive/${RUN}_${tag}.tmp data/models/archive/${RUN}_${tag}.pt
    say "gate ${RUN}_${tag}"
    taskset -c "$BG_CPUS" nice -n 10 $PY -X utf8 -m advisor.gate --rounds 4 --fresh-games 128 --no-recheck --threads 6 \
        data/models/archive/${RUN}_${tag}.pt data/models/best.pt > data/gate/${RUN}_${tag}_vs_r3.log 2>&1
    say "gate ${RUN}_${tag}: $(tail -1 data/gate/${RUN}_${tag}_vs_r3.log | cut -c1-240)"
    PYTHONUTF8=1 taskset -c "$BG_CPUS" nice -n 15 $PY -X utf8 -m advisor.engine_exam data/models/archive/${RUN}_${tag}.pt --against data/models/best.pt \
        --out data/replay/engine_exam_${RUN}_${tag}.json > data/replay/engine_exam_${RUN}_${tag}.out 2>&1
    say "engine exam ${RUN}_${tag}: $(grep paired data/replay/engine_exam_${RUN}_${tag}.out)"
}
say "waiting 4 h"
sleep 14400
check 4h
until [ "$(date +%s)" -ge "$(date -d "$END" +%s)" ]; do sleep 120; done
while pgrep -f "advisor.train --run $RUN " > /dev/null; do sleep 120; done
check end

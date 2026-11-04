#!/usr/bin/env bash
# Start a training run once another has ended (its planned END passed and its process gone),
# then its checks (run_checks.sh). One-off queueing on the office's one GPU:
#   setsid nohup bash scripts/office/start_after.sh AFTER "AFTER_END" RUN "RUN_END" "FLAGS" > /dev/null 2>&1 &
# RUN starts from data/models/best.pt (R3) and is added to data/overnight.conf.
AFTER=$1; AFTER_END=$2; RUN=$3; END=$4; FLAGS=$5
cd ~/autotavern
until [ "$(date +%s)" -ge "$(date -d "$AFTER_END" +%s)" ]; do sleep 120; done
while pgrep -f "advisor.train --run $AFTER " > /dev/null; do sleep 60; done
mkdir -p data/train/$RUN
[ -f data/train/$RUN/last.pt ] || cp data/models/best.pt data/train/$RUN/last.pt
echo "$RUN|$END|10|$FLAGS" >> data/overnight.conf
HOURS=$(awk "BEGIN { printf \"%.2f\", ($(date -d "$END" +%s) - $(date +%s)) / 3600 }")
RUN=$RUN HOURS=$HOURS THREADS=10 EXTRA="$FLAGS" bash scripts/office/train.sh >> data/gate/${RUN}_checks.log 2>&1
exec bash scripts/office/run_checks.sh "$RUN" "$END"

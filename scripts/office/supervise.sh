#!/usr/bin/env bash
# Every 20 minutes on the office machine (user crontab): keep the planned training runs going
# while nobody watches. data/overnight.conf lists them, one per line:
#   RUN|END (date -d format)|THREADS|EXTRA (advisor.train options, without --resume)
# A run that has started (it has a last.pt) and is not running, or has logged nothing for 30
# minutes (hung), before its END is restarted from its last.pt (scripts/office/train.sh) with
# the hours left. A run not started yet is left alone (a waiter may start it).
# Output: data/supervise.log.
set -u
REPO=${REPO:-$HOME/autotavern}
cd "$REPO"
CONF=data/overnight.conf
[ -f "$CONF" ] || exit 0
now=$(date +%s)
while IFS='|' read -r run end threads extra; do
    [[ -z "$run" || "$run" == \#* ]] && continue
    left=$(( $(date -d "$end" +%s) - now ))
    [ "$left" -lt 900 ] && continue
    [ -f "data/train/$run/last.pt" ] || continue
    pid=$(pgrep -f -- "-m advisor.train --run $run " | head -1)
    if [ -n "$pid" ]; then
        age=$(( now - $(stat -c %Y "data/train/$run/log.jsonl") ))
        [ "$age" -lt 1800 ] && continue
        echo "$(date +%F_%H:%M) $run: no log for ${age}s, restarting (pid $pid)"
        kill "$pid"; sleep 15; kill -9 "$pid" 2>/dev/null
    else
        echo "$(date +%F_%H:%M) $run: not running, restarting; its last words:"
        tail -2 "data/train/$run/stdout.log" | cut -c1-200
    fi
    RUN=$run HOURS=$(awk "BEGIN { printf \"%.2f\", $left / 3600 }") THREADS=$threads EXTRA="$extra" \
        bash scripts/office/train.sh
done < "$CONF"

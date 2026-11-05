#!/usr/bin/env bash
# Keeps a run's checkpoint every 100 iterations (data/train/RUN/snap/it<N>.pt), so an experiment
# that branched from the mainline can be gated against it at the same iteration. Cron, every 2 min:
#   */2 * * * * /bin/bash $HOME/autotavern/scripts/office/snapshot.sh main1
set -eo pipefail
RUN=${1:-main1}
D=$HOME/autotavern/data/train/$RUN
[ -f "$D/last.pt" ] || exit 0
it=$(grep '"collect_s"' "$D/log.jsonl" | tail -1 | sed 's/.*"iteration": \([0-9]*\).*/\1/')
[ -n "$it" ] || exit 0
mkdir -p "$D/snap"
last=$(ls "$D/snap" 2>/dev/null | sed -n 's/^it\([0-9]*\)\.pt$/\1/p' | sort -n | tail -1)
if [ -z "$last" ] || [ $((it / 100)) -gt $((last / 100)) ]; then
    cp "$D/last.pt" "$D/snap/it$it.pt.tmp" && mv "$D/snap/it$it.pt.tmp" "$D/snap/it$it.pt"
    echo "$(date '+%F %T') $RUN it $it"
fi

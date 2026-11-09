#!/usr/bin/env bash
# The audit after a gate verdict (advisor.post_audit and its exams) on the office machine: the
# cluster's scripts/hpc/post_audit.sh, sized for BG's office share (CPUs 0-11, beside a training
# run, at nice 15; Nov 9: the cluster is for big GPU work only). Each step is skipped once its
# output exists, so a rerun resumes. From a checkout that nothing trains from (~/at_check):
#
#   cd ~/at_check && setsid nohup bash scripts/office/post_audit.sh CAND CTRL NAME > /dev/null 2>&1 &
#
# Output in data/audit/NAME (log.txt: the steps' times).
set -eo pipefail
CAND=$1 CTRL=$2 NAME=$3
PY=${PY:-$HOME/anaconda3/envs/taverngym/bin/python}
D="data/audit/$NAME"
mkdir -p "$D"
run() { taskset -c "${BG_CPUS:-0-11}" nice -n 15 env PYTHONUTF8=1 OMP_NUM_THREADS=1 "$PY" -X utf8 -m "$@"; }
say() { echo "$(date '+%F %T') $*" >> "$D/log.txt"; }
say "audit $NAME: $CAND against $CTRL"
[ -f "$D/report.md" ] || run advisor.post_audit "$CAND" "$CTRL" --name "$NAME" --fresh "${FRESH:-128}" \
    --workers "${WORKERS:-6}" > "$D/post_audit.txt" 2>&1
say "post_audit done"
[ -f "$D/mid_exam.json" ] || run advisor.mid_exam "$CAND" --against "$CTRL" --out "$D/mid_exam.json" > "$D/mid_exam.txt" 2>&1
say "mid_exam done"
[ -f "$D/engine_exam.json" ] || run advisor.engine_exam "$CAND" --against "$CTRL" --out "$D/engine_exam.json" \
    > "$D/engine_exam.txt" 2>&1
say "engine_exam done"
for who in cand ctrl; do
    NET=$CAND; [ $who = ctrl ] && NET=$CTRL
    [ -f "$D/habits_late_$who.json" ] || run advisor.compare_play "$NET" --json "$D/habits_late_$who.json" \
        > "$D/habits_late_$who.txt" 2>&1
    [ -f "$D/habits_early_$who.json" ] || run advisor.compare_play "$NET" --early --json "$D/habits_early_$who.json" \
        > "$D/habits_early_$who.txt" 2>&1
    [ -f "$D/buys_$who.json" ] || run advisor.buy_audit "$NET" --out "$D/buys_$who.json" > "$D/buys_$who.txt" 2>&1
    [ -f "$D/value_mid_$who.json" ] || run advisor.value_probe "$NET" --rounds 5 8 --out "$D/value_mid_$who.json" \
        > "$D/value_mid_$who.txt" 2>&1
    say "habits, buys, value probe: $who done"
done
touch "$D/DONE"
say "done"

#!/usr/bin/env bash
# The audit after a gate verdict (advisor.post_audit), on the cluster's CPUs: candidate against its
# control on the gate's games, then the exams paired (mid_exam, engine_exam) and the habits next to
# yours (compare_play, early and late) and their buys and sells where you built (buy_audit), all into
# data/audit/NAME. Each step is skipped once its
# output exists and the games resume chunk by chunk, so an array with %1 carries it past the 1-hour
# limit:
#
#   module load slurm/star/21.08.8 && sbatch --array=1-4%1 \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/post_audit.sh \
#       data/models/archive/comp2_end.pt data/models/archive/main1_it1700.pt comp2_end
#SBATCH --job-name=bg-audit
#SBATCH --nice=10000
#SBATCH --cpus-per-task=64
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%A_%a.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/repo"
CAND=$1 CTRL=$2 NAME=$3
D="data/audit/$NAME"
mkdir -p "$D"
echo "$(date '+%F %T') $(hostname): audit $NAME: $CAND against $CTRL"
[ -f "$D/report.md" ] || "$PY" -X utf8 -m advisor.post_audit "$CAND" "$CTRL" --name "$NAME" --workers 60
[ -f "$D/mid_exam.json" ] || "$PY" -X utf8 -m advisor.mid_exam "$CAND" --against "$CTRL" --out "$D/mid_exam.json" \
    > "$D/mid_exam.txt" 2>&1
[ -f "$D/engine_exam.json" ] || "$PY" -X utf8 -m advisor.engine_exam "$CAND" --against "$CTRL" --out "$D/engine_exam.json" \
    > "$D/engine_exam.txt" 2>&1
for who in cand ctrl; do
    NET=$CAND; [ $who = ctrl ] && NET=$CTRL
    [ -f "$D/habits_late_$who.json" ] || "$PY" -X utf8 -m advisor.compare_play "$NET" --json "$D/habits_late_$who.json" \
        > "$D/habits_late_$who.txt" 2>&1
    [ -f "$D/habits_early_$who.json" ] || "$PY" -X utf8 -m advisor.compare_play "$NET" --early --json "$D/habits_early_$who.json" \
        > "$D/habits_early_$who.txt" 2>&1
done
for who in cand ctrl; do
    NET=$CAND; [ $who = ctrl ] && NET=$CTRL
    [ -f "$D/buys_$who.json" ] || "$PY" -X utf8 -m advisor.buy_audit "$NET" --out "$D/buys_$who.json" > "$D/buys_$who.txt" 2>&1
done
touch "$D/DONE"
echo "$(date '+%F %T') done"

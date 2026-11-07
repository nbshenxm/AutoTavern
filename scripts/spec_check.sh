#!/usr/bin/env bash
# At home (Git Bash): a specialist (spec1, trained from your rounds 6+ positions of the training
# games) against main1 at about the same iteration, on the held-out games' rounds 6+ only
# (BG_SPLIT=test BG_ROUNDS="6 19"; docs/TRAINING_PLAN.md, spec1's bar):
#   1. spec1's last.pt on the cluster kept as data/models/archive/spec1_itN.pt
#   2. main1's office snapshot nearest N (data/train/main1/snap, every 100) sent to the cluster
#   3. the gate (gate_vs.sh, from gaterules, refreshed from repo first) and the post-evaluation
#      audit (post_audit.sh: the audit, mid and engine exams, buys, the mid-game value probe), with
#      64 fresh games only (the specialist doesn't play rounds 1-5 at advice time)
#   scripts/spec_check.sh [RUN]
set -eo pipefail
RUN=${1:-spec1}
R=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG
N=$(ssh star "grep '\"collect_s\"' $R/repo/data/train/$RUN/log.jsonl | tail -1" 2>/dev/null | sed 's/.*"iteration": \([0-9]*\).*/\1/')
[ -n "$N" ] || { echo "no iteration for $RUN"; exit 1; }
ssh star "cp $R/repo/data/train/$RUN/last.pt $R/repo/data/models/archive/${RUN}_it$N.pt" 2>/dev/null
M=$(ssh office "ls ~/autotavern/data/train/main1/snap/" 2>/dev/null | sed -n 's/^it\([0-9]*\)\.pt$/\1/p' \
    | awk -v n="$N" '{d = $1 - n; if (d < 0) d = -d; if (best == "" || d < bd) {best = $1; bd = d}} END {print best}')
[ -n "$M" ] || { echo "no main1 snapshot"; exit 1; }
TMP="${TMPDIR:-/tmp}/spec_check"; mkdir -p "$TMP"
scp -q office:autotavern/data/train/main1/snap/it$M.pt "$TMP/main1_it$M.pt"
scp -q "$TMP/main1_it$M.pt" star:$R/repo/data/models/archive/main1_it$M.pt
rm -f "$TMP/main1_it$M.pt"
NAME=${RUN}_it${N}_vs_main1_it$M
echo "$RUN it $N against main1 it $M: $NAME"
ssh star "set -e; module load slurm/star/21.08.8 >/dev/null 2>&1
mkdir -p $R/gaterules/data/models/archive
for f in ${RUN}_it$N.pt main1_it$M.pt; do [ $R/repo/data/models/archive/\$f -ef $R/gaterules/data/models/archive/\$f ] || cp $R/repo/data/models/archive/\$f $R/gaterules/data/models/archive/; done
cp -r $R/repo/advisor $R/repo/scripts $R/gaterules/
export BG_SPLIT=test BG_ROUNDS='6 19' FRESH=64
sbatch --array=1-6%1 $R/repo/scripts/hpc/gate_vs.sh data/models/archive/${RUN}_it$N.pt data/models/archive/main1_it$M.pt $NAME
sbatch --array=1-4%1 $R/repo/scripts/hpc/post_audit.sh data/models/archive/${RUN}_it$N.pt data/models/archive/main1_it$M.pt $NAME" 2>/dev/null | grep -v '^\*\*'

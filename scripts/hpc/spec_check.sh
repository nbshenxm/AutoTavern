#!/usr/bin/env bash
# scripts/spec_check.sh without the home PC: run on the cluster once main1's snapshot
# data/models/archive/main1_itM.pt is there (sent from the office through home beforehand). Waits
# until RUN's log reaches iteration M, keeps RUN's last.pt as data/models/archive/RUN_itN.pt, then
# queues the gate (gate_vs.sh, from gaterules refreshed from repo) and the post-evaluation audit
# (post_audit.sh) on the held-out games' rounds 6+ (BG_SPLIT=test BG_ROUNDS="6 19", 64 fresh games):
#
#   module load slurm/star/21.08.8 && sbatch --begin=now+20minutes \
#       /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/spec_check.sh spec1 2601
#SBATCH --job-name=bg-speccheck
#SBATCH --nice=10000
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=01:00:00
#SBATCH --qos=normal
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%j.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
cd "$ROOT/repo"
RUN=$1 M=$2
A=data/models/archive
[ -f "$A/main1_it$M.pt" ] || { echo "no $A/main1_it$M.pt"; exit 1; }
iter() { grep '"collect_s"' "data/train/$RUN/log.jsonl" | tail -1 | sed 's/.*"iteration": \([0-9]*\).*/\1/'; }
for i in $(seq 1 55); do
    N=$(iter)
    [ "${N:-0}" -ge "$M" ] && break
    sleep 60
done
[ "${N:-0}" -ge "$M" ] || { echo "$RUN still at $N"; exit 1; }
cp "data/train/$RUN/last.pt" "$A/${RUN}_it$N.pt"
NAME=${RUN}_it${N}_vs_main1_it$M
echo "$(date '+%F %T') $RUN it $N against main1 it $M: $NAME"
mkdir -p "$ROOT/gaterules/$A"
for f in "$A/${RUN}_it$N.pt" "$A/main1_it$M.pt"; do  # gaterules' archive may be the same folder (a link)
    [ "$f" -ef "$ROOT/gaterules/$f" ] || cp "$f" "$ROOT/gaterules/$f"
done
cp -r advisor scripts "$ROOT/gaterules/"
export BG_SPLIT=test BG_ROUNDS="6 19" FRESH=64
sbatch --array=1-6%1 "$ROOT/repo/scripts/hpc/gate_vs.sh" "$A/${RUN}_it$N.pt" "$A/main1_it$M.pt" "$NAME"
sbatch --array=1-4%1 "$ROOT/repo/scripts/hpc/post_audit.sh" "$A/${RUN}_it$N.pt" "$A/main1_it$M.pt" "$NAME"
echo "$(date '+%F %T') queued"

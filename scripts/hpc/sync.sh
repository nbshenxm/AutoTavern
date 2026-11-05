#!/usr/bin/env bash
# At home (Git Bash): the committed code to the cluster's $ROOT/repo, and the data a run reads
# (data/meta, data/library, data/models, the held-out human choices, your replay decisions and combats for the exams); `--wheel FILE` also sends
# TavernGym's manylinux wheel (built on the office: maturin build --release --zig
# --compatibility manylinux_2_28). Only inside $ROOT. The repo's python/taverngym (source, no
# compiled module) is removed there: the wheel installs the package and it would shadow it.
set -eo pipefail
cd "$(dirname "$0")/../.."
ROOT=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG
OUT="${TMPDIR:-/tmp}/bg_code"
mkdir -p "$OUT"
git archive --format=tar HEAD > "$OUT/code.tar"
tar --force-local -cf "$OUT/data.tar" data/meta data/library data/models data/search/human_eval data/replay/decisions.jsonl data/replay/combats.jsonl $(ls -d data/search/human_late data/search/human_late_eval data/search/human_mid data/search/human_mid_eval 2>/dev/null)
ssh star "mkdir -p $ROOT/repo $ROOT/wheels $ROOT/logs"
# --stage [WHEEL]: everything to $ROOT/staging for scripts/hpc/stage_apply.sh, queued after the
# running training (which must not change under it)
if [ "$1" = "--stage" ]; then
    ssh star "rm -rf $ROOT/staging && mkdir -p $ROOT/staging"
    scp -q "$OUT/code.tar" "$OUT/data.tar" star:$ROOT/staging/
    if [ -n "$2" ]; then scp -q "$2" star:$ROOT/staging/; fi
    ssh star "echo code=$(git rev-parse --short HEAD) > $ROOT/staging/SYNCED && ls $ROOT/staging"
    exit 0
fi
scp -q "$OUT/code.tar" "$OUT/data.tar" star:$ROOT/
if [ "$1" = "--wheel" ]; then scp -q "$2" star:$ROOT/wheels/; fi
ssh star "cd $ROOT && tar -xf code.tar -C repo && tar -xf data.tar -C repo && rm code.tar data.tar && rm -rf repo/python/taverngym && echo code=$(git rev-parse --short HEAD) > repo/SYNCED && cat repo/SYNCED"

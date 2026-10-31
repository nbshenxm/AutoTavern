#!/usr/bin/env bash
# At home (Git Bash): the committed code to the cluster's $ROOT/repo, and the data a run reads
# (data/meta, data/library, data/models, the held-out human choices); `--wheel FILE` also sends
# TavernGym's manylinux wheel (built on the office: maturin build --release --zig
# --compatibility manylinux_2_28). Only inside $ROOT.
set -eo pipefail
cd "$(dirname "$0")/../.."
ROOT=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG
OUT="${TMPDIR:-/tmp}/bg_code"
mkdir -p "$OUT"
git archive --format=tar HEAD > "$OUT/code.tar"
tar --force-local -cf "$OUT/data.tar" data/meta data/library data/models data/search/human_eval
ssh star "mkdir -p $ROOT/repo $ROOT/wheels $ROOT/logs"
scp -q "$OUT/code.tar" "$OUT/data.tar" star:$ROOT/
if [ "$1" = "--wheel" ]; then scp -q "$2" star:$ROOT/wheels/; fi
ssh star "cd $ROOT && tar -xf code.tar -C repo && tar -xf data.tar -C repo && rm code.tar data.tar && echo code=$(git rev-parse --short HEAD) > repo/SYNCED && cat repo/SYNCED"

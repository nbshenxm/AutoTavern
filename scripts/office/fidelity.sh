#!/usr/bin/env bash
# The simulator check (advisor.fidelity) on the office, started detached by the home sync after
# a game (scripts/sync_model.ps1: the check outgrew the home task's 30 minutes). Its output in
# data/replay/fidelity.out, its exit code in data/replay/fidelity.exit (1: a regression), which
# a later sync collects. Bob's Buddy's part needs the home harness: skipped here.
REPO=${REPO:-$HOME/autotavern}
cd "$REPO"
source "$HOME/anaconda3/etc/profile.d/conda.sh"
conda activate taverngym
nice -n 15 python -X utf8 -m advisor.fidelity --no-bb > data/replay/fidelity.out 2>&1
echo $? > data/replay/fidelity.exit

#!/usr/bin/env bash
# For the home progress page (scripts/sync_model.ps1, advisor.report): print the advisor jobs that
# run here and pack every training run's log into /tmp/bgprogress.tgz.
cd "${REPO:-$HOME/autotavern}"
pgrep -af "^[^ ]*python -X utf8 -m advisor" || true
tar czf /tmp/bgprogress.tgz data/train/*/log.jsonl

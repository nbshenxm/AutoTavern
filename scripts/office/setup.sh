#!/usr/bin/env bash
# One-time setup of the Battlegrounds track on the office machine (Ubuntu, user hofstra):
# a clone of the fork, Rust via rustup (user install, no sudo), a conda env `taverngym` with the
# TavernGym bindings and torch. Re-running it updates the clone and rebuilds.
#   ssh office 'bash -s' < scripts/office/setup.sh
set -euo pipefail
REPO=${REPO:-$HOME/autotavern}
BRANCH=${BRANCH:-bg/client-diff-replay}

if [ ! -d "$REPO/.git" ]; then
    git clone --branch "$BRANCH" https://github.com/nbshenxm/AutoTavern.git "$REPO"
else
    git -C "$REPO" fetch origin && git -C "$REPO" checkout "$BRANCH" && git -C "$REPO" pull --ff-only
fi

if ! command -v cargo >/dev/null 2>&1 && [ ! -x "$HOME/.cargo/bin/cargo" ]; then
    curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain none
fi
export PATH="$HOME/.cargo/bin:$PATH"

CONDA=$(command -v conda || echo "$HOME/miniforge3/bin/conda")
if ! "$CONDA" env list | grep -q '^taverngym '; then
    "$CONDA" create -y -n taverngym --override-channels -c conda-forge python=3.12 numpy pytest maturin
fi
PY=$("$CONDA" run -n taverngym which python)
"$PY" -m pip install -q torch hslog hearthstone
cd "$REPO"
VIRTUAL_ENV= CONDA_PREFIX=$("$CONDA" run -n taverngym python -c 'import sys; print(sys.prefix)') \
    "$CONDA" run -n taverngym maturin develop --release
"$PY" -c "import taverngym, torch; print('taverngym', taverngym.__version__ if hasattr(taverngym, '__version__') else 'ok', 'cuda', torch.cuda.is_available())"

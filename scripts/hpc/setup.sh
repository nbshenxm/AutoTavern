#!/usr/bin/env bash
# One-time setup on the school cluster: the Python env inside our folder (conda-forge Python 3.12,
# PyTorch and numpy from pip) and TavernGym from the manylinux wheel built on the office (no Rust
# here). Then the training tests.
#
#   module load slurm/star/21.08.8 && sbatch /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/setup.sh
#
#SBATCH --job-name=bg-setup
#SBATCH --nice=10000
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --qos=burst
#SBATCH --output=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/logs/%x-%j.out
set -eo pipefail
source /fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo/scripts/hpc/env.sh
if [ ! -x "$ROOT/env/bin/python" ]; then
    conda create -y -p "$ROOT/env" -c conda-forge --override-channels python=3.12
fi
"$PY" -m pip install torch==2.14.1 numpy pytest
"$PY" -m pip install --force-reinstall --no-deps "$ROOT"/wheels/taverngym-*.whl
"$PY" -c "import torch, taverngym; L = dict(taverngym.layout()); print('torch', torch.__version__, 'cuda', torch.version.cuda, 'obs', L['OBS_VERSION'])"
rm -rf "$ROOT/.pip-cache"/* "$ROOT/.conda-pkgs"/*
cd "$ROOT/repo"
"$PY" -m pytest -q tests/test_train.py 2>&1 | tail -3

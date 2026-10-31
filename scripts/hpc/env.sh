# Sourced by every cluster job (`ssh star`): modules, and HOME, temp and every cache inside the
# project folder. The rule: everything in $ROOT, nothing outside it.
ROOT=/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG
mkdir -p "$ROOT/home" "$ROOT/logs" "$ROOT/tmp" "$ROOT/.conda-pkgs" "$ROOT/.pip-cache"
export HOME="$ROOT/home" TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp"
export XDG_CACHE_HOME="$ROOT/home/.cache" XDG_CONFIG_HOME="$ROOT/home/.config" XDG_DATA_HOME="$ROOT/home/.local/share"
export TORCH_HOME="$ROOT/home/.cache/torch" TRITON_CACHE_DIR="$ROOT/home/.cache/triton"
# A batch job isn't a login shell: the module command from the system's setup if missing
type module >/dev/null 2>&1 || source /etc/profile.d/modules.sh
module load miniforge3 2>/dev/null || module load miniforge3/24.3.0-0-gcc-8.5.0-hpjwygs
module load slurm/star/21.08.8 2>/dev/null
export CONDA_PKGS_DIRS="$ROOT/.conda-pkgs" CONDA_ENVS_PATH="$ROOT"
export PIP_CACHE_DIR="$ROOT/.pip-cache"
export PATH="$ROOT/env/bin:$PATH" PY="$ROOT/env/bin/python" PYTHONUNBUFFERED=1 PYTHONUTF8=1

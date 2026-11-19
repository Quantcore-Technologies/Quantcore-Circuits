#!/usr/bin/env bash
# Install quantcore-circuits and its dependencies on a Linux (or Git-Bash / macOS) PC, then test the install.
#
# pip cannot run tests while it installs, so this script is the "tests during install":
#   1. creates (or reuses) the conda env (default `qcc`, Python 3.11)
#   2. installs torch (CPU build), the pinned PyPI packages (requirements/sim-pc.txt), the five upstream snapshots from
#      the wheelhouse and quantcore-circuits[all]
#   3. runs `qcc selftest` (imports, a Q1 + R1 chip: build, DRC, LOM, job export, ansysedt lookup)
#   4. runs `pytest -m "not slow"` when run from a repository checkout (tests/ next to this script's folder)
# It stops at the first failure with a message. It never starts AEDT and runs no solver.
#
# The wheelhouse (dist/wheelhouse/*.whl) is built on the design PC with `python scripts/build_wheelhouse.py` and is not
# in git (dist/ is git-ignored): copy the folder to this PC, or set WHEELHOUSE. Packages other than the six wheels
# (numpy, tqdm, pandas, ...) come from PyPI, so this PC needs internet access for pip.
#
#   bash scripts/install_sim_pc.sh
#   QCC_ENV=qcc WHEELHOUSE=/path/to/wheelhouse SKIP_TORCH=1 SKIP_TESTS=1 bash scripts/install_sim_pc.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${QCC_ENV:-qcc}"
TORCH_VERSION="2.15.0"

fail() { printf '\nINSTALL STOPPED: %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

# ---- the wheelhouse and the requirements ---------------------------------------------------------------------
WH="${WHEELHOUSE:-}"
if [ -z "$WH" ]; then
  for c in "$ROOT/dist/wheelhouse" "$ROOT/scripts/wheelhouse" "$PWD/wheelhouse"; do
    [ -d "$c" ] && { WH="$c"; break; }
  done
fi
[ -n "$WH" ] && [ -d "$WH" ] || fail "no wheelhouse found. Build it on the design PC (python scripts/build_wheelhouse.py), copy dist/wheelhouse here and set WHEELHOUSE=<folder>."
WH="$(cd "$WH" && pwd)"
REQ="$ROOT/requirements/sim-pc.txt"
[ -f "$REQ" ] || REQ="$WH/sim-pc.txt"
[ -f "$REQ" ] || fail "requirements/sim-pc.txt not found (run from a checkout, or copy it into the wheelhouse folder)."
shopt -s nullglob
OWN=("$WH"/quantcore_circuits-*.whl)
[ "${#OWN[@]}" -eq 1 ] || fail "expected exactly one quantcore_circuits-*.whl in $WH, found ${#OWN[@]}."
SNAP=()
for n in kqcircuits quantum_metal sqcircuit qucat pyaedt; do
  f=("$WH/$n"-*.whl)
  [ "${#f[@]}" -ge 1 ] || fail "the wheelhouse has no $n wheel."
  SNAP+=("${f[0]}")
done
echo "wheelhouse: $WH (${#SNAP[@]} snapshots + ${OWN[0]##*/})"

# ---- conda -------------------------------------------------------------------------------------------------------
step "conda env '$ENV_NAME' (Python 3.11)"
command -v conda >/dev/null 2>&1 || fail "conda not found. Install Miniconda, open a new shell and run again."
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "using the existing env $ENV_NAME"
else
  conda create -n "$ENV_NAME" python=3.11 -y || fail "conda create failed."
fi
PY="$(conda run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)' | tail -n 1)"
[ -x "$PY" ] || fail "cannot find the env's python ($PY)."
VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
[ "$VER" = "3.11" ] || fail "env '$ENV_NAME' runs Python $VER, the tested version is 3.11. Use another QCC_ENV or remove the env."

pip_() { "$PY" -m pip "$@" || fail "pip $* failed."; }

# ---- packages ----------------------------------------------------------------------------------------------------
step "pip"
pip_ install --upgrade pip
if [ "${SKIP_TORCH:-0}" != "1" ]; then
  step "torch $TORCH_VERSION (CPU build)"
  pip_ install "torch==$TORCH_VERSION" --index-url https://download.pytorch.org/whl/cpu
fi
step "pinned PyPI packages (requirements/sim-pc.txt)"
pip_ install -r "$REQ"
step "upstream snapshots from the wheelhouse"
pip_ install "${SNAP[@]}"
step "quantcore-circuits[all]"
pip_ install "${OWN[0]}[all]"

# ---- the tests during install ------------------------------------------------------------------------------------
step "qcc selftest"
"$PY" -m quantcore_circuits.cli selftest || fail "qcc selftest failed: read the FAIL lines above (a missing extra, or a broken wheel)."

if [ -d "$ROOT/tests" ] && [ -f "$ROOT/pyproject.toml" ] && [ "${SKIP_TESTS:-0}" != "1" ]; then
  step "pytest -m 'not slow' (repository checkout)"
  (cd "$ROOT" && "$PY" -m pytest -m "not slow" -q -x) \
    || fail "pytest failed. Tests that need git-ignored folders (other-libs/, components/) fail on a fresh clone: read the first failure."
else
  printf '\n(no repository checkout here, or SKIP_TESTS=1: pytest not run; clone the repo and run: %s -m pytest -m "not slow")\n' "$PY"
fi

printf '\nINSTALL OK. Use it with:  conda activate %s   then   qcc --help\n' "$ENV_NAME"
echo "Next: run the design notebooks one by one (docs: overview/simulation-pc)."

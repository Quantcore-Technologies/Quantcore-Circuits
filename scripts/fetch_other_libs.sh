#!/usr/bin/env bash
# Fetch third-party sources from their ORIGINAL upstream repositories into third_party/. other-libs/ (the local
# copies) is never uploaded to this repo, so nothing here depends on it.
#
#   bash scripts/fetch_other_libs.sh                 # required libraries (installed editable)
#   bash scripts/fetch_other_libs.sh klive pyPalace  # also these reference repos (names from the table below)
#   bash scripts/fetch_other_libs.sh all             # required + every reference repo
#   bash scripts/fetch_other_libs.sh links           # only (re)create the other-libs/ path links
#
# Pin a ref with <NAME>_REF, e.g. KQC_REF=<commit> (default: the branch below). Clones are shallow.
# After fetching, other-libs/<folder>/<folder> is linked to third_party/<name> (VM-only; other-libs/ is git-ignored),
# so paths in older specs (other-libs/KQCircuits-main/KQCircuits-main/...) resolve.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TP="$ROOT/third_party"
mkdir -p "$TP"

# name          tier       url                                                   branch       local folder name
REPOS="
KQCircuits      required   https://github.com/iqm-finland/KQCircuits.git          ${KQC_REF:-main}      KQCircuits-main
qiskit-metal    required   https://github.com/qiskit-community/qiskit-metal.git   ${METAL_REF:-main}    qiskit-metal-main
qucat           required   https://github.com/qucat/qucat.git                     ${QUCAT_REF:-master}  qucat-master
SQcircuit       required   https://github.com/stanfordLINQS/SQcircuit.git         ${SQC_REF:-main}      SQcircuit-main
qutip           reference  https://github.com/qutip/qutip.git                     master       qutip-master
pyaedt          reference  https://github.com/ansys/pyaedt.git                    main         pyaedt-main
klayout         reference  https://github.com/KLayout/klayout.git                 master       klayout-master
klive           reference  https://github.com/gdsfactory/klive.git                main         klive-main
gdsfactory      reference  https://github.com/gdsfactory/gdsfactory.git           main         gdsfactory-main
pyPalace        reference  https://github.com/FirasAbouzahr/pyPalace.git          main         pyPalace-main
qibo            reference  https://github.com/qiboteam/qibo.git                   main         qibo-main
qibolab         reference  https://github.com/qiboteam/qibolab.git                main         qibolab-main
gmsh            reference  https://gitlab.onelab.info/gmsh/gmsh.git               gmsh_4_15_2  gmsh-4.15.2-source
"

want() {  # want <name> <tier>: is this repo requested?
  local name=$1 tier=$2
  case " ${ARGS} " in
    *" links "*) return 1 ;;
    *" all "*) return 0 ;;
  esac
  [ "$tier" = "required" ] && return 0
  case " ${ARGS} " in *" $name "*) return 0 ;; esac
  return 1
}
ARGS="$*"

echo "$REPOS" | while read -r name tier url ref folder; do
  [ -z "$name" ] && continue
  dest="$TP/$name"
  if want "$name" "$tier" && [ ! -d "$dest/.git" ]; then
    echo "[fetch] $name ($ref) <- $url"
    if ! git clone --quiet --depth 1 --branch "$ref" "$url" "$dest" 2>/dev/null; then
      # a commit hash (not a branch/tag): full-depth clone, then check it out
      git clone --quiet "$url" "$dest" && git -C "$dest" checkout --quiet "$ref" \
        || { echo "[fetch] $name: clone failed (network allowlist?)"; rm -rf "$dest"; continue; }
    fi
  fi
  if [ -d "$dest" ] && [ ! -e "$ROOT/other-libs/$folder/$folder" ]; then
    mkdir -p "$ROOT/other-libs/$folder"
    ln -s "$dest" "$ROOT/other-libs/$folder/$folder"
  fi
done
echo "[fetch] third_party/: $(ls "$TP" | tr '\n' ' ')"

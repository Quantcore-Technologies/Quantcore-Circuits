"""Build ``dist/wheelhouse/``: the quantcore-circuits wheel plus wheels of the five upstream snapshots.

The wheelhouse is the offline, reproducible install of this repository on another PC (the simulation PC). Nothing is
downloaded: every wheel is built from files already on this PC, with the setuptools of the active environment
(``pip wheel --no-deps --no-build-isolation``).

* **quantcore-circuits**: ``scripts/build_wheel.py`` (builds outside the repo's ``build/`` folder).
* **The five snapshots** (no pinned release on PyPI): KQCircuits (``klayout_package/python``), qiskit-metal
  (``quantum-metal``), SQcircuit, qucat, pyaedt, from the editable sources in ``other-libs/``. ``other-libs/`` is never
  modified: each source is copied to a temporary folder (only the files the wheel needs, no docs / tests / git
  history) and built there. Two builds need a patch in the *copy*: KQCircuits takes its version from git tags (the copy
  has no git, so it is fixed to the version the editable install reports) and qiskit-metal's ``uv_build`` backend is
  swapped for setuptools (``uv_build`` is not installed here and cannot be downloaded).

Run from anywhere, with the env active (qcd)::

    python scripts/build_wheelhouse.py          # → dist/wheelhouse/*.whl  (re-running replaces the wheels)
    python scripts/build_wheelhouse.py --only qucat

Install from it (see ``scripts/install_sim_pc.ps1`` / ``.sh`` and ``CONTRIBUTING.md``)::

    pip install --find-links dist/wheelhouse -r requirements/sim-pc.txt "quantcore-circuits[all]"
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "other-libs"
WHEELHOUSE = ROOT / "dist" / "wheelhouse"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", ".git", "build", "dist", "*.so.debug")

# name -> (source folder under other-libs/, sub-folders copied besides the top-level files, installed distribution)
SNAPSHOTS = {
    "kqcircuits": (
        "KQCircuits-main/KQCircuits-main/klayout_package/python",
        ["kqcircuits", "requirements"],
        "kqcircuits",
    ),
    "quantum-metal": ("qiskit-metal-main/qiskit-metal-main", ["src"], "quantum-metal"),
    "sqcircuit": ("SQcircuit-main/SQcircuit-main", ["SQcircuit"], "SQcircuit"),
    "qucat": ("qucat-master/qucat-master", ["src"], "qucat"),
    "pyaedt": ("pyaedt-main/pyaedt-main", ["src"], "pyaedt"),
}


def _installed_version(dist: str) -> str | None:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None


def _patch_kqcircuits(src: Path, origin: Path, version: str) -> None:
    """Fix the git-tag version (the copy has no git history), ship all data files and KQC's script folders."""
    pp = src / "pyproject.toml"
    text = pp.read_text(encoding="utf-8")
    text = text.replace('dynamic = ["version", "dependencies"', 'dynamic = ["dependencies"')
    text = re.sub(r"\[tool\.setuptools-git-versioning\]\s*enabled = true\s*", "", text)
    text = text.replace('requires = ["setuptools>=64", "setuptools-git-versioning"]', 'requires = ["setuptools>=64"]')
    text = re.sub(r"(?m)^(name = .*)$", rf'\1\nversion = "{version}"', text, count=1)
    pp.write_text(text, encoding="utf-8")
    # upstream's MANIFEST.in ships 3 data files; the editable install (what the tests ran with) has all of them
    # (junctions/QCD*.oas, util/font_polygons.oas, util/edit_node_plugin.png)
    with (src / "MANIFEST.in").open("a", encoding="utf-8") as fh:
        fh.write("\nrecursive-include kqcircuits *.oas *.lyp *.son *.png\nrecursive-include klayout_package *\n")
    # KQC's simulation export reads its helper scripts from <root>/klayout_package/python/scripts, a folder that exists
    # only in a git checkout (an installed copy looks in the current directory, so ``qcc sim build`` failed). Ship
    # scripts/ and drc/ as a top-level ``klayout_package/python/`` folder next to the package (not inside it: KQC
    # imports every module under ``kqcircuits/``, and the mask scripts run code when imported) and make defaults.py
    # find them there.
    root = src / "klayout_package" / "python"
    for d in ("scripts", "drc"):
        if (origin / d).is_dir():
            shutil.copytree(origin / d, root / d, ignore=IGNORE)
    defaults = src / "kqcircuits" / "defaults.py"
    text = defaults.read_text(encoding="utf-8")
    anchor = '_py_path = ROOT_PATH.joinpath("klayout_package/python")\n'
    if anchor not in text or "SIM_SCRIPT_PATH = ROOT_PATH" not in text:
        raise RuntimeError("kqcircuits/defaults.py changed upstream: update _patch_kqcircuits")
    text = text.replace(
        anchor,
        anchor + 'if (_kqcircuits_path.parent / "klayout_package").is_dir():  # wheel install (build_wheelhouse.py)\n'
        '    _py_path = _kqcircuits_path.parent / "klayout_package" / "python"\n',
    )
    text = text.replace(
        'SIM_SCRIPT_PATH = ROOT_PATH / "klayout_package" / "python" / "scripts" / "simulations"',
        'SIM_SCRIPT_PATH = _py_path / "scripts" / "simulations"',
    )
    defaults.write_text(text, encoding="utf-8")
    text = pp.read_text(encoding="utf-8")
    new = text.replace('include = ["kqcircuits*"]', 'include = ["kqcircuits*", "klayout_package*"]')
    pp.write_text(new, encoding="utf-8")


def _patch_metal(src: Path) -> None:
    """uv_build is not available offline: build the same ``src/qiskit_metal`` package with setuptools."""
    pp = src / "pyproject.toml"
    text = pp.read_text(encoding="utf-8")
    text = re.sub(r'requires\s*=\s*\[\s*"uv_build[^\]]*\]', 'requires = [ "setuptools>=64" ]', text)
    text = text.replace('build-backend = "uv_build"', 'build-backend = "setuptools.build_meta"')
    text += (
        '\n[tool.setuptools.packages.find]\nwhere = ["src"]\ninclude = ["qiskit_metal*"]\n'
        '\n[tool.setuptools.package-data]\n"*" = ["*"]\n'
    )
    pp.write_text(text, encoding="utf-8")


def build_snapshot(name: str, out: Path) -> tuple[bool, str]:
    folder, dirs, dist = SNAPSHOTS[name]
    origin = LIBS / folder
    if not origin.is_dir():
        return False, f"missing source folder {origin} (run scripts/fetch_other_libs.sh)"
    with tempfile.TemporaryDirectory(prefix=f"qcc_wh_{name}_") as tmp:
        src = Path(tmp) / name
        src.mkdir()
        for item in origin.iterdir():
            if item.is_file():
                shutil.copy2(item, src / item.name)
        for d in dirs:
            if (origin / d).is_dir():
                shutil.copytree(origin / d, src / d, ignore=IGNORE)
        if name == "kqcircuits":
            _patch_kqcircuits(src, origin, _installed_version(dist) or "0.0.1")
        elif name == "quantum-metal":
            _patch_metal(src)
        cmd = [sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--no-build-isolation", "-w", str(out)]
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        return False, "pip wheel failed:\n" + "\n".join(done.stdout.splitlines()[-15:] + done.stderr.splitlines()[-15:])
    return True, "built"


def build_own(out: Path) -> tuple[bool, str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_wheel  # noqa: PLC0415  (scripts/build_wheel.py)

    for old in out.glob("quantcore_circuits-*.whl"):
        old.unlink()
    code = build_wheel.build(out, quiet=True)
    return code == 0, "built" if code == 0 else "scripts/build_wheel.py failed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="+", choices=["quantcore-circuits", *SNAPSHOTS], help="build just these")
    args = ap.parse_args()
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    todo = args.only or ["quantcore-circuits", *SNAPSHOTS]
    failed = []
    for name in todo:
        if name != "quantcore-circuits":  # a rebuilt snapshot replaces the old wheel(s) of that name
            for old in WHEELHOUSE.glob(f"{name.replace('-', '_')}-*.whl"):
                old.unlink()
            for old in WHEELHOUSE.glob(f"{SNAPSHOTS[name][2]}-*.whl"):
                old.unlink()
        ok, msg = build_own(WHEELHOUSE) if name == "quantcore-circuits" else build_snapshot(name, WHEELHOUSE)
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {msg}", flush=True)
        if not ok:
            failed.append(name)
    print()
    for whl in sorted(WHEELHOUSE.glob("*.whl")):
        print(f"  {whl.relative_to(ROOT)}  ({whl.stat().st_size / 1e6:.1f} MB)")
    if failed:
        print(f"\nfailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

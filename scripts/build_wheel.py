"""Build the quantcore-circuits wheel into ``dist/`` without touching the repo's ``build/`` folder.

setuptools writes ``build/lib`` and ``build/bdist.*`` next to ``pyproject.toml``, but ``build/`` here is where designs
and the KLayout plugin keep their outputs. So the package source (``pyproject.toml``, ``README.md``, ``src/``) is
copied to a temporary folder and built there. No packages are downloaded: the build uses the setuptools of the
active environment (``--no-build-isolation``) and does not build the dependencies (``--no-deps``).

Run from anywhere, with the env active::

    python scripts/build_wheel.py            # → dist/quantcore_circuits-<version>-py3-none-any.whl

Install on another machine: build the wheelhouse (``scripts/build_wheelhouse.py``: this wheel plus the five upstream
snapshots) and use ``scripts/install_sim_pc.ps1`` / ``.sh``, or by hand ``pip install -r requirements/sim-pc.txt`` and
``pip install --find-links dist/wheelhouse "quantcore-circuits[all]"``. The wheel needs neither ``components/`` nor
``build/``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")


def build(dist: Path, quiet: bool = False) -> int:
    """Build the wheel into ``dist``; returns the exit code of ``pip wheel``."""
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qcc_wheel_") as tmp:
        src = Path(tmp) / "quantcore-circuits"
        src.mkdir()
        for name in ("pyproject.toml", "README.md"):
            shutil.copy2(ROOT / name, src / name)
        shutil.copytree(ROOT / "src", src / "src", ignore=IGNORE)
        cmd = [sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--no-build-isolation", "-w", str(dist)]
        done = subprocess.run(cmd, check=False, capture_output=quiet, text=quiet)
    if done.returncode != 0 and quiet:
        print(done.stdout[-2000:], done.stderr[-2000:])
    return done.returncode


def main() -> int:
    dist = ROOT / "dist"
    code = build(dist)
    if code == 0:
        for whl in sorted(dist.glob("quantcore_circuits-*.whl")):
            print(f"{whl.relative_to(ROOT)}  ({whl.stat().st_size / 1e6:.1f} MB)")
    return code


if __name__ == "__main__":
    sys.exit(main())

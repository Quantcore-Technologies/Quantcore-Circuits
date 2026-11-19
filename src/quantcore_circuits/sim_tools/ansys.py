"""Locate Ansys Electronics Desktop (AEDT 2024 R1 or newer) and point KQC's Ansys exporter at it.

Quantcore targets **AEDT 2024** (``v241`` = 2024 R1, installed on the design PC 2026-11-03; ``v242`` = 2024 R2 also
accepted, the newest install wins). Older installs (e.g. 2021 R1) are ignored unless named explicitly through
``QCC_ANSYS_EXECUTABLE``. Search order:

1. ``QCC_ANSYS_EXECUTABLE`` (explicit override, any version; on the Linux server e.g.
   ``/ansys_inc/v242/AnsysEM/ansysedt``)
2. ``ANSYSEM_ROOT<ver>`` set by the AEDT installer, highest version first, ``ver >= MIN_VERSION``
3. standard install folders: ``%ProgramFiles%\\AnsysEM\\v<ver>\\Win64``, ``%ProgramFiles%\\ANSYS Inc\\v<ver>\\AnsysEM``
   (and ``...\\Electronics\\Win64`` for AEDT installed as part of the unified Ansys installer), ``/ansys_inc/v<ver>``
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MIN_VERSION = 241  # AEDT 2024 R1
TARGET_VERSION = 241  # job scripts exported where AEDT is not installed target this version


def _exe_name() -> str:
    return "ansysedt.exe" if os.name == "nt" else "ansysedt"


def candidate_paths(min_version: int = MIN_VERSION) -> list[tuple[int, Path]]:
    """(version, path) candidates for ``ansysedt``, highest version first (existence not checked)."""
    exe = _exe_name()
    out: list[tuple[int, Path]] = []
    for key, value in os.environ.items():
        m = re.fullmatch(r"ANSYSEM_ROOT(\d+)", key.upper())
        if m:
            out.append((int(m.group(1)), Path(value) / exe))
    roots = []
    if os.name == "nt":
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        roots = [
            (pf / "AnsysEM", "v{v}/Win64"),
            (pf / "ANSYS Inc", "v{v}/AnsysEM"),
            (pf / "ANSYS Inc", "v{v}/Electronics/Win64"),
        ]
    else:
        roots = [(Path("/ansys_inc"), "v{v}/AnsysEM"), (Path("/opt/AnsysEM"), "v{v}/Linux64")]
    for base, pattern in roots:
        if not base.is_dir():
            continue
        for d in base.iterdir():
            m = re.fullmatch(r"v(\d{3})", d.name)
            if m:
                v = int(m.group(1))
                out.append((v, base / pattern.format(v=v) / exe))
    out = [(v, p) for v, p in out if v >= min_version]
    return sorted(set(out), key=lambda vp: -vp[0])


def find_ansys_executable(min_version: int = MIN_VERSION) -> Path | None:
    explicit = os.environ.get("QCC_ANSYS_EXECUTABLE")
    if explicit:
        return Path(explicit)
    for _, path in candidate_paths(min_version):
        if path.is_file():
            return path
    return None


def aedt_version(executable: str | Path) -> int | None:
    """Three-digit AEDT version (e.g. 242) guessed from the install path, or None."""
    m = re.search(r"v(\d{3})|AnsysEM(\d{2})\.(\d)", str(executable))
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else int(m.group(2) + m.group(3))


def default_executable(version: int = TARGET_VERSION) -> Path:
    """Standard AEDT install location for ``version`` (used in job scripts when AEDT is not installed here)."""
    if os.name == "nt":
        return Path(r"%PROGRAMFILES%") / "AnsysEM" / f"v{version}" / "Win64" / "ansysedt.exe"
    return Path(f"/ansys_inc/v{version}/AnsysEM/ansysedt")


def configure_kqc_ansys(executable: str | Path | None = None) -> Path:
    """Make KQC's ``export_ansys`` write ``simulation.bat`` with ``executable``, the discovered AEDT >= 2024 R1, or
    the standard 2024 R1 location (so a job exported on a machine without AEDT still targets 2024)."""
    exe = Path(executable) if executable else (find_ansys_executable() or default_executable())
    from kqcircuits.simulations.export.ansys import ansys_export  # pylint: disable=import-outside-toplevel

    ansys_export.ANSYS_EXECUTABLE = exe
    return exe

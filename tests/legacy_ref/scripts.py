"""Run the legacy QWri junction / test-pad scripts (read-only, from ``components/python``) into a temporary folder.

The scripts write GDS files to hard-coded ``D:\\Designs`` paths: the module-level ``path`` is re-pointed into
``tmp_dir`` before the function is called (or the source line is replaced in memory for ``junction_pad.py``, which
writes while it is imported). Nothing outside ``tmp_dir`` is written; nothing from ``components/`` is imported by
the library.
"""

from __future__ import annotations

import sys
from pathlib import Path

import klayout.db as pya

from tests.legacy_ref.legacy import LEGACY, legacy_library

PYTHON = LEGACY / "python"


def _exec(name: str, replace: dict[str, str] | None = None) -> dict:
    legacy_library()  # the scripts instantiate "JJ_finger Top/Bottom" from the QWri library
    path = PYTHON / name
    text = path.read_text(encoding="utf-8", errors="replace")
    for old, new in (replace or {}).items():
        assert old in text, f"{name}: {old!r} not found"
        text = text.replace(old, new)
    namespace: dict = {"__name__": f"qwri_legacy_{path.stem}"}
    sys.path.insert(0, str(PYTHON))  # `from PCell_inserter import Insert`
    try:
        exec(compile(text, str(path), "exec"), namespace)  # noqa: S102
    finally:
        sys.path.remove(str(PYTHON))
    return namespace


def _read(gds: Path) -> pya.Layout:
    layout = pya.Layout()
    layout.read(str(gds))
    return layout


def creator_layout(script: str, func: str, tmp_dir: Path, *args, **kwargs) -> pya.Layout:
    """``junction_creator_HSQ.create_junction`` / ``squid_creator_HSQ.create_squid`` style: ``path`` argument."""
    namespace = _exec(script)
    prefix = str(tmp_dir / f"{Path(script).stem}_")
    namespace[func](*args, path=prefix, **kwargs)
    (gds,) = sorted(tmp_dir.glob(f"{Path(script).stem}_*.gds"))
    return _read(gds)


def module_path_layout(script: str, func: str, tmp_dir: Path, *args) -> pya.Layout:
    """Scripts writing to the module-level ``path`` (``testPad*.py``, ``xtp_testpads_TL_small.py``,
    ``junction_creator_sq.py``)."""
    namespace = _exec(script)
    namespace["path"] = str(tmp_dir / f"{Path(script).stem}_")
    namespace[func](*args)
    (gds,) = sorted(tmp_dir.glob(f"{Path(script).stem}_*.gds"))
    return _read(gds)


def junction_pad_layout(tmp_dir: Path) -> pya.Layout:
    """``junction_pad.py`` builds and writes its SQUID at import time."""
    gds = tmp_dir / "junction_pad.gds"
    _exec("junction_pad.py", {r'path=r"D:\Designs\ScriptedDesigns\junction_squid.gds"': f"path={str(gds)!r}"})
    return _read(gds)


def top_region(layout: pya.Layout, cell_name: str, layer: tuple[int, int]) -> pya.Region:
    cell = layout.cell(cell_name)
    assert cell is not None, f"no cell {cell_name!r} in {[c.name for c in layout.top_cells()]}"
    return pya.Region(cell.begin_shapes_rec(layout.layer(*layer))).merged()

"""Golden-geometry reference: run the legacy QWri PCells (read-only, from ``components/``) in standalone
KLayout and return their fab-mode geometry.

The legacy macros are executed from their source text in an isolated namespace (they rely on KLayout's shared macro
namespace, e.g. ``Xmon_cross`` calls ``Xmon_handle``). Nothing from ``components/`` is imported by the library.
"""

from __future__ import annotations

import html
import re
from functools import cache
from pathlib import Path

import klayout.db as pya

LEGACY = Path(__file__).resolve().parents[2] / "components"
PCELLS = LEGACY / "pymacros" / "QuantumPcells"

# legacy file → (class, library display name)
LEGACY_CELLS = {
    "xmon_handle.lym": ("Xmon_handle", "Xmon Handle"),
    "xmon_cross.lym": ("Xmon_cross", "Xmon Cross"),
    "connector_pad_v2.lym": ("ConnectorPad2", "Connector Pad 2"),
    "JJ_finger_top.lym": ("JJ_finger_top", "JJ_finger Top"),
    "JJ_finger_bottom.lym": ("JJ_finger_bot", "JJ_finger Bottom"),
}


def available() -> bool:
    return PCELLS.is_dir()


def macro_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<text>(.*)</text>", raw, re.S)
    return html.unescape(m.group(1)) if m else raw


@cache
def legacy_library() -> pya.Library:
    """Register the legacy PCells in a library called ``QWri`` (as ``Library_QWri.lym`` does)."""
    namespace: dict = {"pya": pya, "__name__": "qwri_legacy"}
    for fname in LEGACY_CELLS:
        exec(compile(macro_text(PCELLS / fname), str(PCELLS / fname), "exec"), namespace)  # noqa: S102
    lib = pya.Library()
    lib.description = "QWri legacy (test reference)"
    for _, (cls, display) in LEGACY_CELLS.items():
        lib.layout().register_pcell(display, namespace[cls]())
    lib.register("QWri")
    return lib


def legacy_region(display_name: str, layer=(1, 0), **params) -> pya.Region:
    legacy_library()
    layout = pya.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell(display_name, "QWri", params)
    # merged() materialises the region; a Region built from a shape iterator still refers to `layout`
    return pya.Region(cell.begin_shapes_rec(layout.layer(*layer))).merged()


def legacy_junction_layout(kind: str, tmp_dir: Path, js: float = 1.0, second: float = 0) -> pya.Layout:
    """Run ``xjc_junction_TL_mod.create_junction`` / ``xjc_squid_TL_mod.create_squid`` (``js`` × 0.1 µm straight
    finger, ``secondFinger`` = ``second`` µm bent finger, 0 = same) and read the written GDS."""
    legacy_library()
    script = LEGACY / "python" / ("xjc_junction_TL_mod.py" if kind == "junction" else "xjc_squid_TL_mod.py")
    namespace: dict = {"__name__": "legacy_junction"}
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)  # noqa: S102
    prefix = str(tmp_dir / f"legacy_{kind}_")
    (namespace["create_junction"] if kind == "junction" else namespace["create_squid"])(
        js=js, secondFinger=second, path=prefix
    )
    layout = pya.Layout()
    layout.read(f"{prefix}{int(js)}.gds")
    return layout


# ---- generic helpers for the other legacy cells ------------------------------------------------------------------
# (file relative to components/, class) → library display name; each file gets its own library "QWri_<stem>"
_EXTRA_LIBS: dict[str, pya.Library] = {}


def macro_namespace(path: Path, extra: dict | None = None) -> dict:
    """Execute a legacy macro or script (read-only) in a fresh namespace and return it."""
    namespace: dict = {"pya": pya, "__name__": f"qwri_legacy_{path.stem}", **(extra or {})}
    text = macro_text(path) if path.suffix == ".lym" else path.read_text(encoding="utf-8", errors="replace")
    exec(compile(text, str(path), "exec"), namespace)  # noqa: S102
    return namespace


def legacy_pcell_library(relpath: str, classes: dict[str, str]) -> str:
    """Register the PCell classes ``{class: display}`` of ``components/<relpath>`` in their own library; returns
    the library name. Cached per file."""
    lib_name = "QWri_" + re.sub(r"\W+", "_", Path(relpath).stem)
    if lib_name not in _EXTRA_LIBS:
        legacy_library()  # some macros call cells of the base library
        namespace = macro_namespace(LEGACY / relpath)
        lib = pya.Library()
        lib.description = f"QWri legacy {relpath} (test reference)"
        for cls, display in classes.items():
            lib.layout().register_pcell(display, namespace[cls]())
        lib.register(lib_name)
        _EXTRA_LIBS[lib_name] = lib
    return lib_name


def legacy_pcell_regions(relpath: str, cls: str, display: str, layers=((1, 0),), **params) -> dict:
    """Fab-mode geometry of a legacy PCell: ``{(layer, datatype): merged Region}`` (dbu 0.001)."""
    lib_name = legacy_pcell_library(relpath, {cls: display})
    layout = pya.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell(display, lib_name, params)
    return {tuple(li): pya.Region(cell.begin_shapes_rec(layout.layer(*li))).merged() for li in layers}


def legacy_script_layout(relpath: str, call, tmp_dir: Path, gds_glob: str = "*.gds", extra: dict | None = None):
    """Run a legacy script function ``call(namespace)`` that writes a GDS, with its own folder on ``sys.path`` (the
    scripts import each other), and return the layouts it wrote in ``tmp_dir`` (``{file name: Layout}``)."""
    import sys  # pylint: disable=import-outside-toplevel

    legacy_library()
    path = LEGACY / relpath
    sys.path.insert(0, str(path.parent))
    try:
        namespace = macro_namespace(path, extra)
        call(namespace)
    finally:
        sys.path.remove(str(path.parent))
    out = {}
    for gds in sorted(tmp_dir.glob(gds_glob)):
        layout = pya.Layout()
        layout.read(str(gds))
        out[gds.name] = layout
    return out

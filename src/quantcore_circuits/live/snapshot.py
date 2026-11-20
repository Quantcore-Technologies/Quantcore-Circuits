"""KLayout screenshots of a layout, rendered by KLayout itself.

``snapshot`` uses a headless ``klayout.lay.LayoutView`` with KQC's ``default_layer_props.lyp`` (same colours and
stipples as the GUI), so it works in Jupyter, CI and on the server. ``gui_snapshot`` asks the running KLayout GUI
(quantcore-circuits KLayout plugin, command server on port 8083) to save its current view instead, falling back to
``snapshot`` when the GUI is not reachable.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

GUI_PORT = 8083
# helper layers of every face (matched in "<name> <source>", "_" read as " "): KQC's centre lines (waveguide_path),
# avoidance regions, port and refpoint texts. "waveguide length" is kept for layouts written with that older name.
HIDE = (
    "refpoints",
    "ground grid avoidance",
    "waveguide path",
    "waveguide length",
    "annotations",
    "ports",
)
OUTLINE = ("chip boundary",)  # drawn as a frame only (a filled 100/0 box hatched the whole die)


def _face_of(source: str) -> tuple[str, str] | None:
    """``("2t1", "waveguide path")`` for a KQC face layer source such as ``'2t1 waveguide path' 135/2@1``."""
    name = source.strip().strip("'").split("'")[0]
    face, _, layer = name.partition(" ")
    return (face, layer) if len(face) == 3 and face[0].isdigit() and layer else None


def layer_props_path() -> str | None:
    """Quantcore layer properties: KQC's ``default_layer_props.lyp`` with the **ground grid (cheese) visible** and
    every face shown like face ``1t1``.

    KQC ships ``'1t1 ground grid' 132/1`` hidden, which hid the PDK cheese band in every snapshot and KLayout view.
    KQC's ``2t1`` group also shows its ``waveguide path`` (centre lines) and ``base metal gap for EBL`` and hides its
    ``base metal gap``, unlike the other faces: here each face layer gets the visibility of the ``1t1`` layer of the
    same name, so a two-face picture has no centre lines over it. The variant is written next to the temp dir and
    refreshed when KQC's file or this module changes; load it in KLayout (*File → Load Layer Properties*) to see the
    cheese there too."""
    import tempfile  # pylint: disable=import-outside-toplevel
    import xml.etree.ElementTree as ET  # pylint: disable=import-outside-toplevel

    try:
        from kqcircuits.defaults import default_layer_props  # pylint: disable=import-outside-toplevel
    except ImportError:  # pragma: no cover
        return None
    if not default_layer_props or not Path(default_layer_props).exists():
        return None
    src = Path(default_layer_props)
    out = Path(tempfile.gettempdir()) / "quantcore_circuits" / "quantcore_layer_props.lyp"
    newest = max(src.stat().st_mtime, Path(__file__).stat().st_mtime)
    if out.exists() and out.stat().st_mtime >= newest:
        return str(out)
    try:
        tree = ET.parse(src)
        members = [e for e in tree.getroot().iter() if e.tag in ("properties", "group-members")]
        shown = {}  # 1t1 layer name → visible
        for elem in members:
            face = _face_of(elem.findtext("source") or "")
            if face is not None and face[0] == "1t1" and elem.find("visible") is not None:
                shown[face[1]] = elem.find("visible").text
        for elem in members:
            source = elem.findtext("source") or ""
            visible = elem.find("visible")
            if visible is None:
                continue
            face = _face_of(source)
            if face is not None and face[1] in shown:
                visible.text = shown[face[1]]
            if "ground grid'" in source:  # the grid itself, not "ground grid avoidance"
                visible.text = "true"
        out.parent.mkdir(parents=True, exist_ok=True)
        tree.write(out, encoding="utf-8", xml_declaration=True)
    except (ET.ParseError, OSError):  # pragma: no cover
        return str(src)
    return str(out)


def _layer_props() -> str | None:
    return layer_props_path()


def snapshot(
    source,
    png: str | Path,
    size: tuple[int, int] = (1600, 1600),
    box: tuple[float, float, float, float] | None = None,
    background: str = "#ffffff",
    oversampling: int = 2,
    hide: tuple[str, ...] = HIDE,
) -> Path:
    """Render ``source`` (an ``.oas``/``.gds`` path or a :class:`BuildResult`) to ``png``.

    ``box`` (µm, x0 y0 x1 y1) zooms to a region; default is the whole top cell. Layers whose names contain one of
    ``hide`` are switched off (helper layers that clutter a picture).
    """
    from klayout import lay  # pylint: disable=import-outside-toplevel
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    png = Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(source, "layout") and hasattr(source, "top"):
        from quantcore_circuits.assembly import write_layout  # pylint: disable=import-outside-toplevel

        path = png.with_suffix(".oas")
        write_layout(source, path)
    else:
        path = Path(source)
    view = lay.LayoutView()
    view.set_config("background-color", background)
    view.set_config("grid-visible", "false")
    view.set_config("text-visible", "false")
    view.load_layout(str(path), True)
    props = _layer_props()
    if props:
        view.load_layer_props(props, True)
    view.add_missing_layers()
    it = view.begin_layers()
    hidden = [h.replace("_", " ").lower() for h in hide]
    while not it.at_end():
        node = it.current()
        label = f"{node.name} {node.source}".replace("_", " ").lower()
        if any(h in label for h in hidden):
            node.visible = False
        elif any(o in label for o in OUTLINE):
            node.dither_pattern = 1  # hollow
        it.next()
    view.max_hier()
    if box is None:
        fit = _drawn_bbox(view, hidden)
        if fit is not None:
            box = (fit.left, fit.bottom, fit.right, fit.top)
    if box is not None:
        view.zoom_box(pya.DBox(*box))
    else:
        view.zoom_fit()
    view.save_image_with_options(str(png), size[0], size[1], 0, oversampling, 0, pya.DBox(), False)
    return png


ANNOTATION_LAYERS = ("instance names", "refpoints", "annotations", "texts")  # KQC 222/0 etc.: labels, not geometry


def _drawn_bbox(view, hidden: list[str]):
    """Bounding box (µm, +1 %) of the drawn geometry: hidden and annotation layers (KQC ``instance_names`` 222/0 text
    can reach far outside the chip) are left out, so the default view fits the chip, not its labels."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    cv = view.cellview(0)
    layout, top = cv.layout(), cv.cell
    skip = [*hidden, *ANNOTATION_LAYERS]
    bb = pya.DBox()
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        label = f"{info.name} {info.layer}/{info.datatype}".replace("_", " ").lower()
        if info.layer == 222 or any(h in label for h in skip):
            continue
        bb += top.dbbox_per_layer(li)
    if bb.empty():
        return None
    return bb.enlarged(0.01 * bb.width(), 0.01 * bb.height())


def gui_available(port: int = GUI_PORT, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def gui_snapshot(
    png: str | Path,
    size: tuple[int, int] = (1600, 1600),
    layout: str | Path | None = None,
    box: tuple[float, float, float, float] | None = None,
    port: int = GUI_PORT,
    timeout: float = 20.0,
    fallback=None,
) -> tuple[Path, str]:
    """Screenshot from the running KLayout GUI (quantcore-circuits KLayout plugin, port 8083) → ``(png, "gui")``.

    ``layout`` makes the GUI open/reload that file first; ``box`` (µm) zooms. If the GUI is not reachable and
    ``fallback`` (a layout path or BuildResult; defaults to ``layout``) exists, it is rendered headless instead →
    ``(png, "headless")``.
    """
    png = Path(png).resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    msg = {"cmd": "screenshot", "path": str(png), "width": size[0], "height": size[1]}
    if layout:
        msg["layout"] = str(Path(layout).resolve())
    if box:
        msg["box"] = list(box)
    if _layer_props():
        msg["lyp"] = _layer_props()
    msg["hide"] = list(HIDE)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            sock.settimeout(timeout)
            reply = json.loads(sock.recv(65536).decode("utf-8") or "{}")
        if reply.get("ok"):
            return png, "gui"
        raise RuntimeError(reply.get("error", "screenshot failed"))
    except (OSError, ValueError, RuntimeError):
        fallback = fallback if fallback is not None else layout
        if fallback is None:
            raise
        return snapshot(fallback, png, size=size, box=box), "headless"

"""Ports as seen by quantcore_circuits: KQC refpoints ``port_<name>`` + optional ``port_<name>_corner``.

A port has a position, an *outward* unit direction (``corner - port``; the direction a connecting waveguide comes
from) and the CPW centre width ``a`` / gap ``b`` at that point. A port of a multi-face cell (a TSV or bump
transition) also names its KQC chip face (``face``, e.g. ``"2b1"``); ``None`` is the cell's own face.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kqcircuits.defaults import default_layers
from kqcircuits.elements.element import get_refpoints
from kqcircuits.pya_resolver import pya


@dataclass
class Port:
    name: str
    pos: pya.DPoint
    dir: pya.DVector | None  # outward unit vector, None if the port has no corner refpoint
    a: float | None = None
    b: float | None = None
    face: str | None = None  # KQC face id of a multi-face cell's port ("1t1", "1b1", "2b1", "2t1"); None: not recorded

    @property
    def angle(self) -> float | None:
        return None if self.dir is None else math.degrees(math.atan2(self.dir.y, self.dir.x))

    @property
    def corner(self) -> pya.DPoint | None:
        return None if self.dir is None else self.pos + self.dir

    def transformed(self, trans: pya.DCplxTrans) -> Port:
        d = None
        if self.dir is not None:
            d = trans * self.dir
            d = d / d.length()
        return Port(self.name, trans * self.pos, d, self.a, self.b, self.face)

    def as_dict(self) -> dict:
        out = {
            "name": self.name,
            "at": [round(self.pos.x, 6), round(self.pos.y, 6)],
            "dir": None if self.angle is None else round(self.angle, 6),
            "a": self.a,
            "b": self.b,
        }
        if self.face is not None:
            out["face"] = self.face
        return out


def direction_vector(angle_deg: float) -> pya.DVector:
    rad = math.radians(angle_deg)
    x, y = math.cos(rad), math.sin(rad)
    # snap exact axis directions so 90° multiples stay exact
    x, y = (round(x) if abs(x - round(x)) < 1e-12 else x), (round(y) if abs(y - round(y)) < 1e-12 else y)
    return pya.DVector(x, y)


def ports_from_refpoints(refpoints: dict, a: float | None = None, b: float | None = None) -> dict[str, Port]:
    """Extract ports from a refpoint dict (as returned by ``get_refpoints(..., rec_levels=0)``)."""
    ports = {}
    for key, pos in refpoints.items():
        if not key.startswith("port") or key.endswith("_corner"):
            continue
        name = key[len("port_") :] if key.startswith("port_") else key
        if not name:
            name = "port"
        corner = refpoints.get(f"{key}_corner")
        d = None
        if corner is not None and (corner - pos).length() > 0:
            v = corner - pos
            d = v / v.length()
        ports[name] = Port(name, pos, d, a, b)
    return ports


def cell_ports(cell: pya.Cell, a: float | None = None, b: float | None = None, rec_levels: int = 0) -> dict[str, Port]:
    """Ports of a cell in its own coordinates (only the cell's own refpoints by default)."""
    layout = cell.layout()
    refp = get_refpoints(layout.layer(default_layers["refpoints"]), cell, pya.DTrans(), rec_levels)
    return ports_from_refpoints(dict(refp), a, b)


class CellBuildError(RuntimeError):
    """A PCell's build() failed. KLayout swallows the exception and draws it on the error layer; this re-raises it."""


def check_cell(cell: pya.Cell, what: str = "") -> pya.Cell:
    """Raise :class:`CellBuildError` if ``cell`` (or any child) failed to build."""
    if cell is None:
        raise CellBuildError(f"{what or 'cell'}: PCell could not be created (not registered in its library?)")
    layout = cell.layout()
    it = cell.begin_shapes_rec(layout.error_layer())
    messages = []
    while not it.at_end():
        shape = it.shape()
        if shape.is_text():
            messages.append(shape.text_string)
        it.next()
    for err_text in _kqc_error_texts(cell):
        messages.append(err_text)
    if messages:
        first = messages[0].split("\n")[0]
        raise CellBuildError(
            f"{what or cell.name}: {first}" + (f" (+{len(messages) - 1} more)" if len(messages) > 1 else "")
        )
    return cell


def _kqc_error_texts(cell: pya.Cell) -> list[str]:
    """Errors from KQC ``raise_error_on_cell`` (stored as the ``error_on_cell`` instance property)."""
    out = []
    target = cell
    if cell.is_library_cell():
        target = cell.library().layout().cell(cell.library_cell_index())
    for inst in target.each_inst():
        msg = inst.property("error_on_cell")
        if msg:
            out.append(str(msg))
    return out

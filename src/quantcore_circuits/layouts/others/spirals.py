"""Spiral lines ported from the QWri drawing library ``components/python/draw.py::spiral`` (kinetic-inductance /
TWPA spiral inductors; request #7).

The legacy function draws a ``pya.Path`` of width ``w`` through ``npoints`` points of a spiral given by angle,
``φ = linspace(start_ang, end_ang, npoints)``:

* ``archimedean`` (legacy type 0): r = spiral_r · φ;
* ``fermat`` (type 1): r = √(spiral_r² · φ) = spiral_r · √φ;
* ``double_fermat`` (type 2, "double Fermat in/out"): the Fermat arm and its point reflection (−x, −y) joined at the
  centre, so both ends lie outside — a two-terminal spiral inductor. The legacy code has a typo here (it computes
  ``y_bls`` and then uses an undefined ``y1s``, so type 2 raises ``NameError``); the port implements the evident
  intent (``y1s = r sin φ``), which the golden test checks against the legacy function with that one name fixed.

Coordinates are the legacy ones (same numpy and pya calls, so the geometry XORs clean), with ``spiral_r`` and
``width`` in µm (legacy: database units) and the angles in radians. The path is metal on ``base_metal_addition``
(``metal``, default) — place it on a pocket (e.g. ``metal:Rectangle`` with ``subtract: true``, or ``pocket_margin``)
— or etched on ``base_metal_gap_wo_grid`` (``metal=False``, where the legacy chips draw 1/0).

Ports ``a`` (path start) and ``b`` (path end), facing outward along the path tangent (not Manhattan in general),
a = ``width``, b = the element ``b``. ``pocket_margin`` > 0 etches a square pocket that far beyond the spiral's
bounding box; the ports stay at the path ends inside it. LOM: one conductor ``a`` → ``b``, a line of the drawn
centre-line length (:meth:`SpiralLine.qcc_length`) with the mean turn spacing as its gap
(:meth:`SpiralLine.qcc_turn_gap`; :mod:`quantcore_circuits.lom.quantcore_models`).
"""

from __future__ import annotations

import math

import numpy as np
from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

SPIRAL_TYPES = {"archimedean": 0, "fermat": 1, "double_fermat": 2}


def draw_spiral_points(dbu, start_angle, end_angle, spiral_r, spiral_type, npoints) -> list:
    """Legacy ``draw.spiral`` centre line (``spiral_r`` in µm, angles in rad), points in dbu (``pya.Point``)."""
    kind = SPIRAL_TYPES.get(spiral_type, spiral_type)
    spiral_r = spiral_r / dbu
    phi = np.linspace(start_angle, end_angle, int(npoints))
    if kind == 0:
        r = spiral_r * phi
        xs = r * np.cos(phi)
        ys = r * np.sin(phi)
    elif kind == 1:
        r = np.sqrt((spiral_r**2) * phi)
        xs = r * np.cos(phi)
        ys = r * np.sin(phi)
    else:
        r = np.sqrt((spiral_r**2) * phi)
        x1s = r * np.cos(phi)
        y1s = r * np.sin(phi)
        x2s = -r * np.cos(phi)
        y2s = -r * np.sin(phi)
        xs = x2s[::-1].tolist() + x1s.tolist()
        ys = y2s[::-1].tolist() + y1s.tolist()
    return [pya.Point(xs[i], ys[i]) for i in range(len(xs))]


def _end(pts, at_start: bool, dbu: float) -> tuple[pya.DPoint, pya.DVector]:
    seq = pts if at_start else pts[::-1]
    end = seq[0]
    for p in seq[1:]:
        if p != end:
            v = pya.DVector((end.x - p.x) * dbu, (end.y - p.y) * dbu)
            return pya.DPoint(end.x * dbu, end.y * dbu), v / v.length()
    return pya.DPoint(end.x * dbu, end.y * dbu), pya.DVector(1, 0)


class SpiralLine(Element):
    """Spiral line by angle (legacy ``draw.spiral``): Archimedean, Fermat or double Fermat; ports ``a`` / ``b``."""

    spiral_type = Param(pdt.TypeString, "Spiral", "double_fermat", choices=list(SPIRAL_TYPES))
    spiral_r = Param(
        pdt.TypeDouble, "Spiral scale (Archimedean: r = spiral_r·φ; Fermat: r = spiral_r·√φ)", 10, unit="μm"
    )
    start_angle = Param(pdt.TypeDouble, "Start angle", 0.0, unit="rad")
    end_angle = Param(pdt.TypeDouble, "End angle (6 turns = 12π)", 12 * math.pi, unit="rad")
    points = Param(pdt.TypeInt, "Points (legacy npoints; per arm for the double Fermat)", 1000)
    width = Param(pdt.TypeDouble, "Line width (legacy w)", 2, unit="μm")
    metal = Param(pdt.TypeBoolean, "Metal line (base_metal_addition); False: etched (legacy 1/0)", True)
    pocket_margin = Param(pdt.TypeDouble, "Own square pocket beyond the spiral (0 = none)", 0, unit="μm")

    qcc_category = "resonator"

    @classmethod
    def qcc_points(cls, params: dict, dbu: float = 0.001) -> list:
        p = {k: v.default for k, v in cls.get_schema().items()} | dict(params or {})
        return draw_spiral_points(
            dbu, float(p["start_angle"]), float(p["end_angle"]), float(p["spiral_r"]), p["spiral_type"], p["points"]
        )

    @classmethod
    def qcc_length(cls, params: dict) -> float:
        """Drawn centre-line length (µm)."""
        pts = cls.qcc_points(params)
        return sum(pts[i].distance(pts[i + 1]) for i in range(len(pts) - 1)) * 0.001

    @classmethod
    def qcc_turn_gap(cls, params: dict) -> float:
        """Mean spacing between neighbouring turns (µm): radial span / turns − width (double Fermat: the two arms
        interleave, half that pitch)."""
        p = {k: v.default for k, v in cls.get_schema().items()} | dict(params or {})
        pts = cls.qcc_points(p)
        radii = [math.hypot(q.x, q.y) * 0.001 for q in pts]
        turns = abs(float(p["end_angle"]) - float(p["start_angle"])) / (2 * math.pi)
        pitch = (max(radii) - min(radii)) / max(turns, 1e-9)
        if SPIRAL_TYPES.get(p["spiral_type"], p["spiral_type"]) == 2:
            pitch /= 2
        return max(pitch - float(p["width"]), 0.1)

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """Ports: a = the line ``width``, b = the element ``b`` (a route continues as a CPW of that gap)."""
        w, b = float(params.get("width", 2)), float(params.get("b", 6))
        return {"a": (w, b), "b": (w, b)}

    def build(self):
        if self.spiral_type not in SPIRAL_TYPES:
            self.raise_error_on_cell(f"spiral_type must be one of {list(SPIRAL_TYPES)}")
        dbu = self.layout.dbu
        pts = draw_spiral_points(dbu, self.start_angle, self.end_angle, self.spiral_r, self.spiral_type, self.points)
        if len(pts) < 2:
            self.raise_error_on_cell("a spiral needs at least two points")
        path = pya.Region(pya.Path(pts, self.width / dbu))
        if self.metal:
            self.cell.shapes(self.get_layer("base_metal_addition")).insert(path)
            if self.pocket_margin > 0:
                m = round(self.pocket_margin / dbu)
                pocket = pya.Region(path.bbox().enlarged(m, m)) - path
                self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(pocket)
        else:
            self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(path)
        self.add_protection(pya.Region(path.bbox()).sized(round((self.margin + self.pocket_margin) / dbu)))
        for name, at_start in (("a", True), ("b", False)):
            pos, d = _end(pts, at_start, dbu)
            self.add_port(name, pos, d)
        self.refpoints["center"] = pya.DPoint(0, 0)

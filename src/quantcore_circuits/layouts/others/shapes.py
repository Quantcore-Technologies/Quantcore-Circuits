"""Primitive shapes from the QWri library: ``ArcPath`` (``Arc.lym`` "Arc"), ``SpiralPath`` (``spiral.lym``
"Spiral") and ``TextLabel`` (the chips' ``pya.TextGenerator`` labels: qubit numbers, "JS=…", "TOP=…nm"), drawn where
the legacy code draws (layer 1/0 → ``base_metal_gap_wo_grid``, i.e. etched); set ``metal`` to draw them as metal
(``base_metal_addition``) instead. Same pya calls as the legacy code. No ports.
"""

import math

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def legacy_arc_points(dbu, length, n, flag, arc_length, angle=3 * math.pi / 2, angle_begin=math.pi / 2):
    """Legacy ``Arc.arc`` from the origin (``length``/``arc_length`` in µm), points in dbu."""
    n = max(int(n), 32)  # legacy coerce
    length, arc_length = length / dbu, arc_length / dbu
    direction = -1 if flag else 1
    pts = []
    current_angle = angle_begin
    if length < arc_length:
        radius = arc_length / math.pi
        angle = float(direction * (math.pi * length)) / arc_length + angle_begin
    else:
        radius = length / math.pi
    da = (angle - current_angle) / n
    init = pya.Point(pya.DPoint(0.0, 0.0))
    r_point = pya.Point(pya.DPoint(init.x, init.y - radius))
    for _ in range(n + 1):
        pts.append(
            pya.Point(
                pya.DPoint(r_point.x + radius * math.cos(current_angle), r_point.y + radius * math.sin(current_angle))
            )
        )
        current_angle = (current_angle + float(direction * da)) % (2 * math.pi)
    return pts


def spiral_points(dbu, inner_r, outer_r, width, spacing, n):
    """Legacy ``Spiral.produce_impl`` (Archimedean, pitch ``width + spacing`` per turn), points in dbu."""
    n = max(int(n), 4)
    inner, outer = inner_r / dbu, outer_r / dbu
    da = math.pi * 2 / n
    dr = (width + spacing) / n / dbu
    pts, r, a = [], inner, 0.0
    while r < outer:
        pts.append(pya.Point.from_dpoint(pya.DPoint(r * math.cos(a), r * math.sin(a))))
        r += dr
        a = (a + da) % (math.pi * 2)
    return pts


class _Shape(Element):
    metal = Param(pdt.TypeBoolean, "Draw as metal (base_metal_addition) instead of etched", False)

    qcc_category = "shape"

    def _draw(self, region: pya.Region):
        layer = "base_metal_addition" if self.metal else "base_metal_gap_wo_grid"
        self.cell.shapes(self.get_layer(layer)).insert(region)
        self.add_protection(pya.Region(region.bbox()).sized(self.margin / self.layout.dbu))


class ArcPath(_Shape):
    """Circular arc path starting at the origin (legacy "Arc"): ``length`` ≥ ``arc_length`` → half circle of that
    length, shorter → a partial arc of radius ``arc_length / π``."""

    length = Param(pdt.TypeDouble, "Path length", 100, unit="μm")
    width = Param(pdt.TypeDouble, "Path width", 5, unit="μm")
    arc_length = Param(pdt.TypeDouble, "Arc length of a half circle", 100, unit="μm")
    clockwise = Param(pdt.TypeBoolean, "Turn clockwise (legacy flag)", False)
    arc_points = Param(pdt.TypeInt, "Points on the arc", 64)

    def build(self):
        dbu = self.layout.dbu
        pts = legacy_arc_points(dbu, self.length, self.arc_points, self.clockwise, self.arc_length)
        self._draw(pya.Region(pya.Path(pts, self.width / dbu)))


class SpiralPath(_Shape):
    """Archimedean spiral path from ``inner_r`` to ``outer_r`` (legacy "Spiral")."""

    inner_r = Param(pdt.TypeDouble, "Inner radius", 1, unit="μm")
    outer_r = Param(pdt.TypeDouble, "Outer radius", 10, unit="μm")
    width = Param(pdt.TypeDouble, "Path width", 1, unit="μm")
    spacing = Param(pdt.TypeDouble, "Spacing between turns", 1, unit="μm")
    turn_points = Param(pdt.TypeInt, "Points per turn", 64)

    def build(self):
        dbu = self.layout.dbu
        pts = spiral_points(dbu, self.inner_r, self.outer_r, self.width, self.spacing, self.turn_points)
        if len(pts) >= 2:
            self._draw(pya.Region(pya.Path(pts, self.width / dbu)))


class TextLabel(_Shape):
    """Text etched into the ground (legacy chips 01–06: ``TextGenerator.default_generator().text(text, dbu, mag,
    inv)`` inserted on 1/0, and on 3/0 which the fab export derives from 1/0).

    ``mag`` is the legacy magnification (200 for "JS=…" / "TOP=…nm", 300 for the qubit numbers); ``inverted`` = legacy
    ``inv``: the text's box with the letters cut out (metal letters in an etched box). The legacy origin is kept:
    the text starts at (0, 0), so the legacy insertion points apply unchanged.
    """

    text = Param(pdt.TypeString, "Text", "QC")
    mag = Param(pdt.TypeDouble, "Magnification (legacy TextGenerator mag)", 200)
    inverted = Param(pdt.TypeBoolean, "Inverted: box minus letters (legacy inv)", False)
    bias = Param(pdt.TypeDouble, "Bias (legacy TextGenerator bias)", 0, unit="μm")

    def build(self):
        gen = pya.TextGenerator.default_generator()
        region = gen.text(self.text, self.layout.dbu, self.mag, self.inverted, self.bias)
        if not region.is_empty():
            self._draw(region)

"""Alignment, dicing and e-beam markers (ported from QWri ``Marker.lym``, ``boundaryBox.lym``, the marker functions of
``components/python/draw.py`` and the e-beam marker of ``die_creator.py``).

Every DesignChip already draws the PDK die frame (:mod:`quantcore_circuits.layouts.chips.frame`: dicing Ls,
alignment grids, device ID), so these are *optional* cells for legacy-style layouts. They draw on the PDK marker
layers by default (PDK v2, 2026-11-03): dicing markers on ``marker_0`` (1000/0), alignment markers on ``marker_1``
(1001/0), the boundary box on ``chip_boundary`` (100/0). ``marker_layer`` takes any qcc layer name
(:data:`~quantcore_circuits.pdk.QCC_LAYERS`) or KQC layer name; ``base_metal_gap_wo_grid`` reproduces the legacy fab
output (layer 1/0, etched into the base metal). ``CornerMarker(hsq=True)`` is the legacy HSQ marker (chip_05: legacy
500/0 + 150/0 → qcc ``hsq`` (50/0) + ``hsq_boundary``). Geometry is computed in database units with the same pya
calls as the legacy code. Markers have no ports.
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.pdk import QCC_LAYERS


def corner_marker_region(dbu, thickness=50.0, width=500.0) -> pya.Region:
    """Legacy ``Marker.produce_impl``: an L of two half-arms (+x and −y from the origin), in dbu."""
    horz = pya.Region().insert(pya.Box(0, -thickness / dbu / 2, width / dbu / 2, 0))
    vert = pya.Region().insert(pya.Box(0, -width / dbu / 2, thickness / dbu / 2, 0))
    return horz + vert


def cross_marker_region(dbu, length=20.0, width=2.0) -> pya.Region:
    """Legacy ``draw.marker`` (20 µm cross, 2 µm arms by default), in dbu."""
    hl, hw = round(length / 2 / dbu), round(width / 2 / dbu)
    return pya.Region([pya.Box(-hw, -hl, hw, hl), pya.Box(-hl, -hw, hl, hw)])


def global_marker_region(dbu, size=50.0, dx=200.0, dy=400.0) -> pya.Region:
    """Legacy ``draw.global_marker``: six ``size`` squares at (±dx, 0) and (±dx, ±dy), in dbu."""
    h = size / 2
    out = pya.Region()
    for x in (-dx, dx):
        for y in (0.0, -dy, dy):
            out.insert(pya.Box(round((x - h) / dbu), round((y - h) / dbu), round((x + h) / dbu), round((y + h) / dbu)))
    return out


def dicing_marker_region(dbu, length=500.0, width=50.0) -> pya.Region:
    """Legacy ``draw.marker_dicing`` (500 µm cross with 50 µm arms by default), in dbu."""
    hl, hw = round(length / 2 / dbu), round(width / 2 / dbu)
    return pya.Region([pya.Box(-hw, -hl, hw, hl), pya.Box(-hl, -hw, hl, hw)])


def alignment_marker_region(dbu, chip_width=7500.0, chip_height=7500.0, size=5.0, pitch=100.0, inset=150.0):
    """Legacy ``draw.marker_align``: a 2×2 group of ``size`` squares (``pitch`` apart) near each chip corner. Frame:
    chip lower-left corner at the origin (as the legacy function). The right/top groups sit ``inset + pitch + size``
    from the chip edge (legacy: 150 + 105 µm), the left/bottom ones ``inset`` from it."""
    s, p = size / dbu, pitch / dbu
    out = pya.Region()
    x_left, y_bottom = inset / dbu, inset / dbu
    x_right = (chip_width - inset - pitch - size) / dbu
    y_top = (chip_height - inset - pitch - size) / dbu
    for x0, y0 in ((x_left, y_bottom), (x_left, y_top), (x_right, y_top), (x_right, y_bottom)):
        for dx, dy in ((0, 0), (0, p), (p, p), (p, 0)):
            out.insert(pya.Box(round(x0 + dx), round(y0 + dy), round(x0 + dx + s), round(y0 + dy + s)))
    return out


def ebeam_marker_region(dbu, size=600.0, hole=20.0, offset=100.0) -> pya.Region:
    """E-beam marker of legacy ``die_creator.create_die``: a ``size`` window etched around four ``hole`` squares of
    metal at (±offset, ±offset), in dbu."""
    container = pya.Region(pya.Box(-size / dbu / 2, -size / dbu / 2, size / dbu / 2, size / dbu / 2))
    square = pya.Region(pya.Box(-hole / dbu / 2, -hole / dbu / 2, hole / dbu / 2, hole / dbu / 2))
    for x, y in ((-offset, -offset), (-offset, offset), (offset, offset), (offset, -offset)):
        container -= square.transformed(pya.Trans(0, False, x / dbu, y / dbu))
    return container


def boundary_box_region(dbu, size=5000.0, width=5.0) -> pya.Region:
    """Legacy ``BoundBox.produce_impl``: the ``size`` square plus a small cross at each corner, in dbu."""
    box = pya.Box(-size / dbu / 2, -size / dbu / 2, +size / dbu / 2, size / dbu / 2)
    horz = pya.Region().insert(pya.Box(-width / dbu, -width / dbu / 2, width / dbu, width / dbu / 2))
    vert = pya.Region().insert(pya.Box(-width / dbu / 2, -width / dbu, width / dbu / 2, width / dbu))
    marker = horz + vert
    marker.merge()
    out = pya.Region().insert(box)
    half = int(size / dbu / 2)
    for x, y in ((-half, -half), (-half, half), (half, half), (half, -half)):
        out.insert(marker.transformed(pya.Trans(x, y)))
    return out


class _Marker(Element):
    marker_layer = Param(
        pdt.TypeString,
        "Layer: qcc name (marker_0..3, chip_boundary, ...) or KQC name (base_metal_gap_wo_grid = legacy etch)",
        "marker_1",
    )

    qcc_category = "marker"

    def _etch(self, region: pya.Region):
        if self.marker_layer in QCC_LAYERS:
            self.cell.shapes(self.layout.layer(QCC_LAYERS[self.marker_layer])).insert(region)
            return
        self.cell.shapes(self.get_layer(self.marker_layer)).insert(region)
        if self.marker_layer.startswith("base_metal"):
            self.add_protection(pya.Region(region.bbox()).sized(self.margin / self.layout.dbu))


class CornerMarker(_Marker):
    """L-shaped chip-corner alignment marker (legacy ``Marker``); ``hsq=True`` draws the HSQ variant."""

    thickness = Param(pdt.TypeDouble, "Arm thickness", 50, unit="μm")
    width = Param(pdt.TypeDouble, "Marker size (full cross width; each arm is width / 2 long)", 500, unit="μm")
    hsq = Param(pdt.TypeBoolean, "HSQ marker (qcc hsq + hsq_boundary layers instead of the base-metal etch)", False)

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm), legacy ``Marker.lym`` ``fab_l``: the marker cross itself (none for the HSQ
        variant, whose ``fab_l`` the chips set to the HSQ write-field layer 150/0)."""
        from quantcore_circuits.layouts.others.keepout import DBU, dpolygons, full_params  # pylint: disable=C0415

        p = full_params(cls, params)
        return [] if p["hsq"] else dpolygons(corner_marker_region(DBU, p["thickness"], p["width"]))

    def build(self):
        region = corner_marker_region(self.layout.dbu, self.thickness, self.width)
        if self.hsq:
            self.cell.shapes(self.layout.layer(QCC_LAYERS["hsq"])).insert(region)
            self.cell.shapes(self.layout.layer(QCC_LAYERS["hsq_boundary"])).insert(region)
        else:
            self._etch(region)


class CrossMarker(_Marker):
    """Small alignment cross (legacy ``draw.marker``, used beside the ``cpwe`` bond pads)."""

    length = Param(pdt.TypeDouble, "Cross length", 20, unit="μm")
    width = Param(pdt.TypeDouble, "Arm width", 2, unit="μm")

    def build(self):
        self._etch(cross_marker_region(self.layout.dbu, self.length, self.width))


class GlobalMarker(_Marker):
    """Global alignment marker: six squares in two columns (legacy ``draw.global_marker``)."""

    size = Param(pdt.TypeDouble, "Square size", 50, unit="μm")
    dx = Param(pdt.TypeDouble, "Column offset from the centre", 200, unit="μm")
    dy = Param(pdt.TypeDouble, "Row pitch", 400, unit="μm")

    def build(self):
        self._etch(global_marker_region(self.layout.dbu, self.size, self.dx, self.dy))


class DicingMarker(_Marker):
    """Dicing cross (legacy ``draw.marker_dicing``)."""

    length = Param(pdt.TypeDouble, "Cross length", 500, unit="μm")
    width = Param(pdt.TypeDouble, "Arm width", 50, unit="μm")
    marker_layer = Param(pdt.TypeString, "Layer (qcc or KQC name)", "marker_0")

    def build(self):
        self._etch(dicing_marker_region(self.layout.dbu, self.length, self.width))


class AlignmentMarkers(_Marker):
    """E-beam alignment squares at the four chip corners (legacy ``draw.marker_align``); origin = chip lower-left."""

    chip_width = Param(pdt.TypeDouble, "Chip width", 7500, unit="μm")
    chip_height = Param(pdt.TypeDouble, "Chip height", 7500, unit="μm")
    size = Param(pdt.TypeDouble, "Square size", 5, unit="μm")
    pitch = Param(pdt.TypeDouble, "Square pitch in a group", 100, unit="μm")
    inset = Param(pdt.TypeDouble, "Inset of the lower-left group from the chip corner", 150, unit="μm")

    def build(self):
        self._etch(
            alignment_marker_region(
                self.layout.dbu, self.chip_width, self.chip_height, self.size, self.pitch, self.inset
            )
        )


class EbeamMarker(_Marker):
    """E-beam marker: four metal squares in an etched window (legacy ``die_creator``)."""

    size = Param(pdt.TypeDouble, "Window size", 600, unit="μm")
    hole = Param(pdt.TypeDouble, "Square size", 20, unit="μm")
    offset = Param(pdt.TypeDouble, "Square offset from the centre (x and y)", 100, unit="μm")

    def build(self):
        self._etch(ebeam_marker_region(self.layout.dbu, self.size, self.hole, self.offset))


class BoundaryBox(_Marker):
    """Chip boundary square with corner crosses (legacy ``BoundBox``, layer 9/0 → qcc ``chip_boundary``)."""

    size = Param(pdt.TypeDouble, "Box size", 5000, unit="μm")
    width = Param(pdt.TypeDouble, "Corner cross half-length", 5, unit="μm")

    marker_layer = Param(pdt.TypeString, "Layer (qcc or KQC name)", "chip_boundary")

    def build(self):
        self._etch(boundary_box_region(self.layout.dbu, self.size, self.width))

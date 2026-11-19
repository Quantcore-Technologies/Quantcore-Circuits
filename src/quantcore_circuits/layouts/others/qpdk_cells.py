"""Cells re-implemented from gdsfactory/quantum-rf-pdk (QPDK, MIT licence, © the QPDK authors): the geometry is
re-drawn here as KQC Elements in µm (QPDK was read, never imported or run).

* :class:`NeckTermination` — ``qpdk/cells/vortex.py::neck_termination`` (Shulga et al. 2026): a CPW that tapers into
  a narrow neck shorted to ground inside an etched window lined with flux-trapping holes.
* :class:`GatemonCoupler` — ``qpdk/cells/gatemon.py::gatemon_coupler``: a straight CPW with a capacitive reference
  port ``qubit`` for a :class:`~quantcore_circuits.layouts.qubits.qpdk_cells.Gatemon` island.
* :class:`HyperbolicVertexCoupler` — ``qpdk/cells/hyperbolic.py::hyperbolic_vertex_coupler`` (Kollár et al. 2019): a
  disk cut into ``q`` pie-slice pins with a CPW lead per pin.

QPDK draws metal on ``M1_DRAW`` and the etch on ``M1_ETCH`` and exports ``M1_ETCH − M1_DRAW``; here that difference
is drawn on ``base_metal_gap_wo_grid`` (PDK v2 fab 1/0). QPDK port names are kept (``o1``, ``o2``, ``qubit``, …).
CPW widths at the ports are the element's ``a``/``b`` (QPDK ``cpw``: 10/6 µm, the KQC defaults).
"""

from __future__ import annotations

import math

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def _box(dbu, x0, y0, x1, y1) -> pya.Box:
    return pya.DBox(x0, y0, x1, y1).to_itype(dbu)


# ---- neck termination -------------------------------------------------------------------------------------------
def neck_profile(width, neck_width, taper_length, neck_length, taper_shape="linear"):
    """QPDK ``neck_termination`` centre-conductor width profile [(x, w), ...] from the port (x = 0) to the short."""
    if taper_shape == "linear":
        profile = [(0.0, width), (taper_length, neck_width)]
    else:
        n = 41
        profile = [
            (
                taper_length * i / (n - 1),
                neck_width + (width - neck_width) * (1 + math.cos(math.pi * i / (n - 1))) / 2,
            )
            for i in range(n)
        ]
    profile.append((taper_length + neck_length, neck_width))
    return profile


def neck_trap_hole_centres(window_length, window_width, rows, size, pitch, offset, keepout):
    """Centres of QPDK's flux-trap holes around the window (one square grid, open at the port end)."""
    if not rows:
        return []
    half = size / 2
    x0 = window_length + offset + half
    y0 = window_width / 2 + offset + half
    n_inner_x = math.floor((x0 - half) / pitch)
    n_inner_y = math.floor((y0 - half) / pitch)
    out = []
    for i in range(-n_inner_x, rows):
        x = x0 + i * pitch
        for k in range(-n_inner_y, rows):
            y_abs = y0 + k * pitch
            if i < 0 and k < 0:
                continue  # inside the window's footprint
            if i >= 0 and y_abs < (keepout + size) / 2:
                continue  # current path from the neck into the ground
            out += [(x, y_abs), (x, -y_abs)]
    return out


class NeckTermination(Element):
    """Shorted CPW end through a taper and a narrow neck in an etched window (QPDK ``neck_termination``).

    Re-implemented from gdsfactory/quantum-rf-pdk ``qpdk/cells/vortex.py`` (MIT). Port ``o1`` at the origin faces −x
    (CPW ``a``/``b``); the window runs from x = 0 to ``taper_length + neck_length`` (``window_width`` across), the
    centre conductor tapers from ``a`` to ``neck_width`` over ``taper_length`` and the neck joins the ground at the
    window's far edge (refpoints ``neck_start``, ``neck_end`` = the short). ``trap_hole_rows`` rows of square holes
    line the two long sides and the far end, with a hole-free column ``trap_hole_keepout`` wide on the neck axis;
    the ring is open at the port end. LOM: the taper + neck is a short series line and the neck inductance to
    ground at ``neck_end``.
    """

    taper_length = Param(pdt.TypeDouble, "Taper length", 100, unit="μm")
    taper_shape = Param(pdt.TypeString, "Taper profile", "linear", choices=["linear", "smooth"])
    neck_width = Param(pdt.TypeDouble, "Neck width", 2, unit="μm")
    neck_length = Param(pdt.TypeDouble, "Neck length", 325, unit="μm")
    window_width = Param(pdt.TypeDouble, "Etched window width (across the line)", 380, unit="μm")
    trap_hole_rows = Param(pdt.TypeInt, "Rows of flux-trap holes around the window (0 = none)", 4)
    trap_hole_size = Param(pdt.TypeDouble, "Trap hole side", 4, unit="μm")
    trap_hole_pitch = Param(pdt.TypeDouble, "Trap hole pitch", 5.5, unit="μm")
    trap_hole_offset = Param(pdt.TypeDouble, "Ground strip between window and first hole row", 6, unit="μm")
    trap_hole_keepout = Param(pdt.TypeDouble, "Hole-free column on the neck axis at the far end", 24, unit="μm")

    qcc_category = "termination"

    def _check(self):
        for name in ("taper_length", "neck_width", "neck_length"):
            if not getattr(self, name) > 0:
                return f"{name} must be positive, got {getattr(self, name)}"
        if self.neck_width >= self.a:
            return f"neck_width ({self.neck_width}) must be smaller than the CPW width a ({self.a})"
        if self.window_width < self.a + 2 * self.b:
            return f"window_width ({self.window_width}) must be at least the CPW footprint ({self.a + 2 * self.b})"
        if self.trap_hole_rows < 0:
            return f"trap_hole_rows must be >= 0, got {self.trap_hole_rows}"
        if self.trap_hole_rows and not 0 < self.trap_hole_size < self.trap_hole_pitch:
            return "trap_hole_size must be positive and smaller than trap_hole_pitch"
        if self.trap_hole_rows and (self.trap_hole_offset < 0 or self.trap_hole_keepout <= self.neck_width):
            return "trap_hole_offset must be >= 0 and trap_hole_keepout must exceed neck_width"
        return ""

    def build(self):
        problem = self._check()
        if problem:
            self.raise_error_on_cell(f"NeckTermination: {problem}")
        dbu = self.layout.dbu
        length = self.taper_length + self.neck_length
        profile = neck_profile(self.a, self.neck_width, self.taper_length, self.neck_length, self.taper_shape)
        conductor = [pya.DPoint(x, -w / 2) for x, w in profile] + [pya.DPoint(x, w / 2) for x, w in reversed(profile)]
        window = pya.Region(_box(dbu, 0, -self.window_width / 2, length, self.window_width / 2))
        etch = window - pya.Region(pya.DPolygon(conductor).to_itype(dbu))
        h = self.trap_hole_size / 2
        for x, y in neck_trap_hole_centres(
            length,
            self.window_width,
            self.trap_hole_rows,
            self.trap_hole_size,
            self.trap_hole_pitch,
            self.trap_hole_offset,
            self.trap_hole_keepout,
        ):
            etch.insert(_box(dbu, x - h, y - h, x + h, y + h))
        etch.merge()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(self.margin / dbu))
        self.add_port("o1", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.refpoints["neck_start"] = pya.DPoint(self.taper_length, 0)
        self.refpoints["neck_end"] = pya.DPoint(length, 0)


# ---- gatemon coupler --------------------------------------------------------------------------------------------
class GatemonCoupler(Element):
    """Straight CPW ``o1`` → ``o2`` with a capacitive island reference port ``qubit`` (QPDK ``gatemon_coupler``).

    Re-implemented from gdsfactory/quantum-rf-pdk ``qpdk/cells/gatemon.py`` (MIT). The line runs along +x from ``o1``
    (origin, faces −x) to ``o2`` (x = ``length``, faces +x), CPW ``a``/``b``. Port ``qubit`` sits
    ``pocket_gap_top`` beyond the conductor edge at ``coupling_position`` on the ``qubit_side`` and faces away from
    the line: snap a :class:`Gatemon` ``readout`` port to it, and the gatemon's pocket opens into the line's gap
    there. No metal crosses that gap; ``coupling_capacitance`` (fF, QPDK's nominal 5.4 fF, not an extraction) is
    the C between the line at ``coupling_position`` and the island for the LOM model.
    """

    length = Param(pdt.TypeDouble, "Line length", 600, unit="μm")
    coupling_position = Param(pdt.TypeDouble, "Island centre measured from o1", 200, unit="μm")
    island_width = Param(pdt.TypeDouble, "Island width (reference plane)", 150, unit="μm")
    pocket_gap_top = Param(pdt.TypeDouble, "Island edge to conductor edge", 40, unit="μm")
    qubit_side = Param(pdt.TypeString, "Island side of the line", "bottom", choices=["bottom", "top"])
    coupling_capacitance = Param(pdt.TypeDouble, "Nominal line-island capacitance (LOM)", 5.4, unit="fF")

    qcc_category = "coupler"

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """``qubit`` is a reference plane, not a CPW end: a = island width, b = the island-to-line clearance."""
        return {"qubit": (float(params.get("island_width", 150)), float(params.get("pocket_gap_top", 40)))}

    def build(self):
        if not 0 < self.coupling_position < self.length or min(self.island_width, self.pocket_gap_top) <= 0:
            self.raise_error_on_cell("GatemonCoupler: invalid coupling reference plane")
        if self.coupling_capacitance < 0:
            self.raise_error_on_cell("GatemonCoupler: coupling_capacitance must be >= 0")
        dbu = self.layout.dbu
        a, b = self.a, self.b
        gaps = pya.Region(_box(dbu, 0, a / 2, self.length, a / 2 + b))
        gaps.insert(_box(dbu, 0, -a / 2 - b, self.length, -a / 2))
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))
        self.add_port("o1", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.add_port("o2", pya.DPoint(self.length, 0), pya.DVector(1, 0))
        side = -1 if self.qubit_side == "bottom" else 1
        self.add_port(
            "qubit", pya.DPoint(self.coupling_position, side * (a / 2 + self.pocket_gap_top)), pya.DVector(0, side)
        )
        self.refpoints["coupling_point"] = pya.DPoint(self.coupling_position, 0)


# ---- hyperbolic vertex coupler ----------------------------------------------------------------------------------
def _unit(angle_deg: float) -> pya.DVector:
    a = math.radians(angle_deg)
    return pya.DVector(math.cos(a), math.sin(a))


def _snap(v: float, grid: float = 1e-3) -> float:
    return round(v / grid) * grid


def vertex_coupler_port_offsets(q, rotation, pin_radius, lead_length):
    """QPDK ``_vertex_coupler_port_offsets``: lead ends at ``pin_radius + lead_length``, snapped to the 1 nm grid."""
    reach = pin_radius + lead_length
    return [
        (_snap(_unit(rotation + 360 * k / q).x * reach), _snap(_unit(rotation + 360 * k / q).y * reach))
        for k in range(q)
    ]


class HyperbolicVertexCoupler(Element):
    """``q``-pin capacitive disk coupler at a hyperbolic-lattice vertex (QPDK ``hyperbolic_vertex_coupler``).

    Re-implemented from gdsfactory/quantum-rf-pdk ``qpdk/cells/hyperbolic.py`` (MIT). A metal disk of
    ``pin_radius`` is cut into ``q`` pie-slice pins by radial gaps ``pin_gap`` wide (centred between the pins) and
    isolated from ground by a ``ground_gap`` ring; pin ``k`` points along ``rotation + 360 k / q`` degrees and feeds
    a CPW lead (``a``/``b``) that overlaps the disk by ``a`` and ends at port ``o<k+1>``, ``lead_length`` beyond the
    rim (snapped to 1 nm), facing away from the centre (generally not Manhattan). The disk is centred at the
    origin (refpoint ``center``).
    """

    q = Param(pdt.TypeInt, "Number of pins", 3)
    rotation = Param(pdt.TypeDouble, "Direction of pin 0", 0, unit="°")
    pin_radius = Param(pdt.TypeDouble, "Disk radius", 40, unit="μm")
    pin_gap = Param(pdt.TypeDouble, "Radial gap between pins", 4, unit="μm")
    ground_gap = Param(pdt.TypeDouble, "Disk to ground clearance", 6, unit="μm")
    lead_length = Param(pdt.TypeDouble, "CPW lead beyond the disk", 20, unit="μm")

    qcc_category = "coupler"

    def build(self):
        q, r, width, gap = int(self.q), self.pin_radius, self.a, self.b
        if q < 2:
            self.raise_error_on_cell(f"HyperbolicVertexCoupler: q must be at least 2, got {q}")
        pin_chord = 2 * r * math.sin(math.pi / q) - self.pin_gap
        inner_chord = 2 * (r - width) * math.sin(math.pi / q) - self.pin_gap
        if min(pin_chord, inner_chord) <= width:
            self.raise_error_on_cell(
                f"HyperbolicVertexCoupler: pins of a {q}-pin coupler with pin_radius={r} µm are narrower "
                f"({min(pin_chord, inner_chord):.1f} µm) than the lead ({width} µm)"
            )
        dbu = self.layout.dbu

        def strip(end: pya.DVector, length: float, w: float) -> pya.Region:
            start = end * (1 - length / end.length())
            return pya.Region(
                pya.DPath([pya.DPoint(start.x, start.y), pya.DPoint(end.x, end.y)], w).polygon().to_itype(dbu)
            )

        def disk(radius: float) -> pya.Region:
            return pya.Region(pya.DPolygon.ellipse(pya.DBox(-radius, -radius, radius, radius), 128).to_itype(dbu))

        metal = disk(r)
        for k in range(q):
            metal -= strip(_unit(self.rotation + 360 * (k + 0.5) / q) * 2 * r, 2 * r, self.pin_gap)
        clearance = disk(r + self.ground_gap)
        ports = []
        for k, (x, y) in enumerate(vertex_coupler_port_offsets(q, self.rotation, r, self.lead_length)):
            end = pya.DVector(x, y)
            reach = end.length() - r + width
            metal += strip(end, reach, width)
            clearance += strip(end, reach, width + 2 * gap)
            ports.append((f"o{k + 1}", pya.DPoint(x, y), end / end.length()))
        metal.merge()
        etch = (clearance - metal).merged()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(self.margin / dbu))
        for name, pos, direction in ports:
            self.add_port(name, pos, direction)
        self.refpoints["center"] = pya.DPoint(0, 0)

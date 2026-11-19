"""Cells re-implemented from sqdlab/SQDMetal (Apache-2.0, © Prasanna Pakkiam and the SQDMetal authors): the
geometry is re-drawn here as KQC Elements in µm with pya (SQDMetal was read, never imported or run).

* :class:`SmoothCapacitorSemicircle` — ``SQDMetal/Comps/Capacitors.py::Smooth_Capacitor_Semicircle`` (the
  2_transmons_wRes_comp notebook imports it from the older ``Comps/Test_capacitor.py``): a rectangular pad with a
  semicircular bite that wraps a qubit pad end, placed on a qubit pin.
"""

from __future__ import annotations

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


class SmoothCapacitorSemicircle(Element):
    """Coupling pad with a semicircular bite, placed on a qubit pin (SQDMetal ``Smooth_Capacitor_Semicircle``).

    Re-implemented from sqdlab/SQDMetal ``SQDMetal/Comps/Capacitors.py`` (Apache-2.0), same option names in µm.
    Frame: the origin is the target pin (SQDMetal ``pin_inputs.start_pin``) and port ``target`` there faces −x —
    snap it to the qubit pin (``snap="target", to="Q1.top_right_pin"``) to get SQDMetal's placement: the cell is
    turned by the pin normal, and ``orientation`` turns the drawing about the pin on top of that (SQDMetal applies
    both). Unrotated, the ``rect_length`` × ``rect_width`` pad lies along +x with its back edge at
    ``100 − rect_length − circle_offset`` µm and a circle of ``semi_radius`` cut out at x = 100 (SQDMetal shifts the
    drawing so the bite's centre is 100 µm from the pin); the pad and the ``gap_back`` / ``gap_side`` /
    ``gap_front`` clearance box are filleted with ``fillet_radius``. The pad is metal on ``base_metal_addition``
    (it sits inside a qubit's pocket), the clearance box minus the pad is etched.

    SQDMetal's pin ``a`` sits inside the pad (x = ``gap_front`` + the shift) with its normal towards the bite; its
    ``ResonatorMeanderPinPin`` leaves the pad from the back. Here port ``a`` is on the pad's back edge facing away
    from the bite, ``lead_length`` further with a ``trace_width`` CPW lead (metal + ``b`` gaps), so a route starts
    on the pad; set ``lead_length`` to reach the pocket edge when the pad sits in a pocket.
    """

    rect_width = Param(pdt.TypeDouble, "Pad width (across)", 190, unit="μm")
    rect_length = Param(pdt.TypeDouble, "Pad length (towards the bite)", 170, unit="μm")
    semi_radius = Param(pdt.TypeDouble, "Semicircle radius", 61, unit="μm")
    circle_offset = Param(pdt.TypeDouble, "Semicircle centre beyond the pad front", -10, unit="μm")
    gap_side = Param(pdt.TypeDouble, "Clearance at the sides", 25, unit="μm")
    gap_front = Param(pdt.TypeDouble, "Clearance towards the bite", 25, unit="μm")
    gap_back = Param(pdt.TypeDouble, "Clearance behind the pad", 25, unit="μm")
    trace_width = Param(pdt.TypeDouble, "Width of the trace at port a", 10, unit="μm")
    orientation = Param(pdt.TypeDouble, "Rotation of the drawing about the target pin", 0, unit="°")
    fillet_radius = Param(pdt.TypeDouble, "Corner fillet radius (0 = sharp)", 10, unit="μm")
    fillet_resolution = Param(pdt.TypeInt, "Fillet points per quarter circle", 16)
    lead_length = Param(pdt.TypeDouble, "CPW lead from the pad's back edge to port a", 0, unit="μm")

    qcc_category = "capacitor"

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """Port ``a``: the lead (``trace_width``, element ``b``); ``target``: a placement reference, not a CPW."""
        tw, b = float(params.get("trace_width", 10)), float(params.get("b", 6))
        return {"a": (tw, b), "target": (tw, b)}

    def build(self):
        dbu = self.layout.dbu
        length, width, r = self.rect_length, self.rect_width, self.semi_radius
        if min(length, width) <= 0 or r < 0:
            self.raise_error_on_cell("SmoothCapacitorSemicircle: rect_length/rect_width must be positive")
        shift = 100.0 - (length + self.circle_offset)  # SQDMetal: translate by -(rect_length + circle_offset - 0.1 mm)
        n = 4 * max(int(self.fillet_resolution), 1)
        pad = pya.DPolygon(pya.DBox(0, -width / 2, length, width / 2))
        gap = pya.DPolygon(
            pya.DBox(-self.gap_back, -width / 2 - self.gap_side, length + self.gap_front, width / 2 + self.gap_side)
        )
        circle = pya.DPolygon.ellipse(
            pya.DBox(length + self.circle_offset - r, -r, length + self.circle_offset + r, r), 128
        )
        pad_region = pya.Region(pad.to_itype(dbu)) - pya.Region(circle.to_itype(dbu))
        gap_region = pya.Region(gap.to_itype(dbu))
        if self.fillet_radius > 0:
            fr = self.fillet_radius / dbu
            pad_region = pad_region.rounded_corners(fr, fr, n)
            gap_region = gap_region.rounded_corners(fr, fr, n)
        tw, b = self.trace_width, self.b
        lead_metal = pya.Region(pya.DBox(-self.lead_length, -tw / 2, 0, tw / 2).to_itype(dbu))
        lead_gaps = pya.Region(pya.DBox(-self.lead_length, -tw / 2 - b, 0, tw / 2 + b).to_itype(dbu)) - lead_metal
        to_cell = pya.DCplxTrans(1, self.orientation, False, 0, 0) * pya.DCplxTrans(shift, 0)
        itrans = to_cell.to_itrans(dbu)
        metal = (pad_region + (lead_metal if self.lead_length > 0 else pya.Region())).transformed(itrans).merged()
        gaps = (gap_region + (lead_gaps if self.lead_length > 0 else pya.Region())).transformed(itrans) - metal
        self.cell.shapes(self.get_layer("base_metal_addition")).insert(metal)
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps.merged())
        self.add_protection((pya.Region(gaps.bbox()) + pya.Region(metal.bbox())).sized(self.margin / dbu))
        rot = pya.DCplxTrans(1, self.orientation, False, 0, 0)
        self.add_port("a", to_cell * pya.DPoint(-self.lead_length, 0), rot * pya.DVector(-1, 0))
        self.add_port("target", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.refpoints["semicircle_center"] = to_cell * pya.DPoint(length + self.circle_offset, 0)
        self.refpoints["pad_center"] = to_cell * pya.DPoint(length / 2, 0)

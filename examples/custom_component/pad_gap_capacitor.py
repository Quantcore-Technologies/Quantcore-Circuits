"""A custom component for the Quantcore library: two pads facing across a gap in a CPW line (a series capacitor).

Copy this file into ``src/quantcore_circuits/layouts/others/`` (any folder of ``layouts/`` works; file names starting
with ``_`` are skipped), restart KLayout, and ``PadGapCapacitor`` is in the panel (library ``quantcore``, class
``capacitor``), in ``qcc components``, in design.json / design.py, in the DRC, the fab export and the LOM.
See kplugin/TUTORIAL_q1_r1.md, "Make your own component".
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


class PadGapCapacitor(Element):
    """Two pads facing across ``cap_gap`` in a CPW line; ports ``a`` (−x) and ``b`` (+x)."""

    # the class: "qubit", "junction", "coupler", "capacitor", "resonator", "launcher", "termination", "waveguide", ...
    # (quantcore_circuits.layouts.catalog.CATEGORIES). The panel's class filter, the targets offered, the DRC and the
    # fab export read it.
    qcc_category = "capacitor"

    # parameters: the panel's table shows them (name, default, unit); design.json "params" stores only changed ones
    pad_width = Param(pdt.TypeDouble, "Pad width (across the line)", 60, unit="μm")
    pad_length = Param(pdt.TypeDouble, "Pad length (along the line)", 40, unit="μm")
    cap_gap = Param(pdt.TypeDouble, "Gap between the pads", 4, unit="μm")
    ground_gap = Param(pdt.TypeDouble, "Clearance from the pads to ground", 20, unit="μm")

    def build(self):
        dbu = self.layout.dbu
        w, pl, g, c = self.pad_width, self.pad_length, self.cap_gap, self.ground_gap
        length = 2 * pl + g
        clear = pya.DBox(0, -(w / 2 + c), length, w / 2 + c)  # the etched window around both pads
        pads = pya.Region([pya.DBox(0, -w / 2, pl, w / 2).to_itype(dbu),
                           pya.DBox(pl + g, -w / 2, length, w / 2).to_itype(dbu)])
        # negative mask: draw what is etched (the gap), on the layer every Quantcore / KQC cell uses
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(pya.Region(clear.to_itype(dbu)) - pads)
        self.add_protection(pya.Region(clear.enlarged(self.margin, self.margin).to_itype(dbu)))  # no cheese here
        # ports: position and the direction pointing out of the component (a route leaves / arrives along it)
        self.add_port("a", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.add_port("b", pya.DPoint(length, 0), pya.DVector(1, 0))


# ---- the LOM model (optional): without one, Run LOM notes that the component has no circuit model ----------------
from quantcore_circuits.lom import estimates as est  # noqa: E402
from quantcore_circuits.lom.fragment import Element as LomElement  # noqa: E402
from quantcore_circuits.lom.fragment import Fragment, cell_params, register_lom  # noqa: E402


@register_lom("PadGapCapacitor")  # by class name: subclasses inherit the model
def pad_gap_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """Series C between ``a`` and ``b`` (two plates facing across the gap, coplanar estimate)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    w, g = float(p.get("pad_width", 60)), float(p.get("cap_gap", 4))
    c_ff = est.coplanar_coupling(w, float(p.get("pad_length", 40)), float(p.get("pad_length", 40)), g, eps)
    return Fragment(
        nodes={"a": {"island": f"{name}.a"}, "b": {"island": f"{name}.b"}},  # one conductor per pad
        port_nodes={"a": "a", "b": "b"},  # which conductor each port touches
        elements=[LomElement(f"C_{name}", "C", ("a", "b"), est.cap(c_ff, "rough", "pads facing across cap_gap"))],
    )

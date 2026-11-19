"""Two-pad transmon ported from the QWri ``Transmon`` PCell.

The legacy cell only has a positive drawing (metal on legacy layer 1/0): two ``pad_thickness`` × ``pad_height`` pads
facing each other across ``gap`` (the junction gap), each with a 10 µm lead of width 10 µm on the outside. Here the
metal goes to ``base_metal_addition`` (metal wins over gaps, so the cell also works inside another element's gap)
and, with ``pocket_margin`` > 0, the cell etches its own pocket: from lead end to lead end in x and ``pocket_margin``
beyond the pads in y, so the leads end on the pocket edge where the ports are.

Ports (outward): ``left`` (−x) and ``right`` (+x) at the lead ends, CPW width ``a`` (the legacy read-only
``path_width`` = 10 µm). The junction spans the gap: refpoints ``port_squid_a`` (left pad edge) / ``port_squid_b``
(right pad edge) for the simulation builder's junction port.

Junction (design decisions #6 / #21): ``junction_type`` ``"No Squid"`` (default, as the legacy cell: nothing drawn, the
refpoints mark the gap) or a trilayer cell — ``"Quantcore Junction"`` / ``"Quantcore Squid"`` (PDK junctions) or
``"Trilayer Junction"`` / ``"Trilayer Squid"`` — placed across the pad gap (window = the gap between the pad faces,
≤ 32 µm wide, CLEARER on; :func:`~quantcore_circuits.layouts.junctions.trilayer.place_trilayer`), sized by
``junction_params`` (``{"lj_nH": …}`` on the PDK rule, or explicit finger widths). ``"Sim"`` (set by simulation
builds) draws nothing, like ``"No Squid"``.
"""

import json

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def two_pad_metal(dbu, pad_thickness, pad_height, gap, path_width, lead_length=10.0):
    """Legacy ``Transmon.produce_impl`` (= ``Coupler.produce_impl``) metal, in dbu."""
    gap = 1 if gap <= 0 else gap  # legacy coerce_parameters_impl
    left_pad = pya.Box((-gap / 2 - pad_thickness) / dbu, -pad_height / 2 / dbu, (-gap / 2) / dbu, pad_height / 2 / dbu)
    right_pad = pya.Box(gap / 2 / dbu, -pad_height / 2 / dbu, (gap / 2 + pad_thickness) / dbu, pad_height / 2 / dbu)
    metal = pya.Region(left_pad)
    if path_width > 0:
        left_path = pya.Box(
            (-gap / 2 - pad_thickness - lead_length) / dbu,
            -path_width / 2 / dbu,
            (-gap / 2 - pad_thickness) / dbu,
            path_width / 2 / dbu,
        )
        right_path = pya.Box(
            (gap / 2 + pad_thickness) / dbu,
            -path_width / 2 / dbu,
            (gap / 2 + pad_thickness + lead_length) / dbu,
            path_width / 2 / dbu,
        )
        metal.insert([right_pad, left_path, right_path])
    else:
        metal.insert(right_pad)
    return metal


class TwoPadTransmon(Element):
    """Floating two-pad transmon (legacy ``Transmon``); ports ``left`` / ``right`` at the lead ends.

    Like the legacy ``Transmon.lym`` it draws only the pads on 1/0 and no junction (no 2/0, 4/0 or 50/0): the
    refpoints ``port_squid_a`` / ``port_squid_b`` mark the junction gap, where a junction cell (e.g. ``Trilayer
    Junction``) must be placed for fab. Its LOM model assumes that junction."""

    pad_thickness = Param(pdt.TypeDouble, "Pad thickness (along the axis)", 20, unit="μm")
    pad_height = Param(pdt.TypeDouble, "Pad height", 30, unit="μm")
    gap = Param(pdt.TypeDouble, "Gap between the pads (junction gap)", 10, unit="μm")
    lead_length = Param(pdt.TypeDouble, "Lead length outside each pad", 10, unit="μm")
    pocket_margin = Param(pdt.TypeDouble, "Pocket beyond the pads in y (0 = no pocket, legacy)", 20, unit="μm")
    junction_type = Param(
        pdt.TypeString,
        "Junction across the gap: none (legacy) or a trilayer cell",
        "No Squid",
        choices=["No Squid", "Quantcore Junction", "Quantcore Squid", "Trilayer Junction", "Trilayer Squid", "Sim"],
    )
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict, e.g. lj_nH)", "{}")

    qcc_category = "qubit"
    qcc_junction = True

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """design.json params → PCell params: ``junction_params`` dict → JSON (validated)."""
        from quantcore_circuits.layouts.junctions.trilayer import _json_dict  # pylint: disable=C0415

        params = dict(params)
        jp = params.get("junction_params")
        if isinstance(jp, dict):
            params["junction_params"] = json.dumps(jp, sort_keys=True)
        elif isinstance(jp, str):
            _json_dict(jp)
        return params

    def _x_end(self) -> float:
        gap = 1 if self.gap <= 0 else self.gap
        return gap / 2 + self.pad_thickness + (self.lead_length if self.a > 0 else 0)

    def build(self):
        dbu = self.layout.dbu
        metal = two_pad_metal(dbu, self.pad_thickness, self.pad_height, self.gap, self.a, self.lead_length)
        self.cell.shapes(self.get_layer("base_metal_addition")).insert(metal)
        x_end = self._x_end()
        outline = pya.Region(metal.bbox())
        if self.pocket_margin > 0:
            y = self.pad_height / 2 + self.pocket_margin
            pocket = pya.Region(pya.DBox(-x_end, -y, x_end, y).to_itype(dbu))
            gaps = pocket - metal
            self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
            outline = pocket
        self.add_protection(outline.sized(self.margin / dbu))
        self.add_port("left", pya.DPoint(-x_end, 0), pya.DVector(-1, 0))
        self.add_port("right", pya.DPoint(x_end, 0), pya.DVector(1, 0))
        if self.qcc_junction:
            gap = 1 if self.gap <= 0 else self.gap
            self.refpoints["port_squid_a"] = pya.DPoint(-gap / 2, 0)
            self.refpoints["port_squid_b"] = pya.DPoint(gap / 2, 0)
            jtype = str(getattr(self, "junction_type", "No Squid") or "No Squid")
            if jtype not in ("No Squid", "Sim"):
                from quantcore_circuits.layouts.junctions.trilayer import place_trilayer  # pylint: disable=C0415

                gaps = pya.Region(self.cell.begin_shapes_rec(self.get_layer("base_metal_gap_wo_grid")))
                a, b = self.refpoints["port_squid_a"], self.refpoints["port_squid_b"]
                try:
                    place_trilayer(self, jtype, gaps, a, b, self.junction_params)
                except ValueError as e:
                    self.raise_error_on_cell(f"TwoPadTransmon: {e}")
        centre = (1 if self.gap <= 0 else self.gap) / 2 + self.pad_thickness / 2
        self.refpoints["pad_left"] = pya.DPoint(-centre, 0)
        self.refpoints["pad_right"] = pya.DPoint(centre, 0)

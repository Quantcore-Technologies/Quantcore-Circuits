"""Bond pad with CPW taper (ported from QWri ``Connector Pad 2``, fab mode).

Local frame: taper tip (CPW end) at the origin, pad body below it; port ``a`` faces +y. The pad's ground-side edge
(the bottom of the gap below the pad) is at ``y = -(pad_height + taper_length + pad_gap)`` for the square pad, which
is where the legacy chips put the chip edge. Geometry is the legacy fab output, computed with the same pya calls.
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def connector_pad_gaps(dbu, pad_width, pad_gap, pad_height, conn_height, trace_width, trace_gap, rounded):
    """Legacy ``ConnectorPad2.makePAD`` with ``fab=True, sim=False``, returned in dbu (already shifted to the tip)."""
    pw, ph, ch, tw, tg, gd = pad_width, pad_height, conn_height, trace_width, trace_gap, pad_gap
    pad = pya.Box(int(-pw / dbu / 2), 0, int(pw / dbu / 2), int(ph / dbu))
    taper = pya.Polygon(
        [
            pya.Point(-pw / dbu / 2, ph / dbu),
            pya.Point(pw / dbu / 2, ph / dbu),
            pya.Point(tw / dbu / 2, (ph + ch) / dbu),
            pya.Point(-tw / dbu / 2, (ph + ch) / dbu),
        ]
    )
    pad = pya.Region().insert([taper, pad])
    taper_inv = pya.Polygon(
        [
            pya.Point((-pw / 2 - gd) / dbu, ph / dbu),
            pya.Point((pw / 2 + gd) / dbu, ph / dbu),
            pya.Point((tw / 2 + tg) / dbu, (ph + ch) / dbu),
            pya.Point((-tw / 2 - tg) / dbu, (ph + ch) / dbu),
        ]
    )
    extender = ph + 500 if rounded else gd
    inv_box = pya.Box(((-pw / 2) - gd) / dbu, (-extender) / dbu, (pw / 2 + gd) / dbu, ph / dbu)
    inv_pad = pya.Region().insert([taper_inv, inv_box])
    if not rounded:
        out = inv_pad - pad
    else:
        gnd_box = pya.Box(
            ((-pw / 2) - gd - 50) / dbu, (-extender - 50) / dbu, (pw / 2 + gd + 50) / dbu, (ph + ch) / dbu
        )
        cpw = pya.Box((-tw / 2) / dbu, (ph + ch) / dbu, (tw / 2) / dbu, (ph + ch + 700) / dbu)
        cpw_left = pya.Box(((-pw / 2) - gd - 50) / dbu, (ph + ch) / dbu, (-tw / 2 - tg) / dbu, (ph + ch + 700) / dbu)
        cpw_right = pya.Box((tw / 2 + tg) / dbu, (ph + ch) / dbu, ((pw / 2) + gd + 50) / dbu, (ph + ch + 700) / dbu)
        sub_top = pya.Box(
            ((-pw / 2) - gd - 50) / dbu, (ph + ch + 200) / dbu, ((pw / 2) + gd + 50) / dbu, (ph + ch + 5000) / dbu
        )
        sub_below = pya.Box(
            ((-pw / 2) - gd - 50) / dbu, (-ph - 1000) / dbu, ((pw / 2) + gd + 50) / dbu, (-20 - ph / 2) / dbu
        )
        padhalf = pya.Box(-pw / dbu / 2, (-800 - ph) / 2 / dbu, pw / dbu / 2, ph / 2 / dbu)
        metal = pad + (pya.Region().insert([gnd_box]) - inv_pad)
        merged = (metal + cpw + cpw_left + cpw_right + padhalf).merged()
        radius = max(pw, ph) / 2 / dbu
        merged.round_corners(radius, radius, 256)
        metal = merged - sub_top - sub_below
        out = (
            pya.Region(metal.bbox())
            - metal.flatten()
            + pya.Box((-pw / 2 - gd) / dbu, (-ph / 2 - 70) / dbu, (pw / 2 + gd) / dbu, -ph / 2 / dbu)
        )
        out.transform(pya.Trans(0, int((-200) / dbu)))
    out.transform(pya.Trans(0, int((-ph - ch) / dbu)))
    return out


class BondPad(Element):
    """Wire-bond pad tapering to a CPW (``a``/``b``); port ``a`` at the taper tip.

    Ported from the legacy QWri PCell ``Connector Pad 2`` (``pymacros/QuantumPcells/connector_pad_v2.lym``), fab
    mode. Refpoints ``pad_center``, ``chip_edge`` and ``lumped_signal`` / ``lumped_ground`` (the simulation lumped
    port across the side gap at the pad centre)."""

    qcc_category = "launcher"

    pad_width = Param(pdt.TypeDouble, "Pad width", 400, unit="μm")
    pad_height = Param(pdt.TypeDouble, "Pad height", 450, unit="μm")
    pad_gap = Param(pdt.TypeDouble, "Gap around the pad", 225, unit="μm")
    taper_length = Param(pdt.TypeDouble, "Taper length", 450, unit="μm")
    rounded = Param(pdt.TypeBoolean, "Rounded pad with a 200 µm CPW stub", False)

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm), legacy ``connector_pad_v2.lym`` ``fab_l``: the 1/0 etch grown by 50 µm in x."""
        from quantcore_circuits.layouts.others.keepout import DBU, dpolygons, full_params  # pylint: disable=C0415

        p = full_params(cls, params)
        gaps = connector_pad_gaps(
            DBU, p["pad_width"], p["pad_gap"], p["pad_height"], p["taper_length"], p["a"], p["b"], p["rounded"]
        )
        return dpolygons(gaps.sized(round(50 / DBU), 0, 2))

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        """A bond pad is a 50 Ω port to ground on whatever conductor its ``a`` port connects to."""
        from quantcore_circuits.lom.fragment import Element, Fragment  # pylint: disable=import-outside-toplevel

        return Fragment(
            nodes={"pad": {"island": f"{name}.pad"}},
            elements=[Element(f"Port_{name}", "R", ("pad", "gnd"), {"R_ohm": 50.0, "source": "design"})],
            port_nodes={"a": "pad"},
        )

    def build(self):
        dbu = self.layout.dbu
        gaps = connector_pad_gaps(
            dbu, self.pad_width, self.pad_gap, self.pad_height, self.taper_length, self.a, self.b, self.rounded
        )
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))
        self.add_port("a", pya.DPoint(0, 0), pya.DVector(0, 1))
        self.refpoints["pad_center"] = pya.DPoint(0, -(self.taper_length + self.pad_height / 2))
        self.refpoints["chip_edge"] = pya.DPoint(0, -(self.taper_length + self.pad_height + self.pad_gap))
        # lumped-port terminals for whole-chip simulations, across the side gap (the back gap ends at the chip edge,
        # so there is no ground metal behind the pad)
        y = -(self.taper_length + self.pad_height / 2)
        self.refpoints["lumped_signal"] = pya.DPoint(self.pad_width / 2, y)
        self.refpoints["lumped_ground"] = pya.DPoint(self.pad_width / 2 + self.pad_gap, y)

"""Legacy QWri pads: ``ConnectorPad`` (``connector_pad.lym``, "Connector Pad", the v1 bond pad of chips 01–03) and
``TaperedPad`` (``pad.lym``, "Pad": a probe pad tapering to a junction finger).

``ConnectorPad`` is the first version of :class:`~quantcore_circuits.layouts.others.bond_pad.BondPad` ("Connector Pad
2"): the gap around the pad scales with the pad (``trace_gap · pad_width / trace_width``) instead of a ``pad_gap``
parameter, and the etch below the pad has no extension. Fab mode (``fab=True, sim=False``); the legacy ``sim=True``
mode (positive pad + ground ring, which chips 01–02 got by default) is not reproduced.

Frame: taper tip (CPW end) at the origin, pad below it; port ``a`` faces +y, width ``a``/``b`` (legacy
``trace_width``/``trace_gap``). Geometry: same pya calls as the legacy code (``base_metal_gap_wo_grid``).
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def connector_pad_v1_gaps(dbu, pad_width, pad_height, conn_height, trace_width, trace_gap, rounded) -> pya.Region:
    """Legacy ``ConnectorPad.makePAD`` with ``fab=True, sim=False``, in dbu (already shifted to the taper tip)."""
    pw, ph, ch, tw, tg = pad_width, pad_height, conn_height, trace_width, trace_gap
    if ch < 0:  # legacy coerce
        ch = 1
    if tw >= pw:
        tw = pw - 0.01
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
    taper_dist = tg
    gd = tg * (pw / tw)
    taper_inv = pya.Polygon(
        [
            pya.Point((-pw / 2 - gd) / dbu, ph / dbu),
            pya.Point((pw / 2 + gd) / dbu, ph / dbu),
            pya.Point((tw / 2 + taper_dist) / dbu, (ph + ch) / dbu),
            pya.Point((-tw / 2 - taper_dist) / dbu, (ph + ch) / dbu),
        ]
    )
    extender = ph + 500 if rounded else 0
    inv_box = pya.Box(((-pw / 2) - gd) / dbu, (-ph - extender) / dbu, (pw / 2 + gd) / dbu, ph / dbu)
    inv_pad = pya.Region().insert([taper_inv, inv_box])
    if not rounded:
        out = inv_pad - pad
    else:
        gnd_box = pya.Box(((-pw / 2) - gd - 50) / dbu, -extender / dbu, (pw / 2 + gd + 50) / dbu, (ph + ch) / dbu)
        cpw = pya.Box((-tw / 2) / dbu, (ph + ch) / dbu, (tw / 2) / dbu, (ph + ch + 700) / dbu)
        cpw_left = pya.Box(((-pw / 2) - gd - 50) / dbu, (ph + ch) / dbu, (-tw / 2 - tg) / dbu, (ph + ch + 700) / dbu)
        cpw_right = pya.Box((tw / 2 + tg) / dbu, (ph + ch) / dbu, ((pw / 2) + gd + 50) / dbu, (ph + ch + 700) / dbu)
        sub_top = pya.Box(
            ((-pw / 2) - gd - 50) / dbu, (ph + ch + 200) / dbu, ((+pw / 2) + gd + 50) / dbu, (ph + ch + 5000) / dbu
        )
        sub_below = pya.Box(
            ((-pw / 2) - gd - 50) / dbu, (-ph - 1000) / dbu, ((+pw / 2) + gd + 50) / dbu, (-20 - ph / 2) / dbu
        )
        padhalf = pya.Box(-pw / dbu / 2, (-800 - ph) / 2 / dbu, pw / dbu / 2, ph / 2 / dbu)
        gnd = pya.Region().insert([gnd_box]) - inv_pad
        metal = pad + gnd
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


def tapered_pad_region(dbu, pad_width, pad_height, conn_height, finger_width, negative, width, height, x, y):
    """Legacy ``Pad.makePAD`` (with its coerce rules), in dbu: a pad with a taper to ``finger_width``; ``negative``
    (legacy ``ground``) returns the ``width × height`` window minus the pad shifted by (x, y)."""
    pw, ph, ch, fw = pad_width, pad_height, conn_height, finger_width
    if width < pw:  # legacy coerce
        pw = width
    if height < ph + ch:
        height = ph + ch
    if ch < 0:
        ch = 1
    if fw >= pw:
        fw = pw - 0.01
    pad = pya.Box(-pw / dbu / 2, 0, pw / dbu / 2, ph / dbu)
    taper = pya.DPolygon(
        [
            pya.DPoint(-pw / dbu / 2, ph / dbu),
            pya.DPoint(pw / dbu / 2, ph / dbu),
            pya.DPoint(fw / dbu / 2, (ph + ch) / dbu),
            pya.DPoint(-fw / dbu / 2, (ph + ch) / dbu),
        ]
    )
    region = pya.Region().insert([taper, pad])
    if negative:
        move = pya.DTrans(x / dbu, y / dbu)
        window = pya.Region().insert(pya.Box(-width / dbu / 2, 0, width / dbu / 2, height / dbu))
        region = window - region.transform(move)
    return region


class ConnectorPad(Element):
    """Wire-bond pad tapering to a CPW (legacy "Connector Pad", v1); port ``a`` at the taper tip.

    Refpoints: ``pad_center``; ``lumped_signal`` / ``lumped_ground`` (pad edge and ground edge across the side gap at
    the pad centre: the 50 Ω lumped port the simulation builder gives a pad that terminates a sim group, as for
    :class:`~quantcore_circuits.layouts.others.bond_pad.BondPad`)."""

    pad_width = Param(pdt.TypeDouble, "Pad width", 275, unit="μm")
    pad_height = Param(pdt.TypeDouble, "Pad height", 300, unit="μm")
    taper_length = Param(pdt.TypeDouble, "Taper length (legacy conn_height)", 300, unit="μm")
    rounded = Param(pdt.TypeBoolean, "Rounded pad with a 200 µm CPW stub (legacy round)", False)

    qcc_category = "launcher"

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm), legacy ``connector_pad.lym`` ``fab_l``: the 1/0 etch grown by 50 µm in x."""
        from quantcore_circuits.layouts.others.keepout import DBU, dpolygons, full_params  # pylint: disable=C0415

        p = full_params(cls, params)
        gaps = connector_pad_v1_gaps(
            DBU, p["pad_width"], p["pad_height"], p["taper_length"], p["a"], p["b"], p["rounded"]
        )
        return dpolygons(gaps.sized(round(50 / DBU), 0, 2))

    def build(self):
        dbu = self.layout.dbu
        gaps = connector_pad_v1_gaps(
            dbu, self.pad_width, self.pad_height, self.taper_length, self.a, self.b, self.rounded
        )
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))
        self.add_port("a", pya.DPoint(0, 0), pya.DVector(0, 1))
        y = -(self.taper_length + self.pad_height / 2) - (200 if self.rounded else 0)
        self.refpoints["pad_center"] = pya.DPoint(0, y)
        # lumped-port terminals (as BondPad): across the side gap at the pad centre; the gap is trace_gap scaled by
        # pad_width / trace_width (legacy), in both modes
        trace_width = min(self.a, self.pad_width - 0.01)
        self.refpoints["lumped_signal"] = pya.DPoint(self.pad_width / 2, y)
        self.refpoints["lumped_ground"] = pya.DPoint(self.pad_width / 2 + self.b * self.pad_width / trace_width, y)


class TaperedPad(Element):
    """Probe pad tapering to a junction finger (legacy "Pad"); port ``finger`` at the taper tip.

    Legacy frame: pad bottom edge at the origin, tip at ``(0, pad_height + conn_height)``. ``negative`` (legacy
    ``ground``, default) etches the ``window_width × window_height`` window around the pad (shifted by ``x``/``y``);
    otherwise the pad itself is drawn as metal (``base_metal_addition``)."""

    pad_width = Param(pdt.TypeDouble, "Pad width", 275, unit="μm")
    pad_height = Param(pdt.TypeDouble, "Pad height", 300, unit="μm")
    conn_height = Param(pdt.TypeDouble, "Taper length", 300, unit="μm")
    finger_width = Param(pdt.TypeDouble, "Finger (tip) width", 3, unit="μm")
    negative = Param(pdt.TypeBoolean, "Etch the window around the pad (legacy ground)", True)
    window_width = Param(pdt.TypeDouble, "Window width (legacy width)", 300, unit="μm")
    window_height = Param(pdt.TypeDouble, "Window height (legacy height)", 650, unit="μm")
    x = Param(pdt.TypeDouble, "Pad x offset in the window", 0, unit="μm")
    y = Param(pdt.TypeDouble, "Pad y offset in the window", -10, unit="μm")

    qcc_category = "test_structure"

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        return {"finger": (params.get("finger_width", 3), params.get("b", 6))}

    def build(self):
        dbu = self.layout.dbu
        region = tapered_pad_region(
            dbu,
            self.pad_width,
            self.pad_height,
            self.conn_height,
            self.finger_width,
            self.negative,
            self.window_width,
            self.window_height,
            self.x,
            self.y,
        )
        layer = "base_metal_gap_wo_grid" if self.negative else "base_metal_addition"
        self.cell.shapes(self.get_layer(layer)).insert(region)
        self.add_protection(pya.Region(region.bbox()).sized(self.margin / dbu))
        tip = pya.DPoint(self.x if self.negative else 0, (self.y if self.negative else 0) + self.pad_height)
        self.add_port("finger", tip + pya.DVector(0, self.conn_height), pya.DVector(0, 1))

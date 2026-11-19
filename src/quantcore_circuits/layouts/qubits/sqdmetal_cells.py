"""Qubits re-implemented from sqdlab/SQDMetal (Apache-2.0, © Prasanna Pakkiam and the SQDMetal authors): the
geometry is re-drawn here as KQC Elements in µm with pya (SQDMetal was read, never imported or run).

* :class:`TransmonTaperedInsets` — ``SQDMetal/Comps/Qubits.py::TransmonTaperedInsets``: a floating two-pad transmon
  with tapered junction leads, optional pad insets / coupler teeth and connection pads, in a filleted pocket.

SQDMetal builds the pads with shapely buffers: ``buffer(+r).buffer(-r)`` (a closing) then ``buffer(-r).buffer(+r)``
(an opening) with ``r = fillet_radius``; here both are morphological operations with a disc
(:func:`closing` / :func:`opening`, Minkowski sums with a ``4 × fillet_resolution``-gon), which is what the buffers
compute up to shapely's mitre joins at sharp concave corners (filleted away by the closing first).
"""

from __future__ import annotations

import json
import math

from kqcircuits.junctions import junction_type_choices
from kqcircuits.pya_resolver import pya
from kqcircuits.qubits.qubit import Qubit
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.sim_gap import sim_junction_in_gap
from quantcore_circuits.layouts.qubits.xmon import _junction_params

# SQDMetal ``_default_connection_pads`` (µm; loc_W / loc_H are -1, 0, +1)
DEFAULT_CONNECTION_PAD = {
    "pad_gap": 100.0,
    "pad_height": 30.0,
    "pad_width": 200.0,
    "pad_cpw_shift": 0.0,
    "pad_cpw_extent": 25.0,
    "cpw_width": 10.0,
    "cpw_gap": 6.0,
    "cpw_extend": 200.0,
    "pocket_extent": 5.0,
    "pocket_rise": 0.0,
    "fillet_radius_inner": 15.0,
    "fillet_radius_outer": 75.0,
    "fillet_resolution": 16,
    "loc_W": 0,
    "loc_H": 1,
}


# ---- morphology (dbu regions) -----------------------------------------------------------------------------------
def disc_polygon(r: float, n: int) -> pya.Polygon:
    """Closed ``n``-gon inscribed in a circle of radius ``r`` (dbu) about the origin."""
    return pya.Polygon(
        [
            pya.Point(round(r * math.cos(2 * math.pi * k / n)), round(r * math.sin(2 * math.pi * k / n)))
            for k in range(n)
        ]
    )


def dilate(region: pya.Region, r: float, n: int = 64) -> pya.Region:
    if r <= 0:
        return region.dup()
    return region.minkowski_sum(disc_polygon(r, n)).merged()


def erode(region: pya.Region, r: float, n: int = 64) -> pya.Region:
    if r <= 0:
        return region.dup()
    frame = pya.Region(region.bbox().enlarged(int(3 * r) + 10))
    return (frame - dilate(frame - region, r, n)).merged()


def closing(region: pya.Region, r: float, n: int = 64) -> pya.Region:
    """shapely ``buffer(r).buffer(-r)``: fills concave corners with radius ``r``."""
    return erode(dilate(region, r, n), r, n)


def opening(region: pya.Region, r: float, n: int = 64) -> pya.Region:
    """shapely ``buffer(-r).buffer(r)``: rounds convex corners with radius ``r``, drops parts narrower than 2r."""
    return dilate(erode(region, r, n), r, n)


def _rect(dbu, x0, y0, x1, y1) -> pya.Region:
    return pya.Region(pya.DBox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)).to_itype(dbu))


def _circle(dbu, cx, cy, r, n) -> pya.Region:
    if r <= 0:
        return pya.Region()
    return pya.Region(pya.DPolygon.ellipse(pya.DBox(cx - r, cy - r, cx + r, cy + r), n).to_itype(dbu))


def _rounded_rect(dbu, cx, cy, w, h, r, n) -> pya.Region:
    """shapely ``rectangle(w - 2r, h - 2r).buffer(r)``: a ``w × h`` box with corner radius ``r``."""
    box = pya.DPolygon(pya.DBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    if r > 0:
        box = box.round_corners(0, min(r, w / 2, h / 2), n)
    return pya.Region(box.to_itype(dbu))


def _path(dbu, points, width) -> pya.Region:
    return pya.Region(pya.DPath([pya.DPoint(x, y) for x, y in points], width).polygon().to_itype(dbu))


def _mirror(sx: float, sy: float) -> pya.DCplxTrans:
    """The scaling (x, y) → (sx·x, sy·y) for sx, sy = ±1."""
    if sx > 0 and sy > 0:
        return pya.DCplxTrans()
    if sx < 0 and sy < 0:
        return pya.DCplxTrans(1, 180, False, 0, 0)
    return pya.DCplxTrans(1, 0, True, 0, 0) if sy < 0 else pya.DCplxTrans(1, 180, True, 0, 0)


def connection_pad_options(name: str, options: dict) -> dict:
    unknown = sorted(set(options) - set(DEFAULT_CONNECTION_PAD) - {"pin_y_distance"})
    if unknown:
        raise ValueError(f"connection pad {name!r}: unknown option(s) {unknown}")
    return {**DEFAULT_CONNECTION_PAD, **options}


class TransmonTaperedInsets(Qubit):
    """Floating tapered-pad transmon in a filleted pocket (SQDMetal ``TransmonTaperedInsets``).

    Re-implemented from sqdlab/SQDMetal ``SQDMetal/Comps/Qubits.py`` (Apache-2.0), same option names in µm, qubit
    centre at the origin, pads stacked in y (SQDMetal ``orientation`` 0; use the placement rotation for others).
    Two ``pad_width`` × ``pad_height`` pads with round ends ``pad_gap`` apart, each with a ``taper_width_base`` →
    ``taper_width_top`` taper of ``taper_height`` towards the junction (at x = 0, or at a pad end with
    ``junction_position`` "right" / "left" and ``junction_x_offset``), pad corners filleted with ``fillet_radius``;
    optional insets (``inset_width`` × ``inset_depth`` notches in the pad ends) and coupler teeth on the top pad
    (``coupled_pad_*``, drawn when a connection pad sits at loc_W 0, loc_H +1). The pocket is ``pocket_width`` ×
    (``pocket_height`` − ``pocket_lower_tighten``) with ``fillet_radius_gap`` corners, top edge at
    ``pocket_height / 2``. The pads, connection pads and wires are also drawn on ``base_metal_addition`` (SQDMetal
    metal is positive: it wins over any etch on top of it, e.g. a capacitor's clearance box in the pocket).

    ``connection_pads`` (dict / JSON ``{name: {options}}``, SQDMetal defaults: ``pad_gap`` 100, ``pad_width`` 200,
    ``pad_height`` 30, ``cpw_width`` 10, ``cpw_gap`` 6, ``cpw_extend`` 200, ``loc_W`` 0, ``loc_H`` 1, …): a filleted
    pad ``pad_gap`` beyond the qubit pad with a CPW wire out of the pocket to port ``<name>`` (a/b = cpw_width /
    cpw_gap). SQDMetal ends a loc_W 0 wire at ``pocket_width / 2 + cpw_extend`` from the centre (it uses the pocket
    *width* there); kept.

    Ports at SQDMetal's pins, with SQDMetal's normals (kept as they are, a/b = the element ``a``/``b``):
    ``top_right_pin`` / ``top_left_pin`` (x = ±(pocket_width/2 + chrgln_pin_y_offset), level with the top pad +
    ``chrgln_pin_x_offset``; both face +x), ``bottom_right_pin`` / ``bottom_left_pin`` (level with the bottom pad;
    face +y), ``top_pocket_pin`` (0, pocket_height/2; faces +x), ``bottom_pocket_pin`` (0, −pocket_height/2; faces
    −x). These mark where a charge line or a :class:`~quantcore_circuits.layouts.others.sqdmetal_cells.
    SmoothCapacitorSemicircle` goes; they are not CPW ends. SQDMetal's junction pins are refpoints ``pin_island`` /
    ``pin_reservoir``.

    Junction: SQDMetal draws only a junction line (``inductor_width`` × ``inductor_height``, centred); its ends are
    ``port_squid_a`` (top pad = island) / ``port_squid_b``. ``junction_type`` (KQC / Quantcore junction cell,
    ``"No Squid"`` = none) is placed across the taper-tip gap, ``junction_params`` go to it.
    """

    inductor_width = Param(pdt.TypeDouble, "Junction line width", 20, unit="μm")
    inductor_height = Param(pdt.TypeDouble, "Junction line length", 36, unit="μm")
    chrgln_pin_x_offset = Param(pdt.TypeDouble, "Corner pins: offset along y from the pad centre line", 30, unit="μm")
    chrgln_pin_y_offset = Param(pdt.TypeDouble, "Corner pins: offset along x from the pocket edge", 50, unit="μm")
    junction_pin_inset = Param(pdt.TypeDouble, "Junction pins inset from the pad edge", 0, unit="μm")
    pad_gap = Param(pdt.TypeDouble, "Gap between the pads", 100, unit="μm")
    pad_width = Param(pdt.TypeDouble, "Pad width (x, without the round ends)", 800, unit="μm")
    pad_height = Param(pdt.TypeDouble, "Pad height (y)", 110, unit="μm")
    pocket_width = Param(pdt.TypeDouble, "Pocket width", 1000, unit="μm")
    pocket_height = Param(pdt.TypeDouble, "Pocket height", 800, unit="μm")
    pocket_lower_tighten = Param(pdt.TypeDouble, "Pocket shortened from below by", 120, unit="μm")
    taper_width_top = Param(pdt.TypeDouble, "Taper width at the junction", 40, unit="μm")
    taper_width_base = Param(pdt.TypeDouble, "Taper width at the pad", 200, unit="μm")
    taper_height = Param(pdt.TypeDouble, "Taper height (0 = no taper)", 40, unit="μm")
    taper_fillet_radius = Param(pdt.TypeDouble, "Taper corner radius", 3, unit="μm")
    junction_position = Param(
        pdt.TypeString,
        "Junction position (SQDMetal junction_centered True / False / 'left')",
        "center",
        choices=["center", "right", "left"],
    )
    junction_x_offset = Param(pdt.TypeDouble, "Junction offset from the pad end (right / left)", 0, unit="μm")
    inset_width = Param(pdt.TypeDouble, "Inset width (0 = none)", 0, unit="μm")
    inset_depth = Param(pdt.TypeDouble, "Inset depth", 100, unit="μm")
    inset_fillet_radius = Param(pdt.TypeDouble, "Inset corner radius", 10, unit="μm")
    fillet_radius = Param(pdt.TypeDouble, "Pad fillet radius", 50, unit="μm")
    fillet_resolution = Param(pdt.TypeInt, "Fillet points per quarter circle", 16)
    fillet_radius_gap = Param(pdt.TypeDouble, "Pocket corner radius", 50, unit="μm")
    coupled_pad_height = Param(pdt.TypeDouble, "Coupler teeth height (0 = none)", 0, unit="μm")
    coupled_pad_width = Param(pdt.TypeDouble, "Coupler teeth width", 0, unit="μm")
    coupled_pad_gap = Param(pdt.TypeDouble, "Gap between the coupler teeth", 0, unit="μm")
    connection_pads = Param(pdt.TypeString, "Connection pads (JSON {name: {options}})", "{}")
    junction_params = Param(pdt.TypeString, "Junction cell parameters (JSON dict)", "{}")
    junction_type = Param(
        pdt.TypeString,
        "Junction Type",
        "Manhattan",
        choices=junction_type_choices
        + ["Trilayer Junction", "Trilayer Squid", "Quantcore Junction", "Quantcore Squid"],
    )

    qcc_category = "qubit"

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """design.json params → PCell params: dict-valued ``connection_pads`` / ``junction_params`` → JSON."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"TransmonTaperedInsets: unknown parameter(s) {unknown}")
        for key in ("connection_pads", "junction_params"):
            if isinstance(params.get(key), dict):
                params[key] = json.dumps(params[key], sort_keys=True)
        for name, opts in _junction_params(params.get("connection_pads", "{}")).items():
            connection_pad_options(name, opts)
        return params

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """Connection-pad wires: a/b = their cpw_width / cpw_gap."""
        pads = _junction_params(params.get("connection_pads", "{}"))
        return {
            name: (float(o["cpw_width"]), float(o["cpw_gap"]))
            for name, o in ((n, connection_pad_options(n, opts)) for n, opts in pads.items())
        }

    def _taper_x(self) -> float:
        if self.junction_position == "right":
            return self.pad_width / 2 - self.taper_width_base / 2 + self.junction_x_offset
        if self.junction_position == "left":
            return -self.pad_width / 2 + self.taper_width_base / 2 - self.junction_x_offset
        return 0.0

    def _trapezoid(self, dbu, tx, y_base, sign) -> pya.Region:
        """Taper: base ``taper_width_base`` on the pad edge at ``y_base``, tip ``taper_height`` towards ``sign``."""
        hb, ht, th = self.taper_width_base / 2, self.taper_width_top / 2, self.taper_height
        poly = pya.DPolygon(
            [
                pya.DPoint(tx - hb, y_base),
                pya.DPoint(tx - ht, y_base + sign * th),
                pya.DPoint(tx + ht, y_base + sign * th),
                pya.DPoint(tx + hb, y_base),
            ]
        )
        if self.taper_fillet_radius > 0:
            poly = poly.round_corners(0, self.taper_fillet_radius, 36)
        return pya.Region(poly.to_itype(dbu))

    def _pad(self, dbu, sign, teeth: bool) -> pya.Region:
        """Top (sign +1) or bottom (-1) pad, filleted as SQDMetal does."""
        pw, ph, pg = self.pad_width, self.pad_height, self.pad_gap
        n = 64
        yc = sign * (ph + pg) / 2
        pad = _rect(dbu, -pw / 2, yc - ph / 2, pw / 2, yc + ph / 2)
        pad += _circle(dbu, -pw / 2, yc, ph / 2, n) + _circle(dbu, pw / 2, yc, ph / 2, n)
        if self.taper_height > 0:
            pad += self._trapezoid(dbu, self._taper_x(), sign * pg / 2, -sign)
        if teeth and self.coupled_pad_width > 0:
            cw, ch, cg = self.coupled_pad_width, self.coupled_pad_height, self.coupled_pad_gap
            for s in (-1, 1):
                x = s * (cw / 2 + cg / 2)
                cy = ch / 2 + ph / 2 + pg / 2
                pad += _rect(dbu, x - cw / 2, cy - (ch + ph) / 2, x + cw / 2, cy + (ch + ph) / 2)
                pad += _circle(dbu, x, cy + (ch + ph) / 2, cw / 2, n)
        pad.merge()
        r, k = self.fillet_radius / dbu, 4 * int(self.fillet_resolution)
        pad = opening(closing(pad, r, k), r, k)
        if self.inset_depth != 0 and self.inset_width != 0:
            ifr = self.inset_fillet_radius
            y = sign * (pg / 2 + ph / 2)
            x_left = -pw / 2 - ph / 2 + self.inset_depth / 2 - ifr
            for x in (x_left, -x_left):
                pad -= _rounded_rect(dbu, x, y, self.inset_depth, self.inset_width, ifr, 36)
            pad = opening(pad, ifr / dbu, 3 * k)
        return pad.merged()

    def _connection_pad(self, dbu, name, o):
        """(metal, etch, port position, port direction) of one SQDMetal connection pad."""
        pw, ph, pg, pkw = self.pad_width, self.pad_height, self.pad_gap, self.pocket_width
        r, r_out, cw = o["fillet_radius_inner"], o["fillet_radius_outer"], o["cpw_width"]
        cpw, cph = o["pad_width"], o["pad_height"]
        n = 4 * int(o["fillet_resolution"])
        loc_w, loc_h = float(o["loc_W"]), float(o["loc_H"])
        if loc_w not in (-1.0, 0.0, 1.0) or loc_h not in (-1.0, 1.0):
            raise ValueError(f"connection pad {name!r}: loc_W must be -1, 0 or 1 and loc_H -1 or 1")
        if cpw - 2 * r < 0 or cph - 2 * r < 0:
            raise ValueError(f"connection pad {name!r}: pad_width/pad_height too small for fillet_radius_inner {r}")
        if cpw / 2 - cw / 2 - r < r_out:
            raise ValueError(f"connection pad {name!r}: fillet_radius_outer {r_out} too large for pad_width {cpw}")
        if loc_w != 0:
            pad = _rounded_rect(dbu, -cpw / 2, cph / 2, cpw, cph, r, n)
            y0 = o["pad_cpw_shift"] + cw / 2
            wire = [
                (0, y0),
                (o["pad_cpw_extent"], y0),
                ((pkw - pw) / 2 - o["pocket_extent"], y0 + o["pocket_rise"]),
                ((pkw - pw) / 2 + o["cpw_extend"], y0 + o["pocket_rise"]),
            ]
        else:
            pad = _rounded_rect(dbu, 0, cph / 2, cpw, cph, r, n)
            if r_out > 0:
                for s in (-1, 1):
                    xc = s * (cw / 2 + r_out / 2)
                    corner = _rect(dbu, xc - r_out / 2, cph, xc + r_out / 2, cph + r_out)
                    pad += corner - _circle(dbu, s * (cw / 2 + r_out), cph + r_out, r_out, 128)
            wire = [(0, cph), (0, (pkw / 2 - ph - pg / 2 - o["pad_gap"]) + o["cpw_extend"])]
        # SQDMetal: scale by (loc_W or 1, loc_H) about the origin, then translate
        trans = pya.DCplxTrans(pya.DVector(loc_w * pw / 2, loc_h * (ph + pg / 2 + o["pad_gap"]))) * _mirror(
            1.0 if loc_w == 0 else loc_w, loc_h
        )
        pts = [trans * pya.DPoint(x, y) for x, y in wire]
        pad = pad.transformed(trans.to_itrans(dbu))
        path = [(p.x, p.y) for p in pts]
        metal = pad + _path(dbu, path, cw)
        etch = _path(dbu, path, cw + 2 * o["cpw_gap"])
        end, before = pts[-1], pts[-2]
        d = end - before
        return metal, etch, end, d / d.length()

    def build(self):
        dbu = self.layout.dbu
        ph, pg = self.pad_height, self.pad_gap
        pkw, pkh, low = self.pocket_width, self.pocket_height, self.pocket_lower_tighten
        try:
            pads = _junction_params(self.connection_pads)
            pads = {name: connection_pad_options(name, opts) for name, opts in pads.items()}
        except ValueError as e:
            self.raise_error_on_cell(f"TransmonTaperedInsets: {e}")
        teeth = any(float(o["loc_W"]) == 0 and float(o["loc_H"]) == 1 for o in pads.values())
        metal = self._pad(dbu, 1, teeth) + self._pad(dbu, -1, False)
        pocket_h = pkh - low
        pocket = _rounded_rect(dbu, 0, low / 2, pkw, pocket_h, self.fillet_radius_gap, 4 * int(self.fillet_resolution))
        etch = pocket
        ports = []
        for name, o in pads.items():
            try:
                m, e, pos, direction = self._connection_pad(dbu, name, o)
            except ValueError as err:
                self.raise_error_on_cell(f"TransmonTaperedInsets: {err}")
            metal += m
            etch += e
            ports.append((name, pos, direction))
        gaps = (etch - metal).merged()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        # SQDMetal pads are positive metal: they survive another cell's etch over them (e.g. a capacitor's
        # clearance box in the pocket), as base_metal_addition does at fab export
        self.cell.shapes(self.get_layer("base_metal_addition")).insert(metal.merged())
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))
        for name, pos, direction in ports:
            self.add_port(name, pos, direction)

        tx = self._taper_x()
        lp = self.taper_height if self.taper_height > 0 else 1e-3  # SQDMetal pin_route_l (1 nm without a taper)
        xr, xl = pkw / 2 + self.chrgln_pin_y_offset, -pkw / 2 - self.chrgln_pin_y_offset
        y_top, y_bot = pg / 2 + ph / 2 + self.chrgln_pin_x_offset, -pg / 2 - ph / 2 + self.chrgln_pin_x_offset
        for name, pos, direction in (
            ("top_right_pin", (xr, y_top), (1, 0)),
            ("top_left_pin", (xl, y_top), (1, 0)),
            ("bottom_right_pin", (xr, y_bot), (0, 1)),
            ("bottom_left_pin", (xl, y_bot), (0, 1)),
            ("top_pocket_pin", (0, pkh / 2), (1, 0)),
            ("bottom_pocket_pin", (0, -pkh / 2), (-1, 0)),
        ):
            self.add_port(name, pya.DPoint(*pos), pya.DVector(*direction))
        inset = self.junction_pin_inset
        self.refpoints["pin_island"] = pya.DPoint(tx, pg / 2 + inset - lp / 2)
        self.refpoints["pin_reservoir"] = pya.DPoint(tx, -pg / 2 - inset + lp / 2)
        self.refpoints["port_squid_a"] = pya.DPoint(tx, self.inductor_height / 2)
        self.refpoints["port_squid_b"] = pya.DPoint(tx, -self.inductor_height / 2)
        self.refpoints["junction"] = pya.DPoint(tx, 0)
        if self.junction_type != "No Squid":
            gap = pg - 2 * max(self.taper_height, 0)
            if gap <= 0:
                self.raise_error_on_cell("TransmonTaperedInsets: the tapers overlap (2 × taper_height >= pad_gap)")
            trans = pya.DCplxTrans(1, 0, False, tx, -gap / 2)
            sim = {}
            if self.junction_type == "Sim":  # simulation stand-in: pads into both taper tips, port in the gap
                shift, sim = sim_junction_in_gap(gap)
                trans = trans * pya.DCplxTrans(1, 0, False, 0, -shift)
            params = {"junction_total_length": gap, "window_height": gap, **sim,
                      **_junction_params(self.junction_params)}
            refs = self.produce_squid(trans, **params)
            squid_trans = trans * pya.DTrans.M90 if self.mirror_squid else trans
            for ref in ("port_squid_a", "port_squid_b"):
                if ref in refs:
                    self.refpoints[ref] = squid_trans * refs[ref]

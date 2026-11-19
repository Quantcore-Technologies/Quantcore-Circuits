"""Nb trilayer cross junctions with HSQ sidewall protection (ported from QWri ``JJ_finger Top/Bottom`` and
``xjc_junction_TL_mod.py`` / ``xjc_squid_TL_mod.py``).

Two finger exposures cross over each other:

* the *straight* finger (legacy layer 2/0, KQC ``SIS_junction``) connects to the island (``port_common`` side),
* the *bent* finger (legacy layer 4/0, KQC ``SIS_junction_2``) connects to ground (``origin_squid`` side).

Both are drawn as negative-tone windows (window minus finger), exactly as the legacy fab output. HSQ boxes go to the
Quantcore ``hsq`` layer (PDK v2 spacer, 50/0; the legacy scripts drew them on 500/0). The geometry is computed in
database units with the same pya calls as the legacy code (including its float→int truncation), so it XORs clean
against the legacy cells. The scripts set the finger PCells' parameters, so KLayout first runs the legacy
``coerce_parameters_impl`` (:func:`coerce_straight` / :func:`coerce_bent`: e.g. a 0.6 µm bent finger widens its
1 µm lead to 1.26 µm); the cells apply the same rules.

Spacer gradient (PDK 51–53/0, design decision #4): the three shades are three dose levels of the 50/0 spacer. A
rectangular spacer (the HSQ sidewall boxes) is split across its width into three nested strips of width / 3;
windows (spacers with a hole) and concentric spacers are split into three rings (:func:`spacer_gradient_levels`).
``spacer_1`` (51/0) is the level nearest the junction (legacy ``hsqi``, inner), ``spacer_3`` (53/0) the farthest
(``hsqo``, outer). On by default where a spacer is drawn (PDK switch ``JunctionProcess.spacer_gradient``); the legacy
XOR tests compare 2/0, 4/0 and 50/0 only.

Sizing (design decisions #1 / #21): ``lj_nH`` > 0 sizes the straight finger from the PDK junction rule
(:func:`quantcore_circuits.circuit.bridges.fingers_for_lj`: Δ = 1.4 meV, R_n·A of
:class:`quantcore_circuits.pdk.JunctionProcess`; SQUID cells: ``lj_nH`` is the parallel total, each junction gets
twice it), keeping ``second_finger_width`` (0 → the PDK bent finger, 0.6 µm). Otherwise KQC's ``junction_width``
(what a KQC qubit passes to its junction) sets the straight finger when it is at least the PDK minimum finger
(0.1 µm; KQC's 0.02 µm default is ignored), else ``finger_width`` is used as given.

``clearer`` draws the legacy CLEARER: a ``base_metal_addition`` box (window − ``clearer_inset`` on each side, full
window height) so the 1/0 etch leaves base metal in the junction gap and the 2/0 / 4/0 windows cut the fingers from
it. The ``Quantcore*`` cells (:class:`QuantcoreJunction`, :class:`QuantcoreSquid`) are the PDK junctions for any
qubit: TrilayerJunction / TrilayerSquid geometry with the PDK nominal fingers (0.5 × 0.6 µm → R_n = 45 kΩ), the
clearer and the gradient on (``junction_type: "Quantcore Junction"`` / ``"Quantcore Squid"``). Simulation builds
replace every ``junction_type`` by ``"Sim"``, so the clearer never shorts a FEM model.

Frame: KQC junction convention. ``origin_squid`` = (0, 0) at the centre of the window's ground-side edge,
``port_common`` = (0, window_height) on the island side; the legacy junction cell is centred on the window, so its
geometry is shifted up by ``window_height / 2``.
"""

import json
import math

from kqcircuits.junctions.squid import Squid
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.pdk import DEFAULT_PDK, QCC_LAYERS, get_pdk

_PROCESS = get_pdk(DEFAULT_PDK).junction


def straight_finger(dbu, pad_width, pad_height, finger_width, finger_length, width, height, x, y, negative=True):
    """Legacy ``JJ_finger_top`` (the straight finger), in dbu. Returns a Region."""
    pw, ph, fw, fl = pad_width / dbu, pad_height / dbu, finger_width / dbu, finger_length / dbu
    pt1 = pya.Point(pya.DPoint(-pw / 2, 0))
    pt2 = pya.Point(pya.DPoint(pw / 2, 0))
    pt4 = pya.Point(pya.DPoint(-fw / 2, fl / 3))
    pt3 = pya.Point(pya.DPoint(fw / 2, fl / 3))
    jpad = pya.Region()
    jpad.insert(pya.Box(-pw / 2, -ph, pw / 2, 0))
    jpad.insert(pya.Box(-fw / 2, 0, fw / 2, (fl / 4 + fl)))
    jpad.insert(pya.Polygon([pt1, pt2, pt3, pt4]))
    if not negative:
        return jpad
    k, lead_w = (0, 1) if x == 0 else (1, 2)
    move = pya.DTrans(x / dbu, y / dbu)
    origin = pya.Point(pya.DPoint(0, -height / dbu / 2))
    mid = pya.Point(pya.DPoint(0, y / dbu - ph))
    end = pya.Point(pya.DPoint(x / dbu, y / dbu - ph))
    path1 = pya.Path([origin, mid], lead_w * pw, 0, pw / 2)
    path2 = pya.Path([mid, end], k * pw, pw, pw / 2)
    box = pya.Region().insert(pya.Box(-width / dbu / 2, -height / dbu / 2, width / dbu / 2, height / dbu / 2))
    finger = pya.Region().insert(jpad.transformed(move))
    return box - finger - pya.Region().insert(path1) - pya.Region().insert(path2)


def bent_finger(
    dbu, pad_width, pad_height, finger_width, finger_length, conn_height, width, height, x, y, invert, negative=True
):
    """Legacy ``JJ_finger Bottom`` (the bent finger), in dbu. Returns a Region."""
    pw, ph, fw, fl, ch = pad_width / dbu, pad_height / dbu, finger_width / dbu, finger_length / dbu, conn_height / dbu
    ch = fl / 3 if pw < fl else abs(ch)
    pts = [
        pya.Point(pya.DPoint(0, 0)),
        pya.Point(pya.DPoint(fl / 2, ch)),
        pya.Point(pya.DPoint(fl / 2, ch + (2 / 3) * fl)),
        pya.Point(pya.DPoint(-fl / 2, ch + (2 / 3) * fl)),
    ]
    finger = pya.Path(pts, fw)
    p3y = finger.polygon().to_simple_polygon().point(3).y
    hw = pw / 2
    holder = pya.Polygon(
        [
            pya.Point(pya.DPoint(-pw / 2, 0)),
            pya.Point(pya.DPoint(pw / 2, -pw / 2)),
            pya.Point(pya.DPoint(fl / 2 + hw / 2, ch + -hw / 2)),
            pya.Point(pya.DPoint(fl / 2 + hw / 2, p3y + fw)),
            pya.Point(pya.DPoint(fl / 2 - hw / 2, p3y + fw)),
            pya.Point(pya.DPoint(fl / 2 - hw / 2, ch + hw / 2)),
        ]
    )
    jpad = pya.Region().insert(holder)
    jpad.insert(finger)
    jpad.insert(pya.Box(-pw / 2, -ph, pw / 2, 0))
    if invert:
        jpad.transform(pya.Trans(2, True))
    if not negative:
        return jpad
    move = pya.DTrans(x / dbu, y / dbu)
    origin = pya.Point(pya.DPoint(x / dbu, -height / dbu / 2))
    mid = pya.Point(pya.DPoint(x / dbu, y / dbu - ph))
    path1 = pya.Path([origin, mid], pw)
    box = pya.Region().insert(pya.Box(-width / dbu / 2, -height / dbu / 2, width / dbu / 2, height / dbu / 2))
    return box - pya.Region().insert(jpad.transformed(move)) - pya.Region().insert(path1)


def coerce_straight(pad_width: float, pad_height: float, finger_width: float) -> tuple[float, float]:
    """Legacy ``JJ_finger Top.coerce_parameters_impl``: (pad_width, pad_height)."""
    if pad_width < 2 * finger_width + finger_width / 10:
        pad_width = 2 * finger_width + finger_width / 10
    if pad_height < pad_width / 2:
        pad_height = pad_width / 2
    return pad_width, pad_height


def coerce_bent(pad_width, conn_height, finger_width, finger_length, x, y, width, height) -> tuple[float, float, float]:
    """Legacy ``JJ_finger Bottom.coerce_parameters_impl``: (pad_width, conn_height, x), including its quirk of
    resetting ``x`` (not ``y``) when ``y`` is out of the window."""
    if pad_width <= (2 * finger_width) + finger_width / 10:
        pad_width = 2 * finger_width + finger_width / 10
    if conn_height <= finger_length / 3:
        conn_height = finger_length / 3
    if finger_width > pad_width:
        pad_width = 2 * finger_width + finger_width / 10
    if abs(x) > (width / 2 - pad_width):
        x = width / 2 - pad_width
    if abs(y) > (height / 2 - pad_width):
        x = height / 2 - pad_width
    return pad_width, conn_height, x


def coerced_straight_finger(dbu, pad_width, pad_height, finger_width, finger_length, width, height, x, y):
    """:func:`straight_finger` after the legacy parameter coercion."""
    pad_width, pad_height = coerce_straight(pad_width, pad_height, finger_width)
    return straight_finger(dbu, pad_width, pad_height, finger_width, finger_length, width, height, x, y)


def coerced_bent_finger(dbu, pad_width, finger_width, finger_length, conn_height, width, height, x, y, invert):
    """:func:`bent_finger` (pad height 2, read-only in the legacy cell) after the legacy coercion."""
    pad_width, conn_height, x = coerce_bent(pad_width, conn_height, finger_width, finger_length, x, y, width, height)
    return bent_finger(dbu, pad_width, 2, finger_width, finger_length, conn_height, width, height, x, y, invert)


def _strips(poly: pya.Polygon, shades: int, centres: list) -> list:
    """A rectangle split across its short side into ``shades`` strips, nearest a junction centre first."""
    box = poly.bbox()
    along_x = box.width() <= box.height()  # strips run along the long side
    lo, size = (box.left, box.width()) if along_x else (box.bottom, box.height())
    cuts = [lo + round(k * size / shades) for k in range(shades + 1)]
    strips = []
    for k in range(shades):
        if along_x:
            b = pya.Box(cuts[k], box.bottom, cuts[k + 1], box.top)
        else:
            b = pya.Box(box.left, cuts[k], box.right, cuts[k + 1])
        strips.append(pya.Region(b) & pya.Region(poly))
    if centres:
        strips.sort(key=lambda r: min(r.bbox().center().distance(c) for c in centres))
    return strips


def _depth(region: pya.Region, inside: pya.Region | None = None) -> int:
    """Smallest d (dbu) at which ``region`` sized by −d is empty, or (``inside`` given) at which ``inside`` minus
    ``region`` grown by d is empty (bisection)."""
    lo, hi = 0, max(region.bbox().width(), region.bbox().height(), 1)
    if inside is not None:
        hi = max(hi, inside.bbox().width(), inside.bbox().height())
    while hi - lo > 1:
        mid = (lo + hi) // 2
        rest = (inside - region.sized(mid)) if inside is not None else region.sized(-mid)
        if rest.is_empty():
            hi = mid
        else:
            lo = mid
    return hi


def spacer_gradient_levels(spacer: pya.Region, dbu: float, shades: int = 3, centres: list | None = None) -> list:
    """The spacer gradient (PDK ``spacer_1`` … ``spacer_<shades>``) of a spacer region, inner level first.

    * rectangles: ``shades`` nested strips of width / ``shades`` across the short side; the strip nearest one of
      ``centres`` (junction centres, ``DPoint`` µm or ``Point`` dbu; default: the spacer's own centre) is level 1;
    * windows (a polygon with holes): ``shades`` rings of equal width from the hole outwards (level 1 at the hole);
    * other (concentric / round) spacers: ``shades`` rings of equal width from the outside in, level 1 the core.

    The levels lie inside the spacer and tile it (disjoint, union = spacer)."""
    pts = []
    for c in centres or []:
        pts.append(c if isinstance(c, pya.Point) else pya.Point(round(c.x / dbu), round(c.y / dbu)))
    if not pts and not spacer.is_empty():
        pts = [spacer.bbox().center()]
    levels = [pya.Region() for _ in range(shades)]
    for poly in spacer.merged().each():
        if poly.holes() == 0 and poly.is_box():
            for k, strip in enumerate(_strips(poly, shades, pts)):
                levels[k] += strip
            continue
        p = pya.Region(poly)
        if poly.holes() > 0:
            hull = pya.Region(pya.Polygon(list(poly.each_point_hull())))
            holes = hull - p
            t = _depth(holes, p)
            grown = [holes.sized(round(k * t / shades)) for k in range(shades)] + [hull]
            rings = [(grown[k + 1] - grown[k]) & p for k in range(shades)]
        else:
            t = _depth(p)
            shrunk = [p] + [p.sized(-round(k * t / shades)) for k in range(1, shades)] + [pya.Region()]
            rings = [shrunk[k] - shrunk[k + 1] for k in range(shades)][::-1]  # core first, outer ring last
        for k, ring in enumerate(rings):
            levels[k] += ring
    return [lev.merged() for lev in levels]


def spacer_gradient_rings(hsq: pya.Region, step: float, dbu: float, shades: int = 3) -> list:
    """Earlier (pre-#4) gradient: nested rings *around* the spacer, ``step`` µm wide each, inner first. Kept for
    reference only; the cells draw :func:`spacer_gradient_levels`."""
    d = int(round(step / dbu))
    grown = [hsq.sized(k * d).merged() for k in range(shades + 1)]
    return [grown[k + 1] - grown[k] for k in range(shades)]


def insert_spacer(cell: pya.Cell, layout: pya.Layout, spacer: pya.Region, gradient: bool, centres=None) -> None:
    """Draw a spacer on qcc ``hsq`` (50/0) and, with ``gradient``, its dose levels on ``spacer_1..3`` (51–53/0)."""
    if spacer.is_empty():
        return
    spacer = spacer.merged()
    cell.shapes(layout.layer(QCC_LAYERS["hsq"])).insert(spacer)
    if gradient:
        levels = spacer_gradient_levels(spacer, layout.dbu, _PROCESS.spacer_shades, centres)
        for shade, level in enumerate(levels, 1):
            if not level.is_empty():
                cell.shapes(layout.layer(QCC_LAYERS[f"spacer_{shade}"])).insert(level)


class _TrilayerBase(Squid):
    """Shared parameters of trilayer junctions (µm)."""

    qcc_category = "junction"

    finger_width = Param(pdt.TypeDouble, "Straight finger width (junction size)", 0.1, unit="μm")
    second_finger_width = Param(pdt.TypeDouble, "Bent finger width (0 = same as straight)", 0.0, unit="μm")
    window_width = Param(pdt.TypeDouble, "Exposure window width", 32.0, unit="μm")
    window_height = Param(pdt.TypeDouble, "Exposure window height (= qubit gap it spans)", 20.0, unit="μm")
    straight_finger_length = Param(pdt.TypeDouble, "Straight finger length", 3.2, unit="μm")
    straight_finger_y = Param(pdt.TypeDouble, "Straight finger offset (legacy y)", -3.6, unit="μm")
    bent_finger_length = Param(pdt.TypeDouble, "Bent finger length", 3.0, unit="μm")
    bent_finger_y = Param(pdt.TypeDouble, "Bent finger offset (legacy y)", -2.5, unit="μm")
    bent_pad_width = Param(pdt.TypeDouble, "Bent finger lead width", 1.0, unit="μm")
    bent_shift = Param(pdt.TypeDouble, "Bent finger cell shift in y", 0.5, unit="μm")
    with_hsq = Param(pdt.TypeBoolean, "Draw HSQ sidewall boxes", True)
    hsq_width = Param(pdt.TypeDouble, "HSQ box width", 0.2, unit="μm")
    hsq_extra = Param(pdt.TypeDouble, "HSQ box extra length", 0.2, unit="μm")
    spacer_gradient = Param(
        pdt.TypeBoolean,
        "Spacer gradient: 51–53/0 dose levels inside the 50/0 spacer (width / 3 strips; rings for windows)",
        _PROCESS.spacer_gradient,
    )
    lj_nH = Param(
        pdt.TypeDouble,
        "Size by the PDK junction rule for this L_J (SQUID: parallel total; 0 = use the finger widths)",
        0.0,
        unit="nH",
    )
    clearer = Param(pdt.TypeBoolean, "Draw the CLEARER metal box under the windows (base_metal_addition)", False)
    clearer_inset = Param(pdt.TypeDouble, "CLEARER inset from the window sides", 1.0, unit="μm")

    def _fingers(self, n: int = 1) -> tuple[float, float]:
        """(straight, bent) finger widths after the sizing rules (``lj_nH``, KQC ``junction_width``)."""
        fw, sfw = self.finger_width, self.second_finger_width or self.finger_width
        if self.lj_nH > 0:
            from quantcore_circuits.circuit.bridges import fingers_for_lj  # pylint: disable=import-outside-toplevel

            fw, sfw, _ = fingers_for_lj(self.lj_nH, n, _PROCESS, self.second_finger_width or None)
        elif self.junction_width >= _PROCESS.finger_range_um[0]:
            fw = self.junction_width
            sfw = self.second_finger_width or fw
        return fw, sfw

    def _widths(self, n: int = 1):
        fw, sfw = self._fingers(n)
        pad_width = 0.5 if fw <= 0.25 else 2 * fw + fw / 10
        return fw, sfw, pad_width

    def _insert_layers(self, straight, bent, hsq, centres=None):
        """Fingers, spacer (+ gradient), CLEARER, protection and the frame refpoints. ``centres``: junction centres
        (µm, final frame) that order the gradient levels."""
        shift = pya.Trans(0, False, 0, int(round(self.window_height / 2 / self.layout.dbu)))
        self.cell.shapes(self.get_layer("SIS_junction")).insert(straight.transformed(shift))
        self.cell.shapes(self.get_layer("SIS_junction_2")).insert(bent.transformed(shift))
        if self.with_hsq and not hsq.is_empty():
            insert_spacer(self.cell, self.layout, hsq.transformed(shift), self.spacer_gradient, centres)
        w, h = self.window_width, self.window_height
        if self.clearer:
            ci = min(self.clearer_inset, w / 2 - 0.5)
            box = pya.DBox(-w / 2 + ci, 0, w / 2 - ci, h)
            self.cell.shapes(self.get_layer("base_metal_addition")).insert(box.to_itype(self.layout.dbu))
        self.add_protection(pya.DBox(-w / 2 - self.margin, -self.margin, w / 2 + self.margin, h + self.margin))
        self.refpoints["origin_squid"] = pya.DPoint(0, 0)
        self.refpoints["port_common"] = pya.DPoint(0, h)

    @staticmethod
    def _hsq_boxes(dbu, fw, sfw, y_off, overlap, hsq_width, extra):
        lx = -fw / 2 - hsq_width + overlap
        rx = fw / 2 - overlap
        y0 = (-sfw + y_off - extra) / dbu / 2  # the legacy "/2" centres the box on the junction
        y1 = (sfw + y_off + extra) / dbu / 2
        return pya.Box(lx / dbu, y0, (lx + hsq_width) / dbu, y1), pya.Box(rx / dbu, y0, (rx + hsq_width) / dbu, y1)


class TrilayerJunction(_TrilayerBase):
    """Single Nb trilayer cross junction (legacy ``xjc_junction_TL_mod.create_junction``)."""

    hsq_overlap = Param(pdt.TypeDouble, "HSQ overlap onto the finger", 0.045, unit="μm")
    bent_conn_height = Param(pdt.TypeDouble, "Bent finger connection height", 1.0, unit="μm")
    bent_finger_x = Param(pdt.TypeDouble, "Bent finger offset (legacy x)", 0.2, unit="μm")

    def build(self):
        dbu = self.layout.dbu
        fw, sfw, pad_width = self._widths()
        w, h = self.window_width, self.window_height
        straight = coerced_straight_finger(
            dbu, pad_width, 3, fw, self.straight_finger_length, w, h, 0, self.straight_finger_y
        )
        straight.transform(pya.Trans(0, True, 0, 0))  # legacy inserts the straight finger mirrored
        bent = coerced_bent_finger(
            dbu,
            self.bent_pad_width,
            sfw,
            self.bent_finger_length,
            self.bent_conn_height,
            w,
            h - 1,
            self.bent_finger_x,
            self.bent_finger_y,
            False,
        )
        bent.transform(pya.Trans(0, False, 0 / dbu, self.bent_shift / dbu))
        hsq = pya.Region()
        y_off = 2 * self.bent_finger_length / 3 + self.bent_conn_height + (self.bent_finger_y / 2) + 0.25
        for box in self._hsq_boxes(dbu, fw, sfw, y_off, self.hsq_overlap, self.hsq_width, self.hsq_extra):
            hsq.insert(box)
        # junction overlap centre (for markers / DRC), legacy (0, 1.0) in the centred frame
        centre = pya.DPoint(0, y_off / 2 + h / 2)
        self._insert_layers(straight, bent, hsq, [centre])
        self.refpoints["junction_1"] = centre


class TrilayerSquid(_TrilayerBase):
    """Two trilayer junctions forming a SQUID (legacy ``xjc_squid_TL_mod.create_squid``)."""

    junction_spacing = Param(pdt.TypeDouble, "Distance of each junction from the axis", 8.0, unit="μm")
    hsq_overlap = Param(pdt.TypeDouble, "HSQ overlap onto the finger", 0.03, unit="μm")
    lead_length = Param(pdt.TypeDouble, "Lead (pad) length of the straight fingers", 10.0, unit="μm")

    def build(self):
        dbu = self.layout.dbu
        fw, sfw, pad_width = self._widths(2)
        w, h, xs, ch = self.window_width, self.window_height, self.junction_spacing, self.lead_length
        mirror = pya.Trans(0, True, 0, 0)
        sargs = (dbu, pad_width, ch, fw, self.straight_finger_length, w, h)
        s1 = coerced_straight_finger(*sargs, xs, self.straight_finger_y)
        s2 = coerced_straight_finger(*sargs, -xs, self.straight_finger_y)
        straight = s1.transformed(mirror) & s2.transformed(mirror)  # legacy intersects the two negative windows
        shift = pya.Trans(0, False, 0, self.bent_shift / dbu)
        bargs = (dbu, self.bent_pad_width, sfw, self.bent_finger_length, ch, w, h - 1)
        b1 = coerced_bent_finger(*bargs, xs, self.bent_finger_y, False)
        b2 = coerced_bent_finger(*bargs, -xs, self.bent_finger_y, True)
        bent = b1.transformed(shift) & b2.transformed(shift)
        hsq = pya.Region()
        y_off = 2 * self.bent_finger_length / 3 + self.bent_finger_y + ch / 4
        for box in self._hsq_boxes(dbu, fw, sfw, y_off, self.hsq_overlap, self.hsq_width, self.hsq_extra):
            hsq.insert(box.transformed(pya.Trans(0, False, xs / dbu, 0)))
            hsq.insert(box.transformed(pya.Trans(0, False, -xs / dbu, 0)))
        centres = [pya.DPoint(xs, y_off / 2 + h / 2), pya.DPoint(-xs, y_off / 2 + h / 2)]
        self._insert_layers(straight, bent, hsq, centres)
        self.refpoints["junction_1"], self.refpoints["junction_2"] = centres


_NOMINAL = _PROCESS.nominal_fingers_um


def _squid_nominal() -> tuple[float, float]:
    """Fingers of each junction of the PDK nominal SQUID. The R_n window applies to the whole SQUID
    (2026-11-13), so a symmetric SQUID of R_n = ``rn_nominal_kohm`` has two junctions of twice that (90 kΩ each:
    0.25 × 0.6 µm on the default rule)."""
    from quantcore_circuits.circuit.bridges import fingers_for_lj, lj_from_rn  # pylint: disable=C0415

    straight, bent, _ = fingers_for_lj(lj_from_rn(_PROCESS.rn_nominal_kohm * 1e3, _PROCESS.gap_meV), 2, _PROCESS)
    return straight, bent


_SQUID_NOMINAL = _squid_nominal()


class QuantcoreJunction(TrilayerJunction):
    """The Quantcore PDK junction (``junction_type: "Quantcore Junction"`` in any KQC / Quantcore qubit): a
    TrilayerJunction with the PDK nominal fingers (straight 0.5 × bent 0.6 µm → R_n = 45 kΩ, L_J ≈ 6.7 nH on the
    default rule), the CLEARER box and the spacer gradient on. Size it with ``lj_nH`` or, from a KQC qubit, with the
    qubit's ``junction_width`` (straight finger, µm)."""

    qcc_category = "junction"

    finger_width = Param(pdt.TypeDouble, "Straight finger width (junction size)", _NOMINAL[0], unit="μm")
    second_finger_width = Param(pdt.TypeDouble, "Bent finger width (0 = same as straight)", _NOMINAL[1], unit="μm")
    clearer = Param(pdt.TypeBoolean, "Draw the CLEARER metal box under the windows (base_metal_addition)", True)


class QuantcoreSquid(TrilayerSquid):
    """The Quantcore PDK SQUID (``junction_type: "Quantcore Squid"``): a symmetric TrilayerSquid whose **whole SQUID**
    sits at the PDK nominal R_n (2026-11-13: the 40–50 kΩ window is for the SQUID; its junctions are higher):
    two junctions of 90 kΩ each (0.25 × 0.6 µm), parallel 45 kΩ, L_J ≈ 6.7 nH at zero flux. CLEARER and gradient on.
    ``lj_nH`` sizes the parallel total."""

    qcc_category = "junction"

    finger_width = Param(pdt.TypeDouble, "Straight finger width (junction size)", _SQUID_NOMINAL[0], unit="μm")
    second_finger_width = Param(
        pdt.TypeDouble, "Bent finger width (0 = same as straight)", _SQUID_NOMINAL[1], unit="μm"
    )
    clearer = Param(pdt.TypeBoolean, "Draw the CLEARER metal box under the windows (base_metal_addition)", True)


def trilayer_classes() -> dict:
    """KQC junction-library name → class, for the trilayer junction cells (``"Quantcore Junction"`` → ...)."""
    from kqcircuits.util.library_helper import to_library_name  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.layouts.junctions import legacy_junctions  # pylint: disable=import-outside-toplevel

    classes = [TrilayerJunction, TrilayerSquid, QuantcoreJunction, QuantcoreSquid]
    classes += [legacy_junctions.TrilayerJunctionHSQ, legacy_junctions.TrilayerSquidHSQ, legacy_junctions.SquidV0]
    classes += [legacy_junctions.TrilayerJunctionCompact]
    return {to_library_name(c.__name__): c for c in classes}


def is_squid_class(cls) -> bool:
    return issubclass(cls, TrilayerSquid) or cls.__name__ == "SquidV0"


def trilayer_junction_values(junction_type: str, params: dict | None = None, pdk=None):
    """Electrical values (:class:`~quantcore_circuits.circuit.bridges.JunctionValues`) of the junction a trilayer
    cell draws for ``params`` (``lj_nH``, ``finger_width``, ``second_finger_width``, KQC ``junction_width``), on the
    PDK rule; None when ``junction_type`` is not a trilayer cell."""
    from quantcore_circuits.circuit.bridges import (  # pylint: disable=import-outside-toplevel
        fingers_for_lj,
        junction_from_fingers,
    )

    cls = trilayer_classes().get(str(junction_type))
    if cls is None:
        return None
    schema = cls.get_schema()
    p = {k: v.default for k, v in schema.items()} | dict(params or {})
    n = 2 if is_squid_class(cls) else 1
    fw, sfw = float(p["finger_width"]), float(p["second_finger_width"] or p["finger_width"])
    if float(p.get("lj_nH") or 0) > 0:
        fw, sfw, _ = fingers_for_lj(float(p["lj_nH"]), n, pdk or _PROCESS, float(p["second_finger_width"]) or None)
    elif float(p.get("junction_width") or 0) >= _PROCESS.finger_range_um[0]:
        fw = float(p["junction_width"])
        sfw = float(p["second_finger_width"] or fw)
    return junction_from_fingers(fw, sfw, n, pdk or _PROCESS)


# ---- placing a trilayer junction across a gap (Metal junction lines, TwoPadTransmon) -----------------------------
MAX_WINDOW_WIDTH = 32.0  # µm, the trilayer cells' default window width


def _json_dict(text) -> dict:
    if isinstance(text, dict):
        return dict(text)
    value = json.loads(str(text or "").strip() or "{}")
    if not isinstance(value, dict):
        raise ValueError(f"junction_params must be a JSON dict, got {value!r}")
    return value


def _span(gap: pya.Region, origin: pya.DPoint, u: pya.DVector, t0: float, t1: float, at: float, dbu: float):
    """Extent (t_lo, t_hi) along unit vector ``u`` from ``origin`` of the piece of ``gap`` that a thin probe from
    ``t0`` to ``t1`` crosses at ``t = at``; None when ``at`` is not in the gap."""
    probe = pya.DPath([origin + u * t0, origin + u * t1], 2 * dbu, 0, 0).polygon().to_itype(dbu)
    best = None
    for poly in (gap & pya.Region(probe)).each():
        ts = [((pt.x * dbu - origin.x) * u.x + (pt.y * dbu - origin.y) * u.y) for pt in poly.each_point_hull()]
        lo, hi = min(ts), max(ts)
        if lo - 2 * dbu <= at <= hi + 2 * dbu:
            best = (lo, hi)
    return best


def trilayer_on_line(gap: pya.Region, a: pya.DPoint, b: pya.DPoint, dbu: float) -> tuple[pya.DCplxTrans, float, float]:
    """(transformation, window height, window width) of a trilayer junction cell bridging the gap that the
    junction line ``a`` (island side) → ``b`` crosses: ``origin_squid`` on the ``b``-side gap edge, ``port_common`` on
    the ``a``-side edge, the window as wide as fits (≤ 32 µm, 1 µm inside the gap on both sides)."""
    d = a - b
    length = d.length()
    if length <= 0:
        raise ValueError("junction line has zero length")
    u = d / length
    reach = length + 100.0
    span = _span(gap, b, u, -reach, reach, length / 2, dbu)
    t_lo, t_hi = span if span is not None else (0.0, length)
    origin = b + u * t_lo
    height = t_hi - t_lo
    v = pya.DVector(-u.y, u.x)
    mid = origin + u * (height / 2)
    side = _span(gap, mid, v, -100.0, 100.0, 0.0, dbu)
    width = MAX_WINDOW_WIDTH if side is None else min(MAX_WINDOW_WIDTH, 2 * min(-side[0], side[1]) - 2.0)
    angle = math.degrees(math.atan2(u.y, u.x)) - 90.0
    return pya.DCplxTrans(1, angle, False, origin.x, origin.y), height, width


def place_trilayer(element, jtype: str, gap: pya.Region, a: pya.DPoint, b: pya.DPoint, junction_params="{}"):
    """Insert the trilayer cell ``jtype`` (a Junction Library name, e.g. ``"Quantcore Junction"``) into
    ``element`` across the gap of the junction line a (island side, ``port_common``) → b (``origin_squid``), with
    the CLEARER on and ``junction_params`` (JSON / dict) passed on; returns the window footprint (dbu region).
    Raises ``ValueError`` for an unknown type or parameter."""
    cls = trilayer_classes().get(jtype)
    if cls is None:
        raise ValueError(
            f"junction_type {jtype!r} is not a trilayer junction cell; use one of {sorted(trilayer_classes())}"
        )
    trans, height, width = trilayer_on_line(gap, a, b, element.layout.dbu)
    params = {"window_height": height, "window_width": width, "clearer": True, **_json_dict(junction_params)}
    unknown = sorted(set(params) - set(cls.get_schema()))
    if unknown:
        raise ValueError(f"junction_params: unknown parameter(s) {unknown} for {cls.__name__}")
    cell = cls.create(element.layout, face_ids=element.face_ids, **params)
    element.insert_cell(cell, trans)
    box = pya.DBox(-width / 2, 0, width / 2, height)
    return pya.Region((trans * pya.DPolygon(box)).to_itype(element.layout.dbu))

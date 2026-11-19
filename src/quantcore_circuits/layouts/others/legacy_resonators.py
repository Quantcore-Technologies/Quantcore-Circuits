"""Meandered CPW resonators ported from the QWri library (fab mode): ``Coupled Resonator``, ``CPW Resonator``,
``Qubit Resonator`` and ``Coupled Connector``.

The legacy PCells trace a centre-line polyline (horizontal runs joined by semicircular arcs of fixed arc *length*
``arc_length``, i.e. radius ``arc_length / π``), draw it as a ``trace width`` path and etch ``negative`` = path grown
by the gap − path. Square boxes at the two ends short them to ground (box removed from the gap) or open them (box
added). The geometry here is the legacy fab output (legacy layer 1/0 with ``fab=True`` → ``base_metal_gap_wo_grid``),
computed with the same pya calls, the same int rounding and the same parameter coercion KLayout applies to the
legacy cells, so it XORs clean. Legacy 3/0 (second-metal envelope) and 10/0 (markers) are not drawn: 3/0 is derived
at mask export.

Trace width / gap are the element's ``a`` / ``b`` (legacy ``path_width`` / ``gap``), so routes inherit them; legacy
``n`` (points per arc) is ``arc_points`` here because a KQC chip passes its own ``n`` down to its elements.
"""

from __future__ import annotations

import math

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


class _Pen:
    """The legacy ``arc`` / ``horzPath`` / ``vertPath`` helpers (dbu, legacy rounding)."""

    def __init__(self, arc_len_dbu: float, n: int):
        self.arc_len, self.n = arc_len_dbu, n

    def arc(self, init, flag, length, angle_begin=math.pi / 2, angle_end=3 * math.pi / 2):
        """Semicircle (or the part of one of the global arc length) starting at ``init``; ``flag`` = clockwise."""
        direction = -1 if flag else 1
        counter = 0
        current_angle = angle_begin
        pts = [init]
        if length < self.arc_len:
            radius = self.arc_len / math.pi
            angle_end = float(math.pi * length) / self.arc_len + angle_begin
        else:
            radius = length / math.pi
        da = float((abs(angle_end) - current_angle) / self.n)
        r_point = pya.Point(
            pya.DPoint(init.x - (radius * math.cos(angle_begin)), init.y - (radius * math.sin(angle_begin)))
        )
        while counter <= self.n:
            x = r_point.x + radius * math.cos(current_angle)
            y = r_point.y + radius * math.sin(current_angle)
            pts.append(pya.Point(pya.DPoint(x, y)))
            current_angle = (current_angle + float(direction * da)) % (2 * math.pi)
            counter += 1
        return pts

    @staticmethod
    def horz(point, length, flag=True):
        """Point ``length`` to the right (``flag``) or left."""
        if not flag:
            length = -length
        return pya.Point(pya.DPoint(point.x + length, point.y))

    @staticmethod
    def vert(point, length, flag=True):
        """Point ``length`` down (``flag``) or up."""
        if flag:
            length = -length
        return pya.Point(pya.DPoint(point.x, point.y + length))


def _strip(dbu, pts, path_width, gap):
    """(trace region, negative = trace grown by the gap − trace), as the legacy cells compute them."""
    strip = pya.Region().insert(pya.Path(pts, path_width / dbu))
    strip = strip.flatten()
    return strip, strip.sized(gap / dbu) - strip


def _end_box_open(dbu, p, path_width, gap):
    """Legacy ``finalBox`` of the coupled/qubit resonators: the gap cap below a downward tail end."""
    return pya.Box(p.x - (path_width / 2 + gap) / dbu, p.y - (+gap) / dbu, p.x + (path_width / 2 + gap) / dbu, p.y)


def _square(dbu, p, half):
    return pya.Box(p.x - half / dbu, p.y - half / dbu, p.x + half / dbu, p.y + half / dbu)


# ---- Coupled Resonator ------------------------------------------------------------------------------------------
def coupled_resonator_points(
    dbu, cpw_len, width, arc_length, neck_length, clength, flip, tail, tail_len, tail_end, n
) -> list:
    """Legacy ``CoupledResonator.produce_impl`` centre line (dbu points). Coupler section on y = 0, meander below."""
    # KLayout's coerce_parameters_impl of the legacy cell
    if neck_length < arc_length:
        neck_length = arc_length
    if clength <= 0 or clength >= cpw_len:
        clength = width
    if arc_length < 50:
        arc_length = 50
    n = max(n, 30)

    len_dbu, wid_dbu = cpw_len / dbu, width / dbu
    arc_len, neck_dbu, c_length = arc_length / dbu, neck_length / dbu, clength / dbu
    pen = _Pen(arc_len, n)
    length = len_dbu
    arc_flag = flip
    radius = arc_len / math.pi

    def direction(x):
        return 1 if x else -1

    init = pya.Point(pya.DPoint(0.0, 0.0))
    pts = []
    start = pya.Point(init.x - (direction(arc_flag) * c_length / 2), init.y)
    if c_length >= wid_dbu:
        left_arc = pen.arc(start, not arc_flag, arc_len / 2, angle_begin=math.pi / 2)
        length = length - arc_len / 2
    else:
        left_arc = [start]
    if neck_dbu > arc_len and c_length >= wid_dbu:  # extra length on the non-twisted arm: half the neck
        extra_neck = neck_dbu - arc_len
        pts.append(pen.vert(left_arc[-1], extra_neck / 2))
        length = length - (extra_neck / 2)
    pts.extend(left_arc[::-1])
    pts.append(pen.horz(pya.Point(init.x - (direction(arc_flag) * c_length / 2), init.y), c_length, arc_flag))
    length = length - c_length
    if neck_dbu > arc_len:  # the neck on the twisted side
        extra_neck = neck_dbu - arc_len
        pts.extend(pen.arc(pts[-1], arc_flag, arc_len / 2))
        pts.append(pen.vert(pts[-1], extra_neck, True))
        pts.extend(pen.arc(pts[-1], arc_flag, arc_len / 2, math.pi * int(not arc_flag), -math.pi / 2))
        arc_flag = not arc_flag
        length = length - extra_neck - arc_len
    else:
        pts.extend(pen.arc(pts[-1], arc_flag, arc_len))
        arc_flag = not arc_flag
        length = length - arc_len

    tail_dbu = 0
    if tail:
        tail_dbu = tail_len / dbu  # the legacy "tail_calculate" switch is never set, so tail_len always applies
        length = length - tail_dbu
        period, lead = (wid_dbu + arc_len), (arc_len / 2 + (wid_dbu / 2 - radius))
        if (length % period) > lead:
            tail_dbu = length % period - lead + tail_dbu
        else:
            tail_dbu = length % period + period - lead + tail_dbu
            length = length - period
    while length - wid_dbu - arc_len >= 0:
        pts.append(pen.horz(pts[-1], wid_dbu, arc_flag))
        length = length - wid_dbu
        pts.extend(pen.arc(pts[-1], arc_flag, arc_len))
        length = length - arc_len
        arc_flag = not arc_flag
    if tail:
        pts.append(pen.horz(pts[-1], wid_dbu / 2 - radius, arc_flag))
        pts.extend(pen.arc(pts[-1], arc_flag, arc_len / 2))
        if not tail_end:
            pts.append(pen.vert(pts[-1], tail_dbu, True))
        else:
            pts.insert(0, pen.vert(pts[0], tail_dbu, True))
    return pts


def resonator_end_gaps(dbu, pts, path_width, gap, cgap, ground):
    """Fab gaps of the coupled / qubit resonators: the start (``pts[0]``) is shorted; the end is open with a gap
    cap (``ground``) or left without one, for a connection (``ground=False``)."""
    gap = 1 if gap < 0 else gap
    cgap = max(cgap, 1)
    _, negative = _strip(dbu, pts, path_width, gap)
    init_box = _square(dbu, pts[0], path_width / 2 + gap + cgap)
    final_box = _end_box_open(dbu, pts[-1], path_width, gap)
    return negative - init_box + final_box if ground else negative - init_box - final_box


# ---- CPW Resonator ----------------------------------------------------------------------------------------------
def cpw_resonator_points(
    dbu, cpw_len, width, arc_length, neck_length, gap, cgap, tail, tail_length, mid_tail, n
) -> list:
    """Legacy ``CPWResonator.produce_impl`` centre line (dbu points): starts at x = −(gap + cgap) on y = 0 and
    meanders to +x, the first arm below."""
    if neck_length < arc_length:
        neck_length = arc_length
    gap = 1 if gap < 0 else gap
    cgap = max(cgap, 1)
    arc_length = max(arc_length, 50)
    tail_length = max(tail_length, arc_length)
    n = max(n, 30)

    len_dbu, wid_dbu = cpw_len / dbu, width / dbu
    arc_path, tail_dbu, neck_dbu = arc_length / dbu, tail_length / dbu, neck_length / dbu
    pen = _Pen(arc_path, n)
    init = pya.Point(pya.DPoint(0.0, 0.0))
    pts = [pya.Point(pya.DPoint((-gap - cgap) / dbu, 0)), init]
    length = len_dbu
    arc_flag = True
    if tail:
        length = length - tail_dbu - arc_path / 2  # reserve the tail
        if (length % (wid_dbu + arc_path)) > wid_dbu:
            neck_dbu = (wid_dbu + arc_path - length % (wid_dbu + arc_path)) + neck_dbu  # keep the length fixed
    if neck_dbu > arc_path:
        length = length - neck_dbu - arc_path - wid_dbu
        pts.append(pen.horz(pts[-1], wid_dbu, arc_flag))
        pts.extend(pen.arc(pts[-1], arc_flag, arc_path / 2))
        pts.append(pen.vert(pts[-1], neck_dbu - arc_path, True))
        pts.extend(pen.arc(pts[-1], arc_flag, arc_path / 2, angle_begin=0, angle_end=-math.pi / 2))
        arc_flag = not arc_flag
    if mid_tail and tail:
        count = int(len_dbu / (wid_dbu + arc_path))
        wid_dbu = len_dbu / (count + 0.5) - arc_path
    while length >= 0:
        if length >= wid_dbu + arc_path:
            pts.append(pen.horz(pts[-1], wid_dbu, arc_flag))
            length = length - wid_dbu
            pts.extend(pen.arc(pts[-1], arc_flag, arc_path))
            length = length - arc_path
        elif length > wid_dbu:
            pts.append(pen.horz(pts[-1], wid_dbu, arc_flag))
            length = length - wid_dbu
            pts.append(pen.horz(pts[-1], length, arc_flag))
            length = -1
        else:
            pts.append(pen.horz(pts[-1], length, arc_flag))
            length = length - wid_dbu
        arc_flag = not arc_flag
    if tail:
        arc_flag = not arc_flag
        pts.extend(pen.arc(pts[-1], arc_flag, arc_path / 2))
        pts.append(pen.vert(pts[-1], tail_dbu, True))
    return pts


def cpw_resonator_gaps(dbu, pts, path_width, gap, cgap):
    """Fab gaps of the CPW Resonator: both ends end on ground (no gap cap)."""
    gap = 1 if gap < 0 else gap
    cgap = max(cgap, 1)
    final_p, init_p = pts[-1], pts[0]
    final_box = _square(dbu, final_p, path_width / 2 + gap)
    half = (path_width / 2 + gap + cgap) / dbu
    init_box = pya.Box(init_p.x - half, init_p.y - half, init_p.x, init_p.y + half)
    outer = pya.Region().insert(pya.Path(pts, path_width / dbu))
    outer.flatten()
    return outer.sized(gap / dbu) - outer - init_box - final_box


# ---- Qubit Resonator --------------------------------------------------------------------------------------------
def qubit_resonator_points(
    dbu,
    cpw_len,
    width,
    arc_length,
    neck_length,
    clength,
    flip,
    coupler_direction,
    tail_end,
    coupler_flat,
    tail_conn_length,
    n,
) -> list:
    """Legacy ``QubitResonator.produce_impl`` centre line (dbu points); the tail is always drawn."""
    if neck_length < arc_length:
        neck_length = arc_length
    if clength <= 0 or clength >= cpw_len:
        clength = width
    arc_length = max(arc_length, 50)
    n = max(n, 30)

    len_dbu, wid_dbu = cpw_len / dbu, width / dbu
    arc_len, neck_dbu, c_length = arc_length / dbu, neck_length / dbu, clength / dbu
    pen = _Pen(arc_len, n)
    length = len_dbu
    arc_flag = flip
    radius = arc_len / math.pi

    def direction(x):
        return 1 if x else -1

    init = pya.Point(pya.DPoint(0.0, 0.0))
    pts = []
    start = pya.Point(init.x - (direction(arc_flag) * c_length / 2), init.y)
    if not coupler_flat:
        left_arc = pen.arc(start, not arc_flag, arc_len / 2, angle_begin=math.pi / 2)
        length = length - arc_len / 2
    else:
        left_arc = [start]
        tail_end = False  # the extra tail only goes on the twisted end
    if neck_dbu > arc_len and c_length >= wid_dbu + radius and not coupler_flat and not coupler_direction:
        extra_neck = neck_dbu - arc_len
        pts.append(pen.vert(left_arc[-1], extra_neck / 2))
        length = length - (extra_neck / 2)
    pts.extend(left_arc[::-1])
    pts.append(pen.horz(pya.Point(init.x - (direction(arc_flag) * c_length / 2), init.y), c_length, arc_flag))
    length = length - c_length
    neck = list(pen.arc(pts[-1], arc_flag, arc_len / 2))
    extra_neck = neck_dbu - arc_len
    if extra_neck > 0:
        neck.append(pen.vert(neck[-1], extra_neck, True))
        length = length - extra_neck
    if coupler_direction:
        arc_flag = not arc_flag
    neck.extend(pen.arc(neck[-1], arc_flag, arc_len / 2, math.pi * int(not arc_flag), -math.pi / 2))
    length = length - arc_len
    pts.extend(neck)
    arc_flag = not arc_flag

    tail_len = tail_conn_length / dbu
    length = length - tail_len
    element_len = wid_dbu + arc_len
    remainder_len = length % element_len
    if remainder_len > arc_len / 2 + (wid_dbu / 2 - radius):
        tail_extra = remainder_len - (arc_len / 2 + (wid_dbu / 2 - radius))
    else:
        tail_extra = remainder_len + element_len - (arc_len / 2 + (wid_dbu / 2 - radius))
        length = length - element_len
    meander = [pts[-1]]
    while length - wid_dbu - arc_len >= 0:
        meander.append(pen.horz(meander[-1], wid_dbu, arc_flag))
        length = length - wid_dbu
        meander.extend(pen.arc(meander[-1], arc_flag, arc_len))
        length = length - arc_len
        arc_flag = not arc_flag
    pts.extend(meander)
    pts.append(pen.horz(pts[-1], wid_dbu / 2 - radius, arc_flag))
    pts.extend(pen.arc(pts[-1], arc_flag, arc_len / 2))
    pts.append(pen.vert(pts[-1], tail_len, True))
    if not tail_end:
        pts.append(pen.vert(pts[-1], tail_extra, True))
    else:
        pts.insert(0, pen.vert(pts[0], tail_extra, True))
    return pts


# ---- Coupled Connector ------------------------------------------------------------------------------------------
def coupled_connector_points(dbu, cpw_len, width, arc_length, neck_length, clength, flip, n) -> list:
    """Legacy ``CoupledConnector.produce_impl`` centre line (dbu points): from the origin down into a meander."""
    if neck_length < arc_length:
        neck_length = arc_length
    if clength <= 0 or clength >= cpw_len:
        clength = 500
    arc_length = max(arc_length, 50)
    n = max(n, 30)

    len_dbu, wid_dbu = cpw_len / dbu, width / dbu
    arc_len, neck_dbu, c_length = arc_length / dbu, neck_length / dbu, clength / dbu
    pen = _Pen(arc_len, n)
    length = len_dbu
    arc_flag = flip
    radius = arc_len / math.pi
    init = pya.Point(pya.DPoint(0.0, 0.0))
    pts = []
    if neck_dbu > arc_len:
        length = length - (neck_dbu - arc_len) / 2
    pts.append(init)
    if neck_dbu > arc_len:
        length = length - (neck_dbu - arc_len) - arc_len
    else:
        arc_flag = not arc_flag
        length = length - arc_len
    # the legacy tail is always on
    length = length - c_length - arc_len / 2 - arc_len - neck_dbu
    if (length % (wid_dbu + arc_len)) > arc_len / 2 + (wid_dbu / 2 - radius):
        tail_len = length % (wid_dbu + arc_len) - (arc_len / 2 + (wid_dbu / 2 - radius))
    else:
        tail_len = length % (wid_dbu + arc_len) + (wid_dbu + arc_len) - (arc_len / 2 + (wid_dbu / 2 - radius))
        length = length - (wid_dbu + arc_len)
    angle_begin = 0 if arc_flag else math.pi
    pts.append(pen.vert(pts[-1], tail_len, True))
    pts.extend(pen.arc(pts[-1], arc_flag, arc_len / 2, angle_begin=angle_begin))
    pts.append(pen.horz(pts[-1], wid_dbu / 2 - radius, not arc_flag))
    pts.extend(pen.arc(pts[-1], not arc_flag, arc_len))
    length = length - arc_len
    while length >= 0:
        pts.append(pen.horz(pts[-1], wid_dbu, arc_flag))
        length = length - wid_dbu
        pts.extend(pen.arc(pts[-1], arc_flag, arc_len))
        length = length - arc_len
        arc_flag = not arc_flag
    pts.append(pen.horz(pts[-1], wid_dbu / 2 - radius, arc_flag))
    pts.extend(pen.arc(pts[-1], arc_flag, arc_len / 2))
    pts.append(pen.vert(pts[-1], tail_len, True))
    return pts


def coupled_connector_gaps(dbu, pts, path_width, gap, cgap, ground):
    """Fab gaps of the Coupled Connector: start shorted; end connected (``ground``, legacy "connector side
    ungrounded for a capacitor") or open with a gap box."""
    gap = 1 if gap < 0 else gap
    cgap = max(cgap, 1)
    _, negative = _strip(dbu, pts, path_width, gap)
    init_box = _square(dbu, pts[0], path_width / 2 + gap + cgap)
    final_box = _square(dbu, pts[-1], path_width / 2 + gap)
    return negative - init_box - final_box if ground else negative - init_box + final_box


# ---- elements ---------------------------------------------------------------------------------------------------
def _snap(x: float) -> float:
    return float(round(x)) if abs(x - round(x)) < 1e-9 else x


def _end_direction(pts, at_start: bool, dbu: float) -> tuple[pya.DPoint, pya.DVector]:
    """End point (µm) and outward unit direction of a polyline end (skips repeated points)."""
    seq = pts if at_start else pts[::-1]
    end = seq[0]
    for p in seq[1:]:
        if p != end:
            v = pya.DVector((end.x - p.x) * dbu, (end.y - p.y) * dbu)
            v = v / v.length()
            return pya.DPoint(end.x * dbu, end.y * dbu), pya.DVector(_snap(v.x), _snap(v.y))
    return pya.DPoint(end.x * dbu, end.y * dbu), pya.DVector(0, -1)


class _MeanderResonator(Element):
    """Shared parameters of the legacy meandered resonators (µm)."""

    cpw_len = Param(pdt.TypeDouble, "Length of the resonator", 4000, unit="μm")
    width = Param(pdt.TypeDouble, "Meander width (straight run between arcs)", 500, unit="μm")
    arc_length = Param(pdt.TypeDouble, "Arc length of a meander turn (radius = arc_length / π)", 300, unit="μm")
    neck_length = Param(pdt.TypeDouble, "Neck length", 400, unit="μm")
    cgap = Param(pdt.TypeDouble, "Coupling gap (ground strip around the shorted end)", 6, unit="μm")
    arc_points = Param(pdt.TypeInt, "Points per arc (legacy n)", 256)

    qcc_category = "resonator"
    _M3_EXTRA = 0.0  # legacy 3/0: centre line grown by b + cgap + this (µm)

    def _points(self) -> list:
        raise NotImplementedError

    def _keepout_region(self, pts) -> pya.Region:
        """Legacy 3/0 (``fab_l``): the centre-line path (width a) grown by b + cgap + ``_M3_EXTRA`` (dbu)."""
        dbu = self.layout.dbu
        gap, cgap = (1 if self.b < 0 else self.b), max(self.cgap, 1)
        strip = pya.Region().insert(pya.Path(pts, self.a / dbu))
        strip.flatten()
        return strip.sized(round((gap + cgap + self._M3_EXTRA) / dbu))

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): the legacy PCell's ``fab_l`` shape (:mod:`..keepout`)."""
        from quantcore_circuits.layouts.others.keepout import as_cell, dpolygons  # pylint: disable=C0415

        obj = as_cell(cls, params)
        return dpolygons(cls._keepout_region(obj, cls._points(obj)))

    def _gaps(self, pts) -> pya.Region:
        raise NotImplementedError

    def _ports(self, pts):
        dbu = self.layout.dbu
        pos, d = _end_direction(pts, True, dbu)
        self.refpoints["short_end"] = pos
        pos, d = _end_direction(pts, False, dbu)
        self.add_port("end", pos, d)

    def build(self):
        dbu = self.layout.dbu
        pts = self._points()
        gaps = self._gaps(pts)
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        envelope = pya.Region(pya.Path(pts, self.a / dbu)).sized(self.b / dbu)
        self.add_protection((envelope + gaps).merged().sized(self.margin / dbu))
        self._ports(pts)


class CoupledResonator(_MeanderResonator):
    """λ/4 meander resonator with a straight coupler section on y = 0 (legacy ``Coupled Resonator``); port ``end``.

    The coupler runs from x = −clength/2 to +clength/2 (mirrored by ``flip``) on y = 0, the meander hangs below it.
    The start next to the coupler (refpoint ``short_end``) is shorted to ground; port ``end`` is the far tail end:
    open with a gap cap (``ground=True``, a hanger resonator; the cap lies *beyond* the port, so anything joined
    there galvanically is cut off) or without one, to continue into a qubit claw (``ground=False``). A feedline
    with the same CPW runs at y = ``a/2 + b + cgap + b + a/2`` above the coupler (refpoint ``feedline_center``), as
    in the legacy chips (26 µm for 10/6/4).
    """

    clength = Param(pdt.TypeDouble, "Coupling length", 500, unit="μm")
    ground = Param(pdt.TypeBoolean, "Open far end with a gap cap (False: end left for a connection)", True)
    flip = Param(pdt.TypeBoolean, "Flip the meander direction", True)
    tail = Param(pdt.TypeBoolean, "Tail", True)
    tail_len = Param(pdt.TypeDouble, "Extra tail length", 0, unit="μm")
    tail_end = Param(pdt.TypeBoolean, "Tail on the coupler end", False)

    def _points(self):
        return coupled_resonator_points(
            self.layout.dbu,
            self.cpw_len,
            self.width,
            self.arc_length,
            self.neck_length,
            self.clength,
            self.flip,
            self.tail,
            self.tail_len,
            self.tail_end,
            self.arc_points,
        )

    def _gaps(self, pts):
        return resonator_end_gaps(self.layout.dbu, pts, self.a, self.b, self.cgap, self.ground)

    def _ports(self, pts):
        super()._ports(pts)
        self.refpoints["coupler_center"] = pya.DPoint(0, 0)
        self.refpoints["feedline_center"] = pya.DPoint(0, self.a + 2 * self.b + max(self.cgap, 1))


class CpwResonator(_MeanderResonator):
    """Meandered CPW resonator grounded at both ends (legacy ``CPW Resonator``); ports ``start`` and ``end``.

    Starts at x = −(b + cgap) on y = 0 heading +x (port ``start``, facing −x), first arm below, optional neck and
    tail (``tail``, ``tail_length``, ``mid_tail``). Both ends run into ground (no gap caps): ``start`` at the
    centre-line start, ``end`` where the drawn gap stops, ``a/2 + b`` before the last centre-line point (the legacy
    end box clears the gap there). A route joined at either port continues the conductor; left free, the end is
    shorted to ground.
    """

    width = Param(pdt.TypeDouble, "Meander width (straight run between arcs)", 500, unit="μm")
    arc_length = Param(pdt.TypeDouble, "Arc length of a meander turn (radius = arc_length / π)", 100, unit="μm")
    neck_length = Param(pdt.TypeDouble, "Neck length", 100, unit="μm")
    tail = Param(pdt.TypeBoolean, "Tail", False)
    tail_length = Param(pdt.TypeDouble, "Tail length", 100, unit="μm")
    mid_tail = Param(pdt.TypeBoolean, "Tail in the middle", False)

    def _points(self):
        return cpw_resonator_points(
            self.layout.dbu,
            self.cpw_len,
            self.width,
            self.arc_length,
            self.neck_length,
            self.b,
            self.cgap,
            self.tail,
            self.tail_length,
            self.mid_tail,
            self.arc_points,
        )

    def _gaps(self, pts):
        return cpw_resonator_gaps(self.layout.dbu, pts, self.a, self.b, self.cgap)

    def _keepout_region(self, pts) -> pya.Region:
        """Legacy 3/0: bbox of the simulation-mode CPW (trace + coupling ring + start box − end box) grown by
        a/2 + b + 15 µm in x and 35 µm in y (``CPWResonator.lym``)."""
        dbu = self.layout.dbu
        gap, cgap, pw = (1 if self.b < 0 else self.b), max(self.cgap, 1), self.a
        final_box = _square(dbu, pts[-1], pw / 2 + gap)
        half = (pw / 2 + gap + cgap) / dbu
        init_p = pts[0]
        init_box = pya.Box(init_p.x - half, init_p.y - half, init_p.x, init_p.y + half)
        outer = pya.Region().insert(pya.Path(pts, pw / dbu))
        outer.flatten()
        ring = outer.sized((gap + cgap) / dbu) - outer.sized(gap / dbu)
        cpw = ring + outer + init_box - final_box
        return pya.Region().insert(cpw.bbox()).sized((pw / 2 + gap + 15) / dbu, 35 / dbu, 2)

    def _ports(self, pts):
        dbu = self.layout.dbu
        pos, d = _end_direction(pts, True, dbu)
        self.add_port("start", pos, d)
        pos, d = _end_direction(pts, False, dbu)
        # the legacy end box (half-size a/2 + b around the last point) clears the last a/2 + b of the gap: the drawn
        # CPW, and so the port, ends that far before the last centre-line point (``start`` has no such box ahead)
        self.add_port("end", pos - d * (self.a / 2 + (1 if self.b < 0 else self.b)), d)


class QubitResonator(_MeanderResonator):
    """λ/4 readout resonator with a coupler section and a mandatory tail to a qubit (legacy ``Qubit Resonator``).

    Like :class:`CoupledResonator` (coupler on y = 0, shorted start ``short_end``, port ``end`` at the tail), plus
    ``coupler_direction`` / ``coupler_flat`` variants and a fixed ``tail_conn_length`` before the computed extra tail.
    ``end`` is an open end with ``ground=True`` (the gap cap lies beyond the port: nothing joined there galvanically
    is connected); ``ground=False`` leaves it for a connection.
    """

    width = Param(pdt.TypeDouble, "Meander width (straight run between arcs)", 400, unit="μm")
    cgap = Param(pdt.TypeDouble, "Coupling gap (ground strip around the shorted end)", 2, unit="μm")
    clength = Param(pdt.TypeDouble, "Coupling length", 500, unit="μm")
    ground = Param(pdt.TypeBoolean, "Open far end with a gap cap (False: end left for a connection)", True)
    flip = Param(pdt.TypeBoolean, "Flip the meander direction", True)
    coupler_direction = Param(pdt.TypeBoolean, "Coupling direction", False)
    tail_end = Param(pdt.TypeBoolean, "Extra tail on the twisted end", True)
    coupler_flat = Param(pdt.TypeBoolean, "Flat coupler (no arc at the coupler start)", False)
    tail_conn_length = Param(pdt.TypeDouble, "Tail connection length", 100, unit="μm")

    _M3_EXTRA = 7.0  # legacy: (5 + gap) + 2 + cgap

    def _points(self):
        return qubit_resonator_points(
            self.layout.dbu,
            self.cpw_len,
            self.width,
            self.arc_length,
            self.neck_length,
            self.clength,
            self.flip,
            self.coupler_direction,
            self.tail_end,
            self.coupler_flat,
            self.tail_conn_length,
            self.arc_points,
        )

    def _gaps(self, pts):
        return resonator_end_gaps(self.layout.dbu, pts, self.a, self.b, self.cgap, self.ground)

    def _ports(self, pts):
        super()._ports(pts)
        self.refpoints["coupler_center"] = pya.DPoint(0, 0)


class CoupledConnector(_MeanderResonator):
    """Meandered CPW connector from the origin downwards (legacy ``Coupled Connector``); ports ``start``, ``end``.

    The start (origin, facing +y) is shorted to ground; the end (facing −y) is left without a gap cap for a
    connection (``ground=True``, legacy "connector side ungrounded for a capacitor") or open with a gap box
    (``ground=False``, default: the box covers the port, so ``end`` cannot be joined galvanically).
    """

    width = Param(pdt.TypeDouble, "Meander width (straight run between arcs)", 500, unit="μm")
    clength = Param(pdt.TypeDouble, "Coupling length (subtracted from the meander length)", 500, unit="μm")
    ground = Param(pdt.TypeBoolean, "End left without a gap cap, for a connection", False)
    flip = Param(pdt.TypeBoolean, "Flip the meander direction", True)

    qcc_category = "waveguide"
    _M3_EXTRA = 30.0  # legacy: (10 + gap) + 20 + cgap

    def _points(self):
        return coupled_connector_points(
            self.layout.dbu,
            self.cpw_len,
            self.width,
            self.arc_length,
            self.neck_length,
            self.clength,
            self.flip,
            self.arc_points,
        )

    def _gaps(self, pts):
        return coupled_connector_gaps(self.layout.dbu, pts, self.a, self.b, self.cgap, self.ground)

    def _ports(self, pts):
        dbu = self.layout.dbu
        pos, d = _end_direction(pts, True, dbu)
        self.add_port("start", pos, d)
        pos, d = _end_direction(pts, False, dbu)
        self.add_port("end", pos, d)

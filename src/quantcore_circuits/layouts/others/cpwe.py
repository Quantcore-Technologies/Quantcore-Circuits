"""CPW-E cells (ported from the ``components/python/cpwe.py`` drawing library of the Glasgow group, used by the
``pymacros/Cong`` macros: bond pads, the capacitively coupled λ/4 resonators, finger/gap capacitors, tapers, meanders).

The legacy library draws the CPW *gaps* (etched) with an implicit pen ``(x, y, ori)`` in nm (dbu 0.001); arcs are
KLayout ``Basic.ARC`` cells. :class:`CpwePen` reproduces it call for call (same ``pya`` boxes, transforms and ARC
PCell), collecting the gaps in a Region. The cells below wrap one legacy function each, horizontal (``ori='h'``),
starting at the origin, with parameters in µm (``a``/``b`` = legacy ``w``/``s``):

* :class:`CpweBondPad` (``b_pad``): open end + wide line + taper; port ``a`` at the CPW end.
* :class:`CpweQuarterWaveResonator` (``quarter_cap_coupled``): open coupler arm, bend, taper, meander, shorted end.
* :class:`CpweFingerCapacitor` (``finger_cap``), :class:`CpweGapCapacitor` (``gap_cap``),
  :class:`CpweFingerLine` (``finger_line``), :class:`CpweTaper` (``tapper``), :class:`CpweOpenEnd` (``term_open``),
  :class:`CpweMeanderLine` (``meander_line``; with ``lead`` = legacy ``quarter_wave``).

Geometry → ``base_metal_gap_wo_grid``. Ports face outward; CPW widths from the relevant ``w``/``s``.
"""

from __future__ import annotations

import numpy as np
from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def exp_pts(x_start, x_end, y_start, y_end, b, t_type, npts):
    """Legacy ``draw.exp_pts`` (exponential taper profiles)."""
    points = np.linspace(0, 1, npts)
    x = np.linspace(x_start, x_end, npts)
    if t_type == 1:
        y = (y_start - y_end) * np.exp(-1 * b * points) + (y_start - (y_start - y_end))
    elif t_type == 2:
        y = y_start + (y_end - y_start) * (np.exp(b * points)) / (np.exp(b))
    else:
        p1 = np.linspace(-0.5, 0, int(npts / 2))
        p2 = np.linspace(0, 0.5, int(npts / 2))
        y1 = (y_end - y_start) * (0.5 * np.exp(b * p1)) + (y_end - (y_end - y_start))
        y2 = (y_end - y_start) * (1 - 0.5 * np.exp(-b * p2)) + (y_end - (y_end - y_start))
        x = (0.5 + np.concatenate((p1, p2))) * (x_end - x_start) + x_start
        y = np.concatenate((y1, y2))
    return [(x[i], y[i]) for i in range(len(points))]


class CpwePen:
    """The legacy ``cpwe`` functions, drawing into ``self.region`` (dbu = nm) instead of the global current cell."""

    def __init__(self, dbu: float = 0.001):
        self.dbu = dbu
        self.region = pya.Region()
        self._scratch = pya.Layout()
        self._scratch.dbu = dbu
        self._arc_layer = self._scratch.layer(1, 0)

    def _insert(self, shape):
        self.region.insert(shape)

    def line(self, x, y, ori, w, s, length, rev):
        ang = 0 if ori == "h" else 1
        turn = 0 if not rev else 2
        x_last, y_last = x, y
        for box in (pya.Box(0, -1 * 0.5 * w - s, length, -1 * 0.5 * w), pya.Box(0, 0.5 * w, length, 0.5 * w + s)):
            if ang == 0:
                x_last = x - length if rev else x + length
                self._insert(box.transformed(pya.Trans(0 + turn, False, x, y)))
            else:
                y_last = y - length if rev else y + length
                self._insert(box.transformed(pya.Trans(1 + turn, False, x, y)))
        return x_last, y_last, length

    def finger_cap(self, x, y, ori, w, s, f_sep, f_length, f_n, rev):
        ang = 0 if ori == "h" else 1
        turn = 2 if rev else 0
        x_last, y_last, l_tot = x, y, f_length + f_sep
        f_width = (w - ((f_n - 1) * f_sep)) / f_n
        boxes = [
            pya.Box(0, -1 * 0.5 * w - s, f_length + f_sep, -1 * 0.5 * w),
            pya.Box(0, 0.5 * w + s, f_length + f_sep, 0.5 * w),
        ]
        count = 0
        for i in range(f_n):
            if count == 0:
                boxes.append(
                    pya.Box(0, -0.5 * w + i * (f_width + f_sep), f_length, -0.5 * w + f_width + i * (f_width + f_sep))
                )
                count = 1
            else:
                boxes.append(
                    pya.Box(
                        f_sep,
                        -0.5 * w + i * (f_width + f_sep),
                        f_length + f_sep,
                        -0.5 * w + f_width + i * (f_width + f_sep),
                    )
                )
                count = 0
        invertbox = pya.Box(0, -1 * 0.5 * w, f_length + f_sep, 0.5 * w)
        invpat = pya.Region(boxes) ^ pya.Region(invertbox)
        if ang == 0:
            x_last = x - (f_length + f_sep) if rev else x + f_length + f_sep
            self._insert(invpat.transformed(pya.Trans(turn, False, x, y)))
        else:
            y_last = y - (f_length + f_sep) if rev else y + f_length + f_sep
            self._insert(invpat.transformed(pya.Trans(1 + turn, False, x, y)))
        return x_last, y_last, l_tot

    def gap_cap(self, x, y, ori, w, s, cap_sep, rev):
        ang = 0 if ori == "h" else 1
        turn = 2 if rev else 0
        x_last, y_last = x, y
        box = pya.Box(0, -1 * 0.5 * w - s, cap_sep, 1 * 0.5 * w + s)
        if ang == 0:
            x_last = x - cap_sep if rev else x + cap_sep
            self._insert(box.transformed(pya.Trans(turn, False, x, y)))
        else:
            y_last = y - cap_sep if rev else y + cap_sep
            self._insert(box.transformed(pya.Trans(1 + turn, False, x, y)))
        return x_last, y_last, cap_sep

    def finger_line(self, x, y, ori, w, s, f_sep, f_length, f_width, f_n, rev):
        ang = 1 if ori == "h" else 0
        turn = 2 if rev else 0
        total_len = f_sep * (f_n - 1) + f_width * f_n
        x_last, y_last = x, y
        boxes1, boxes2 = [], []
        count = 0
        for i in range(f_n):
            y0, y1 = 0 + i * (f_width + f_sep), f_width + i * (f_width + f_sep)
            if count == 0:
                boxes1.append(pya.Box(-0.5 * w - s, y0, -0.5 * w - s + f_length, y1))
                boxes2.append(pya.Box(0.5 * w + s, y0, 0.5 * w + s - f_length, y1))
                count = 1
            else:
                boxes1.append(pya.Box(-0.5 * w, y0, -0.5 * w - f_length, y1))
                boxes2.append(pya.Box(0.5 * w, y0, 0.5 * w + f_length, y1))
                count = 0
        invertbox1 = pya.Box(-1 * 0.5 * w - s, 0, -1 * 0.5 * w, (f_width * f_n) + (f_sep * (f_n - 1)))
        invertbox2 = pya.Box(0.5 * w, 0, 0.5 * w + s, (f_width * f_n) + (f_sep * (f_n - 1)))
        for pattern in (pya.Region(boxes1) ^ pya.Region(invertbox1), pya.Region(boxes2) ^ pya.Region(invertbox2)):
            if ang == 0:
                y_last = y - total_len if rev else y + total_len
                self._insert(pattern.transformed(pya.Trans(turn, False, x, y)))
            else:
                x_last = x - total_len if rev else x + total_len
                self._insert(pattern.transformed(pya.Trans(turn + 3, False, x, y)))
        return x_last, y_last, total_len

    def tapper(self, x, y, ori, w_start, s_start, w_end, s_end, length, t_type, weight, rev):
        ang = 0 if ori == "h" else 1
        turn = 2 if rev else 0
        x_last, y_last = x, y
        poly_pts = []
        if t_type == 0:
            poly_pts.append(
                [
                    pya.Point(0, -0.5 * w_start - s_start),
                    pya.Point(0, -0.5 * w_start),
                    pya.Point(length, -0.5 * w_end),
                    pya.Point(length, -0.5 * w_end - s_end),
                ]
            )
            poly_pts.append(
                [
                    pya.Point(0, 0.5 * w_start + s_start),
                    pya.Point(0, 0.5 * w_start),
                    pya.Point(length, 0.5 * w_end),
                    pya.Point(length, 0.5 * w_end + s_end),
                ]
            )
        else:
            for sign in (-1, 1):
                outer = exp_pts(
                    0,
                    length,
                    y_start=sign * (0.5 * w_start + s_start),
                    y_end=sign * (0.5 * w_end + s_end),
                    b=weight,
                    t_type=t_type,
                    npts=100,
                )
                inner = exp_pts(
                    0, length, y_start=sign * 0.5 * w_start, y_end=sign * 0.5 * w_end, b=weight, t_type=t_type, npts=100
                )
                inner.reverse()
                poly_pts.append([pya.Point(x1, y1) for x1, y1 in outer + inner])
        for pts in poly_pts:
            if ang == 0:
                x_last = x - length if rev else x + length
                self._insert(pya.Polygon(pts).transformed(pya.Trans(turn, False, x, y)))
            else:
                y_last = y - length if rev else y + length
                self._insert(pya.Polygon(pts).transformed(pya.Trans(1 + turn, False, x, y)))
        return x_last, y_last, length

    def _basic_arc(self, x_um, y_um, start, end, r1, r2, npoints):
        cell = self._scratch.create_cell(
            "ARC",
            "Basic",
            {
                "layer": pya.LayerInfo(1, 0),
                "actual_start_angle": start,
                "actual_end_angle": end,
                "actual_radius1": r1,
                "actual_radius2": r2,
                "npoints": npoints,
            },
        )
        region = pya.Region(cell.begin_shapes_rec(self._arc_layer))
        disp = pya.DCellInstArray(cell.cell_index(), pya.DTrans(pya.DVector(x_um, y_um))).trans.disp
        self._insert(region.transformed(pya.Trans(disp.to_itype(self.dbu))))

    def arc(self, x, y, ori, w, s, turn, start_angle, end_angle, m_radius, npoints):
        rot = np.sqrt((end_angle - start_angle) ** 2)
        dirc = (end_angle - start_angle) / rot
        l_tot = (2 * np.pi * m_radius) * (rot / 360)
        if dirc == -1:
            start_angle, end_angle = end_angle, start_angle
        if ori == "v":
            if turn == "l":
                x_last = x - m_radius - (rot - 90) * (m_radius) / 90
                y_last = y + m_radius * dirc - (rot - 90) * (m_radius) * dirc / 90
                x = (x - m_radius) / 1000
            else:
                start_angle = start_angle + (180 - rot) + ((180 - rot) / 90) * 180 * (1 - dirc) / 2
                end_angle = end_angle + (180 - rot) + ((180 - rot) / 90) * 180 * (1 - dirc) / 2
                x_last = x + m_radius + (rot - 90) * (m_radius) / 90
                y_last = y + m_radius * dirc - (rot - 90) * (m_radius) * dirc / 90
                x = (x + m_radius) / 1000
            y = y / 1000
        else:
            if turn == "l":
                start_angle = start_angle + 270 + (180 - rot) + (1 - dirc) * (180 - rot)
                end_angle = end_angle + 270 + (180 - rot) + (1 - dirc) * (180 - rot)
                y_last = y - m_radius - (rot - 90) * (m_radius) / 90
                x_last = x + m_radius * dirc - (rot - 90) * (m_radius) * dirc / 90
                y = (y - m_radius) / 1000
            else:
                start_angle = start_angle + 270
                end_angle = end_angle + 270
                y_last = y + m_radius + (rot - 90) * (m_radius) / 90
                x_last = x + m_radius * dirc - (rot - 90) * (m_radius) * dirc / 90
                y = (y + m_radius) / 1000
            x = x / 1000
        r_in, r_out = (m_radius - 0.5 * w - s) / 1000, (m_radius - 0.5 * w) / 1000
        self._basic_arc(x, y, start_angle, end_angle, r_in, r_out, npoints)
        r_in, r_out = (m_radius + 0.5 * w) / 1000, (m_radius + 0.5 * w + s) / 1000
        self._basic_arc(x, y, start_angle, end_angle, r_in, r_out, npoints)
        return x_last, y_last, l_tot

    def term_open(self, x, y, ori, w, s, length, rev):
        ang = 0 if ori == "h" else 1
        turn = 2 if rev else 0
        x_last, y_last = x, y
        box = pya.Box(0, -0.5 * w - s, length, 0.5 * w + s)
        if ang == 0:
            x_last = x - length if rev else x + length
            self._insert(box.transformed(pya.Trans(turn, False, x, y)))
        else:
            y_last = y - length if rev else y + length
            self._insert(box.transformed(pya.Trans(1 + turn, False, x, y)))
        return x_last, y_last, length

    def marker(self, x, y):
        self._insert(pya.Box(x - 1000, y - 10000, x + 1000, y + 10000))
        self._insert(pya.Box(x - 10000, y - 1000, x + 10000, y + 1000))

    def meander_line(self, x, y, ori, w, s, m_radius, m_length, m_bias, n, flip, term_early):
        m_length = int(m_length)
        ltot = 0
        if not flip:
            up = int(m_length * m_bias)
            down = m_length - up
            st, sp, rt, rp, rq, rr, t = False, True, 0, 90, 180, 360, "r"
            x, y, length = self.arc(x, y, ori, w, s, t, rt, rp, m_radius, 1000)
            ltot += length
            ori = "v" if ori == "h" else "h"
            for step in (
                ("line", up - m_radius, st),
                ("arc", rt, rq),
                ("line", m_length, sp),
                ("arc", rq, rr),
            ):
                x, y, length = self._step(x, y, ori, w, s, t, m_radius, step)
                ltot += length
            for _ in range(n - 1):
                for step in (("line", m_length, st), ("arc", rt, rq), ("line", m_length, sp), ("arc", rq, rr)):
                    x, y, length = self._step(x, y, ori, w, s, t, m_radius, step)
                    ltot += length
            if not term_early:
                for step in (("line", down - m_radius, False), ("arc", rt, rp)):
                    x, y, length = self._step(x, y, ori, w, s, t, m_radius, step)
                    ltot += length
        else:
            up = int(m_length * (1 - m_bias))
            down = m_length - up
            st, sp, t = True, False, "r"
            x, y, length = self.arc(x, y, ori, w, s, "l", 0, 90, m_radius, 1000)
            ltot += length
            ori = "v" if ori == "h" else "h"
            for step in (("line", up - m_radius, st), ("arc", 180, 360), ("line", m_length, sp), ("arc", 0, 180)):
                x, y, length = self._step(x, y, ori, w, s, t, m_radius, step)
                ltot += length
            for _ in range(n - 1):
                for step in (("line", m_length, st), ("arc", 180, 360), ("line", m_length, sp), ("arc", 0, 180)):
                    x, y, length = self._step(x, y, ori, w, s, t, m_radius, step)
                    ltot += length
            if not term_early:
                for step in (("line", down - m_radius, st), ("arc", 360, 270)):
                    x, y, length = self._step(x, y, ori, w, s, t, m_radius, step)
                    ltot += length
        return x, y, ltot

    def _step(self, x, y, ori, w, s, t, m_radius, step):
        if step[0] == "line":
            return self.line(x, y, ori, w, s, step[1], step[2])
        return self.arc(x, y, ori, w, s, t, step[1], step[2], m_radius, 1000)

    def b_pad(self, x, y, ori, wb, sb, w, s, tl, bl, btl, t_type, weight, rev, mirror, markers):
        l_tot = 0
        if not mirror:
            x, y, length = self.term_open(x, y, ori, wb, sb, tl, rev)
            l_tot += length
            x, y, length = self.line(x, y, ori, wb, sb, bl, rev)
            l_tot += length
            x, y, length = self.tapper(x, y, ori, wb, sb, w, s, btl, t_type, weight, rev)
            l_tot += length
            if markers:
                self.marker(x, y - (50000 + w + s))
                self.marker(x, y + (50000 + w + s))
        else:
            if markers:
                self.marker(x, y - (50000 + w + s))
                self.marker(x, y + (50000 + w + s))
            x, y, length = self.tapper(x, y, ori, w, s, wb, sb, btl, t_type, weight, rev)
            l_tot += length
            x, y, length = self.line(x, y, ori, wb, sb, bl, rev)
            l_tot += length
            x, y, length = self.term_open(x, y, ori, wb, sb, tl, rev)
            l_tot += length
        return x, y, l_tot

    def quarter_cap_coupled(
        self, x, y, ori, w, s, wcap, scap, cap_len, cap_rad, t_len, m_radius, m_length, m_n, ex1, ex2, flip
    ):
        ltot = 0
        if flip:
            st, sp, t = True, False, "r"
            a1, a2, a3, a4, a5 = 360, 270, 180, 0, 360
        else:
            sp, st, t = True, False, "l"
            a1, a2, a3, a4, a5 = 0, 90, 180, 360, 0
        x, y, _ = self.term_open(x, y, ori, wcap, scap, scap, st)
        x, y, length = self.line(x, y, ori, wcap, scap, cap_len, st)
        ltot += length
        x, y, length = self.arc(x, y, ori, wcap, scap, t, a1, a2, cap_rad, 1000)
        ltot += length
        ori = "v"
        x, y, length = self.tapper(x, y, ori, wcap, scap, w, s, t_len, 0, 0, sp)
        ltot += length
        x, y, length = self.line(x, y, ori, w, s, m_length + m_radius + ex1, sp)
        ltot += length
        x, y, length = self.arc(x, y, ori, w, s, t, a4, a3, m_radius, 1000)
        ltot += length
        x, y, length = self.line(x, y, ori, w, s, m_length, st)
        ltot += length
        x, y, length = self.arc(x, y, ori, w, s, t, a3, a5, m_radius, 1000)
        ltot += length
        for _ in range(m_n - 1):
            x, y, length = self.line(x, y, ori, w, s, m_length, sp)
            ltot += length
            x, y, length = self.arc(x, y, ori, w, s, t, a4, a3, m_radius, 1000)
            ltot += length
            x, y, length = self.line(x, y, ori, w, s, m_length, st)
            ltot += length
            x, y, length = self.arc(x, y, ori, w, s, t, a3, a5, m_radius, 1000)
            ltot += length
        x, y, length = self.line(x, y, ori, w, s, ex2, sp)
        ltot += length
        return x, y, ltot


def _nm(um: float) -> float:
    """µm → legacy nm units (kept as float, as the legacy scripts pass them)."""
    return um * 1000.0


class _Cpwe(Element):
    qcc_category = "waveguide"

    def _emit(self, pen: CpwePen):
        dbu = self.layout.dbu
        region = pen.region.merged()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(region)
        if not region.is_empty():
            self.add_protection(pya.Region(region.bbox()).sized(self.margin / dbu))

    def _port(self, name, x_nm, y_nm, direction):
        self.add_port(name, pya.DPoint(x_nm / 1000.0, y_nm / 1000.0), direction)


class CpweBondPad(_Cpwe):
    """Bond pad: open end ``tl``, wide line ``bl`` (``pad_width``/``pad_gap``), taper ``btl`` to the CPW ``a``/``b``
    (legacy ``cpwe.b_pad``, horizontal). Port ``a`` at the CPW end facing +x (``mirror``: at the origin, −x).
    Refpoints ``pad_center`` and ``lumped_signal`` / ``lumped_ground`` (across the side gap at the pad centre: the
    simulation builder's 50 Ω lumped port, as for ``BondPad``)."""

    pad_width = Param(pdt.TypeDouble, "Pad centre width (legacy wb)", 500, unit="μm")
    pad_gap = Param(pdt.TypeDouble, "Pad gap (legacy sb)", 300, unit="μm")
    end_length = Param(pdt.TypeDouble, "Open-end length (legacy tl)", 10, unit="μm")
    pad_length = Param(pdt.TypeDouble, "Pad length before the taper (legacy bl)", 50, unit="μm")
    taper_length = Param(pdt.TypeDouble, "Taper length (legacy btl)", 500, unit="μm")
    taper_type = Param(pdt.TypeInt, "Taper profile: 0 linear, 1–3 exponential (legacy t_type)", 3)
    weight = Param(pdt.TypeDouble, "Exponent weight of the taper", 25)
    mirror = Param(pdt.TypeBoolean, "Mirrored: taper first, pad at the +x end", False)
    markers = Param(pdt.TypeBoolean, "Alignment crosses beside the taper end", False)

    qcc_category = "launcher"

    def build(self):
        pen = CpwePen(self.layout.dbu)
        x, y, _ = pen.b_pad(
            0,
            0,
            "h",
            _nm(self.pad_width),
            _nm(self.pad_gap),
            _nm(self.a),
            _nm(self.b),
            _nm(self.end_length),
            _nm(self.pad_length),
            _nm(self.taper_length),
            self.taper_type,
            self.weight,
            False,
            self.mirror,
            self.markers,
        )
        self._emit(pen)
        if self.mirror:
            self._port("a", 0, 0, pya.DVector(-1, 0))
        else:
            self._port("a", x, y, pya.DVector(1, 0))
        centre = self.taper_length + self.pad_length / 2 if self.mirror else self.end_length + self.pad_length / 2
        self.refpoints["pad_center"] = pya.DPoint(centre, 0)
        # lumped-port terminals (as BondPad): across the pad's side gap at the pad centre
        self.refpoints["lumped_signal"] = pya.DPoint(centre, self.pad_width / 2)
        self.refpoints["lumped_ground"] = pya.DPoint(centre, self.pad_width / 2 + self.pad_gap)


class CpweQuarterWaveResonator(_Cpwe):
    """λ/4 resonator capacitively coupled through an open-ended arm parallel to the feedline (legacy
    ``cpwe.quarter_cap_coupled``): open end at the origin, coupler arm along x (``cap_length``, CPW
    ``cap_width``/``cap_gap``), bend, taper to the resonator CPW ``a``/``b``, meander, shorted end.

    Refpoints: ``open_end`` (origin), ``short_end``, ``coupler_center``. :meth:`qcc_resonator_length` gives the
    legacy returned length (µm, without the open-end box)."""

    cap_width = Param(pdt.TypeDouble, "Coupler centre width (legacy wcap)", 3, unit="μm")
    cap_gap = Param(pdt.TypeDouble, "Coupler gap (legacy scap)", 1.6, unit="μm")
    cap_length = Param(pdt.TypeDouble, "Coupler length (legacy cap_len)", 200, unit="μm")
    cap_radius = Param(pdt.TypeDouble, "Coupler bend radius (legacy cap_rad)", 20, unit="μm")
    taper_length = Param(pdt.TypeDouble, "Taper to the resonator CPW (legacy t_len)", 20, unit="μm")
    meander_radius = Param(pdt.TypeDouble, "Meander radius (legacy m_radius)", 50, unit="μm")
    meander_length = Param(pdt.TypeDouble, "Meander straight length (legacy m_length)", 1000, unit="μm")
    meanders = Param(pdt.TypeInt, "Meander periods (legacy m_n)", 2)
    excess_1 = Param(pdt.TypeDouble, "Extra length before the meander (legacy ex1)", 300, unit="μm")
    excess_2 = Param(pdt.TypeDouble, "Extra length after the meander (legacy ex2)", 70.26554, unit="μm")
    flip = Param(pdt.TypeBoolean, "Mirror (legacy flip)", True)

    qcc_category = "resonator"

    @staticmethod
    def _draw(p: dict, dbu: float):
        pen = CpwePen(dbu)
        end = pen.quarter_cap_coupled(
            0,
            0,
            "h",
            _nm(p["a"]),
            _nm(p["b"]),
            _nm(p["cap_width"]),
            _nm(p["cap_gap"]),
            _nm(p["cap_length"]),
            _nm(p["cap_radius"]),
            _nm(p["taper_length"]),
            _nm(p["meander_radius"]),
            _nm(p["meander_length"]),
            p["meanders"],
            _nm(p["excess_1"]),
            _nm(p["excess_2"]),
            p["flip"],
        )
        return pen, end

    @classmethod
    def qcc_resonator_length(cls, params: dict) -> float:
        """Centre-line length from the open end to the short (legacy return value, without the open-end box), µm."""
        p = {k: v.default for k, v in cls.get_schema().items()} | dict(params)
        return float(cls._draw(p, 0.001)[1][2]) / 1000.0

    def build(self):
        names = ("a", "b", "cap_width", "cap_gap", "cap_length", "cap_radius", "taper_length", "meander_radius")
        names += ("meander_length", "meanders", "excess_1", "excess_2", "flip")
        pen, (x, y, _length) = self._draw({n: getattr(self, n) for n in names}, self.layout.dbu)
        self._emit(pen)
        self.refpoints["open_end"] = pya.DPoint(0, 0)
        self.refpoints["short_end"] = pya.DPoint(x / 1000.0, y / 1000.0)
        self.refpoints["coupler_center"] = pya.DPoint(
            (-1 if self.flip else 1) * (self.cap_gap + self.cap_length / 2), 0
        )


class CpweFingerCapacitor(_Cpwe):
    """Interdigital capacitor interrupting the centre line (legacy ``cpwe.finger_cap``); ports ``a`` (−x), ``b``."""

    finger_gap = Param(pdt.TypeDouble, "Finger separation (legacy f_sep)", 2, unit="μm")
    finger_length = Param(pdt.TypeDouble, "Finger length (legacy f_length)", 50, unit="μm")
    fingers = Param(pdt.TypeInt, "Number of fingers (legacy f_n)", 4)

    qcc_category = "capacitor"

    def build(self):
        pen = CpwePen(self.layout.dbu)
        x, y, _ = pen.finger_cap(
            0, 0, "h", _nm(self.a), _nm(self.b), _nm(self.finger_gap), _nm(self.finger_length), self.fingers, False
        )
        self._emit(pen)
        self._port("a", 0, 0, pya.DVector(-1, 0))
        self._port("b", x, y, pya.DVector(1, 0))


class CpweGapCapacitor(_Cpwe):
    """Gap in the centre line (legacy ``cpwe.gap_cap``); ports ``a`` (−x), ``b`` (+x)."""

    cap_gap = Param(pdt.TypeDouble, "Gap length (legacy cap_sep)", 5, unit="μm")

    qcc_category = "capacitor"

    def build(self):
        pen = CpwePen(self.layout.dbu)
        x, y, _ = pen.gap_cap(0, 0, "h", _nm(self.a), _nm(self.b), _nm(self.cap_gap), False)
        self._emit(pen)
        self._port("a", 0, 0, pya.DVector(-1, 0))
        self._port("b", x, y, pya.DVector(1, 0))


class CpweFingerLine(_Cpwe):
    """CPW with interdigital fingers between centre line and ground on both sides (legacy ``cpwe.finger_line``);
    ports ``a`` (−x) and ``b`` (+x)."""

    finger_gap = Param(pdt.TypeDouble, "Finger separation (legacy f_sep)", 2, unit="μm")
    finger_length = Param(pdt.TypeDouble, "Finger length (legacy f_length)", 4, unit="μm")
    finger_width = Param(pdt.TypeDouble, "Finger width (legacy f_width)", 2, unit="μm")
    fingers = Param(pdt.TypeInt, "Number of fingers (legacy f_n)", 10)

    qcc_category = "capacitor"

    def build(self):
        pen = CpwePen(self.layout.dbu)
        x, y, _ = pen.finger_line(
            0,
            0,
            "h",
            _nm(self.a),
            _nm(self.b),
            _nm(self.finger_gap),
            _nm(self.finger_length),
            _nm(self.finger_width),
            self.fingers,
            False,
        )
        self._emit(pen)
        self._port("a", 0, 0, pya.DVector(-1, 0))
        self._port("b", x, y, pya.DVector(1, 0))


class CpweTaper(_Cpwe):
    """Taper from ``a``/``b`` to ``a_end``/``b_end`` (legacy ``cpwe.tapper``: linear or exponential profiles)."""

    a_end = Param(pdt.TypeDouble, "Centre width at the +x end", 20, unit="μm")
    b_end = Param(pdt.TypeDouble, "Gap at the +x end", 12, unit="μm")
    length = Param(pdt.TypeDouble, "Taper length", 100, unit="μm")
    taper_type = Param(pdt.TypeInt, "Profile: 0 linear, 1–3 exponential (legacy t_type)", 0)
    weight = Param(pdt.TypeDouble, "Exponent weight", 25)

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        return {"b": (params.get("a_end", 20), params.get("b_end", 12))}

    def build(self):
        pen = CpwePen(self.layout.dbu)
        x, y, _ = pen.tapper(
            0,
            0,
            "h",
            _nm(self.a),
            _nm(self.b),
            _nm(self.a_end),
            _nm(self.b_end),
            _nm(self.length),
            self.taper_type,
            self.weight,
            False,
        )
        self._emit(pen)
        self._port("a", 0, 0, pya.DVector(-1, 0))
        self._port("b", x, y, pya.DVector(1, 0))


class CpweOpenEnd(_Cpwe):
    """Open CPW termination (legacy ``cpwe.term_open``): the gap box of ``length``; port ``a`` at the origin (−x)."""

    length = Param(pdt.TypeDouble, "Termination length", 10, unit="μm")

    qcc_category = "termination"

    def build(self):
        pen = CpwePen(self.layout.dbu)
        pen.term_open(0, 0, "h", _nm(self.a), _nm(self.b), _nm(self.length), False)
        self._emit(pen)
        self._port("a", 0, 0, pya.DVector(-1, 0))


class CpweMeanderLine(_Cpwe):
    """Meandered CPW (legacy ``cpwe.meander_line``; with ``lead`` > 0 it is legacy ``cpwe.quarter_wave``: lead,
    meander, lead). Starts at the origin going +x; ports ``a`` (start, −x) and ``b`` (end)."""

    meander_radius = Param(pdt.TypeDouble, "Bend radius (legacy m_radius)", 50, unit="μm")
    meander_length = Param(pdt.TypeDouble, "Straight length (legacy m_length)", 500, unit="μm")
    bias = Param(pdt.TypeDouble, "Skew of the meander (legacy m_bias)", 0.5)
    meanders = Param(pdt.TypeInt, "Meander periods (legacy n)", 2)
    flip = Param(pdt.TypeBoolean, "Mirror (legacy flip)", False)
    term_early = Param(pdt.TypeBoolean, "End on a straight section (legacy term_early)", False)
    lead = Param(pdt.TypeDouble, "Straight lead before and after (legacy quarter_wave resonator_excess)", 0, unit="μm")

    def build(self):
        pen = CpwePen(self.layout.dbu)
        w, s = _nm(self.a), _nm(self.b)
        x, y = 0, 0
        if self.lead > 0:
            x, y, _ = pen.line(x, y, "h", w, s, _nm(self.lead), False)
        x, y, _ = pen.meander_line(
            x,
            y,
            "h",
            w,
            s,
            _nm(self.meander_radius),
            _nm(self.meander_length),
            self.bias,
            self.meanders,
            self.flip,
            self.term_early,
        )
        end_dir = pya.DVector(1, 0)
        if self.lead > 0:
            x, y, _ = pen.line(x, y, "h", w, s, _nm(self.lead), False)
        elif self.term_early:
            end_dir = pya.DVector(0, 1) if not self.flip else pya.DVector(0, -1)
        self._emit(pen)
        self._port("a", 0, 0, pya.DVector(-1, 0))
        self._port("b", x, y, end_dir)

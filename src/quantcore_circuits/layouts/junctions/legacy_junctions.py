"""Earlier generations of the QWri trilayer junctions and SQUIDs, as KQC junctions (usable as ``junction_type``).

* :class:`TrilayerJunctionHSQ` / :class:`TrilayerSquidHSQ`: the first HSQ generation, legacy
  ``junction_creator_HSQ.create_junction`` / ``squid_creator_HSQ.create_squid`` (chips 05, 06, 08 and the 11f JJ
  placer). Compared with :class:`~.trilayer.TrilayerJunction` (``xjc_*_TL_mod``) the bent finger sits 0.5 µm lower
  in an unshifted window, the HSQ boxes are 0.1 µm (not 0.2 µm) longer than the finger and the SQUID's straight
  leads keep the 3 µm finger-pad height.
* :class:`SquidV0`: the pre-HSQ SQUID of ``junction_creator_sq.create_junction_squid`` (and the stand-alone
  ``junction_pad.py``, whose bent window is 16 µm high instead of 18 µm): straight fingers at their 0.2 µm default
  width, bent fingers ``0.2·js + 0.06`` µm wide, bent window shifted up by 1 µm, no HSQ.

Same layers and frame as :mod:`.trilayer`: straight finger → ``SIS_junction`` (legacy 2/0), bent finger →
``SIS_junction_2`` (4/0), HSQ → qcc ``hsq`` (PDK v2 50/0; legacy 500/0), spacer gradient on 51–53/0 (on by default,
:func:`~.trilayer.spacer_gradient_levels`), sizing by ``lj_nH`` / KQC ``junction_width`` and the optional CLEARER as
in :mod:`.trilayer`; ``origin_squid`` at the ground-side window edge,
``port_common`` on the island side; geometry computed with the legacy pya calls, so it XORs clean against them.
The legacy scripts take ``js`` (finger width in units of 0.1 µm, 0.2 µm for :class:`SquidV0`) and ``secondFinger``
(bent-finger width in µm, 0 = same): here they are ``finger_width`` and ``second_finger_width`` in µm.

The scripts set the finger parameters with ``change_pcell_parameters``, so KLayout runs the legacy
``coerce_parameters_impl`` of ``JJ_finger Top/Bottom`` first (e.g. a 0.6 µm bent finger widens its 1 µm lead to
1.26 µm); :func:`coerce_straight` / :func:`coerce_bent` apply the same rules here.
"""

from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.trilayer import (  # noqa: F401  (coerce_* re-exported for jj_fingers)
    TrilayerJunction,
    TrilayerSquid,
    _TrilayerBase,
    bent_finger,
    coerce_bent,
    coerce_straight,
    coerced_bent_finger,
    coerced_straight_finger,
    straight_finger,
)


class TrilayerJunctionHSQ(TrilayerJunction):
    """Single trilayer junction, first HSQ generation (legacy ``junction_creator_HSQ.create_junction``)."""

    qcc_category = "junction"

    bent_finger_y = Param(pdt.TypeDouble, "Bent finger offset (legacy y)", -2.0, unit="μm")
    bent_shift = Param(pdt.TypeDouble, "Bent finger cell shift in y", 0.0, unit="μm")
    hsq_extra = Param(pdt.TypeDouble, "HSQ box extra length", 0.1, unit="μm")

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
        y_off = 2 * self.bent_finger_length / 3 + self.bent_conn_height + self.bent_finger_y + 1
        for box in self._hsq_boxes(dbu, fw, sfw, y_off, self.hsq_overlap, self.hsq_width, self.hsq_extra):
            hsq.insert(box)
        centre = pya.DPoint(0, y_off / 2 + h / 2)
        self._insert_layers(straight, bent, hsq, [centre])
        self.refpoints["junction_1"] = centre


class TrilayerSquidHSQ(TrilayerSquid):
    """Two trilayer junctions forming a SQUID, first HSQ generation (legacy ``squid_creator_HSQ.create_squid``)."""

    qcc_category = "junction"

    bent_finger_y = Param(pdt.TypeDouble, "Bent finger offset (legacy y)", -2.0, unit="μm")
    bent_shift = Param(pdt.TypeDouble, "Bent finger cell shift in y", 0.0, unit="μm")
    hsq_extra = Param(pdt.TypeDouble, "HSQ box extra length", 0.1, unit="μm")
    straight_pad_height = Param(pdt.TypeDouble, "Straight finger pad (lead) height", 3.0, unit="μm")
    bent_conn_height = Param(pdt.TypeDouble, "Bent finger connection height", 1.0, unit="μm")

    def build(self):
        dbu = self.layout.dbu
        fw, sfw, pad_width = self._widths(2)
        w, h, xs = self.window_width, self.window_height, self.junction_spacing
        sph, ch = self.straight_pad_height, self.bent_conn_height
        mirror = pya.Trans(0, True, 0, 0)
        sargs = (dbu, pad_width, sph, fw, self.straight_finger_length, w, h)
        s1 = coerced_straight_finger(*sargs, xs, self.straight_finger_y)
        s2 = coerced_straight_finger(*sargs, -xs, self.straight_finger_y)
        straight = s1.transformed(mirror) & s2.transformed(mirror)  # legacy intersects the two negative windows
        shift = pya.Trans(0, False, 0, self.bent_shift / dbu)
        args = (dbu, self.bent_pad_width, sfw, self.bent_finger_length, ch, w, h - 1)
        b1 = coerced_bent_finger(*args, xs, self.bent_finger_y, False)
        b2 = coerced_bent_finger(*args, -xs, self.bent_finger_y, True)
        bent = b1.transformed(shift) & b2.transformed(shift)
        hsq = pya.Region()
        y_off = 2 * self.bent_finger_length / 3 + ch + self.bent_finger_y + 1
        for box in self._hsq_boxes(dbu, fw, sfw, y_off, self.hsq_overlap, self.hsq_width, self.hsq_extra):
            hsq.insert(box.transformed(pya.Trans(0, False, xs / dbu, 0)))
            hsq.insert(box.transformed(pya.Trans(0, False, -xs / dbu, 0)))
        centres = [pya.DPoint(xs, y_off / 2 + h / 2), pya.DPoint(-xs, y_off / 2 + h / 2)]
        self._insert_layers(straight, bent, hsq, centres)
        self.refpoints["junction_1"], self.refpoints["junction_2"] = centres


class SquidV0(_TrilayerBase):
    """Pre-HSQ SQUID (legacy ``junction_creator_sq.create_junction_squid``; ``junction_pad.py`` with
    ``bent_window_height=16``)."""

    qcc_category = "junction"

    finger_width = Param(pdt.TypeDouble, "Straight finger width", 0.2, unit="μm")
    second_finger_width = Param(pdt.TypeDouble, "Bent finger width (junction size)", 0.26, unit="μm")
    window_height = Param(pdt.TypeDouble, "Straight finger window height", 18.0, unit="μm")
    bent_window_height = Param(pdt.TypeDouble, "Bent finger window height", 18.0, unit="μm")
    straight_finger_length = Param(pdt.TypeDouble, "Straight finger length", 2.0, unit="μm")
    straight_finger_y = Param(pdt.TypeDouble, "Straight finger offset (legacy y)", -2.0, unit="μm")
    straight_pad_width = Param(pdt.TypeDouble, "Straight finger lead width", 0.5, unit="μm")
    bent_finger_length = Param(pdt.TypeDouble, "Bent finger length", 2.0, unit="μm")
    bent_finger_y = Param(pdt.TypeDouble, "Bent finger offset (legacy y)", -2.5, unit="μm")
    bent_pad_width = Param(pdt.TypeDouble, "Bent finger lead width", 0.5, unit="μm")
    bent_conn_height = Param(pdt.TypeDouble, "Bent finger connection height", 0.5, unit="μm")
    bent_shift = Param(pdt.TypeDouble, "Bent finger cell shift in y", 1.0, unit="μm")
    junction_spacing = Param(pdt.TypeDouble, "Distance of each junction from the axis", 8.0, unit="μm")
    with_hsq = Param(pdt.TypeBoolean, "Draw HSQ sidewall boxes (none in this generation)", False, hidden=True)

    def build(self):
        dbu = self.layout.dbu
        w, h, xs = self.window_width, self.window_height, self.junction_spacing
        mirror = pya.Trans(0, True, 0, 0)
        fw, sfw = self._fingers(2)
        sargs = (dbu, self.straight_pad_width, 3, fw, self.straight_finger_length, w, h)
        s1 = coerced_straight_finger(*sargs, xs, self.straight_finger_y)
        s2 = coerced_straight_finger(*sargs, -xs, self.straight_finger_y)
        straight = s1.transformed(mirror) & s2.transformed(mirror)
        bh = self.bent_window_height
        args = (dbu, self.bent_pad_width, sfw, self.bent_finger_length, self.bent_conn_height, w, bh)
        b1 = coerced_bent_finger(*args, xs, self.bent_finger_y, False)
        b2 = coerced_bent_finger(*args, -xs, self.bent_finger_y, True)
        shift = pya.Trans(0, False, 0, self.bent_shift / dbu)
        bent = b1.transformed(shift) & b2.transformed(shift)
        self._insert_layers(straight, bent, pya.Region())


class TrilayerJunctionCompact(_TrilayerBase):
    """Compact single trilayer junction for dense junction test arrays (legacy ``chip_11m_TestJJ16x_pads.py``
    ``create_testPad``, cell ``JX_500``, placed many times by ``chip_11f_JJplacer.py``).

    A 12 × 12 µm window (legacy ``junction_width + 1``) holding a straight finger (1.2 µm lead) and a bent finger
    (1.6 µm lead), HSQ boxes 0.1 µm below / 0.2 µm above the finger, and a triangular notch (``tip_width`` wide,
    from ``tip_depth`` to the window edge) cut from each finger window where its lead meets the edge. The legacy
    script fails with ``secondFinger=0`` (undefined ``js``); here ``second_finger_width=0`` means "same as the
    straight finger". The pads of the legacy script are commented out there; they are not drawn here either.
    """

    qcc_category = "junction"

    finger_width = Param(pdt.TypeDouble, "Straight finger width (legacy 0.2·size)", 0.2, unit="μm")
    second_finger_width = Param(pdt.TypeDouble, "Bent finger width (legacy secondFinger)", 0.6, unit="μm")
    window_width = Param(pdt.TypeDouble, "Exposure window width", 12.0, unit="μm")
    window_height = Param(pdt.TypeDouble, "Exposure window height", 12.0, unit="μm")
    straight_finger_length = Param(pdt.TypeDouble, "Straight finger length", 3.0, unit="μm")
    straight_finger_y = Param(pdt.TypeDouble, "Straight finger offset (legacy y)", -2.4, unit="μm")
    straight_pad_width = Param(pdt.TypeDouble, "Straight finger lead width", 1.2, unit="μm")
    straight_pad_height = Param(pdt.TypeDouble, "Straight finger pad height", 3.0, unit="μm")
    bent_finger_length = Param(pdt.TypeDouble, "Bent finger length", 3.0, unit="μm")
    bent_finger_y = Param(pdt.TypeDouble, "Bent finger offset (legacy y)", -3.4, unit="μm")
    bent_finger_x = Param(pdt.TypeDouble, "Bent finger offset (legacy x)", 0.2, unit="μm")
    bent_pad_width = Param(pdt.TypeDouble, "Bent finger lead width", 1.6, unit="μm")
    bent_conn_height = Param(pdt.TypeDouble, "Bent finger connection height (coerced ≥ length / 3)", 0.5, unit="μm")
    bent_shift = Param(pdt.TypeDouble, "Unused here", 0.0, unit="μm", hidden=True)
    hsq_overlap = Param(pdt.TypeDouble, "HSQ overlap onto the finger", 0.045, unit="μm")
    hsq_y = Param(pdt.TypeDouble, "HSQ box offset (legacy y_off)", -0.85, unit="μm")
    hsq_extra = Param(pdt.TypeDouble, "HSQ box extra length below", 0.1, unit="μm")
    hsq_extra_top = Param(pdt.TypeDouble, "HSQ box extra length above", 0.2, unit="μm")
    tip_cut = Param(pdt.TypeBoolean, "Cut the triangular notches at the lead ends", True)
    tip_width = Param(pdt.TypeDouble, "Notch width at the window edge", 5.0, unit="μm")
    tip_depth = Param(pdt.TypeDouble, "Notch apex distance from the centre (legacy finger_origin)", 4.5, unit="μm")

    def build(self):
        dbu = self.layout.dbu
        fw, sfw = self._fingers(1)
        w, h = self.window_width, self.window_height
        straight = coerced_straight_finger(
            dbu,
            self.straight_pad_width,
            self.straight_pad_height,
            fw,
            self.straight_finger_length,
            w,
            h,
            0,
            self.straight_finger_y,
        )
        straight.transform(pya.Trans(0, True, 0, 0))  # legacy inserts the straight finger mirrored
        bent = coerced_bent_finger(
            dbu,
            self.bent_pad_width,
            sfw,
            self.bent_finger_length,
            self.bent_conn_height,
            w,
            h,
            self.bent_finger_x,
            self.bent_finger_y,
            False,
        )
        if self.tip_cut:
            top = pya.Polygon(
                [
                    pya.Point(-self.tip_width / dbu / 2, (h / 2) / dbu),
                    pya.Point(self.tip_width / dbu / 2, (h / 2) / dbu),
                    pya.Point(0 / dbu, self.tip_depth / dbu),
                ]
            )
            straight -= pya.Region(top)
            bent -= pya.Region(top.transformed(pya.Trans(0, True, 0, 0)))
        lx = -fw / 2 - self.hsq_width + self.hsq_overlap
        rx = fw / 2 - self.hsq_overlap
        y0 = (-sfw + self.hsq_y - self.hsq_extra) / dbu / 2
        y1 = (sfw + self.hsq_y + self.hsq_extra_top) / dbu / 2
        hsq = pya.Region()
        hsq.insert(pya.Box(lx / dbu, y0, (lx + self.hsq_width) / dbu, y1))
        hsq.insert(pya.Box(rx / dbu, y0, (rx + self.hsq_width) / dbu, y1))
        centre = pya.DPoint(0, self.hsq_y / 2 + h / 2)
        self._insert_layers(straight, bent, hsq, [centre])
        self.refpoints["junction_1"] = centre

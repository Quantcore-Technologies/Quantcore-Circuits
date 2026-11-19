"""Junction test structures (ported from the QWri ``testPad*.py`` / ``xtp_testpads_TL_small.py`` scripts).

* :class:`JunctionTestPads`: two probe pads facing each other across a 20 µm junction window, with a trilayer
  junction (straight + bent finger) between the triangular pad tips. One class covers the four legacy scripts;
  :func:`legacy_test_pad_params` gives each script's parameters (``testPad_AVAQUS`` chips 01–02, ``testPad_Nb_TL``
  chip 04, ``testPad_Nb_TL_HSQ`` chips 05/06/08, ``xtp_testpads_TL_small`` chip 10a).
* :class:`JunctionGroundPad`: one rounded 400 µm pad in a 500 µm etch window, joined to ground by a 50 µm bridge
  carrying the junction (legacy ``testPad.py``, chips 01–02).

Frame: pad structure centred at the origin (legacy frame); the junction sits at the origin (``JunctionGroundPad``:
at ``junction_y`` on the bridge). Layers (fab mode): legacy 1/0 → ``base_metal_gap_wo_grid``, 2/0 (straight
finger) → ``SIS_junction``, 4/0 (bent finger) → ``SIS_junction_2``, 500/0 → qcc ``hsq`` (+ the 51–53/0 spacer
gradient, on by default: :func:`~quantcore_circuits.layouts.junctions.trilayer.spacer_gradient_levels`). The legacy
scripts also draw a separate 3/0 pattern (the other pad kept in the second metal); the Quantcore stack derives 3/0
from 1/0 at export, so it is not drawn — :func:`junction_test_pad_regions` / :func:`junction_ground_pad_regions`
still return it (``"m3"``). No ports: these are probe structures; refpoints mark the pads and the junction.
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.legacy_junctions import coerced_bent_finger, coerced_straight_finger
from quantcore_circuits.layouts.junctions.trilayer import _PROCESS, insert_spacer


def junction_test_pad_regions(
    dbu,
    upper_pad_width=500,
    upper_pad_height=400,
    lower_pad_width=500,
    lower_pad_height=400,
    middle_height=300,
    box_extra=100,
    box_height=0,
    upper_pad_trim=50,
    lower_pad_trim=50,
    junction_width=20,
    junction_height=20,
    finger_origin=5,
    finger_width=0.5,
    second_finger_width=0.6,
    straight_finger_y=-2.4,
    straight_pad_width=1.2,
    straight_finger_length=3,
    bent_finger_x=0.2,
    bent_finger_y=-3.4,
    bent_pad_width=1.6,
    bent_finger_length=3,
    bent_conn_height=0.5,
    with_hsq=True,
    hsq_width=0.2,
    hsq_overlap=0.045,
    hsq_y_offset=-0.85,
    hsq_extra_low=0.1,
    hsq_extra_high=0.2,
    label="",
    label_size=100,
    label_pos=(-140, 400),
) -> dict:
    """Legacy ``create_testPad`` geometry in dbu: ``{"m1", "m3", "straight", "bent", "hsq"}`` Regions."""
    gw, gh, tw, th, mh = upper_pad_width, upper_pad_height, lower_pad_width, lower_pad_height, middle_height
    total = box_height or (gh + mh + th)
    pad_box = pya.Polygon(
        pya.Box((-gw - box_extra) / dbu / 2, -total / 2 / dbu, (gw + box_extra) / dbu / 2, total / dbu / 2)
    )
    pad1 = pya.Polygon(pya.Box(-gw / dbu / 2, mh / dbu / 2, gw / dbu / 2, (gh + (mh / 2) - upper_pad_trim) / dbu))
    pad2 = pya.Polygon(pya.Box(-tw / dbu / 2, -mh / dbu / 2, tw / dbu / 2, (-mh / 2 - th + lower_pad_trim) / dbu))
    p1 = pya.Point(-gw / dbu / 2, mh / 2 / dbu)
    p2 = pya.Point(gw / dbu / 2, mh / 2 / dbu)
    p3 = pya.Point(0 / dbu, finger_origin / dbu)
    t1 = pya.Polygon([p1, p2, p3])
    t2 = pya.Polygon([pya.Point(p1.x, -p1.y), pya.Point(p2.x, -p2.y), pya.Point(p3.x, -p3.y)])
    cutout = pya.Polygon(
        pya.Box(
            -junction_width / 2 / dbu, -junction_height / dbu / 2, junction_width / 2 / dbu, junction_height / dbu / 2
        )
    )
    m1 = pya.Region(pad_box) - pya.Region(pad1) - pya.Region(t1) - pya.Region(cutout)
    m3 = pya.Region(pad_box) - pya.Region(pad2) - pya.Region(t2) - pya.Region(cutout)
    jw, jh = junction_width + 1, junction_height + 1
    straight = coerced_straight_finger(
        dbu, straight_pad_width, 3, finger_width, straight_finger_length, jw, jh, 0, straight_finger_y
    ).transformed(pya.Trans(0, True, 0, 0))
    bent = coerced_bent_finger(
        dbu,
        bent_pad_width,
        second_finger_width,
        bent_finger_length,
        bent_conn_height,
        jw,
        jh,
        bent_finger_x,
        bent_finger_y,
        False,
    )
    straight -= pya.Region(t1)
    bent -= pya.Region(t2)
    hsq = pya.Region()
    if with_hsq:
        lx = -finger_width / 2 - hsq_width + hsq_overlap
        rx = finger_width / 2 - hsq_overlap
        y0 = (-second_finger_width + hsq_y_offset - hsq_extra_low) / dbu / 2
        y1 = (second_finger_width + hsq_y_offset + hsq_extra_high) / dbu / 2
        hsq.insert(pya.Box(lx / dbu, y0, (lx + hsq_width) / dbu, y1))
        hsq.insert(pya.Box(rx / dbu, y0, (rx + hsq_width) / dbu, y1))
    if label:
        text = pya.TextGenerator.default_generator().text(label, dbu, label_size, False)
        m1 += text.transformed(pya.Trans(0, False, label_pos[0] / dbu, label_pos[1] / dbu))
    return {"m1": m1, "m3": m3, "straight": straight, "bent": bent, "hsq": hsq}


def legacy_test_pad_params(variant: str, size: float = 1.0, second_finger: float = 0.0) -> dict:
    """:class:`JunctionTestPads` parameters reproducing legacy ``<variant>.create_testPad(size, second_finger)``.

    ``size`` is the legacy junction size (straight finger ``0.2·size`` µm); ``second_finger`` the bent-finger width in
    µm (0 → same as the straight finger; the legacy scripts fail in that case).
    """
    second = second_finger or round(0.2 * size, 6)
    common = {"finger_width": 0.2 * size, "second_finger_width": second}
    presets = {
        "testPad_AVAQUS": {
            "upper_pad_width": 200,
            "upper_pad_height": 300,
            "lower_pad_width": 200,
            "lower_pad_height": 300,
            "middle_height": 100,
            "upper_pad_trim": 0,
            "finger_width": (0.2 * size) + 0.06,
            "second_finger_width": 0.2 * size,
            "with_hsq": False,
            "label": str(int(0.2 * size * 1000)) + "NM",
        },
        "testPad_Nb_TL": {
            "upper_pad_height": 300,
            "lower_pad_height": 300,
            "upper_pad_trim": 0,
            "finger_width": (0.2 * size) + 0.06,
            "with_hsq": False,
        },
        "testPad_Nb_TL_HSQ": {},
        "xtp_testpads_TL_small": {
            "upper_pad_width": 150,
            "upper_pad_height": 175,
            "lower_pad_width": 150,
            "lower_pad_height": 175,
            "middle_height": 75,
            "box_extra": 25,
            "box_height": 175 + 75 / 4 + 175,
            "hsq_extra_low": 0.3,
            "hsq_extra_high": 0.3,
        },
    }
    if variant not in presets:
        raise ValueError(f"unknown legacy test pad {variant!r}; variants: {sorted(presets)}")
    return {**common, **presets[variant]}


class JunctionTestPads(Element):
    """Two probe pads with a trilayer junction between their tips (legacy ``testPad_*`` / ``xtp_testpads``)."""

    qcc_category = "test_structure"

    upper_pad_width = Param(pdt.TypeDouble, "Upper pad width", 500, unit="μm")
    upper_pad_height = Param(pdt.TypeDouble, "Upper pad height", 400, unit="μm")
    lower_pad_width = Param(pdt.TypeDouble, "Lower pad width", 500, unit="μm")
    lower_pad_height = Param(pdt.TypeDouble, "Lower pad height", 400, unit="μm")
    middle_height = Param(pdt.TypeDouble, "Distance between the pads (junction region)", 300, unit="μm")
    box_extra = Param(pdt.TypeDouble, "Etch window wider than the upper pad by", 100, unit="μm")
    box_height = Param(pdt.TypeDouble, "Etch window height (0 = pads + middle)", 0, unit="μm")
    upper_pad_trim = Param(pdt.TypeDouble, "Upper pad shortened by (towards the window edge)", 50, unit="μm")
    lower_pad_trim = Param(pdt.TypeDouble, "Lower pad shortened by (towards the window edge)", 50, unit="μm")
    junction_width = Param(pdt.TypeDouble, "Junction window width", 20, unit="μm")
    junction_height = Param(pdt.TypeDouble, "Junction window height", 20, unit="μm")
    finger_origin = Param(pdt.TypeDouble, "Pad tip distance from the junction", 5, unit="μm")
    finger_width = Param(pdt.TypeDouble, "Straight finger width", 0.5, unit="μm")
    second_finger_width = Param(pdt.TypeDouble, "Bent finger width", 0.6, unit="μm")
    straight_finger_y = Param(pdt.TypeDouble, "Straight finger offset (legacy y)", -2.4, unit="μm")
    straight_pad_width = Param(pdt.TypeDouble, "Straight finger lead width", 1.2, unit="μm")
    straight_finger_length = Param(pdt.TypeDouble, "Straight finger length", 3, unit="μm")
    bent_finger_x = Param(pdt.TypeDouble, "Bent finger offset (legacy x)", 0.2, unit="μm")
    bent_finger_y = Param(pdt.TypeDouble, "Bent finger offset (legacy y)", -3.4, unit="μm")
    bent_pad_width = Param(pdt.TypeDouble, "Bent finger lead width", 1.6, unit="μm")
    bent_finger_length = Param(pdt.TypeDouble, "Bent finger length", 3, unit="μm")
    bent_conn_height = Param(pdt.TypeDouble, "Bent finger connection height", 0.5, unit="μm")
    with_hsq = Param(pdt.TypeBoolean, "Draw HSQ sidewall boxes", True)
    hsq_width = Param(pdt.TypeDouble, "HSQ box width", 0.2, unit="μm")
    hsq_overlap = Param(pdt.TypeDouble, "HSQ overlap onto the finger", 0.045, unit="μm")
    hsq_y_offset = Param(pdt.TypeDouble, "HSQ box centre offset (legacy y_off)", -0.85, unit="μm")
    hsq_extra_low = Param(pdt.TypeDouble, "HSQ box extra length below", 0.1, unit="μm")
    hsq_extra_high = Param(pdt.TypeDouble, "HSQ box extra length above", 0.2, unit="μm")
    spacer_gradient = Param(
        pdt.TypeBoolean,
        "Spacer gradient: 51–53/0 dose levels inside the HSQ (width / 3 strips)",
        _PROCESS.spacer_gradient,
    )
    label = Param(pdt.TypeString, "Text etched above the pads (empty = none)", "")
    label_size = Param(pdt.TypeDouble, "Label height", 100, unit="μm")
    label_pos = Param(pdt.TypeList, "Label position [x, y]", [-140, 400], unit="μm")

    _NAMES = (
        "upper_pad_width upper_pad_height lower_pad_width lower_pad_height middle_height box_extra box_height "
        "upper_pad_trim lower_pad_trim junction_width junction_height finger_origin finger_width "
        "second_finger_width straight_finger_y straight_pad_width straight_finger_length bent_finger_x "
        "bent_finger_y bent_pad_width bent_finger_length bent_conn_height with_hsq hsq_width hsq_overlap "
        "hsq_y_offset hsq_extra_low hsq_extra_high label label_size"
    ).split()

    def _regions(self) -> dict:
        params = {n: getattr(self, n) for n in self._NAMES}
        pos = (float(self.label_pos[0]), float(self.label_pos[1]))
        return junction_test_pad_regions(self.layout.dbu, **params, label_pos=pos)

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): the legacy scripts' own 3/0 pattern (``m3``: the pad structure, the other pad
        kept in the second metal)."""
        from quantcore_circuits.layouts.others.keepout import as_cell, dpolygons  # pylint: disable=C0415

        return dpolygons(cls._regions(as_cell(cls, params))["m3"])

    def build(self):
        dbu = self.layout.dbu
        regions = self._regions()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(regions["m1"])
        self.cell.shapes(self.get_layer("SIS_junction")).insert(regions["straight"])
        self.cell.shapes(self.get_layer("SIS_junction_2")).insert(regions["bent"])
        insert_spacer(
            self.cell, self.layout, regions["hsq"], self.spacer_gradient, [pya.DPoint(0, self.hsq_y_offset / 2)]
        )
        self.add_protection(pya.Region(regions["m1"].bbox()).sized(self.margin / dbu))
        mh = self.middle_height
        self.refpoints["junction"] = pya.DPoint(0, 0)
        self.refpoints["upper_pad"] = pya.DPoint(0, (mh / 2 + self.upper_pad_height + mh / 2 - self.upper_pad_trim) / 2)
        self.refpoints["lower_pad"] = pya.DPoint(
            0, -(mh / 2 + self.lower_pad_height + mh / 2 - self.lower_pad_trim) / 2
        )


def junction_ground_pad_regions(
    dbu,
    box_size=500,
    pad_size=400,
    pad_r_inner=40,
    pad_r_outer=20,
    corner_points=64,
    bridge_width=50,
    junction_y=-225,
    finger_width=0.26,
    second_finger_width=0.2,
    straight_finger_y=-2,
    straight_pad_width=1.2,
    straight_finger_length=3,
    straight_window=(52, 50),
    bent_finger_y=-4,
    bent_pad_width=1,
    bent_finger_length=3,
    bent_conn_height=0.5,
    bent_window=(52, 49),
    bent_offset=1,
) -> dict:
    """Legacy ``testPad.create_testPad`` geometry in dbu: ``{"m1", "m3", "straight", "bent"}`` Regions."""
    pad_box = pya.Polygon(pya.Box(-box_size / dbu / 2, -box_size / dbu / 2, box_size / dbu / 2, box_size / dbu / 2))
    pad = pya.Polygon(pya.Box(-pad_size / dbu / 2, -pad_size / dbu / 2, pad_size / dbu / 2, pad_size / dbu / 2))
    pad = pad.round_corners(pad_r_inner / dbu, pad_r_outer / dbu, corner_points)
    cutout = pya.Polygon(
        pya.Box(-bridge_width / 2 / dbu, -box_size / dbu / 2, bridge_width / 2 / dbu, -pad_size / dbu / 2)
    )
    m1 = pya.Region(pad_box) - pya.Region(pad) - pya.Region(cutout)
    m3 = pya.Region(pad_box) - pya.Region(cutout)
    straight = coerced_straight_finger(
        dbu,
        straight_pad_width,
        3,
        finger_width,
        straight_finger_length,
        straight_window[0],
        straight_window[1],
        0,
        straight_finger_y,
    ).transformed(pya.Trans(0, True, 0 / dbu, junction_y / dbu))
    bent = coerced_bent_finger(
        dbu,
        bent_pad_width,
        second_finger_width,
        bent_finger_length,
        bent_conn_height,
        bent_window[0],
        bent_window[1],
        0,
        bent_finger_y,
        False,
    ).transformed(pya.Trans(0, False, 0 / dbu, (junction_y + bent_offset) / dbu))
    return {"m1": m1, "m3": m3, "straight": straight, "bent": bent}


class JunctionGroundPad(Element):
    """Rounded probe pad joined to ground by a bridge carrying a trilayer junction (legacy ``testPad.py``)."""

    qcc_category = "test_structure"

    box_size = Param(pdt.TypeDouble, "Etch window size", 500, unit="μm")
    pad_size = Param(pdt.TypeDouble, "Pad size", 400, unit="μm")
    pad_r_inner = Param(pdt.TypeDouble, "Pad inner corner radius", 40, unit="μm")
    pad_r_outer = Param(pdt.TypeDouble, "Pad outer corner radius", 20, unit="μm")
    corner_points = Param(pdt.TypeInt, "Points per full circle of the pad corners", 64)
    bridge_width = Param(pdt.TypeDouble, "Width of the bridge to ground", 50, unit="μm")
    junction_y = Param(pdt.TypeDouble, "Junction position on the bridge (y)", -225, unit="μm")
    finger_width = Param(pdt.TypeDouble, "Straight finger width (legacy 0.2·size + 0.06)", 0.26, unit="μm")
    second_finger_width = Param(pdt.TypeDouble, "Bent finger width", 0.2, unit="μm")

    def _regions(self) -> dict:
        return junction_ground_pad_regions(
            self.layout.dbu,
            box_size=self.box_size,
            pad_size=self.pad_size,
            pad_r_inner=self.pad_r_inner,
            pad_r_outer=self.pad_r_outer,
            corner_points=self.corner_points,
            bridge_width=self.bridge_width,
            junction_y=self.junction_y,
            finger_width=self.finger_width,
            second_finger_width=self.second_finger_width,
        )

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): the legacy ``testPad.py`` 3/0 (the etch window minus the ground bridge)."""
        from quantcore_circuits.layouts.others.keepout import as_cell, dpolygons  # pylint: disable=C0415

        return dpolygons(cls._regions(as_cell(cls, params))["m3"])

    def build(self):
        dbu = self.layout.dbu
        regions = self._regions()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(regions["m1"])
        self.cell.shapes(self.get_layer("SIS_junction")).insert(regions["straight"])
        self.cell.shapes(self.get_layer("SIS_junction_2")).insert(regions["bent"])
        self.add_protection(pya.Region(regions["m1"].bbox()).sized(self.margin / dbu))
        self.refpoints["pad_center"] = pya.DPoint(0, 0)
        self.refpoints["junction"] = pya.DPoint(0, self.junction_y)


def probe_pad_pair_regions(
    dbu,
    pad_width=500.0,
    upper_pad_height=400.0,
    lower_pad_height=400.0,
    middle_height=200.0,
    window_extra=100.0,
    pad_trim=50.0,
    cutout=11.0,
    tip_width=5.0,
    tip_y=6.0,
    tip_apex=4.5,
) -> dict:
    """Legacy ``chip_11m_TestJJ16x_pads.create_testPad`` pads (commented out there), in dbu: ``{"m1", "m3"}`` —
    1/0 = window − upper pad − its tip triangle − centre cut-out, 3/0 = window − lower pad − its triangle − cut-out."""
    h = upper_pad_height + middle_height + lower_pad_height
    window = pya.Polygon(
        pya.Box((-pad_width - window_extra) / dbu / 2, -h / 2 / dbu, (pad_width + window_extra) / dbu / 2, h / dbu / 2)
    )
    pad1 = pya.Polygon(
        pya.Box(
            -pad_width / dbu / 2,
            middle_height / dbu / 2,
            pad_width / dbu / 2,
            (upper_pad_height + middle_height / 2 - pad_trim) / dbu,
        )
    )
    pad2 = pya.Polygon(
        pya.Box(
            -pad_width / dbu / 2,
            -middle_height / dbu / 2,
            pad_width / dbu / 2,
            (-middle_height / 2 - lower_pad_height + pad_trim) / dbu,
        )
    )
    p1 = pya.Point(-tip_width / dbu / 2, tip_y / dbu)
    p2 = pya.Point(tip_width / dbu / 2, tip_y / dbu)
    p3 = pya.Point(0 / dbu, tip_apex / dbu)
    t1 = pya.Polygon([p1, p2, p3])
    t2 = pya.Polygon([pya.Point(p1.x, -p1.y), pya.Point(p2.x, -p2.y), pya.Point(p3.x, -p3.y)])
    cut = pya.Polygon(pya.Box(-cutout / 2 / dbu, -cutout / dbu / 2, cutout / 2 / dbu, cutout / dbu / 2))
    m1 = pya.Region(window) - pya.Region(pad1) - pya.Region(t1) - cut
    m3 = pya.Region(window) - pya.Region(pad2) - pya.Region(t2) - cut
    return {"m1": m1, "m3": m3}


class ProbePadPair(Element):
    """Probe-pad pair of the chip_11m junction test array (legacy ``chip_11m_TestJJ16x_pads.create_testPad``, whose
    pads are commented out there; chip_11f lands the ``JX_500`` junctions on such pads).

    A ``pad_width + window_extra`` × (pads + ``middle_height``) window: the upper pad is kept in the base metal (1/0
    = window − upper pad − its tip − the centre ``cutout``), the lower pad in the second metal (the legacy 3/0 =
    window − lower pad − its tip − cut-out, returned by :meth:`qcc_keepout`). At the legacy sizes the pads end
    ``middle_height / 2`` (100 µm) from the junction, as drawn; set ``middle_height`` to the cut-out height (11 µm)
    to bring them to it. ``junction_type`` ``"Trilayer Junction Compact"`` (or any trilayer cell) places that
    junction centred in the cut-out (``junction_params`` passed on, e.g. ``{"finger_width": 0.2, "lj_nH": …}``;
    the compact junction's 12 µm window overlaps the 11 µm cut-out by 0.5 µm per side, the "1 µm overlap" request).
    No ports (DC probe pads); refpoints ``junction``, ``upper_pad``, ``lower_pad``.
    """

    qcc_category = "test_structure"

    pad_width = Param(pdt.TypeDouble, "Pad width", 500, unit="μm")
    upper_pad_height = Param(pdt.TypeDouble, "Upper (base-metal) pad height", 400, unit="μm")
    lower_pad_height = Param(pdt.TypeDouble, "Lower (second-metal) pad height", 400, unit="μm")
    middle_height = Param(pdt.TypeDouble, "Distance between the pads (junction region)", 200, unit="μm")
    window_extra = Param(pdt.TypeDouble, "Window wider than the pads by", 100, unit="μm")
    pad_trim = Param(pdt.TypeDouble, "Pads shortened by (towards the window edge)", 50, unit="μm")
    cutout = Param(pdt.TypeDouble, "Centre cut-out (junction site) size", 11, unit="μm")
    junction_type = Param(
        pdt.TypeString,
        "Junction in the cut-out: none (legacy) or a trilayer cell",
        "No Squid",
        choices=["No Squid", "Trilayer Junction Compact", "Quantcore Junction", "Trilayer Junction"],
    )
    junction_params = Param(pdt.TypeString, "Junction cell parameters (JSON dict)", "{}")

    def _regions(self) -> dict:
        names = "pad_width upper_pad_height lower_pad_height middle_height window_extra pad_trim cutout".split()
        return probe_pad_pair_regions(self.layout.dbu, **{n: getattr(self, n) for n in names})

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): the legacy script's second-metal pattern (``m3``)."""
        from quantcore_circuits.layouts.others.keepout import as_cell, dpolygons  # pylint: disable=C0415

        return dpolygons(cls._regions(as_cell(cls, params))["m3"])

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        import json  # pylint: disable=import-outside-toplevel

        params = dict(params)
        if isinstance(params.get("junction_params"), dict):
            params["junction_params"] = json.dumps(params["junction_params"], sort_keys=True)
        return params

    def build(self):
        from quantcore_circuits.layouts.junctions.trilayer import _json_dict, trilayer_classes  # pylint: disable=C0415

        dbu = self.layout.dbu
        regions = self._regions()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(regions["m1"])
        self.add_protection(pya.Region(regions["m1"].bbox()).sized(self.margin / dbu))
        if self.junction_type != "No Squid":
            cls = trilayer_classes().get(self.junction_type)
            if cls is None:
                self.raise_error_on_cell(f"ProbePadPair: junction_type {self.junction_type!r} is not a trilayer cell")
            params = _json_dict(self.junction_params)
            if cls.__name__ != "TrilayerJunctionCompact":  # a full-size window spans the cut-out exactly
                params = {"window_height": self.cutout, "window_width": self.cutout, **params}
            cell = cls.create(self.layout, **params)
            h = float(cell.pcell_parameters_by_name().get("window_height", self.cutout))
            self.insert_cell(cell, pya.DTrans(0, -h / 2))
        mh = self.middle_height
        self.refpoints["junction"] = pya.DPoint(0, 0)
        self.refpoints["upper_pad"] = pya.DPoint(0, (mh / 2 + self.upper_pad_height + mh / 2 - self.pad_trim) / 2)
        self.refpoints["lower_pad"] = pya.DPoint(0, -(mh / 2 + self.lower_pad_height + mh / 2 - self.pad_trim) / 2)

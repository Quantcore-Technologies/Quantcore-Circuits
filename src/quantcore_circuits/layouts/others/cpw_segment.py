"""Straight CPW segment and flux-trapping hole arrays (ported from QWri ``CPW.lym`` "Coplanar Waveguide" — the
feedline of chips 01–07 — and the ``flux_holes`` arrays of ``flux_holes.py`` / the legacy chips).

``CpwSegment``: legacy fab mode with ground (``fab=True, ground=True``): the two gap strips of a straight CPW of
``length``, centred at the origin along x; ports ``a`` (−x end) and ``b`` (+x end), CPW width ``a``/``b`` (legacy
``cwidth``/``gap``). ``FluxHoleArray``: a regular array of square holes in the ground plane (vortex traps).
``FluxHoles``: square holes at an explicit list of centres (the ``FluxHoles`` QComponent of the legacy design
notebook ``14.0 Two_feedline_resonator_chip.ipynb``: 5 µm squares on rows along the feedlines).
All etch into ``base_metal_gap_wo_grid`` with the legacy pya calls.
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def cpw_segment_gaps(dbu, length, cwidth, gap, lc_thickness=10.0, rc_thickness=10.0) -> pya.Region:
    """Legacy ``CPW.makeCPW`` with ``fab=True, ground=True`` (incl. its coerce rules), in dbu."""
    lc = lc_thickness if lc_thickness > 0 else cwidth
    rc = rc_thickness if rc_thickness > 0 else cwidth
    if cwidth <= gap:
        cwidth = gap * 5 / 3
    centre = pya.Box(-length / dbu / 2, -cwidth / dbu / 2, length / dbu / 2, cwidth / dbu / 2)
    lower = pya.Box(-length / dbu / 2, -(lc + gap + cwidth / 2) / dbu, length / dbu / 2, (-gap - cwidth / 2) / dbu)
    upper = pya.Box(-length / dbu / 2, +(gap + cwidth / 2) / dbu, length / dbu / 2, +(rc + gap + cwidth / 2) / dbu)
    cpw = pya.Region().insert([centre, upper, lower])
    return pya.Region().insert(cpw.bbox()) - cpw


def flux_hole_region(dbu, hole_size=5.0, pitch_x=20.0, pitch_y=15.0, nx=10, ny=2) -> pya.Region:
    """The flux-hole arrays of the legacy chips: ``nx × ny`` squares of ``hole_size`` (first centred at the origin),
    ``pitch_x`` / ``pitch_y`` apart, in dbu."""
    hole = pya.Box(-hole_size / 2 / dbu, -hole_size / 2 / dbu, hole_size / 2 / dbu, hole_size / 2 / dbu)
    out = pya.Region()
    for i in range(int(nx)):
        for j in range(int(ny)):
            out.insert(hole.moved(int(round(i * pitch_x / dbu)), int(round(j * pitch_y / dbu))))
    return out


class CpwSegment(Element):
    """Straight CPW segment centred at the origin (legacy "Coplanar Waveguide"); ports ``a`` (−x) and ``b`` (+x)."""

    length = Param(pdt.TypeDouble, "Length", 200, unit="μm")
    lc_thickness = Param(pdt.TypeDouble, "Lower ground strip drawn (legacy lc_thickness)", 10, unit="μm")
    rc_thickness = Param(pdt.TypeDouble, "Upper ground strip drawn (legacy rc_thickness)", 10, unit="μm")
    keepout_gap = Param(pdt.TypeDouble, "3/0 keep-out growth across the line (legacy c_gap)", 0, unit="μm")

    qcc_category = "waveguide"

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm), legacy ``CPW.lym`` ``fab_l``: the bbox of conductor + drawn ground strips grown
        by ``keepout_gap`` (legacy ``c_gap``; the chips use 0) across the line."""
        from quantcore_circuits.layouts.others.keepout import DBU, dpolygons, full_params  # pylint: disable=C0415

        p = full_params(cls, params)
        cw, gap = float(p["a"]), float(p["b"])
        lc = float(p["lc_thickness"]) if float(p["lc_thickness"]) > 0 else cw
        rc = float(p["rc_thickness"]) if float(p["rc_thickness"]) > 0 else cw
        if cw <= gap:
            cw = gap * 5 / 3
        length = float(p["length"])
        box = pya.Box(-length / DBU / 2, -(lc + gap + cw / 2) / DBU, length / DBU / 2, (rc + gap + cw / 2) / DBU)
        return dpolygons(pya.Region(box).sized(0, round(float(p["keepout_gap"]) / DBU), 2))

    def build(self):
        dbu = self.layout.dbu
        gaps = cpw_segment_gaps(dbu, self.length, self.a, self.b, self.lc_thickness, self.rc_thickness)
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))
        self.add_port("a", pya.DPoint(-self.length / 2, 0), pya.DVector(-1, 0))
        self.add_port("b", pya.DPoint(self.length / 2, 0), pya.DVector(1, 0))


class FluxHoleArray(Element):
    """Array of square flux-trapping holes in the ground plane (legacy chips' ``flux_holes``)."""

    hole_size = Param(pdt.TypeDouble, "Hole size", 5, unit="μm")
    pitch_x = Param(pdt.TypeDouble, "Pitch in x", 20, unit="μm")
    pitch_y = Param(pdt.TypeDouble, "Pitch in y", 15, unit="μm")
    nx = Param(pdt.TypeInt, "Holes in x", 10)
    ny = Param(pdt.TypeInt, "Holes in y", 2)

    qcc_category = "other"

    def build(self):
        dbu = self.layout.dbu
        holes = flux_hole_region(dbu, self.hole_size, self.pitch_x, self.pitch_y, self.nx, self.ny)
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(holes)


def flux_holes_at(dbu, centers, hole_size=5.0) -> pya.Region:
    """Square holes of ``hole_size`` centred on ``centers`` ([(x, y), ...] or a flat [x0, y0, x1, y1, ...]), dbu."""
    flat = [float(v) for c in centers for v in (c if isinstance(c, list | tuple) else [c])]
    if len(flat) % 2:
        raise ValueError(f"centers needs x, y pairs, got {len(flat)} numbers")
    h = hole_size / 2
    out = pya.Region()
    for x, y in zip(flat[::2], flat[1::2]):
        out.insert(pya.DBox(x - h, y - h, x + h, y + h).to_itype(dbu))
    return out


class FluxHoles(Element):
    """Square flux-trapping holes at explicit centres (legacy notebook 14 ``FluxHoles`` QComponent, ``size`` 5 µm).

    ``centers`` is a flat list ``[x0, y0, x1, y1, ...]`` in µm (local frame); ``design.json`` may also give
    ``[[x0, y0], [x1, y1], ...]``. The holes etch into the ground (``base_metal_gap_wo_grid``); no ports.
    """

    centers = Param(pdt.TypeList, "Hole centres, flat x, y list (µm)", [0, 0])
    hole_size = Param(pdt.TypeDouble, "Hole size (legacy size)", 5, unit="μm")

    qcc_category = "other"

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """``centers`` as pairs ``[[x, y], ...]`` → the flat PCell list (unknown parameters raise ``ValueError``)."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"FluxHoles: unknown parameter(s) {unknown}")
        centers = params.get("centers")
        if centers is not None and any(isinstance(c, list | tuple) for c in centers):
            params["centers"] = [float(v) for c in centers for v in c]
        return params

    def build(self):
        holes = flux_holes_at(self.layout.dbu, self.centers, self.hole_size)
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(holes)

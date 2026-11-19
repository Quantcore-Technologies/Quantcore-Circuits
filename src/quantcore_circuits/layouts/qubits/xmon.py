"""Xmon qubit (ported from QWri ``Xmon Cross`` + ``Xmon Handle``) as a KQC ``Qubit`` with ports.

Local frame: cross centred at the origin; claws on the north/west/east arms; the junction sits in the gap below the
south arm (as in the legacy chips). Geometry is the legacy fab output: ``base_metal_gap_wo_grid`` = bounding box of
the positive metal minus the metal, computed with the same pya calls as the legacy PCell.

Ports (outward directions): ``claw_n`` (+y), ``claw_w`` (−x), ``claw_e`` (+x) at the claw tail tips, width
``claw_tail_width``; ``flux`` (−y) at the flux-line tip below the junction when ``flux_port`` is set. The SQUID
refpoints are exposed as ``port_squid_a``/``port_squid_b`` for KQC ``JunctionSimPort``.

Claw gaps (decision #22): ``claw_spacing`` is the etched clearance around the claw body and ``ground_sliver``
the ground strip between the cross gap and that clearance (2 µm each by default). The claw *tail* is the start of
the readout CPW, so its clearance is ``claw_tail_gap`` (−1 = the element's ``b``, the chip / PDK CPW gap): a 10/6
route continues a 10/6 tail, a 10/10 route needs ``claw_tail_gap = 10`` (or a chip ``b`` of 10). The claw ports
declare exactly that gap (with ``claw_ground``: the ground frame's ``claw_ground_gap``). The legacy PCells used
``claw_spacing`` for the tail too: ``claw_tail_gap = claw_spacing`` reproduces them.

Junction: ``junction_type`` picks the cell (``"No Squid"`` = none; ``"Quantcore Junction"`` / ``"Quantcore Squid"``
= the PDK trilayer junctions with CLEARER and spacer gradient); ``junction_params`` (a dict in ``design.json``,
stored as JSON) is passed to that cell, e.g. ``{"finger_width": 0.5, "second_finger_width": 0.6}`` for the
trilayer junctions (the legacy chips sweep the junction size) or ``{"lj_nH": 6.7}`` (sized by the PDK junction
rule, :func:`quantcore_circuits.circuit.bridges.fingers_for_lj`). ``junction_window = [w, h]`` keeps a ``w × h`` box
centred in the junction gap as metal (``base_metal_addition``, subtracted from the 1/0 etch at export): the
legacy chips' "CLEARER" step, so the trilayer bridges the cross arm and ground where the fingers (2/0, 4/0) define
the junction (chip_01: 30 × 18 µm, chip_01_creator/02: 30 × 20 µm). An optional third value moves the window centre
away from the cross (negative: towards it): chip_03 and chip_05 use ``[30, 27, -3]`` (gap 20: the window runs from
6.5 µm inside the arm to 0.5 µm into the ground), chip_10a ``[30, 45, 12.5]`` at its junctions (from the arm end to
25 µm into the ground, so it also clears the flux-line tip there) and ``[30, 45, -12.5]`` at its SQUIDs (shifted
25 µm towards the cross, "cut inside"). The window is drawn by the Xmon, so it works with every
``junction_type``.
"""

import ast
import json

from kqcircuits.junctions import junction_type_choices
from kqcircuits.pya_resolver import pya
from kqcircuits.qubits.qubit import Qubit
from kqcircuits.util.parameters import Param, pdt

_CLAWS = ("n", "w", "e")


def claw_region(dbu, width, thickness, fwidth, hlength, tail, tail_l, tail_width=10.0):
    """Legacy ``Xmon_handle.makeCap`` (arguments in µm, result in dbu)."""
    width, thickness, fwidth = width / dbu, thickness / dbu, fwidth / dbu
    hlength, tail_l, tail_width = hlength / dbu, tail_l / dbu, tail_width / dbu
    base = pya.Box(-width / 2, 0, width / 2, thickness)
    finger_left = pya.Box(-(width / 2 + fwidth), 0, -width / 2, hlength)
    finger_right = pya.Box(width / 2, 0, (width / 2 + fwidth), hlength)
    cap = pya.Region().insert([base, finger_left, finger_right])
    tail_box = pya.Box(-tail_width / 2, -tail_l, tail_width / 2, 0) if tail else pya.Box()
    return cap + tail_box


def ground_claw(cap, dbu, ggap, tail_l, width, thickness, hlength, path_w=10.0):
    """Legacy ``Xmon_handle.groundHandle`` (arguments in µm, ``cap`` in dbu)."""
    ggap, tail_l, width = ggap / dbu, tail_l / dbu, width / dbu
    thickness, hlength, path_w = thickness / dbu, hlength / dbu, path_w / dbu
    tailcov = pya.Region().insert(pya.Box((-path_w / 2 - ggap), (-tail_l - 2 * ggap), path_w / 2 + ggap, -tail_l))
    cap_cov = pya.Region().insert(pya.Box(-width / 2, thickness, width / 2, hlength + (2 * ggap)))
    grown = pya.Region().insert(cap.sized(ggap * 2, ggap).bbox()) - cap.sized(ggap, ggap)
    return grown - tailcov - cap_cov + cap


def xmon_positive(
    dbu,
    arm_width,
    cross_length,
    ground_sliver,
    gap,
    claws,
    claw_spacing,
    claw_base,
    claw_finger_width,
    claw_length,
    claw_tail,
    claw_ground,
    claw_ground_gap,
    claw_tail_length,
    claw_tail_width=10.0,
    claw_tail_gap=None,
):
    """Legacy ``Xmon_cross.produce_impl`` positive metal (``fab=False``) in dbu. ``claw_tail_gap`` (µm, None = the
    legacy ``claw_spacing``) is the clearance of the claw tail (without ``claw_ground``)."""
    t, w = arm_width / dbu, cross_length / dbu
    cross = pya.Region().insert(pya.Box(-w / 2, -t / 2, w / 2, t / 2)) + pya.Region().insert(
        pya.Box(-t / 2, -w / 2, t / 2, w / 2)
    )
    if not cross.is_merged():
        cross.merge()
    # NB: two-argument Region.sized(d, mode) is *isotropic* sizing by d with corner mode `mode`; the legacy code passes
    # (gap+da) as the second argument, so the ground rectangle is the cross bbox grown by `grow` on all sides.
    # Kept verbatim so the geometry matches the legacy cells exactly.
    grow = (gap + ground_sliver + claw_base + claw_tail_length + claw_spacing) / dbu
    boundary = pya.Region().insert(cross.sized(grow, (gap + ground_sliver) / dbu).bbox()) - cross.sized(
        gap / dbu, gap / dbu
    )
    final = cross + boundary
    pad_width = arm_width + 2 * claw_ground_gap + 2 * gap + 2 * ground_sliver
    x_off = (cross_length / 2 + gap + ground_sliver + claw_base + claw_spacing) / dbu
    transforms = {
        "n": pya.ICplxTrans(1, 0, True, 0, x_off),
        "w": pya.ICplxTrans(1, 270, False, -x_off, 0),
        "e": pya.ICplxTrans(1, 90, False, x_off, 0),
    }
    claw = claw_region(
        dbu, pad_width, claw_base, claw_finger_width, claw_length, claw_tail, claw_tail_length, claw_tail_width
    )
    tail = None
    if claw_tail and not claw_ground and claw_tail_gap is not None and claw_tail_gap != claw_spacing:
        tw, tl = claw_tail_width / dbu, claw_tail_length / dbu
        tail = pya.Region(pya.Box(-tw / 2, -tl, tw / 2, 0))
    if claw_ground:
        claw = ground_claw(claw, dbu, claw_ground_gap, claw_tail_length, pad_width, claw_base, claw_length, 10.0)
    for name in claws:
        placed = claw.transformed(transforms[name])
        final = final - placed.sized(claw_spacing / dbu)
        if tail is not None:
            final -= tail.transformed(transforms[name]).sized(claw_tail_gap / dbu)
        final += placed
    return final


def _junction_params(text) -> dict:
    """``junction_params`` (JSON, or a Python dict repr as KLayout stores a dict) → dict."""
    if isinstance(text, dict):
        return dict(text)
    text = str(text or "").strip() or "{}"
    try:
        value = json.loads(text)
    except ValueError:
        value = ast.literal_eval(text)
    if not isinstance(value, dict):
        raise ValueError(f"junction_params must be a dict, got {value!r}")
    return value


class Xmon(Qubit):
    """Grounded cross transmon with claw couplers; junction below the south arm.

    Ported from the legacy QWri PCells ``Xmon Cross`` (``pymacros/QuantumPcells/xmon_cross.lym``) and ``Xmon Handle``
    (``xmon_handle.lym``), fab mode. Claw-tail ports declare ``a = claw_tail_width`` and the element ``b`` (the tail
    itself is drawn with a ``claw_spacing`` clearance; a route continues as the chip CPW, see the catalog note).
    """

    qcc_category = "qubit"

    arm_width = Param(pdt.TypeDouble, "Cross arm width", 25, unit="μm")
    cross_length = Param(pdt.TypeDouble, "Cross tip-to-tip length", 300, unit="μm")
    gap = Param(pdt.TypeDouble, "Gap between cross and ground", 25, unit="μm")
    ground_sliver = Param(pdt.TypeDouble, "Ground between cross gap and claw clearance", 2, unit="μm")
    claws = Param(pdt.TypeList, "Claws to draw (any of n, w, e)", ["n"])
    claw_spacing = Param(pdt.TypeDouble, "Claw clearance to ground", 2, unit="μm")
    claw_base = Param(pdt.TypeDouble, "Claw base thickness", 25, unit="μm")
    claw_finger_width = Param(pdt.TypeDouble, "Claw finger width", 25, unit="μm")
    claw_length = Param(pdt.TypeDouble, "Claw finger length", 100, unit="μm")
    claw_tail = Param(pdt.TypeBoolean, "Claw has a tail (connection stub)", True)
    claw_tail_length = Param(pdt.TypeDouble, "Claw tail length", 50, unit="μm")
    claw_tail_width = Param(pdt.TypeDouble, "Claw tail width (CPW centre width at the port)", 10, unit="μm")
    claw_ground = Param(pdt.TypeBoolean, "Ground frame around the claw", False)
    claw_ground_gap = Param(pdt.TypeDouble, "Claw ground gap", 6, unit="μm")
    claw_tail_gap = Param(
        pdt.TypeDouble, "Claw tail gap to ground (= the readout CPW gap; -1 = the element's b)", -1, unit="μm"
    )
    flux_port = Param(pdt.TypeBoolean, "Add flux-line port and current slot below the junction", False)
    flux_x = Param(pdt.TypeDouble, "Flux tip x offset from the qubit axis", -10.5, unit="μm")
    flux_tip_depth = Param(pdt.TypeDouble, "Flux tip distance beyond the gap edge", 0.5, unit="μm")
    flux_slot = Param(pdt.TypeList, "Flux slot size [length, width] (empty = none)", [28, 5], unit="μm")
    junction_type = Param(
        pdt.TypeString,
        "Junction Type",
        "Trilayer Junction",
        choices=junction_type_choices
        + ["Trilayer Junction", "Trilayer Squid", "Quantcore Junction", "Quantcore Squid"],
    )
    fluxline_type = Param(pdt.TypeString, "Fluxline Type (KQC)", "none")
    junction_params = Param(pdt.TypeString, "Junction cell parameters (JSON dict)", "{}")
    junction_window = Param(
        pdt.TypeList,
        "Metal window [width, height(, offset)] in the junction gap (legacy CLEARER; offset > 0 = away from the "
        "cross; empty = none)",
        [],
    )

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """design.json params → PCell params: ``junction_params`` dict → JSON. Unknown parameters raise."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"Xmon: unknown parameter(s) {unknown}")
        jp = params.get("junction_params")
        if isinstance(jp, dict):
            params["junction_params"] = json.dumps(jp, sort_keys=True)
        elif isinstance(jp, str):
            _junction_params(jp)  # validate
        return params

    # ports whose connecting line is shorted to ground at the port (used by the simulation builder)
    qcc_shorted_ports = ("flux",)

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """Per-port CPW widths (a, b) as drawn: the claw tail width and its gap (``claw_tail_gap``, −1 = the
        element's ``b``; with ``claw_ground`` the frame's ``claw_ground_gap``)."""
        tail = params.get("claw_tail_width", 10)
        return {f"claw_{c}": (tail, cls.claw_tail_gap_um(params)) for c in _CLAWS}

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): the legacy ``Xmon Cross`` ``fab_l`` shape, the cross grown isotropically by
        2·claw_base + 10 + claw_finger_width (85 µm by default)."""
        from quantcore_circuits.layouts.others.keepout import DBU, dpolygons, full_params  # pylint: disable=C0415

        p = full_params(cls, params)
        t, w = float(p["arm_width"]) / DBU, float(p["cross_length"]) / DBU
        cross = pya.Region().insert(pya.Box(-w / 2, -t / 2, w / 2, t / 2)) + pya.Region().insert(
            pya.Box(-t / 2, -w / 2, t / 2, w / 2)
        )
        grow = (2 * float(p["claw_base"]) + 10 + float(p["claw_finger_width"])) / DBU
        return dpolygons(cross.merged().sized(round(grow)))

    @classmethod
    def claw_tail_gap_um(cls, params: dict) -> float:
        """The drawn clearance of the claw tails (µm)."""
        if params.get("claw_ground", False):
            return float(params.get("claw_ground_gap", 6))
        gap = float(params.get("claw_tail_gap", -1))
        return gap if gap >= 0 else float(params.get("b", 6))

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        """Grounded transmon: island (C to ground + JJ/SQUID to ground) and one coupler node per claw (C_g to the
        island, C to ground). Capacitances are calibrated estimates until a C-matrix fills them (FEM nets
        ``<name>.island``, ``<name>.claw_<c>``). The flux port carries a flux-bias control line."""
        from quantcore_circuits.lom.calibration import estimate  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.fragment import (  # pylint: disable=C0415
            Element,
            Fragment,
            effective_junction,
            junction_kind,
            junction_value,
        )

        params = {k: v.default for k, v in cls.get_schema().items()} | dict(inst.params)
        frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
        c_is, src = estimate("Xmon", "C_island", params, pdk.name)
        frag.elements.append(
            Element(
                f"C_{name}",
                "C",
                ("island", "gnd"),
                {"estimate": c_is, "unit": "fF", "fem": "cmatrix", "estimate_source": src},
                {"param": f"{name}.cross_length"},
            )
        )
        kind = junction_kind(params.get("junction_type", ""))  # None: "No Squid", a junction-less reference cross
        # the design's junction, else the drawn trilayer junction on the PDK rule (components-pdk)
        ej = effective_junction(inst, params, kind=kind or "JJ")
        lj = ej.lj0_nH
        if kind is None:
            frag.notes.append(f"{name}: junction_type 'No Squid' → no junction element (island C only)")
        else:
            frag.elements.append(
                Element(f"J_{name}", kind, ("island", "gnd"), junction_value(ej), {"param": f"{name}.junction.Lj_nH"})
            )
        if lj and kind is not None:
            frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))
        cross = float(params["cross_length"])
        frag.knobs[f"{name}.cross_length"] = (round(cross * 0.5, 1), round(cross * 1.8, 1))
        for c in params.get("claws") or []:
            node = f"claw_{c}"
            frag.nodes[node] = {"island": f"{name}.claw_{c}"}
            frag.port_nodes[node] = node
            cg, src_g = estimate("Xmon", "Cg", params, pdk.name)
            cc, src_c = estimate("Xmon", "C_claw", params, pdk.name)
            frag.elements.append(
                Element(
                    f"Cg_{name}_{node}",
                    "C",
                    ("island", node),
                    {"estimate": cg, "unit": "fF", "fem": "cmatrix", "estimate_source": src_g},
                    {"param": f"{name}.claw_length"},
                )
            )
            frag.elements.append(
                Element(
                    f"Cc_{name}_{node}",
                    "C",
                    (node, "gnd"),
                    {"estimate": cc, "unit": "fF", "fem": "cmatrix", "estimate_source": src_c},
                )
            )
            claw = float(params["claw_length"])
            frag.knobs[f"{name}.claw_length"] = (round(claw * 0.4, 1), round(claw * 2.2, 1))
        if params.get("flux_port"):
            frag.port_nodes["flux"] = "control:flux"
        return frag

    def _claw_tip(self, name):
        x = self.cross_length / 2 + self.gap + self.ground_sliver + self.claw_base + self.claw_spacing
        d = x + self.claw_tail_length
        return {
            "n": (pya.DPoint(0, d), pya.DVector(0, 1)),
            "w": (pya.DPoint(-d, 0), pya.DVector(-1, 0)),
            "e": (pya.DPoint(d, 0), pya.DVector(1, 0)),
        }[name]

    def build(self):
        dbu = self.layout.dbu
        claws = [str(c).lower() for c in self.claws]
        unknown = set(claws) - set(_CLAWS)
        if unknown:
            self.raise_error_on_cell(f"Unknown claw(s) {sorted(unknown)}; use n, w, e")
        metal = xmon_positive(
            dbu,
            self.arm_width,
            self.cross_length,
            self.ground_sliver,
            self.gap,
            claws,
            self.claw_spacing,
            self.claw_base,
            self.claw_finger_width,
            self.claw_length,
            self.claw_tail,
            self.claw_ground,
            self.claw_ground_gap,
            self.claw_tail_length,
            self.claw_tail_width,
            self.claw_tail_gap if self.claw_tail_gap >= 0 else self.b,
        )
        outer = pya.Region().insert(metal.bbox())
        gaps = outer - metal

        junction_y = -(self.cross_length / 2 + self.gap)
        if self.flux_port:
            tip = pya.DPoint(self.flux_x, junction_y - self.flux_tip_depth)
            self.add_port("flux", tip, pya.DVector(0, -1))
            if len(self.flux_slot) == 2:
                length, width = float(self.flux_slot[0]), float(self.flux_slot[1])
                slot = pya.DBox(tip.x, tip.y - width, tip.x + length, tip.y)
                gaps += pya.Region(slot.to_itype(dbu))
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))

        for name in claws:
            if self.claw_tail:
                pos, direction = self._claw_tip(name)
                self.add_port(f"claw_{name}", pos, direction)

        if len(self.junction_window) in (2, 3):
            w, h = float(self.junction_window[0]), float(self.junction_window[1])
            dy = float(self.junction_window[2]) if len(self.junction_window) == 3 else 0.0
            yc = junction_y + self.gap / 2 - dy  # dy > 0 moves the window away from the cross (into the ground)
            window = pya.DBox(-w / 2, yc - h / 2, w / 2, yc + h / 2)
            self.cell.shapes(self.get_layer("base_metal_addition")).insert(window.to_itype(dbu))
            self.refpoints["junction_window"] = window.center()
        elif self.junction_window:
            self.raise_error_on_cell(
                f"junction_window needs [width, height] or [width, height, offset], got {list(self.junction_window)}"
            )

        if self.junction_type != "No Squid":
            squid_trans = pya.DCplxTrans(1, 0, False, 0, junction_y)
            if self.mirror_squid:
                squid_trans = squid_trans * pya.DTrans.M90
            squid_params = {"window_height": self.gap, **_junction_params(self.junction_params)}
            squid_refs = self.produce_squid(pya.DCplxTrans(1, 0, False, 0, junction_y), **squid_params)
            for ref in ("port_squid_a", "port_squid_b"):
                if ref in squid_refs:
                    self.refpoints[ref] = squid_trans * squid_refs[ref]
        self.refpoints["probe_island"] = pya.DPoint(0, 0)
        self.refpoints["probe_ground"] = pya.DPoint(0, junction_y - self.gap)

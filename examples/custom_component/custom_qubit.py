"""A custom qubit for the Quantcore library: a floating "fork" transmon with a Quantcore trilayer junction.

Two forked islands (a neck, a wide body with a slot cut from its outer end, rounded corners) face each other across
the junction gap. The junction is the PDK trilayer junction (``Quantcore Junction``) placed across that gap by
:func:`quantcore_circuits.layouts.junctions.trilayer.place_trilayer`, so it is sized on the PDK junction rule and the
LOM reads its L_J from the same rule. Two pins leave the qubit:

* ``claw`` (+x): a readout claw beside the top island and its tail; the readout resonator connects here,
* ``drive`` (-x): an open-ended drive stub that ends beside the bottom island (a control pin, not a circuit node).

Use it without copying anything into the library: put this folder on ``sys.path`` and add it by its dotted path,

    sys.path.insert(0, "examples/custom_component")
    d.add("Q1", "custom_qubit.ForkTransmon", at=(0, 0), junction=junction, **params)

(``params, junction = trilayer_junction("custom_qubit.ForkTransmon", lj_nH=12.0)``). To make it a library cell, copy
the file into ``src/quantcore_circuits/layouts/qubits/``. Guide: docs/library/custom-components/custom-qubit.md.
"""

import json

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


def _json_dict(text) -> dict:
    """``junction_params`` (a JSON string, or a dict) -> dict."""
    if isinstance(text, dict):
        return dict(text)
    value = json.loads(str(text or "").strip() or "{}")
    if not isinstance(value, dict):
        raise ValueError(f"junction_params must be a dict, got {value!r}")
    return value


class ForkTransmon(Element):
    """Floating two-island transmon with forked islands; ports ``claw`` (+x) and ``drive`` (-x).

    Local frame: the junction gap is centred on the origin, island 1 below it, island 2 above it.
    """

    qcc_category = "qubit"  # the panel's class filter, the DRC, the fab export and the LOM read this
    qcc_junction = True

    # --- the shape: every number is a parameter, so the panel and design.json can change it ---------------------
    body_w = Param(pdt.TypeDouble, "Island body width", 240, unit="μm")
    body_len = Param(pdt.TypeDouble, "Island body length", 260, unit="μm")
    neck_w = Param(pdt.TypeDouble, "Neck width (towards the junction)", 30, unit="μm")
    neck_len = Param(pdt.TypeDouble, "Neck length", 40, unit="μm")
    slot_w = Param(pdt.TypeDouble, "Fork slot width (0 = no fork)", 50, unit="μm")
    slot_len = Param(pdt.TypeDouble, "Fork slot depth from the outer end", 130, unit="μm")
    gap = Param(pdt.TypeDouble, "Junction gap between the two necks", 20, unit="μm")
    corner_r = Param(pdt.TypeDouble, "Corner rounding of the islands", 15, unit="μm")
    clearance = Param(pdt.TypeDouble, "Etched clearance around the islands", 40, unit="μm")
    claw_w = Param(pdt.TypeDouble, "Readout claw width", 20, unit="μm")
    claw_len = Param(pdt.TypeDouble, "Readout claw length (along the island)", 120, unit="μm")
    claw_gap = Param(pdt.TypeDouble, "Gap between the claw and the island", 12, unit="μm")
    tail_len = Param(pdt.TypeDouble, "Length of the claw / drive tails outside the pocket", 40, unit="μm")
    drive_gap = Param(pdt.TypeDouble, "Gap between the drive stub tip and the island", 30, unit="μm")

    # --- the junction: the same two parameters every Quantcore qubit has ------------------------------------------
    junction_type = Param(
        pdt.TypeString,
        "Junction across the gap",
        "Quantcore Junction",
        choices=["No Squid", "Quantcore Junction", "Quantcore Squid", "Trilayer Junction", "Trilayer Squid", "Sim"],
    )
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict, e.g. lj_nH)", "{}")

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """design.json params -> PCell params: ``junction_params`` dict -> JSON; unknown names raise."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"ForkTransmon: unknown parameter(s) {unknown}")
        if isinstance(params.get("junction_params"), dict):
            params["junction_params"] = json.dumps(params["junction_params"], sort_keys=True)
        elif isinstance(params.get("junction_params"), str):
            _json_dict(params["junction_params"])  # validate
        return params

    # ---- geometry (µm; every helper returns dbu Regions) ---------------------------------------------------------
    def _island(self, sign: int) -> pya.DPolygon:
        """One island as a polygon: neck + body with the fork slot; ``sign`` +1 = top island, -1 = bottom."""
        g, nl, bl, bw, nw = self.gap / 2, self.neck_len, self.body_len, self.body_w, self.neck_w
        y0, y1, y2 = g, g + nl, g + nl + bl  # gap edge, neck/body step, outer end
        hs = max(self.slot_w, 0) / 2
        sd = min(max(self.slot_len, 0), bl - 20) if hs > 0 else 0
        pts = [(-nw / 2, y0), (nw / 2, y0), (nw / 2, y1), (bw / 2, y1), (bw / 2, y2)]
        if sd > 0:
            pts += [(hs, y2), (hs, y2 - sd), (-hs, y2 - sd), (-hs, y2)]
        pts += [(-bw / 2, y2), (-bw / 2, y1), (-nw / 2, y1)]
        return pya.DPolygon([pya.DPoint(x, sign * y) for x, y in pts])

    def _claw_box(self) -> pya.DBox:
        x0 = self.body_w / 2 + self.claw_gap
        y_top = self.gap / 2 + self.neck_len + self.body_len
        return pya.DBox(x0, y_top - self.claw_len, x0 + self.claw_w, y_top)

    def _x_claw_port(self) -> float:
        return self._claw_box().right + self.clearance + self.tail_len

    def _x_drive_port(self) -> float:
        return -(self.body_w / 2 + self.clearance + self.tail_len)

    def _y_drive(self) -> float:
        return -(self.gap / 2 + self.neck_len + self.body_len / 2)

    def _round(self, region: pya.Region) -> pya.Region:
        r = max(self.corner_r, 0) / self.layout.dbu
        return region.round_corners(r, r, 64) if r > 0 else region

    def build(self):
        dbu = self.layout.dbu
        a, b = self.a, self.b
        islands = self._round(pya.Region([self._island(1).to_itype(dbu), self._island(-1).to_itype(dbu)]))
        claw = pya.Region(self._claw_box().to_itype(dbu))
        # the tails continue as the CPW of the pins (centre width a, gap b)
        cb = self._claw_box()
        yc = (cb.top + cb.bottom) / 2
        claw_tail = pya.DBox(cb.right - 1, yc - a / 2, self._x_claw_port(), yc + a / 2)
        yd = self._y_drive()
        drive_tail = pya.DBox(self._x_drive_port(), yd - a / 2, -(self.body_w / 2 + self.drive_gap), yd + a / 2)
        tails = pya.Region([claw_tail.to_itype(dbu), drive_tail.to_itype(dbu)])
        metal = islands + claw + tails

        # negative mask: the etched pocket = clearance around islands + claw, and the CPW gaps b around the tails
        clear = (islands + claw).sized(round(self.clearance / dbu), 2)
        corridors = pya.Region(
            [
                pya.DBox(claw_tail.left, yc - a / 2 - b, claw_tail.right, yc + a / 2 + b).to_itype(dbu),
                pya.DBox(drive_tail.left, yd - a / 2 - b, drive_tail.right, yd + a / 2 + b).to_itype(dbu),
            ]
        )
        etch = (clear + corridors) - metal
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(round(self.margin / dbu)))

        # pins: position + direction pointing out of the component (a route leaves / arrives along it)
        self.add_port("claw", pya.DPoint(self._x_claw_port(), yc), pya.DVector(1, 0))
        self.add_port("drive", pya.DPoint(self._x_drive_port(), yd), pya.DVector(-1, 0))

        # the junction: refpoints mark its ends (the simulation builder reads them), place_trilayer draws it
        a_pt, b_pt = pya.DPoint(0, self.gap / 2), pya.DPoint(0, -self.gap / 2)
        self.refpoints["port_squid_a"] = b_pt  # island 1 side
        self.refpoints["port_squid_b"] = a_pt  # island 2 side
        jtype = str(self.junction_type or "No Squid")
        if jtype not in ("No Squid", "Sim"):
            from quantcore_circuits.layouts.junctions.trilayer import place_trilayer

            gaps = pya.Region(self.cell.begin_shapes_rec(self.get_layer("base_metal_gap_wo_grid")))
            try:
                place_trilayer(self, jtype, gaps, a_pt, b_pt, self.junction_params)
            except ValueError as e:
                self.raise_error_on_cell(f"ForkTransmon: {e}")

    # ---- the LOM model --------------------------------------------------------------------------------------------
    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        """Floating transmon: island1 / island2 (C to ground each, C between), the junction between them, the
        readout claw as its own node (C_g to island 2, C to ground), the drive pin as a control line.

        The capacitances are rough formulas (see :mod:`quantcore_circuits.lom.estimates`) until a Q3D C-matrix of
        the cell replaces them: the FEM nets are ``<name>.island1``, ``<name>.island2`` and ``<name>.claw``.
        """
        from quantcore_circuits.lom import estimates as est
        from quantcore_circuits.lom.fragment import (
            Element as LomElement,
        )
        from quantcore_circuits.lom.fragment import (
            Fragment,
            cell_params,
            junction_element,
            junction_kind,
        )

        p = cell_params(inst)
        eps = est.substrate_eps(pdk)
        bw, bl, nw, nl = (float(p[k]) for k in ("body_w", "body_len", "neck_w", "neck_len"))
        gap, clr = float(p["gap"]), float(p["clearance"])
        sw, sl = max(float(p["slot_w"]), 0.0), max(float(p["slot_len"]), 0.0)

        # island to ground: the body and the neck as pads in a ground cut-out, plus the fork's two inner slot walls
        # as CPW edges (a thin ground-facing edge adds capacitance, the slot's metal-free area removes none)
        c_body = est.pad_to_ground(bw, bl, clr, clr, eps, open_edges=0)
        c_neck = nl * est.cpw_c_per_um(nw, clr, eps)
        c_slot = 2 * sl * est.cpw_c_per_um(max(sw, 1.0), clr, eps) * 0.5 if sw > 0 else 0.0
        c_island = c_body + c_neck + c_slot
        # island to island: the necks facing across the gap, plus the two bodies far apart
        c_mut = est.coplanar_coupling(nw, nl, nl, gap, eps) + est.coplanar_coupling(
            bw, bl, bl, gap + 2 * nl, eps, screening=0.3
        )
        # claw: a strip beside island 2, facing it over the claw length
        cw, cl, cgp = float(p["claw_w"]), float(p["claw_len"]), float(p["claw_gap"])
        c_g = est.coplanar_coupling(cl, cw, bl, cgp, eps, screening=0.5)
        c_claw = est.cpw_line(cl, cw, clr, eps)

        formula = f"{bw:g}×{bl:g} µm body + {nw:g}×{nl:g} µm neck, fork slot {sw:g}×{sl:g}, clearance {clr:g} µm"
        frag = Fragment(
            nodes={
                "island1": {"island": f"{name}.island1"},
                "island2": {"island": f"{name}.island2"},
                "claw": {"island": f"{name}.claw"},
            },
            port_nodes={"claw": "claw", "drive": "control:drive", "squid_a": "island1", "squid_b": "island2"},
        )
        els = frag.elements
        els.append(LomElement(f"C_{name}_1", "C", ("island1", "gnd"), est.cap(c_island, "rough", formula)))
        els.append(LomElement(f"C_{name}_2", "C", ("island2", "gnd"), est.cap(c_island, "rough", formula)))
        els.append(LomElement(f"C_{name}_12", "C", ("island1", "island2"), est.cap(c_mut, "rough", formula)))
        els.append(
            LomElement(f"Cg_{name}_claw", "C", ("island2", "claw"), est.cap(c_g, "rough", "claw strip facing island 2"))
        )
        els.append(LomElement(f"Cc_{name}_claw", "C", ("claw", "gnd"), est.cap(c_claw, "rough", "claw as a CPW stub")))
        kind = "SQUID" if junction_kind(str(p.get("junction_type"))) == "SQUID" else "JJ"
        els.append(junction_element(name, "island1", "island2", inst, kind, drawn_params=p))
        lj = els[-1].value.get("Lj_nH")
        if lj:
            frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))
        frag.knobs[f"{name}.body_len"] = (round(bl * 0.6, 1), round(bl * 1.6, 1))
        frag.notes.append(f"{name}: rough capacitances (no calibration for the fork shape); run a C-matrix to replace")
        return frag


# ---- registration ----------------------------------------------------------------------------------------------------
# Cells in src/quantcore_circuits/layouts/ are registered into the KQC library automatically. A class that lives
# outside the package (this example) registers itself when the module is imported:
import quantcore_circuits.layouts as _layouts  # noqa: E402  (imports and loads the libraries first)

_layouts.register_pcell_classes([ForkTransmon])

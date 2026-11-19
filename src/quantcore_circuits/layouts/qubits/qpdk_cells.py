"""Qubits re-implemented from gdsfactory/quantum-rf-pdk (QPDK, MIT licence, © the QPDK authors): the geometry is
re-drawn here as KQC Elements in µm (QPDK was read, never imported or run).

* :class:`Flipmon` — ``qpdk/cells/transmon.py::flipmon_with_bbox`` (Li et al. 2021 vacuum-gap transmon): a circular
  two-face transmon, M1 inner disc + outer ring on the bottom chip, an M2 disc on the top chip joined to the inner
  disc by an indium bump; optionally with the ``plate_capacitor_single`` readout coupler that QPDK's
  ``flipmon_with_resonator_and_probeline`` puts outside the ring.
* :class:`Gatemon` — ``qpdk/cells/gatemon.py::gatemon`` (Riechert et al. 2025 carbon-nanotube gatemon): a pocketed
  island with a gate feed; its readout couples through :class:`~quantcore_circuits.layouts.others.qpdk_cells.
  GatemonCoupler`.

QPDK draws metal on ``M1_DRAW``/``M2_DRAW`` and etch on ``M1_ETCH``/``M2_ETCH`` and exports etch − draw; here that
difference is drawn on ``base_metal_gap_wo_grid`` of face 0 (``1t1``, PDK v2 fab 1/0) and face 1 (``2b1``, the
flip-chip top face, which PDK v2 does not export yet: ``export_fab`` warns). Indium bumps go to ``indium_bump`` of
both faces (KQC convention).
"""

from __future__ import annotations

import json
import math

from kqcircuits.elements.element import Element
from kqcircuits.junctions import junction_type_choices
from kqcircuits.pya_resolver import pya
from kqcircuits.qubits.qubit import Qubit
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.sim_gap import sim_junction_in_gap
from quantcore_circuits.layouts.qubits.xmon import _junction_params

# Gatemon process layers (QPDK CNT_CONTACT, CNT, HBN, JJ_PATCH, TOP_GATE). No fab numbers were given for them
# (decision #29): drawn at the numbers *proposed* here (600–604/0, free in the PDK map), for the lead to map in
# ``pdk``/``fab_export`` once they are confirmed.
GATEMON_LAYERS = {
    "cnt_contact": pya.LayerInfo(600, 0, "qcc_cnt_contact"),  # Nb/Au landing pads, stems and tips
    "cnt": pya.LayerInfo(601, 0, "qcc_cnt"),  # nanotube placement trace
    "hbn": pya.LayerInfo(602, 0, "qcc_hbn"),  # hBN dielectric flake
    "jj_patch": pya.LayerInfo(603, 0, "qcc_jj_patch"),  # Al reconnection patches (contact pad ↔ M1)
    "top_gate": pya.LayerInfo(604, 0, "qcc_top_gate"),  # top gate over the hBN, landing on the M1 gate feed
}


def _disk(dbu, radius, n, centre=(0.0, 0.0)) -> pya.Region:
    cx, cy = centre
    return pya.Region(
        pya.DPolygon.ellipse(pya.DBox(cx - radius, cy - radius, cx + radius, cy + radius), n).to_itype(dbu)
    )


def _rect(dbu, x0, y0, x1, y1) -> pya.Region:
    return pya.Region(pya.DBox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)).to_itype(dbu))


def _polar(r, angle_deg) -> pya.DPoint:
    a = math.radians(angle_deg)
    return pya.DPoint(r * math.cos(a), r * math.sin(a))


class Flipmon(Qubit):
    """Circular flip-chip transmon (QPDK ``flipmon_with_bbox``), optionally with its plate readout coupler.

    Re-implemented from gdsfactory/quantum-rf-pdk ``qpdk/cells/transmon.py`` (MIT); coupler from
    ``qpdk/cells/capacitor.py::plate_capacitor_single`` as placed by ``flipmon_with_resonator_and_probeline``.
    Centred at the origin. Face 0 (M1): inner disc of ``inner_circle_radius`` and a ring of centre radius
    ``outer_ring_radius`` and width ``outer_ring_width`` (QPDK ring = centre radius ± width / 2, so 80–140 µm at
    defaults), in an etched disc ``m1_etch_extension_gap`` beyond the ring. Face 1 (M2): a disc of
    ``top_circle_radius`` in an etched disc ``m2_etch_extension_gap`` larger. A ``bump_diameter`` indium bump at the
    centre joins the inner disc and the M2 disc (one island, ``port_squid_a`` side); the ring is the other island.

    Junction: ``junction_type`` (KQC/Quantcore junction cell, ``"No Squid"`` = none) placed radially across the
    disc-ring gap at ``junction_position_rotation`` degrees (QPDK: 0 = +x; the test chip uses 180), ground side on
    the ring; ``junction_params`` (dict / JSON) goes to the junction cell. QPDK's own evaporated
    ``squid_junction_long`` is not drawn (other process). Refpoints ``port_squid_a`` (disc edge) / ``port_squid_b``
    (ring edge), ``junction``, and QPDK's placement ports ``inner_ring_near_junction``, ``outer_ring_near_junction``,
    ``outer_ring_outside`` (all at +x, as in QPDK).

    Coupler (``with_coupler``): a ``coupler_width`` (radial) × ``coupler_length`` plate centred ``coupler_offset``
    beyond the ring's outer edge at +x, in a ``coupler_etch_margin`` etch box, with a CPW (``a``/``b``) lead to port
    ``coupler`` on the M1 etch edge (facing +x). QPDK's plate port ``o1`` is ``coupler_etch_margin`` beyond the plate,
    inside the etched disc; here the lead continues to the etch edge (13 µm further at defaults) so that a route
    starting at ``coupler`` is a CPW on ground — subtract that from QPDK's route length.
    """

    inner_circle_radius = Param(pdt.TypeDouble, "Inner disc radius (M1)", 60, unit="μm")
    outer_ring_radius = Param(pdt.TypeDouble, "Outer ring centre radius (M1)", 110, unit="μm")
    outer_ring_width = Param(pdt.TypeDouble, "Outer ring width (M1)", 60, unit="μm")
    top_circle_radius = Param(pdt.TypeDouble, "Top disc radius (M2, face 1)", 110, unit="μm")
    bump_diameter = Param(pdt.TypeDouble, "Indium bump diameter", 15, unit="μm")
    m1_etch_extension_gap = Param(pdt.TypeDouble, "M1 etch radius beyond the ring", 30, unit="μm")
    m2_etch_extension_gap = Param(pdt.TypeDouble, "M2 etch radius beyond the top disc", 40, unit="μm")
    junction_position_rotation = Param(pdt.TypeDouble, "Junction angle around the centre", 0, unit="°")
    junction_params = Param(pdt.TypeString, "Junction cell parameters (JSON dict)", "{}")
    with_coupler = Param(pdt.TypeBoolean, "Draw the plate readout coupler and its port", True)
    coupler_width = Param(pdt.TypeDouble, "Coupler plate radial width", 10, unit="μm")
    coupler_length = Param(pdt.TypeDouble, "Coupler plate length (tangential)", 58, unit="μm")
    coupler_offset = Param(pdt.TypeDouble, "Coupler plate centre beyond the ring's outer edge", 10, unit="μm")
    coupler_etch_margin = Param(pdt.TypeDouble, "Etch margin around the plate", 2, unit="μm")
    n = Param(pdt.TypeInt, "Number of points on a full circle", 144)
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
        """design.json params → PCell params: ``junction_params`` dict → JSON. Unknown parameters raise."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"Flipmon: unknown parameter(s) {unknown}")
        if isinstance(params.get("junction_params"), dict):
            params["junction_params"] = json.dumps(params["junction_params"], sort_keys=True)
        return params

    def _radii(self):
        ring_in = self.outer_ring_radius - self.outer_ring_width / 2
        ring_out = self.outer_ring_radius + self.outer_ring_width / 2
        return ring_in, ring_out, ring_out + self.m1_etch_extension_gap

    def build(self):
        dbu, n = self.layout.dbu, int(self.n)
        ring_in, ring_out, r_etch1 = self._radii()
        if not 0 < self.inner_circle_radius < ring_in:
            self.raise_error_on_cell(
                "Flipmon: the inner disc must end inside the ring (inner_circle_radius < "
                "outer_ring_radius - outer_ring_width / 2)"
            )
        metal1 = _disk(dbu, self.inner_circle_radius, n) + (_disk(dbu, ring_out, n) - _disk(dbu, ring_in, n))
        etch1 = _disk(dbu, r_etch1, n)
        if self.with_coupler:
            rc = ring_out + self.coupler_offset
            w, ln, m = self.coupler_width, self.coupler_length, self.coupler_etch_margin
            if rc - w / 2 <= ring_out or self.a > ln:
                self.raise_error_on_cell("Flipmon: the coupler plate must clear the ring and be at least a long")
            metal1 += _rect(dbu, rc - w / 2, -ln / 2, rc + w / 2, ln / 2)
            etch1 += _rect(dbu, rc - w / 2 - m, -ln / 2 - m, rc + w / 2 + m, ln / 2 + m)
            r_port = max(r_etch1, rc + w / 2 + m)
            metal1 += _rect(dbu, rc + w / 2, -self.a / 2, r_port, self.a / 2)
            etch1 += _rect(dbu, rc + w / 2, -self.a / 2 - self.b, r_port, self.a / 2 + self.b)
            self.add_port("coupler", pya.DPoint(r_port, 0), pya.DVector(1, 0))
        gap1 = (etch1 - metal1).merged()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid", 0)).insert(gap1)
        self.add_protection(pya.Region(gap1.bbox()).sized(self.margin / dbu), 0)

        metal2 = _disk(dbu, self.top_circle_radius, n)
        gap2 = _disk(dbu, self.top_circle_radius + self.m2_etch_extension_gap, n) - metal2
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid", 1)).insert(gap2)
        self.add_protection(pya.Region(gap2.bbox()).sized(self.margin / dbu), 1)
        bump = _disk(dbu, self.bump_diameter / 2, n)
        for face in (0, 1):
            self.cell.shapes(self.get_layer("indium_bump", face)).insert(bump)

        theta = self.junction_position_rotation
        self.refpoints["junction"] = _polar((self.inner_circle_radius + ring_in) / 2, theta)
        self.refpoints["port_squid_a"] = _polar(self.inner_circle_radius, theta)
        self.refpoints["port_squid_b"] = _polar(ring_in, theta)
        if self.junction_type != "No Squid":
            gap = ring_in - self.inner_circle_radius
            trans = pya.DCplxTrans(1, theta + 90, False, pya.DVector(_polar(ring_in, theta)))
            sim = {}
            if self.junction_type == "Sim":  # simulation stand-in: pads into disc and ring, port in the gap
                shift, sim = sim_junction_in_gap(gap)
                trans = trans * pya.DCplxTrans(1, 0, False, 0, -shift)
            params = {"junction_total_length": gap, "window_height": gap, **sim,
                      **_junction_params(self.junction_params)}
            refs = self.produce_squid(trans, **params)
            squid_trans = trans * pya.DTrans.M90 if self.mirror_squid else trans
            for ref in ("port_squid_a", "port_squid_b"):
                if ref in refs:
                    self.refpoints[ref] = squid_trans * refs[ref]
        self.refpoints["bump"] = pya.DPoint(0, 0)
        self.refpoints["inner_ring_near_junction"] = pya.DPoint(self.inner_circle_radius / 2, 0)
        self.refpoints["outer_ring_near_junction"] = pya.DPoint(ring_in, 0)
        self.refpoints["outer_ring_outside"] = pya.DPoint(ring_out, 0)


class Gatemon(Element):
    """Carbon-nanotube gatemon island in an etched pocket with a gate feed (QPDK ``gatemon``), M1 only.

    Re-implemented from gdsfactory/quantum-rf-pdk ``qpdk/cells/gatemon.py`` (MIT), same parameters and checks,
    island centred at the origin with the readout side at +y. Drawn (M1): the ``island_size`` island, the pocket
    (``pocket_gap`` to the side walls, ``pocket_gap_top`` above, down to 0.2 × electrode height below the lower
    contact pad), the M1 gate feed with its landing beside the hBN, and a ``gate_length`` CPW (``a``/``b``) out of
    the pocket to port ``gate`` (faces −y). Port ``readout`` is the island's top edge (faces +y, a = island width,
    b = ``pocket_gap_top``): snap it to a :class:`GatemonCoupler` ``qubit`` port.

    Process layers (``draw_process_layers``, on by default; :data:`GATEMON_LAYERS`, proposed fab 600–604/0, not
    yet in the PDK map — design decision #29): the Nb/Au contacts (two ``electrode_size`` pads centred at
    ``electrode_offset``, the upper one 0.85 × its height under the island, the lower one 0.8 × under the ground;
    ``lead_width`` stems down / up to the weak link and branches to ``junction_x``, tips ``junction_length`` apart),
    the nanotube (``junction_width`` × (``junction_length`` + 2 · ``nanotube_contact_overlap``) across the tips),
    the hBN flake (``hbn_size`` from ``hbn_left``, centred on the weak link), the Al reconnection patches
    (``size_patch`` on each pad's overlap with the M1) and the top gate (``gate_tip_width`` strip from the weak link
    over the hBN onto the M1 gate landing, ``gate_tip_gap`` of overlap). These are re-drawn from QPDK's derived
    coordinates (the QPDK source was not available locally for an XOR check). Refpoints: ``junction`` (the weak
    link), ``contact_island`` / ``contact_ground`` (pad centres), ``hbn`` (flake centre). The weak link joins the
    island to ground: ``port_squid_a`` is the island edge above the contact stems, ``port_squid_b`` the pocket's
    ground edge below them (the M1 terminals of the contacts).
    """

    island_size = Param(pdt.TypeList, "Island (width, height)", [150, 150], unit="[μm, μm]")
    pocket_gap = Param(pdt.TypeDouble, "Island to pocket side walls", 60, unit="μm")
    pocket_gap_top = Param(pdt.TypeDouble, "Island to the readout side of the pocket", 40, unit="μm")
    electrode_size = Param(pdt.TypeList, "Nb/Au landing pad (width, height)", [60, 60], unit="[μm, μm]")
    electrode_spacing = Param(pdt.TypeDouble, "Gap between the landing pads", 100, unit="μm")
    lead_width = Param(pdt.TypeDouble, "Contact stem width", 2, unit="μm")
    junction_length = Param(pdt.TypeDouble, "Gap between the contact tips", 1, unit="μm")
    junction_width = Param(pdt.TypeDouble, "Nanotube placement width", 0.002, unit="μm")
    junction_offset = Param(pdt.TypeDouble, "Stems to weak link (x)", 20, unit="μm")
    nanotube_contact_overlap = Param(pdt.TypeDouble, "Tube overlap onto each contact", 0.5, unit="μm")
    hbn_size = Param(pdt.TypeList, "hBN footprint (width, height)", [80, 80], unit="[μm, μm]")
    size_patch = Param(pdt.TypeList, "Al reconnection patch (width, height)", [60, 50], unit="[μm, μm]")
    electrode_offset = Param(pdt.TypeDouble, "Contact stems x relative to the island", -40, unit="μm")
    gate_offset = Param(pdt.TypeDouble, "Stems to the M1 gate feed (x)", 100, unit="μm")
    gate_tip_width = Param(pdt.TypeDouble, "Top-gate tip width", 16, unit="μm")
    gate_tip_gap = Param(pdt.TypeDouble, "hBN to M1 gate landing clearance", 5, unit="μm")
    gate_length = Param(pdt.TypeDouble, "M1 gate CPW beyond the pocket", 50, unit="μm")
    draw_process_layers = Param(
        pdt.TypeBoolean, "Draw contacts, nanotube, hBN, patches and top gate (proposed fab 600–604/0)", True
    )

    qcc_category = "qubit"

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """``readout`` is the island edge (a reference plane for the coupler), not a CPW end."""
        size = list(params.get("island_size") or [150, 150])
        return {"readout": (float(size[0]), float(params.get("pocket_gap_top", 40)))}

    def _geometry(self) -> dict:
        """QPDK's derived coordinates (µm), after its checks; raises ValueError like QPDK."""
        iw, ih = (float(v) for v in self.island_size)
        ew, eh = (float(v) for v in self.electrode_size)
        hw, hh = (float(v) for v in self.hbn_size)
        pw, ph = (float(v) for v in self.size_patch)
        a, b = self.a, self.b
        dims = (
            iw,
            ih,
            self.pocket_gap,
            self.pocket_gap_top,
            ew,
            eh,
            self.electrode_spacing,
            self.lead_width,
            self.junction_length,
            self.junction_width,
            self.junction_offset,
            self.nanotube_contact_overlap,
            hw,
            hh,
            pw,
            ph,
            self.gate_tip_width,
            self.gate_tip_gap,
            self.gate_length,
        )
        if min(dims) <= 0:
            raise ValueError("Gatemon dimensions must be positive")
        if self.junction_width < 2 * self.layout.dbu:
            raise ValueError("Nanotube placement width must span at least two database units")
        if self.junction_width > self.lead_width or self.nanotube_contact_overlap > self.lead_width:
            raise ValueError("Nanotube trace and overlap must fit on the contact tips")
        if self.junction_length + 2 * self.lead_width >= self.electrode_spacing:
            raise ValueError("The contact branches must fit between the electrode pads")
        if self.lead_width > ew or pw > ew or ph > 0.85 * eh:
            raise ValueError("Contact leads and reconnection patches must fit the electrodes")
        if abs(self.electrode_offset) + ew / 2 > iw / 2:
            raise ValueError("The junction electrodes must lie under the island")
        pocket_half = iw / 2 + self.pocket_gap
        gate_x = self.electrode_offset + self.gate_offset
        junction_x = self.electrode_offset + self.junction_offset
        gate_half_extent = max(self.gate_tip_width / 2, a / 2 + b)
        if self.gate_offset - a / 2 <= ew / 2:
            raise ValueError("The gate line overlaps the junction electrodes")
        if gate_x + gate_half_extent >= pocket_half:
            raise ValueError("The gate line is outside the pocket")
        upper_bottom = -ih / 2 - 0.15 * eh
        lower_top = upper_bottom - self.electrode_spacing
        pocket_bottom = lower_top - 0.2 * eh
        junction_y = (upper_bottom + lower_top) / 2
        stem_right = self.electrode_offset + self.lead_width / 2
        gate_tip_left = junction_x - self.gate_tip_width / 2
        if gate_tip_left <= stem_right:
            raise ValueError("The gate tip must clear the left contact stems")
        hbn_left = (stem_right + gate_tip_left) / 2
        gate_landing_x = hbn_left + hw + self.gate_tip_gap
        if gate_landing_x >= gate_x - a / 2:
            raise ValueError("The hBN footprint and gate landing must fit before the gate line")
        if hbn_left <= -pocket_half:
            raise ValueError("The hBN footprint is outside the pocket")
        if junction_y - hh / 2 <= pocket_bottom or junction_y + hh / 2 >= -ih / 2:
            raise ValueError("The hBN footprint must fit between island and ground")
        return {
            "iw": iw,
            "ih": ih,
            "eh": eh,
            "hw": hw,
            "pocket_half": pocket_half,
            "gate_x": gate_x,
            "junction_x": junction_x,
            "junction_y": junction_y,
            "upper_bottom": upper_bottom,
            "lower_top": lower_top,
            "pocket_bottom": pocket_bottom,
            "hbn_left": hbn_left,
            "gate_landing_x": gate_landing_x,
        }

    def build(self):
        try:
            g = self._geometry()
        except ValueError as e:
            self.raise_error_on_cell(f"Gatemon: {e}")
        dbu, a, b = self.layout.dbu, self.a, self.b
        iw, ih, gx = g["iw"], g["ih"], g["gate_x"]
        metal = _rect(dbu, -iw / 2, -ih / 2, iw / 2, ih / 2)
        metal += _rect(dbu, gx - a / 2, g["pocket_bottom"], gx + a / 2, g["junction_y"] + self.gate_tip_width / 2)
        metal += _rect(
            dbu,
            g["gate_landing_x"],
            g["junction_y"] - self.gate_tip_width / 2,
            gx + a / 2,
            g["junction_y"] + self.gate_tip_width / 2,
        )
        pocket = _rect(dbu, -g["pocket_half"], g["pocket_bottom"], g["pocket_half"], ih / 2 + self.pocket_gap_top)
        y_end = g["pocket_bottom"] - self.gate_length
        gate_cpw = _rect(dbu, gx - a / 2 - b, y_end, gx + a / 2 + b, g["pocket_bottom"]) - _rect(
            dbu, gx - a / 2, y_end, gx + a / 2, g["pocket_bottom"]
        )
        gaps = ((pocket - metal) + gate_cpw).merged()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gaps)
        self.add_protection(pya.Region(gaps.bbox()).sized(self.margin / dbu))
        self.add_port("readout", pya.DPoint(0, ih / 2), pya.DVector(0, 1))
        self.add_port("gate", pya.DPoint(gx, y_end), pya.DVector(0, -1))
        self.refpoints["junction"] = pya.DPoint(g["junction_x"], g["junction_y"])
        self.refpoints["contact_island"] = pya.DPoint(self.electrode_offset, g["upper_bottom"] + g["eh"] / 2)
        self.refpoints["contact_ground"] = pya.DPoint(self.electrode_offset, g["lower_top"] - g["eh"] / 2)
        self.refpoints["hbn"] = pya.DPoint(g["hbn_left"] + g["hw"] / 2, g["junction_y"])
        self.refpoints["port_squid_a"] = pya.DPoint(self.electrode_offset, -ih / 2)
        self.refpoints["port_squid_b"] = pya.DPoint(self.electrode_offset, g["pocket_bottom"])
        if self.draw_process_layers:
            for name, region in self._process_layers(g).items():
                self.cell.shapes(self.layout.layer(GATEMON_LAYERS[name])).insert(region.merged())

    def _process_layers(self, g: dict) -> dict:
        """The gatemon's non-M1 layers (dbu regions), from QPDK's derived coordinates ``g``."""
        dbu, lw, jl = self.layout.dbu, self.lead_width, self.junction_length
        ew, eh = (float(v) for v in self.electrode_size)
        pw, ph = (float(v) for v in self.size_patch)
        hw, hh = (float(v) for v in self.hbn_size)
        ex, jx, jy = self.electrode_offset, g["junction_x"], g["junction_y"]
        ub, lt = g["upper_bottom"], g["lower_top"]
        y_up, y_lo = jy + jl / 2 + lw / 2, jy - jl / 2 - lw / 2  # branch centre lines (tips jl apart)
        contacts = _rect(dbu, ex - ew / 2, ub, ex + ew / 2, ub + eh) + _rect(dbu, ex - ew / 2, lt - eh, ex + ew / 2, lt)
        contacts += _rect(dbu, ex - lw / 2, y_up - lw / 2, ex + lw / 2, ub)  # stems
        contacts += _rect(dbu, ex - lw / 2, lt, ex + lw / 2, y_lo + lw / 2)
        contacts += _rect(dbu, ex - lw / 2, y_up - lw / 2, jx + lw / 2, y_up + lw / 2)  # branches to the tips
        contacts += _rect(dbu, ex - lw / 2, y_lo - lw / 2, jx + lw / 2, y_lo + lw / 2)
        ov, tw = self.nanotube_contact_overlap, max(self.junction_width, 2 * dbu)
        cnt = _rect(dbu, jx - tw / 2, jy - jl / 2 - ov, jx + tw / 2, jy + jl / 2 + ov)
        hbn = _rect(dbu, g["hbn_left"], jy - hh / 2, g["hbn_left"] + hw, jy + hh / 2)
        # patches on the pads' far ends (over the island / the ground; QPDK allows ph ≤ 0.85 · eh)
        patch = _rect(dbu, ex - pw / 2, ub + eh - ph, ex + pw / 2, ub + eh)
        patch += _rect(dbu, ex - pw / 2, lt - eh, ex + pw / 2, lt - eh + ph)
        gt = self.gate_tip_width
        top_gate = _rect(dbu, jx - gt / 2, jy - gt / 2, g["gate_landing_x"] + self.gate_tip_gap, jy + gt / 2)
        return {"cnt_contact": contacts, "cnt": cnt, "hbn": hbn, "jj_patch": patch, "top_gate": top_gate}

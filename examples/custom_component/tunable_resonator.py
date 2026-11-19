"""A custom component: a lambda/4 CPW resonator, shorted to ground through a SQUID array (a flux-tunable resonator).

    pin a (open end, coupled to a feedline) ~~~ meandered CPW ~~~ island ─[SQUID]─ island ─[SQUID]─ ... ─ ground
                                                                                  pin flux (a short-circuited line)

The line is a meander of a chosen total length. At its far end the centre conductor continues into a chain of
``n_squids`` islands; each gap between two islands holds one Quantcore SQUID (two trilayer junctions, drawn by
:class:`~quantcore_circuits.layouts.junctions.trilayer.QuantcoreSquid`), the last one lands on the ground plane. A
flux line ends next to the array (pin ``flux``). A route from pin ``a`` to a feedline hanger finishes the resonator.

Copy this file into ``src/quantcore_circuits/layouts/others/`` (or keep it here and use the dotted reference
``custom_component.tunable_resonator.TunableResonator``). Guide: docs/library/custom-components/tunable-resonator.md.
"""

from __future__ import annotations

import math

from kqcircuits.elements.element import Element
from kqcircuits.elements.waveguide_coplanar import WaveguideCoplanar
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.trilayer import QuantcoreSquid
from quantcore_circuits.lom.fragment import Fragment, Line, cell_params, effective_junction, register_lom

ISLAND_WIDTH = 36.0  # the array islands are wider than the SQUID window (32 um)
POCKET_SIDE = 10.0  # ground clearance beside the islands
SQUID_GAP = 20.0  # window height of the SQUID = the gap each SQUID spans (QuantcoreSquid default)


def run_length(length: float, runs: int, pitch: float, r: float, lead: float) -> float:
    """Length of one straight run of a meander of ``runs`` runs whose total centre-line length is ``length``.

    The meander is a zig-zag of ``runs`` runs joined by ``runs - 1`` pairs of corners of radius ``r``; a rounded corner
    is shorter than the sharp one by (2 - pi/2) r. ``lead`` is the straight piece after the last run."""
    corners = 2 * (runs - 1)
    return (length - lead - (runs - 1) * pitch + corners * (2 - math.pi / 2) * r) / runs


def vertical_geometry(runs: int, pitch: float) -> float:
    """y of the last run (and of the SQUID array): the meander climbs by ``pitch`` per run."""
    return (runs - 1) * pitch


def equivalent_length_um(l_array_nH: float, length_um: float, a_um: float, b_um: float, pdk_name: str) -> float:
    """Extra line length that a series inductance at the shorted end adds to a lambda/4 line (exact, one mode).

    A line of length ``length_um`` open at one end and closed by an inductance L at the other resonates where
    tan(beta l) = Z0 / (omega L). The same frequency is that of a plain lambda/4 line of length l + l_eq, so the LOM
    (which models the line as a lambda/4 line) gets l_eq as extra length. Z0 and the phase velocity come from the PDK
    (kinetic inductance included)."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel

    if l_array_nH <= 0 or length_um <= 0:
        return 0.0
    f = 5.0
    for _ in range(4):  # the CPW values depend weakly on frequency
        props = cpw_properties(f, a_um, b_um, pdk_name)
        vp, z0 = props["vp_m_s"], props["Z0_ohm"]
        lo, hi = 1e-3, vp / (4 * length_um * 1e-6) / 1e9  # GHz; hi is the lambda/4 frequency of the bare line
        for _ in range(80):
            mid = (lo + hi) / 2
            w = 2 * math.pi * mid * 1e9
            if math.tan(w * length_um * 1e-6 / vp) < z0 / (w * l_array_nH * 1e-9):
                lo = mid
            else:
                hi = mid
        f = (lo + hi) / 2
    return vp / (4 * f * 1e9) * 1e6 - length_um


class TunableResonator(Element):
    """Lambda/4 CPW resonator with a SQUID array at its shorted end; pins ``a`` (open end) and ``flux``."""

    qcc_category = "resonator"

    length = Param(pdt.TypeDouble, "CPW length from pin a to the array", 1400.0, unit="μm")
    runs = Param(pdt.TypeInt, "Straight runs of the meander (odd)", 5)
    pitch = Param(pdt.TypeDouble, "Distance between two runs", 80.0, unit="μm")
    bend_radius = Param(pdt.TypeDouble, "Corner radius of the meander", 20.0, unit="μm")
    lead = Param(pdt.TypeDouble, "Straight piece between the last run and the array", 40.0, unit="μm")
    n_squids = Param(pdt.TypeInt, "SQUIDs in the array (in series)", 2)
    lj_nH = Param(pdt.TypeDouble, "L_J0 of each SQUID (0 = the PDK nominal SQUID)", 1.0, unit="nH")
    island_length = Param(pdt.TypeDouble, "Length of an island between two SQUIDs", 30.0, unit="μm")
    flux_length = Param(pdt.TypeDouble, "Length of the flux line from its pin to the array", 150.0, unit="μm")
    flux_gap = Param(pdt.TypeDouble, "Distance from the pocket to the short of the flux line", 10.0, unit="μm")
    route_um = Param(
        pdt.TypeDouble,
        "Length of the route from pin a to the feedline (the LOM reads it for the array correction only)",
        0.0,
        unit="μm",
    )

    def build(self):
        dbu = self.layout.dbu
        n = int(self.runs)
        if n % 2 == 0 or n < 1:
            self.raise_error_on_cell("runs must be odd: the meander has to end on the side of the array")
        run = run_length(self.length, n, self.pitch, self.bend_radius, self.lead)
        if run < 2 * self.bend_radius + 10 or self.pitch < 2 * self.bend_radius + self.a + 2 * self.b:
            self.raise_error_on_cell("the meander does not fit: raise length, lower runs or bend_radius, raise pitch")

        # 1. the CPW meander (WaveguideCoplanar rounds the corners and draws the two gaps)
        pts = [pya.DPoint(0, 0)]
        for i in range(n):
            y = i * self.pitch
            x_to = run if i % 2 == 0 else 0.0
            if i > 0:
                pts.append(pya.DPoint(0.0 if i % 2 == 0 else run, y))
            pts.append(pya.DPoint(x_to, y))
        x_e = run + self.lead
        y_arr = vertical_geometry(n, self.pitch)
        pts.append(pya.DPoint(x_e, y_arr))
        self.insert_cell(WaveguideCoplanar, path=pya.DPath(pts, 0), a=self.a, b=self.b, r=self.bend_radius)

        # 2. the array: islands joined by SQUIDs; the pocket is the ground cut-out around the chain
        h = SQUID_GAP
        step = self.island_length + h
        x_end = x_e + self.n_squids * step
        half = ISLAND_WIDTH / 2 + POCKET_SIDE
        pocket = pya.Region(pya.DBox(x_e, y_arr - half, x_end, y_arr + half).to_itype(dbu))
        islands = pya.Region()
        for j in range(self.n_squids):
            x0 = x_e + j * step
            islands.insert(
                pya.DBox(x0, y_arr - ISLAND_WIDTH / 2, x0 + self.island_length, y_arr + ISLAND_WIDTH / 2).to_itype(dbu)
            )
        # the first island is the end of the centre conductor; the clearer metal of each SQUID closes its gap
        etch = pocket - islands
        for j in range(self.n_squids):
            x_slot_end = x_e + (j + 1) * step  # ground side of SQUID j (the next island, or the ground plane)
            squid_trans = pya.DCplxTrans(1, 90, False, x_slot_end, y_arr)
            self.insert_cell(
                QuantcoreSquid, squid_trans, inst_name=f"squid_{j + 1}", window_height=h, lj_nH=self.lj_nH
            )

        # 3. the flux line: a CPW that ends in a short, ``flux_gap`` below the pocket
        x_f = x_e + (x_end - x_e) / 2
        y_short = y_arr - half - self.flux_gap
        y_pin = y_short - self.flux_length
        for sign in (-1, 1):
            x_in = x_f + sign * self.a / 2
            x_out = x_f + sign * (self.a / 2 + self.b)
            etch.insert(pya.DBox(min(x_in, x_out), y_pin, max(x_in, x_out), y_short).to_itype(dbu))
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch.merged())
        self.add_protection(pya.Region(etch.bbox()).sized(round(self.margin / dbu)))
        self.add_port("a", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.add_port("flux", pya.DPoint(x_f, y_pin), pya.DVector(0, -1))


# ---- the LOM model --------------------------------------------------------------------------------------------------
@register_lom("TunableResonator")
def tunable_resonator_lom(name: str, inst, pdk) -> Fragment:
    """A lambda/4 line from pin ``a`` (open) to the array (short), plus the flux-dependent inductance of the array.

    The array is N SQUIDs in series: L_array(Phi) = N * L_J0 / sqrt(cos^2(pi Phi) + d^2 sin^2(pi Phi)) with L_J0 the
    two junctions of one SQUID in parallel and d the asymmetry (``squid_l_eff``; d = 0 gives L_J0 / |cos(pi Phi)|, i.e.
    N * L_J / (2 |cos(pi Phi)|) with L_J of one junction). Phi and d are the instance's ``junction`` values
    (``flux_phi0``, ``asym``), L_J0 its ``junction.Lj_nH`` or else the drawn trilayer SQUID. An inductance at the
    shorted end of a lambda/4 line lowers its frequency exactly like extra line, so the model adds that equivalent
    length (:func:`equivalent_length_um`) to the line. The SQUID capacitances (about 100 fF each at 1 nH) are not
    modelled: in series, at 6 GHz, they are far above the array's reactance.
    """
    p = cell_params(inst)
    a_um, b_um = float(p.get("a", pdk.cpw_a)), float(p.get("b", pdk.cpw_b))
    each = {"junction_type": "Quantcore Squid", "junction_params": {"lj_nH": float(p["lj_nH"])} if p["lj_nH"] else {}}
    ej = effective_junction(inst, each, pdk, kind="SQUID")
    n_sq = int(p["n_squids"])
    l_array = n_sq * ej.lj_eff_nH
    geometric = float(p["length"])
    extra = equivalent_length_um(l_array, geometric + float(p["route_um"]), a_um, b_um, pdk.name)
    frag = Fragment(nodes={"res": {"island": f"{name}.res"}}, port_nodes={"a": "res", "flux": "control:flux"})
    frag.lines.append(
        Line(name, "res", ("a", None), geometric + extra, a_um, b_um, ("open", "short"), True, knob=f"{name}.length")
    )
    frag.knobs[f"{name}.length"] = (round(geometric * 0.8, 1), round(geometric * 1.25, 1))
    frag.notes.append(
        f"{name}: {n_sq} SQUIDs, L_array {l_array:.3g} nH at Phi = {ej.flux_phi0:g} Phi0 "
        f"(L_J0 {ej.lj0_nH:.3g} nH each) "
        f"= {extra:.0f} um of extra line at the shorted end"
    )
    return frag

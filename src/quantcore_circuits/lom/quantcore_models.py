"""LOM models for Quantcore cells ported from the legacy QWri library and the CPW-E drawing library.

Same conventions as :mod:`.kqc_models` (estimates labelled ``analytic`` / ``rough``, see :mod:`.estimates`; FEM
replaces capacitances by island name ``<inst>.<node>``).

=============================================  ====================================================================
cell                                           lumped model
=============================================  ====================================================================
TwoPadTransmon (legacy ``Transmon``)           floating: island1 (``left`` pad + lead), island2 (``right``), C to
                                               ground each, C between, JJ between (``squid_a``/``squid_b`` = the
                                               junction ends)
PadCoupler (legacy ``Coupler``)                series gap capacitor: π network between ``left`` and ``right``
ConnectorPad, CpweBondPad                      50 Ω port (like BondPad)
TaperedPad                                     probe pad: C to ground (DC test structure)
CpwSegment                                     a line between ``a`` and ``b`` (wire when both are connected)
CoupledResonator, QubitResonator               λ/4 line: shorted start (refpoint ``short_end``) → port ``end``;
                                               its coupler section next to a separate feedline is a ``hanger``
                                               (declare ``d.couple("K_R1", "R1", "<feedline instance>")``)
CpwResonator                                   resonator line between ``start`` and ``end`` (both grounded when free)
CoupledConnector                               line ``start`` (shorted) → ``end``: λ/4 when ``end`` meets a capacitor
CpweQuarterWaveResonator                       λ/4 line, no ports: open coupler arm → shorted end; the arm next to
                                               a feedline is a ``hanger`` at the open end (declared coupling)
CpweFingerCapacitor, CpweGapCapacitor          π network between ``a`` and ``b``
CpweFingerLine                                 a wire with the fingers' shunt C to ground
CpweTaper                                      a pass-through section of the line it joins (``Line.through``)
CpweOpenEnd                                    zero-length open end: a route into it is an open-ended resonator
NeckTermination (QPDK)                         shorted end via taper + neck: the routed line's last section, at its
                                               inductive equivalent length (``Line.through``, rough)
CpweMeanderLine                                resonator line between ``a`` and ``b`` (like KQC ``Meander``)
SpiralLine (legacy ``draw.spiral``)            resonator line ``a`` → ``b`` of the drawn length (open ends when free;
                                               gap = mean turn spacing, rough; kinetic inductance as a CPW)
FluxHoleArray, FluxHoles                       ground perforation: no circuit elements
WaveguideCoplanarStraight (KQC)                bare CPW segment without ports: no circuit elements
=============================================  ====================================================================

Line lengths are the drawn centre lines (the cells' own point functions), so they include tails and necks.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from quantcore_circuits.lom import estimates as est
from quantcore_circuits.lom.fragment import (
    Element,
    Fragment,
    Line,
    cell_params,
    junction_element,
    junction_kind,
    port_resistor,
    register_lom,
)


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float(default)


def _C(frag: Fragment, name: str, a: str, b: str, value: dict, knob: str | None = None) -> None:
    frag.elements.append(Element(name, "C", (a, b), value, {"param": knob} if knob else None))


def _knob(frag: Fragment, param: str, value: float) -> None:
    frag.knobs[param] = (round(value * 0.8, 1), round(value * 1.25, 1))


# ---- qubits and couplers ------------------------------------------------------------------------------------------
def _two_pad_caps(p: dict, eps: float) -> tuple[float, float, str]:
    """(C pad → ground, C pad ↔ pad, formula) of the legacy two-pad drawing: the pads face each other across ``gap``
    along their ``pad_height`` edges; ``pad_thickness`` is their extent along the axis, the lead length the clearance
    behind them and ``pocket_margin`` the clearance above/below (no pocket: the surrounding gap is unknown, 50 µm)."""
    h, t = _f(p.get("pad_height"), 30), _f(p.get("pad_thickness"), 20)
    gap = _f(p.get("gap"), 10)
    gap = 1.0 if gap <= 0 else gap
    margin = _f(p.get("pocket_margin"), 20)
    side = margin if margin > 0 else 50.0
    back = max(_f(p.get("lead_length"), 10), 1.0)
    cg, cm = est.two_pads(h, t, gap, side, back, eps)
    return cg, cm, f"two {t:g}×{h:g} µm pads across {gap:g} µm in a {side:g} µm pocket (coupled strips + CPW)"


@register_lom("TwoPadTransmon")
def two_pad_transmon_lom(name: str, inst, pdk) -> Fragment:
    """Legacy two-pad transmon: floating, island1 = ``left`` pad, island2 = ``right`` pad, JJ across the gap.

    The pads alone are small (a few fF): the qubit's C_Σ comes from whatever the leads connect to, so run a C-matrix
    of the assembled qubit to replace these values.
    """
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    cg, cm, formula = _two_pad_caps(p, eps)
    frag = Fragment(
        nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}},
        port_nodes={"left": "island1", "right": "island2", "squid_a": "island1", "squid_b": "island2"},
    )
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(cg, "analytic", formula), f"{name}.pad_height")
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(cg, "analytic", formula), f"{name}.pad_height")
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(cm, "analytic", formula), f"{name}.gap")
    jtype = str(p.get("junction_type") or "No Squid")
    kind = "SQUID" if junction_kind(jtype) == "SQUID" else "JJ"  # "No Squid" (legacy): a JJ is assumed
    frag.elements.append(junction_element(name, "island1", "island2", inst, kind, drawn_params=p))
    if jtype in ("No Squid", "Sim"):
        frag.notes.append(f"{name}: no junction drawn (junction_type {jtype!r}); a JJ across the gap is assumed")
    lj = frag.elements[-1].value.get("Lj_nH")
    if lj:
        frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))
    else:
        frag.notes.append(f"{name}: no junction.Lj_nH in the design; the qubit mode needs one to simulate")
    frag.notes.append(f"{name}: two-pad transmon pads only ({cg + cm:.2g} fF); the leads' loads set C_Σ")
    return frag


@register_lom("PadCoupler")
def pad_coupler_lom(name: str, inst, pdk) -> Fragment:
    """Legacy gap coupler (two facing pads): series C between ``left`` and ``right``, C to ground at each."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    cg, cm, formula = _two_pad_caps(p, eps)
    frag = Fragment(
        nodes={"left": {"island": f"{name}.left"}, "right": {"island": f"{name}.right"}},
        port_nodes={"left": "left", "right": "right"},
    )
    _C(frag, f"C_{name}", "left", "right", est.cap(cm, "analytic", formula), f"{name}.gap")
    _C(frag, f"C_{name}_left", "left", "gnd", est.cap(cg, "analytic", formula))
    _C(frag, f"C_{name}_right", "right", "gnd", est.cap(cg, "analytic", formula))
    return frag


# ---- QPDK / SQDMetal re-implementations (layouts/*/qpdk_cells.py, sqdmetal_cells.py) -----------------------------
EPS0_FF_PER_UM = 8.8541878128e-3  # ε0 in fF/µm
FLIP_CHIP_GAP_UM = 8.0  # KQC's default chip_distance; PDK v2 has no second face


def _qubit_junction(frag: Fragment, name: str, inst, p: dict, a: str, b: str, note: str = "", kind=None) -> None:
    """J_<name> from ``junction_type`` (``"No Squid"``: none, a note), or of ``kind``, with Lj/Cj from the design's
    ``junction``."""
    kind = kind or junction_kind(p.get("junction_type", "Manhattan"))
    if kind is None:
        frag.notes.append(f"{name}: no junction ({p.get('junction_type')!r}); the islands are not shunted")
        return
    frag.elements.append(junction_element(name, a, b, inst, kind, note, drawn_params=p))
    lj = frag.elements[-1].value.get("Lj_nH")
    if lj:
        frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))
    else:
        frag.notes.append(f"{name}: no junction.Lj_nH in the design; the qubit mode needs one to simulate")


@register_lom("Flipmon")
def flipmon_lom(name: str, inst, pdk) -> Fragment:
    """QPDK flipmon: floating; island1 = M1 ring (the coupler plate faces it), island2 = M1 disc + the M2 top disc
    (face 2b1, joined by the indium bump), junction across the disc–ring gap, plate coupler ``cplr`` at ``coupler``.

    The M2 disc is part of island2: its overlap with the M1 ring across an assumed 8 µm flip-chip vacuum gap (KQC's
    default ``chip_distance``; PDK v2 has no second face and drops 2b1) is a parallel plate C to island1, and its
    edge facing the top-face ground (``m2_etch_extension_gap``) a disc-in-a-gap C to ground (rough, both)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    r_d, r_c, w = (
        _f(p.get("inner_circle_radius"), 60),
        _f(p.get("outer_ring_radius"), 110),
        _f(p.get("outer_ring_width"), 60),
    )
    ring_in, ring_out = r_c - w / 2, r_c + w / 2
    g1 = _f(p.get("m1_etch_extension_gap"), 30)
    r_t, g2 = _f(p.get("top_circle_radius"), 110), _f(p.get("m2_etch_extension_gap"), 40)
    frag = Fragment(
        nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}},
        port_nodes={"squid_a": "island2", "squid_b": "island1"},  # disc edge / ring edge
    )
    _C(
        frag,
        f"C_{name}_1",
        "island1",
        "gnd",
        est.cap(
            est.ring_to_ground(ring_out, w, g1, eps),
            "analytic",
            f"ring {ring_in:g}–{ring_out:g} µm, outer edge as half CPW ({g1:g} µm gap)",
        ),
        f"{name}.outer_ring_radius",
    )
    _C(
        frag,
        f"C_{name}_12",
        "island1",
        "island2",
        est.cap(
            est.concentric_rings(r_d, ring_in, eps),
            "rough",
            "disc–ring facing edges as coplanar strips along the mean circumference",
        ),
        f"{name}.inner_circle_radius",
    )
    span = ring_out + g1 - r_d
    c2 = est.disk_to_ground(r_d, span, eps) * ((span - w) / span) ** 2
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c2, "rough", "M1 disc to ground screened by the ring"))
    overlap = math.pi * (min(r_t, ring_out) ** 2 - ring_in**2) if r_t > ring_in else 0.0
    if overlap > 0:
        c_flip = EPS0_FF_PER_UM * overlap / FLIP_CHIP_GAP_UM
        _C(
            frag,
            f"C_{name}_12_flip",
            "island1",
            "island2",
            est.cap(
                c_flip,
                "rough",
                f"M2 disc r {r_t:g} over the M1 ring: parallel plate, {overlap:.0f} µm² across an assumed "
                f"{FLIP_CHIP_GAP_UM:g} µm vacuum gap",
            ),
            f"{name}.top_circle_radius",
        )
    _C(
        frag,
        f"C_{name}_2_top",
        "island2",
        "gnd",
        est.cap(
            est.disk_to_ground(r_t, g2, eps),
            "rough",
            f"M2 disc r {r_t:g} in its {g2:g} µm top-face gap (single-face formula)",
        ),
    )
    _qubit_junction(frag, name, inst, p, "island1", "island2")
    if str(p.get("with_coupler", True)).lower() not in ("false", "0"):
        cw, cl = _f(p.get("coupler_width"), 10), _f(p.get("coupler_length"), 58)
        s_in = max(_f(p.get("coupler_offset"), 10) - cw / 2, 0.5)
        s_out = max(ring_out + g1 - (ring_out + s_in + cw), _f(p.get("coupler_etch_margin"), 2))
        frag.nodes["cplr"] = {"island": f"{name}.cplr"}
        frag.port_nodes["coupler"] = "cplr"
        _C(
            frag,
            f"Cg_{name}_cplr",
            "island1",
            "cplr",
            est.cap(
                est.coplanar_coupling(cl, cw, w, s_in, eps),
                "analytic",
                f"plate {cl:g}×{cw:g} µm facing the ring across {s_in:g} µm (CPS)",
            ),
            f"{name}.coupler_length",
        )
        cc = est.pad_to_ground(cl, cw, s_out, s_out, eps, open_edges=1) + est.cpw_line(s_out, 10, 6, eps)
        _C(frag, f"Cc_{name}_cplr", "cplr", "gnd", est.cap(cc, "rough", "plate in the M1 etch + its lead"))
    frag.notes.append(
        f"{name}: M2 top disc (face 2b1) counted in island2 across an assumed {FLIP_CHIP_GAP_UM:g} µm flip-chip gap "
        "(rough; PDK v2 does not fabricate face 2b1); coupler ↔ disc C neglected (screened by the ring)"
    )
    return frag


@register_lom("Gatemon")
def gatemon_lom(name: str, inst, pdk) -> Fragment:
    """QPDK gatemon: grounded island (``island_size``) in a pocket; the carbon-nanotube weak link to ground is not
    drawn and is modelled as a JJ with the design's ``junction`` values (gate-tunable Lj); ``readout`` is the island
    edge (the island node), ``gate`` a DC gate line with a small C to the island (rough)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    size = p.get("island_size") or [150, 150]
    iw, ih = _f(size[0], 150), _f(size[-1], 150)
    side, top = _f(p.get("pocket_gap"), 60), _f(p.get("pocket_gap_top"), 40)
    frag = Fragment(
        nodes={"island": {"island": f"{name}.island"}, "gate": {"island": f"{name}.gate"}},
        port_nodes={"readout": "island", "gate": "gate", "squid_a": "island", "squid_b": "gnd"},
    )
    c_is = est.pad_to_ground(iw, ih, side, (side + top) / 2, eps)
    _C(
        frag,
        f"C_{name}",
        "island",
        "gnd",
        est.cap(
            c_is, "analytic", f"{iw:g}×{ih:g} µm island in its pocket ({side:g} µm sides, {top:g} µm readout side)"
        ),
        f"{name}.island_size",
    )
    _qubit_junction(frag, name, inst, p, "island", "gnd", note="carbon-nanotube weak link (not drawn): a JJ", kind="JJ")
    frag.notes.append(f"{name}: the CNT junction is not drawn; modelled as a JJ with the design's junction values")
    _C(
        frag,
        f"Cgate_{name}",
        "island",
        "gate",
        est.cap(0.2, "rough", "M1 gate tip beside the junction, below the island (rough, ±100 %)"),
    )
    gl = _f(p.get("gate_length"), 50)
    _C(frag, f"C_{name}_gate", "gate", "gnd", est.cap(est.cpw_line(gl + side, 10, 6, eps), "rough", "gate feed CPW"))
    return frag


@register_lom("GatemonCoupler")
def gatemon_coupler_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """QPDK gatemon coupler: a straight CPW ``o1`` → ``o2`` (a line) and the cell's nominal ``coupling_capacitance``
    from the line to the node at ``qubit`` (the gatemon island it is snapped to; the snap merges ``qubit`` with
    that island, so the C links line and island, not a galvanic join)."""
    p = cell_params(inst)
    length = _f(p.get("length"), 600)
    frag = Fragment(
        nodes={"line": {"island": f"{name}.line"}, "qubit": {"island": f"{name}.qubit"}},
        port_nodes={"o1": "line", "o2": "line", "qubit": "qubit"},
    )
    frag.lines.append(
        Line(name, "line", ("o1", "o2"), length, _f(p.get("a"), 10), _f(p.get("b"), 6), ("short", "short"))
    )
    ck = _f(p.get("coupling_capacitance"), 5.4)
    _C(
        frag,
        f"Cg_{name}",
        "line",
        "qubit",
        est.cap(ck, "rough", "QPDK nominal coupling_capacitance (cell parameter)"),
        f"{name}.coupling_capacitance",
    )
    return frag


@register_lom("HyperbolicVertexCoupler")
def hyperbolic_vertex_coupler_lom(name: str, inst, pdk) -> Fragment:
    """QPDK hyperbolic-lattice vertex coupler: ``q`` pie-slice pins of a disk, port ``o<k+1>`` on pin k; C between
    neighbouring pins across the radial ``pin_gap`` and from each pin's arc to ground across ``ground_gap``
    (non-neighbour pins neglected; rough)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    q = max(int(_f(p.get("q"), 3)), 1)
    r, gap, gg = _f(p.get("pin_radius"), 40), _f(p.get("pin_gap"), 4), _f(p.get("ground_gap"), 6)
    lead = _f(p.get("lead_length"), 20)
    frag = Fragment()
    for k in range(q):
        node = f"o{k + 1}"
        frag.nodes[node] = {"island": f"{name}.{node}"}
        frag.port_nodes[node] = node
        cg = est.ring_to_ground(r, r, gg, eps) / q + est.cpw_line(lead, 10, 6, eps)
        _C(
            frag,
            f"C_{name}_{node}",
            node,
            "gnd",
            est.cap(cg, "rough", f"pin arc (1/{q} of a r {r:g} disk edge) + lead"),
        )
    slice_w = math.pi * r / q  # mean width of a pie slice
    pairs = [(k, (k + 1) % q) for k in range(q)] if q > 2 else ([(0, 1)] if q == 2 else [])
    for i, j in pairs:
        cm = est.coplanar_coupling(r, slice_w, slice_w, gap, eps)
        _C(
            frag,
            f"C_{name}_o{i + 1}_o{j + 1}",
            f"o{i + 1}",
            f"o{j + 1}",
            est.cap(cm, "rough", f"radial edges ({r:g} µm) across the {gap:g} µm pin gap (CPS)"),
            f"{name}.pin_gap",
        )
    return frag


@register_lom("TransmonTaperedInsets")
def transmon_tapered_insets_lom(name: str, inst, pdk) -> Fragment:
    """SQDMetal TransmonTaperedInsets: floating; island1 = top pad (``port_squid_a``), island2 = bottom pad; each
    connection pad is its own conductor (port ``<name>``) with a C to the qubit pad on its side (``loc_H``). Corner
    pins are placement marks: ``top_*`` → island1, ``bottom_*`` → island2 (a capacitor snapped there couples to that
    pad), pocket pins → ground. Pads as coupled strips in the pocket (round ends counted in the width; tapers,
    insets and teeth neglected: analytic)."""
    from quantcore_circuits.layouts.qubits.sqdmetal_cells import connection_pad_options  # pylint: disable=C0415
    from quantcore_circuits.layouts.qubits.xmon import _junction_params  # pylint: disable=C0415

    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    pw, ph, pg = _f(p.get("pad_width"), 800), _f(p.get("pad_height"), 110), _f(p.get("pad_gap"), 100)
    kw, kh = _f(p.get("pocket_width"), 1000), _f(p.get("pocket_height"), 800)
    lower = _f(p.get("pocket_lower_tighten"), 120)
    width = pw + ph  # with the round ends
    side = max((kw - width) / 2, 1.0)
    back_top = max(kh / 2 - pg / 2 - ph, 1.0)
    back_bot = max(kh / 2 - lower - pg / 2 - ph, 1.0)
    c1, c12 = est.two_pads(width, ph, pg, side, back_top, eps)
    c2, _ = est.two_pads(width, ph, pg, side, back_bot, eps)
    frag = Fragment(nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}})
    frag.port_nodes |= {
        "squid_a": "island1",
        "squid_b": "island2",
        "top_right_pin": "island1",
        "top_left_pin": "island1",
        "bottom_right_pin": "island2",
        "bottom_left_pin": "island2",
        "top_pocket_pin": "gnd",
        "bottom_pocket_pin": "gnd",
    }
    f = f"{width:g}×{ph:g} µm pads across {pg:g} µm in a {kw:g}×{kh:g} µm pocket (coupled strips + CPW)"
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(c1, "analytic", f), f"{name}.pad_width")
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c2, "analytic", f), f"{name}.pad_width")
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "analytic", f), f"{name}.pad_gap")
    _qubit_junction(frag, name, inst, p, "island1", "island2")
    for pname, opts in _junction_params(p.get("connection_pads") or "{}").items():
        o = connection_pad_options(pname, opts)
        node = f"cp_{pname}"
        frag.nodes[node] = {"island": f"{name}.{pname}"}
        frag.port_nodes[pname] = node
        qpad = "island1" if float(o["loc_H"]) > 0 else "island2"
        cpw_, cph, gap = float(o["pad_width"]), float(o["pad_height"]), max(float(o["pad_gap"]), 0.5)
        cg = est.coplanar_coupling(cpw_, cph, ph, gap, eps)
        wire = max(kh / 2 - ph - pg / 2 - gap - cph, 0.0) + float(o["cpw_extend"])
        cc = est.pad_to_ground(cpw_, cph, side, max(float(o["pocket_extent"]), 1.0), eps, open_edges=1) + est.cpw_line(
            wire, float(o["cpw_width"]), float(o["cpw_gap"]), eps
        )
        _C(
            frag,
            f"Cg_{name}_{pname}",
            qpad,
            node,
            est.cap(cg, "analytic", f"{cpw_:g}×{cph:g} µm connection pad facing the qubit pad across {gap:g} µm (CPS)"),
        )
        _C(frag, f"Cc_{name}_{pname}", node, "gnd", est.cap(cc, "rough", "connection pad + its CPW wire"))
    return frag


@register_lom("SmoothCapacitorSemicircle")
def smooth_capacitor_semicircle_lom(name: str, inst, pdk) -> Fragment:
    """SQDMetal semicircle capacitor: one pad (port ``a``) whose semicircular bite wraps the qubit pad at ``target``
    (a placement reference: snapped to a qubit pin, its node becomes that pad, so the C links pad and qubit pad).
    C_target: the bite's arc facing the qubit pad's round end across an assumed 5 µm gap (the concentric SQDMetal
    2_transmons geometry; rough); pad to ground across its clearances (rough)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    w, length = _f(p.get("rect_width"), 190), _f(p.get("rect_length"), 170)
    r = _f(p.get("semi_radius"), 61)
    gs, gb = _f(p.get("gap_side"), 25), _f(p.get("gap_back"), 25)
    tw, lead = _f(p.get("trace_width"), 10), _f(p.get("lead_length"), 0)
    frag = Fragment(
        nodes={"pad": {"island": f"{name}.pad"}, "target": {"island": f"{name}.target"}},
        port_nodes={"a": "pad", "target": "target"},
    )
    ct = est.coplanar_coupling(math.pi * r, max(w / 2 - r, tw), 2 * r, 5.0, eps)
    _C(
        frag,
        f"C_{name}",
        "pad",
        "target",
        est.cap(ct, "rough", f"semicircle arc {math.pi * r:.0f} µm around the qubit pad end, assumed 5 µm gap (CPS)"),
        f"{name}.semi_radius",
    )
    cg = est.pad_to_ground(w, length, gs, gb, eps, open_edges=1) + est.cpw_line(lead, tw, 6, eps)
    _C(frag, f"C_{name}_pad", "pad", "gnd", est.cap(cg, "rough", f"{w:g}×{length:g} µm pad in its clearance + lead"))
    return frag


# ---- pads ---------------------------------------------------------------------------------------------------------
@register_lom("ConnectorPad")
def connector_pad_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Legacy wire-bond pad (v1): a 50 Ω port on the conductor its ``a`` port connects to."""
    return Fragment(nodes={"pad": {"island": f"{name}.pad"}}, elements=[port_resistor(name)], port_nodes={"a": "pad"})


@register_lom("CpweBondPad")
def cpwe_bond_pad_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """CPW-E bond pad: a 50 Ω port at ``a``."""
    return Fragment(nodes={"pad": {"island": f"{name}.pad"}}, elements=[port_resistor(name)], port_nodes={"a": "pad"})


@register_lom("TaperedPad")
def tapered_pad_lom(name: str, inst, pdk) -> Fragment:
    """Legacy probe pad tapering to a junction finger: the pad's C to ground (DC test pad, not an RF port)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    w, h = _f(p.get("pad_width"), 275), _f(p.get("pad_height"), 300)
    side = max((_f(p.get("window_width"), 300) - w) / 2, 1.0) if p.get("negative", True) else 50.0
    c = est.pad_to_ground(w, h, side, side, eps)
    frag = Fragment(nodes={"pad": {"island": f"{name}.pad"}}, port_nodes={"finger": "pad"})
    _C(frag, f"C_{name}", "pad", "gnd", est.cap(c, "rough", f"{w:g}×{h:g} µm pad in a {side:g} µm clearance"))
    return frag


# ---- lines and resonators -----------------------------------------------------------------------------------------
def _drawn_length(cls_name: str, p: dict, fallback: float) -> float:
    """Centre-line length (µm) from the legacy cell's own point function; ``fallback`` if it cannot run."""
    from quantcore_circuits.layouts.others import legacy_resonators as lr  # pylint: disable=import-outside-toplevel

    try:
        cls = getattr(lr, cls_name)
        ns = SimpleNamespace(**p, layout=SimpleNamespace(dbu=0.001))
        pts = [(q.x * 0.001, q.y * 0.001) for q in cls._points(ns)]  # pylint: disable=protected-access
        length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        return length if length > 0 else fallback
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return fallback


def _resonator_line(name, p, cls_name, ports, term, resonator=True, node="res") -> tuple[Fragment, float]:
    length = _drawn_length(cls_name, p, _f(p.get("cpw_len"), 4000))
    frag = Fragment(nodes={node: {"island": f"{name}.{node}"}}, port_nodes={q: node for q in ports if q})
    frag.lines.append(
        Line(name, node, ports, length, _f(p.get("a"), 10), _f(p.get("b"), 6), term, resonator, knob=f"{name}.cpw_len")
    )
    _knob(frag, f"{name}.cpw_len", _f(p.get("cpw_len"), 4000))
    return frag, length


def _coupled_meander(name: str, inst, cls_name: str) -> Fragment:
    p = cell_params(inst)
    # ``ground`` draws the gap cap (open end); without it the trace runs into the ground plane unless connected
    end = "open" if p.get("ground", True) else "short"
    frag, _ = _resonator_line(name, p, cls_name, (None, "end"), ("short", end))
    frag.hangers.append(
        {
            "line": name,
            "coupling_length_um": _f(p.get("clength"), 500),
            "ground_gap_um": max(_f(p.get("cgap"), 6), 0.5),
            "end": "short",
            "source": "coupler section next to a separate feedline (legacy placement)",
        }
    )
    return frag


@register_lom("CoupledResonator")
def coupled_resonator_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Legacy coupled resonator: λ/4 meander from the shorted start next to the coupler section to port ``end``."""
    return _coupled_meander(name, inst, "CoupledResonator")


@register_lom("QubitResonator")
def qubit_resonator_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Legacy qubit resonator: as CoupledResonator, the tail (port ``end``) runs to the qubit."""
    return _coupled_meander(name, inst, "QubitResonator")


@register_lom("CpwResonator")
def cpw_resonator_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Legacy CPW resonator: a resonator line between ``start`` and ``end`` (both run into ground when free: λ/2)."""
    p = cell_params(inst)
    frag, _ = _resonator_line(name, p, "CpwResonator", ("start", "end"), ("short", "short"))
    frag.notes.append(f"{name}: coupling to a feedline is not in the cell; declare it with d.couple(...)")
    return frag


@register_lom("CoupledConnector")
def coupled_connector_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Legacy coupled connector: a line from the shorted ``start`` to ``end`` (λ/4 when ``end`` meets a capacitor,
    a wire when both ends are connected)."""
    p = cell_params(inst)
    end = "short" if p.get("ground", False) else "open"
    frag, _ = _resonator_line(
        name, p, "CoupledConnector", ("start", "end"), ("short", end), resonator=False, node="line"
    )
    return frag


@register_lom("CpwSegment")
def cpw_segment_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Legacy straight CPW (feedline): one conductor from ``a`` to ``b`` (a stub resonator only with a free end)."""
    p = cell_params(inst)
    length = _f(p.get("length"), 200)
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(Line(name, "line", ("a", "b"), length, _f(p.get("a"), 10), _f(p.get("b"), 6), ("short", "short")))
    return frag


@register_lom("CpweQuarterWaveResonator")
def cpwe_quarter_wave_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """CPW-E λ/4: open coupler arm (no port) → bend → taper → meander → shorted end, as one λ/4 line.

    The coupler arm runs next to a feedline the cell does not contain: declare ``d.couple("K_<R>", "<R>",
    "<feedline instance>")`` for the hanger (coupled section at the open end; the ground strip is set by the
    placement, 6 µm assumed).
    """
    from quantcore_circuits.layouts.others.cpwe import CpweQuarterWaveResonator  # pylint: disable=C0415

    p = cell_params(inst)
    length = CpweQuarterWaveResonator.qcc_resonator_length(p)
    frag = Fragment(nodes={"res": {"island": f"{name}.res"}})
    frag.lines.append(
        Line(name, "res", (None, None), length, _f(p.get("a"), 10), _f(p.get("b"), 6), ("open", "short"), True)
    )
    frag.hangers.append(
        {
            "line": name,
            "coupling_length_um": _f(p.get("cap_length"), 200),
            "ground_gap_um": 6.0,
            "end": "open",
            "source": "rough: CPW-E coupler arm at the open end; ground strip to the feedline assumed 6 µm",
        }
    )
    frag.notes.append(f"{name}: λ/4 of {length:.0f} µm (drawn); coupler arm CPW differs from the line CPW")
    return frag


@register_lom("CpweMeanderLine")
def cpwe_meander_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """CPW-E meander (+ leads): a resonator line between ``a`` and ``b`` (λ/2 bus between two couplers, a stub
    resonator with a free end, a wire to a port/feedline)."""
    p = cell_params(inst)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    r, m_len = _f(p.get("meander_radius"), 50), _f(p.get("meander_length"), 500)
    n = int(_f(p.get("meanders"), 2))
    try:
        from quantcore_circuits.layouts.others.cpwe import CpwePen  # pylint: disable=import-outside-toplevel

        _, _, ltot = CpwePen(0.001).meander_line(
            0,
            0,
            "h",
            a * 1e3,
            b * 1e3,
            r * 1e3,
            m_len * 1e3,
            _f(p.get("bias"), 0.5),
            n,
            bool(p.get("flip")),
            bool(p.get("term_early")),
        )
        length = ltot / 1e3
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        length = (2 * n + 1) * m_len + (2 * n + 1) * math.pi * r  # rough: straight runs + half turns
    length += 2 * max(_f(p.get("lead"), 0), 0.0)
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(Line(name, "line", ("a", "b"), length, a, b, ("short", "short"), True, knob=f"{name}.meanders"))
    return frag


@register_lom("SpiralLine")
def spiral_line_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Spiral line (legacy ``draw.spiral``): one conductor ``a`` → ``b``, a line of the drawn centre-line length with
    the mean turn spacing as its gap (rough: neighbouring turns are not a ground plane; mutual inductance between
    turns is not modelled; the film kinetic inductance enters as for any CPW). Open ends when nothing connects (a
    spiral λ/2 resonator); an etched spiral (``metal=False``) is a slot, not a conductor: no element."""
    from quantcore_circuits.layouts.others.spirals import SpiralLine  # pylint: disable=import-outside-toplevel

    p = cell_params(inst)
    if p.get("metal") is False:
        return Fragment(notes=[f"{name}: etched spiral (a slot in the ground plane): no circuit element"])
    length, gap = SpiralLine.qcc_length(p), SpiralLine.qcc_turn_gap(p)
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(Line(name, "line", ("a", "b"), length, _f(p.get("width"), 2), gap, ("open", "open"), True))
    frag.notes.append(
        f"{name}: spiral line {length:.0f} µm (gap = mean turn spacing {gap:.2g} µm; rough; kinetic L as a CPW)"
    )
    return frag


@register_lom("CpweTaper")
def cpwe_taper_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """CPW-E taper: a pass-through section of ``length`` between ``a`` and ``b`` (``Line.through``: inside a
    resonator it extends the line; the width step is not modelled, mean a/b)."""
    p = cell_params(inst)
    a = (_f(p.get("a"), 10) + _f(p.get("a_end"), 20)) / 2
    b = (_f(p.get("b"), 6) + _f(p.get("b_end"), 12)) / 2
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(Line(name, "line", ("a", "b"), _f(p.get("length"), 100), a, b, ("short", "short"), through=True))
    return frag


@register_lom("NeckTermination")
def neck_termination_lom(name: str, inst, pdk) -> Fragment:
    """QPDK neck termination: the line routed to ``o1`` ends shorted after a taper (``a`` → ``neck_width``) and a
    narrow neck, both a strip in an etched window. A pass-through end section (``Line.through``, shorted far end):
    the route is the resonator. A short series section at a current antinode adds the electrical length
    ℓ · L'_section / L'_cpw, so taper and neck count at their per-length inductance (strip in the window, gap =
    (window − width)/2) relative to the a/b CPW (analytic CPW formulas; rough)."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel

    p = cell_params(inst)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    w, win = _f(p.get("neck_width"), 2), _f(p.get("window_width"), 380)
    lt, ln = _f(p.get("taper_length"), 100), _f(p.get("neck_length"), 325)

    def l_per_um(width: float, gap: float) -> float:  # H/m up to a constant: Z0 / v_p
        q = cpw_properties(6.0, width, gap, pdk.name)
        return q["Z0_ohm"] / q["vp_m_s"]

    ref = l_per_um(a, b)
    mid = (a + w) / 2
    taper_eq = lt * l_per_um(mid, max((win - mid) / 2, b)) / ref
    neck_eq = ln * l_per_um(w, max((win - w) / 2, b)) / ref
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"o1": "line"})
    frag.lines.append(Line(name, "line", ("o1", None), taper_eq + neck_eq, a, b, ("short", "short"), through=True))
    frag.notes.append(
        f"{name}: taper {lt:g} µm + neck {ln:g} µm counted as {taper_eq + neck_eq:.0f} µm of {a:g}/{b:g} µm CPW "
        f"(L' ratio {neck_eq / ln:.2f} for the neck; rough: no neck L_k beyond the CPW formula, no C of the window)"
    )
    return frag


@register_lom("CpweOpenEnd")
def cpwe_open_end_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """CPW-E open termination: a zero-length open end; a route into it becomes an open-ended resonator."""
    p = cell_params(inst)
    frag = Fragment(nodes={"end": {"island": f"{name}.end"}}, port_nodes={"a": "end"})
    frag.lines.append(Line(name, "end", ("a", None), 0.0, _f(p.get("a"), 10), _f(p.get("b"), 6), ("open", "open")))
    return frag


# ---- CPW-E capacitors ---------------------------------------------------------------------------------------------
def _pi(name, cab, cg, kind_ab, formula_ab, formula_g, knob=None) -> Fragment:
    frag = Fragment(nodes={"a": {"island": f"{name}.a"}, "b": {"island": f"{name}.b"}}, port_nodes={"a": "a", "b": "b"})
    _C(frag, f"C_{name}", "a", "b", est.cap(cab, kind_ab, formula_ab), knob)
    _C(frag, f"C_{name}_a", "a", "gnd", est.cap(cg, "rough", formula_g))
    _C(frag, f"C_{name}_b", "b", "gnd", est.cap(cg, "rough", formula_g))
    return frag


@register_lom("CpweFingerCapacitor")
def cpwe_finger_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """CPW-E interdigital capacitor in the centre line: ``fingers`` fingers sharing the centre width, overlap
    ``finger_length − finger_gap`` (Igreja–Dias) + tip gaps; C to ground: half the section as CPW each side."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    n, sep, flen = int(_f(p.get("fingers"), 4)), _f(p.get("finger_gap"), 2), _f(p.get("finger_length"), 50)
    fw = max((a - (n - 1) * sep) / max(n, 1), 0.1)
    cab = est.interdigital(n, fw, sep, max(flen - sep, 0.0), eps)
    cab += est.coplanar_coupling(n * fw, max(fw, 10.0), max(fw, 10.0), max(sep, 0.5), eps)
    cg = est.cpw_line((flen + sep) / 2, a, b, eps)
    return _pi(
        name,
        cab,
        cg,
        "analytic",
        f"{n} fingers {fw:.2g} µm / {sep:g} µm, overlap {flen - sep:g} µm (Igreja & Dias 2004) + tips",
        "half the capacitor section as CPW",
        f"{name}.finger_length",
    )


@register_lom("CpweGapCapacitor")
def cpwe_gap_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """CPW-E gap in the centre line: end-to-end C across ``cap_gap`` (rough); open-end fringe to ground each side."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    a, b, g = _f(p.get("a"), 10), _f(p.get("b"), 6), max(_f(p.get("cap_gap"), 5), 0.1)
    cab = est.coplanar_coupling(a, max(a, 10.0), max(a, 10.0), g, eps)
    cg = est.cpw_line(b, a, b, eps)
    return _pi(
        name,
        cab,
        cg,
        "rough",
        f"centre-line ends {a:g} µm wide across {g:g} µm (CPS)",
        "open-end fringe ≈ a CPW stub one gap long",
        f"{name}.cap_gap",
    )


@register_lom("CpweFingerLine")
def cpwe_finger_line_lom(name: str, inst, pdk) -> Fragment:
    """CPW-E finger line: the centre conductor continues from ``a`` to ``b`` (a wire) with interleaved fingers from
    the centre and the ground in both gaps: a shunt C to ground (interdigital per side + the section as CPW)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    n, sep = int(_f(p.get("fingers"), 10)), _f(p.get("finger_gap"), 2)
    flen, fw = _f(p.get("finger_length"), 4), _f(p.get("finger_width"), 2)
    overlap = max(2 * flen - b, 0.0)
    total = n * fw + (n - 1) * sep
    c = 2 * est.interdigital(n, fw, sep, overlap, eps) + est.cpw_line(total, a, max(b - flen, 0.5), eps)
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    _C(
        frag,
        f"C_{name}",
        "line",
        "gnd",
        est.cap(c, "rough", f"{n} fingers per gap, overlap {overlap:g} µm (Igreja & Dias) + {total:g} µm of CPW"),
        f"{name}.fingers",
    )
    return frag


# ---- no circuit elements ------------------------------------------------------------------------------------------
@register_lom("FluxHoleArray")
@register_lom("FluxHoles")
def flux_holes_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """Flux-trapping holes in the ground plane: no ports, no circuit elements."""
    return Fragment()


@register_lom("WaveguideCoplanarStraight")
def kqc_cpw_segment_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC bare straight CPW segment (the piece routes are drawn with): no ports, so no circuit elements; connect
    with a route or a ``WaveguideCoplanar``. (``WaveguideCoplanarCurved`` has ports and a line model since
    2026-11-15: :mod:`.kqc_models`.)"""
    return Fragment(notes=[f"{name}: bare KQC CPW segment without ports; no circuit elements"])

"""LOM models for stock KQCircuits cells, registered from outside their classes (:func:`register_lom`).

This is the template for giving any third-party cell a lumped model: map its ports to nodes, add elements with
estimates (labelled ``calibration`` / ``analytic`` / ``rough``, see :mod:`.estimates`), and let FEM replace them
later by island name (``<inst>.island``, ``<inst>.island1``/``island2`` for floating qubits, ``<inst>.<port>`` for
coupler pads).

=============================================  ====================================================================
KQC cell                                       lumped model
=============================================  ====================================================================
Swissmon                                       grounded: island C (CPW-arm cross, anchored on the Xmon Q3D),
                                               JJ/SQUID to ground; per coupler node C_g + C to ground
CircularTransmonSingleIsland                   grounded: disk C, JJ to ground; per arc coupler C_g + C to ground
DoublePads, DoublePadsSplines                  floating: island1 (coupler side) and island2, each C to ground,
                                               C between them, JJ/SQUID between them; coupler node C_g to island1
ConcentricTransmon                             floating: island1 = outer ring, island2 = inner disk; arc couplers
                                               on the ring
FingerCapacitorSquare/Taper, SmoothCapacitor,  π network: C_ab between the ports, C to ground at each port
CircularCapacitor, SpiralCapacitor
QuarterWaveCpwResonator                        probe line ``pl`` (a, b) + coupling capacitor + λ/4 line
HangerResonator                                probe line ``pl`` (a, b) + resonator line (resonator_a/_b) with a
                                               coupled-line section (HANGER) to ``pl``
SpiralResonatorPolygon                         resonator line between a and b
Launcher, LauncherDC                           50 Ω port
WaveguideCoplanar, WaveguideComposite,         a line: a wire between connected ports, a resonator when an end is
Meander, WaveguideCoplanarCurved               free (Meander: always a resonator, λ/2 bus between two couplers;
                                               Curved: r·|alpha|, ports from registry.KQC_EXTRA_PORTS)
WaveguideCoplanarTaper, AirbridgeConnection    a pass-through section (``Line.through``) of the line it joins
WaveguideCoplanarSplitter                      one conductor (T-junction)
AirbridgeRectangular, AirbridgeMultiFace       wire; nothing joined: a ground strap (ports → gnd)
junctions (Squid subclasses)                   JJ / SQUID from ``common`` to ground (``No Squid``: none)
Fluxline*                                      flux control port
CapacitiveXCoupler                             arms p11..p41 (registry.KQC_EXTRA_PORTS), each C_ab (its finger
                                               capacitor) to the floating centre ``c``; C to ground per arm/centre
=============================================  ====================================================================
"""

from __future__ import annotations

import math
import re

from quantcore_circuits.lom import estimates as est
from quantcore_circuits.lom.calibration import estimate
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


def _lst(x, n=None, default=0.0) -> list[float]:
    vals = [_f(v, default) for v in (x if isinstance(x, (list, tuple)) else [x])]
    if n is not None and len(vals) < n:
        vals += [vals[-1] if vals else default] * (n - len(vals))
    return vals


def _C(frag: Fragment, name: str, a: str, b: str, value: dict, knob: str | None = None) -> None:
    frag.elements.append(Element(name, "C", (a, b), value, {"param": knob} if knob else None))


def _junction(frag: Fragment, name: str, inst, params: dict, a: str, b: str) -> None:
    kind = junction_kind(params.get("junction_type", "Manhattan"))
    if params.get("with_squid", True) is False or kind is None:
        frag.notes.append(f"{name}: no junction ({params.get('junction_type')!r}); the islands are not shunted")
        return
    frag.elements.append(junction_element(name, a, b, inst, kind, drawn_params=params))
    lj = frag.elements[-1].value.get("Lj_nH")
    if lj:
        frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))
    else:
        frag.notes.append(f"{name}: no junction.Lj_nH in the design; the qubit mode needs one to simulate")


def _cross_anchor(pdk) -> float:
    """Q3D/analytic ratio of the Xmon island at its calibration geometry (applied to other cross islands)."""
    ref, _ = estimate("Xmon", "C_island", {"cross_length": 300.0}, pdk.name)
    ana = est.cross_island([150.0] * 4, 25.0, 25.0, est.substrate_eps(pdk))
    return ref / ana if ref else 1.0


# ---- qubits -------------------------------------------------------------------------------------------------------
@register_lom("Swissmon")
def swissmon_lom(name: str, inst, pdk) -> Fragment:
    """KQC Swissmon: grounded cross transmon (island + JJ/SQUID to ground) with up to three coupler horseshoes.

    Island: the four arms as CPW sections (arm width / gap width, WNES), scaled by the Xmon Q3D/analytic ratio at the
    Xmon calibration point. Couplers: C to ground = the horseshoe as a CPW of its width and ``cpl_b`` (+ the port
    stub); C_g = the Xmon claw calibration at the coupler length (rough: the Swissmon coupler is screened by a
    ground strip, the Xmon claw is not). Run a C-matrix of the cell (``q3d_cmatrix``) to replace them.
    """
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    arms = _lst(p.get("arm_length", [150.0] * 4), 4, 150.0)
    width = sum(_lst(p.get("arm_width", [24] * 4), 4, 24)) / 4
    gap = sum(_lst(p.get("gap_width", [12] * 4), 4, 12)) / 4
    anchor = _cross_anchor(pdk)
    frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
    c_is = anchor * est.cross_island(arms, width, gap, eps)
    _C(
        frag,
        f"C_{name}",
        "island",
        "gnd",
        est.cap(c_is, "analytic", f"CPW-arm cross ({width:g}/{gap:g} µm) × {anchor:.3f} Xmon Q3D anchor"),
        f"{name}.arm_length",
    )
    _junction(frag, name, inst, p, "island", "gnd")
    lengths = _lst(p.get("cpl_length", [120] * 3), 3, 120)
    widths = _lst(p.get("cpl_width", [24] * 3), 3, 24)
    gaps = _lst(p.get("cpl_gap", [102] * 3), 3, 102)
    cpl_b = _lst(p.get("cpl_b", [6] * 3), 3, 6)
    for i, length in enumerate(lengths):
        if length <= 0:  # no horseshoe drawn: the port's CPW runs into the ground plane
            frag.port_nodes[f"cplr{i}"] = "gnd"
            frag.notes.append(f"{name}.cplr{i}: cpl_length 0 (no coupler), its port ends on ground")
            continue
        node = f"cplr{i}"
        frag.nodes[node] = {"island": f"{name}.{node}"}
        frag.port_nodes[node] = node
        cg, _ = estimate("Xmon", "Cg", {"claw_length": length}, pdk.name)
        horseshoe = 2 * length + gaps[i] + widths[i]
        cc = est.cpw_line(horseshoe, widths[i], cpl_b[i], eps)
        _C(
            frag,
            f"Cg_{name}_{node}",
            "island",
            node,
            est.cap(cg, "rough", "Xmon claw calibration at the coupler length (screened coupler)"),
            f"{name}.cpl_length",
        )
        _C(
            frag,
            f"Cc_{name}_{node}",
            node,
            "gnd",
            est.cap(cc, "analytic", f"horseshoe as CPW {widths[i]:g}/{cpl_b[i]:g} µm × {horseshoe:g} µm"),
        )
    frag.port_nodes["drive"] = "control:drive"
    frag.port_nodes["flux"] = "control:flux"
    return frag


@register_lom("CircularTransmonSingleIsland")
def circular_single_island_lom(name: str, inst, pdk) -> Fragment:
    """KQC circular single-island transmon: grounded disk + JJ to ground, arc couplers between disk and ground."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    r, gg = _f(p.get("r_island"), 120), _f(p.get("ground_gap"), 80)
    frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
    _C(
        frag,
        f"C_{name}",
        "island",
        "gnd",
        est.cap(est.disk_to_ground(r, gg, eps), "analytic", f"disk r={r:g} µm in a {gg:g} µm ground gap (bent CPW)"),
        f"{name}.r_island",
    )
    _junction(frag, name, inst, p, "island", "gnd")
    _arc_couplers(frag, name, p, eps, island="island", r_island_edge=r, island_width=r, r_ground=r + gg)
    frag.port_nodes["drive"] = "control:drive"
    return frag


def _arc_couplers(frag, name, p, eps, island, r_island_edge, island_width, r_ground):
    """Arc couplers of the KQC circular/concentric qubits (ports ``coupler_1`` …): C_g to ``island``, C to ground."""
    rc = _f(p.get("couplers_r"), 150)
    widths = _lst(p.get("couplers_width", [10, 20, 30]))
    amps = _lst(p.get("couplers_arc_amplitude", [35, 45, 15]), len(widths))
    a_s = _lst(p.get("couplers_a", [10, 3, 4.5]), len(widths))
    b_s = _lst(p.get("couplers_b", [6, 32, 20]), len(widths))
    for i, w in enumerate(widths):
        node = f"coupler_{i + 1}"
        frag.nodes[node] = {"island": f"{name}.{node}"}
        frag.port_nodes[node] = node
        arc = rc * math.radians(amps[i])
        s_in = max(rc - w / 2 - r_island_edge, 1.0)
        s_out = max(r_ground - rc - w / 2, 1.0)
        cg = est.coplanar_coupling(arc, w, island_width, s_in, eps)
        cc = arc * est.cpw_c_per_um(w, s_out, eps) / 2 + est.cpw_line(s_out, a_s[i], b_s[i], eps)
        _C(
            frag,
            f"Cg_{name}_{node}",
            island,
            node,
            est.cap(cg, "rough", f"arc {arc:.0f} µm facing the island across {s_in:g} µm (CPS)"),
            f"{name}.couplers_arc_amplitude",
        )
        _C(frag, f"Cc_{name}_{node}", node, "gnd", est.cap(cc, "rough", "arc outer edge (half CPW) + port lead"))


def _double_pads(name: str, inst, pdk, kind: str) -> Fragment:
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    gw, gh = _lst(p.get("ground_gap", [700, 700]), 2, 700)
    w1, h1 = _lst(p.get("island1_extent", [500, 100]), 2, 100)
    w2, h2 = _lst(p.get("island2_extent", [500, 100]), 2, 100)
    s = _f(p.get("island_island_gap"), 70)
    off = _f(p.get("squid_offset"), 0)
    back1 = gh / 2 - (off + s / 2 + h1)
    back2 = gh / 2 - (-off + s / 2 + h2)
    w = (w1 + w2) / 2
    c1, c12 = est.two_pads(w1, (h1 + h2) / 2, s, (gw - w1) / 2, back1, eps)
    c2, _ = est.two_pads(w2, (h1 + h2) / 2, s, (gw - w2) / 2, back2, eps)
    _, c12 = est.two_pads(w, (h1 + h2) / 2, s, (gw - w) / 2, (back1 + back2) / 2, eps)
    frag = Fragment(
        nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}},
        notes=[] if kind == "DoublePads" else [f"{name}: spline islands estimated as their bounding rectangles"],
    )
    f = "coupled strips in a ground slot (Simons ch. 7) + short-edge CPW"
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(c1, "analytic", f), f"{name}.island1_extent")
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c2, "analytic", f), f"{name}.island2_extent")
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "analytic", f), f"{name}.island_island_gap")
    _junction(frag, name, inst, p, "island1", "island2")
    cw, ch = _lst(p.get("coupler_extent", [150, 20]), 2, 20)
    c_off = _f(p.get("coupler_offset"), 20)
    top = off + s / 2 + h1 + c_off + ch
    cg = est.coplanar_coupling(cw, ch, h1, c_off, eps)
    cc = est.pad_to_ground(cw, ch, (gw - cw) / 2, max(gh / 2 - top, 1.0), eps, open_edges=1)
    frag.nodes["cplr"] = {"island": f"{name}.cplr"}
    frag.port_nodes["cplr"] = "cplr"
    _C(
        frag,
        f"Cg_{name}_cplr",
        "island1",
        "cplr",
        est.cap(cg, "analytic", f"coupler {cw:g}×{ch:g} µm facing island1 across {c_off:g} µm (CPS)"),
        f"{name}.coupler_extent",
    )
    _C(frag, f"Cc_{name}_cplr", "cplr", "gnd", est.cap(cc, "rough", "coupler pad in the qubit ground gap"))
    frag.port_nodes["drive"] = "control:drive"
    frag.notes.append(f"{name}: floating transmon; island2 ↔ coupler capacitance neglected (screened by island1)")
    return frag


@register_lom("DoublePads")
def double_pads_lom(name: str, inst, pdk) -> Fragment:
    """KQC DoublePads: floating transmon, two rectangular islands shunted by a SQUID/JJ, one coupler (``cplr``)."""
    return _double_pads(name, inst, pdk, "DoublePads")


@register_lom("DoublePadsSplines")
def double_pads_splines_lom(name: str, inst, pdk) -> Fragment:
    """KQC DoublePadsSplines: as DoublePads (spline islands approximated by their extents)."""
    return _double_pads(name, inst, pdk, "DoublePadsSplines")


@register_lom("ConcentricTransmon")
def concentric_lom(name: str, inst, pdk) -> Fragment:
    """KQC concentric transmon: floating; island1 = outer ring (couplers face it), island2 = inner disk."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    r_in, r_out = _f(p.get("r_inner"), 120), _f(p.get("r_outer"), 250)
    w_out, gg = _f(p.get("outer_island_width"), 80), _f(p.get("ground_gap"), 80)
    frag = Fragment(nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}})
    c12 = est.concentric_rings(r_in, r_out - w_out, eps)
    c1 = est.ring_to_ground(r_out, w_out, gg, eps)
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(c1, "analytic", "ring outer edge as half CPW"), f"{name}.r_outer")
    _C(
        frag,
        f"C_{name}_12",
        "island1",
        "island2",
        est.cap(c12, "rough", "disk–ring facing edges as coplanar strips along the mean circumference"),
        f"{name}.r_inner",
    )
    # inner disk → ground through the ring: the disk in a ground ring at r_out + gg, times the open (non-metal)
    # fraction of the radial span squared for the ring's screening (rough)
    span = r_out + gg - r_in
    c2 = est.disk_to_ground(r_in, span, eps) * ((span - w_out) / span) ** 2
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c2, "rough", "disk to ground screened by the ring"))
    _junction(frag, name, inst, p, "island1", "island2")
    _arc_couplers(frag, name, p, eps, island="island1", r_island_edge=r_out, island_width=w_out, r_ground=r_out + gg)
    frag.port_nodes["drive"] = "control:drive"
    return frag


# ---- capacitors ---------------------------------------------------------------------------------------------------
def _pi_network(name, cab, ca, cb, kind_ab, formula_ab, kind_g, formula_g, knob=None) -> Fragment:
    frag = Fragment(nodes={"a": {"island": f"{name}.a"}, "b": {"island": f"{name}.b"}}, port_nodes={"a": "a", "b": "b"})
    _C(frag, f"C_{name}", "a", "b", est.cap(cab, kind_ab, formula_ab), knob)
    _C(frag, f"C_{name}_a", "a", "gnd", est.cap(ca, kind_g, formula_g))
    _C(frag, f"C_{name}_b", "b", "gnd", est.cap(cb, kind_g, formula_g))
    return frag


def _fingers(p: dict, eps: float) -> tuple[float, float, float]:
    n = int(_f(p.get("finger_number"), 5))
    w, s = _f(p.get("finger_width"), 5), _f(p.get("finger_gap"), 3)
    length, end = _f(p.get("finger_length"), 20), _f(p.get("finger_gap_end"), 3)
    cab = est.interdigital(n, w, s, max(length - end, 0.0), eps) if length > 0 else 0.0
    # finger tips facing the opposite bus bar (gap capacitor when finger_length = 0)
    tips = (n * w + (n - 1) * s) if length <= 0 else n * w
    cab += est.coplanar_coupling(tips, max(w, 10.0), max(w, 10.0), max(end, 0.5), eps)
    area_w = n * w + (n - 1) * s
    return cab, area_w, length + end


@register_lom("FingerCapacitorSquare")
def finger_capacitor_square_lom(name: str, inst, pdk) -> Fragment:
    """KQC square finger capacitor: interdigital C_ab (Igreja–Dias) + tip gaps; C to ground across ground_padding."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    cab, area_w, area_l = _fingers(p, eps)
    pad = _f(p.get("ground_padding"), 20)
    cg = est.pad_to_ground(area_l / 2 + _f(p.get("finger_width"), 5), area_w, pad, pad, eps) / 2
    return _pi_network(
        name,
        cab,
        cg,
        cg,
        "analytic",
        "interdigital (Igreja & Dias 2004) + finger-tip gaps",
        "rough",
        "half the finger area as a pad in the ground padding",
        f"{name}.finger_number",
    )


@register_lom("FingerCapacitorTaper")
def finger_capacitor_taper_lom(name: str, inst, pdk) -> Fragment:
    """KQC tapered finger capacitor: interdigital C_ab; C to ground of each taper as a CPW section (gap b)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    cab, area_w, _ = _fingers(p, eps)
    taper = _f(p.get("taper_length"), 60)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    cg = est.cpw_line(taper, (area_w + a) / 2, b, eps)
    return _pi_network(
        name, cab, cg, cg, "analytic", "interdigital (Igreja & Dias 2004)", "rough", "taper as a CPW section"
    )


@register_lom("SmoothCapacitor")
def smooth_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """KQC smooth capacitor: the meandering gap between the electrodes as coplanar strips (rough)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    fc = _f(p.get("finger_control"), 2.1)
    w, s = _f(p.get("finger_width"), 10), _f(p.get("finger_gap"), 5)
    scale = w + s
    f_len = max(scale * (2 * fc - 3), 0.0) + scale * math.pi  # one finger: straight part + two quarter turns
    gap_len = max(fc, 0.5) * f_len + 2 * w
    cab = est.coplanar_coupling(gap_len, w, w, s, eps)
    gg = _f(p.get("ground_gap"), 10)
    cg = est.pad_to_ground(max(fc, 1.0) * scale, 2 * max(fc, 1.0) * scale, gg, gg, eps, open_edges=1) / 2
    return _pi_network(
        name,
        cab,
        cg,
        cg,
        "rough",
        f"electrode gap ≈ {gap_len:.0f} µm of coplanar strips",
        "rough",
        "electrode as a pad in the ground gap",
        f"{name}.finger_control",
    )


@register_lom("CircularCapacitor")
def circular_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """KQC circular capacitor: centre disk (port a) and outer arc island (port b), C along the arc."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    r_in, r_out = _f(p.get("r_inner"), 20), _f(p.get("r_outer"), 80)
    w, ang, gg = _f(p.get("outer_island_width"), 40), _f(p.get("swept_angle"), 180), _f(p.get("ground_gap"), 20)
    s = max(r_out - w - r_in, 1.0)
    arc = (r_in + s / 2) * math.radians(ang)
    cab = est.coplanar_coupling(arc, r_in, w, s, eps)
    ca = est.disk_to_ground(r_in, s, eps) * (1 - ang / 360)  # the part of the disk edge not facing the arc
    cb = r_out * math.radians(ang) * est.cpw_c_per_um(2 * w, gg, eps) / 2
    return _pi_network(
        name,
        cab,
        ca,
        cb,
        "rough",
        f"disk–arc gap {s:g} µm over {arc:.0f} µm (CPS)",
        "rough",
        "free disk edge / arc outer edge (half CPW)",
        f"{name}.swept_angle",
    )


@register_lom("SpiralCapacitor")
def spiral_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """KQC spiral capacitor: two interleaved spiral fingers as coplanar strips along the spiral (rough)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    w, s = _f(p.get("finger_width"), 10), _f(p.get("finger_gap"), 5)
    ang = (_f(p.get("spiral_angle"), 180) + max(_f(p.get("spiral_angle2"), -1), 0.0)) / 2 or 180.0
    a = _f(p.get("a"), 10)
    pitch = 2 * (w + s)
    r_mean = a / 2 + w + s + pitch * ang / 720  # Archimedean spiral, mean radius over the swept angle
    coupled = 2 * r_mean * math.radians(ang)
    cab = est.coplanar_coupling(coupled, w, w, s, eps)
    gg = _f(p.get("ground_gap"), 10)
    cg = r_mean * 2 * math.pi * est.cpw_c_per_um(w, gg, eps) / 4
    return _pi_network(
        name,
        cab,
        cg,
        cg,
        "rough",
        f"spiral fingers ≈ {coupled:.0f} µm of coplanar strips",
        "rough",
        "outer spiral edge to ground",
        f"{name}.spiral_angle",
    )


@register_lom("CapacitiveXCoupler")
def x_coupler_lom(name: str, inst, pdk) -> Fragment:
    """KQC capacitive X coupler: four CPW arms (ports ``p11``..``p41``, :data:`~quantcore_circuits.layouts.registry.
    KQC_EXTRA_PORTS`) each coupled through its FingerCapacitorSquare (the element's finger parameters, KQC's default
    finger_length, ground_padding = b) to a floating centre cross (node ``c``): a star of four C_ab, as
    FingerCapacitorSquare's estimate. C to ground: each arm's CPW up to its capacitor, the centre's four inner CPW
    sections, and half each capacitor's finger block per side (rough). ``remove_capacitors``: one conductor."""
    from kqcircuits.elements.finger_capacitor_square import FingerCapacitorSquare  # pylint: disable=C0415

    from quantcore_circuits.layouts.registry import x_coupler_arms  # pylint: disable=import-outside-toplevel

    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    arms = x_coupler_arms(p)
    lengths = {k: sum(math.dist(u, v) for u, v in zip(pts, pts[1:])) for k, pts in arms.items()}
    inner = {k: math.hypot(*pts[-1]) for k, pts in arms.items()}
    if p.get("remove_capacitors"):
        frag = Fragment(nodes={"c": {"island": f"{name}.c"}}, port_nodes=dict.fromkeys(arms, "c"))
        total = sum(lengths.values()) + sum(inner.values())
        _C(frag, f"C_{name}", "c", "gnd", est.cap(est.cpw_line(total, a, b, eps), "rough", f"{total:.0f} µm of CPW"))
        frag.notes.append(f"{name}: CapacitiveXCoupler without capacitors: one conductor (a 4-way CPW junction)")
        return frag
    cap_p = {k: v.default for k, v in FingerCapacitorSquare.get_schema().items()}
    cap_p |= {k: p[k] for k in ("finger_number", "finger_width", "finger_gap", "finger_gap_end") if k in p}
    cab, area_w, area_l = _fingers(cap_p, eps)
    fw = _f(cap_p.get("finger_width"), 10)
    half = area_l / 2 + fw + b  # capacitor centre → its port (KQC x_end, ground_padding = b)
    cg = est.pad_to_ground(area_l / 2 + fw, area_w, b, b, eps) / 2  # as FingerCapacitorSquare's model, per side
    f_ab = "interdigital (Igreja & Dias 2004) + finger-tip gaps, as FingerCapacitorSquare"
    frag = Fragment(nodes={"c": {"island": f"{name}.c"}})
    c_centre = 0.0
    for arm in arms:
        frag.nodes[arm] = {"island": f"{name}.{arm}"}
        frag.port_nodes[arm] = arm
        _C(frag, f"C_{name}_{arm}", arm, "c", est.cap(cab, "analytic", f_ab), f"{name}.finger_number")
        out = max(lengths[arm] - half, 0.0)
        f_g = f"{out:.0f} µm of arm CPW + half the finger block"
        _C(frag, f"C_{name}_{arm}_g", arm, "gnd", est.cap(est.cpw_line(out, a, b, eps) + cg, "rough", f_g))
        c_centre += est.cpw_line(max(inner[arm] - half, 0.0), a, b, eps) + cg
    _C(frag, f"C_{name}_c", "c", "gnd", est.cap(c_centre, "rough", "inner arm CPW sections + half finger blocks"))
    return frag


# ---- resonators ---------------------------------------------------------------------------------------------------
@register_lom("QuarterWaveCpwResonator")
def quarter_wave_lom(name: str, inst, pdk) -> Fragment:
    """KQC λ/4 CPW resonator element: probe line ``pl`` (ports a, b), a coupling capacitor (``type_coupler``) and the
    resonator line from the capacitor to ``resonator_b`` (galvanic termination = short)."""
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    kind = str(p.get("type_coupler", "smooth"))
    nf, lf = _f(p.get("n_fingers"), 1), _f(p.get("l_fingers"), 1)
    res_a, res_b = _f(p.get("res_a"), 10), _f(p.get("res_b"), 10)
    if kind == "smooth":  # KQC cap_params: SmoothCapacitor(finger_control=n_fingers, finger_width=10, finger_gap=5)
        fc, w, s = nf, 10.0, 5.0
        f_len = max((w + s) * (2 * fc - 3), 0.0) + (w + s) * math.pi
        ck = est.coplanar_coupling(max(fc, 0.5) * f_len + 2 * w, w, w, s, eps)
        src = ("rough", "SmoothCapacitor electrode gap (CPS)")
    else:
        cap_p = {"finger_number": int(nf), "finger_length": lf, "finger_gap_end": 5, "finger_gap": 5}
        cap_p["finger_width"] = 15
        if kind == "gap":
            cap_p |= {"finger_length": 0, "finger_gap_end": lf, "finger_gap": 0, "finger_width": 10}
        elif kind == "ground gap":
            cap_p |= {"finger_length": 0, "finger_gap_end": lf, "finger_gap": 50 - lf / 2, "finger_width": 20}
        ck, _, _ = _fingers(cap_p, eps)
        src = ("analytic", f"{kind} finger capacitor (Igreja & Dias 2004)")
    frag = Fragment(
        nodes={"pl": {"island": f"{name}.pl"}, "res": {"island": f"{name}.res"}},
        port_nodes={"a": "pl", "b": "pl", "resonator_b": "res"},
    )
    _C(frag, f"Ck_{name}", "pl", "res", est.cap(ck, *src), f"{name}.n_fingers")
    # both KQC terminations end in the ground plane: "galvanic" (term 0) and "airbridge" (an AirbridgeConnection
    # without its right waveguide, landing on ground)
    term_end = "short"
    length = _f(p.get("resonator_length"), 1000)
    frag.lines.append(
        Line(
            name,
            "res",
            (None, "resonator_b"),
            length,
            res_a,
            res_b,
            ("open", term_end),
            True,
            knob=f"{name}.resonator_length",
        )
    )
    frag.knobs[f"{name}.resonator_length"] = (round(length * 0.8, 1), round(length * 1.25, 1))
    return frag


@register_lom("HangerResonator")
def hanger_resonator_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC hanger resonator: probe line ``pl`` (a, b) and a resonator line (``resonator_a`` … ``resonator_b``,
    unconnected KQC waveguide ends are grounded) coupled to it over ``coupling_length`` across ``ground_width``."""
    p = cell_params(inst)
    length = _f(p.get("resonator_length"), 1000)
    frag = Fragment(
        nodes={"pl": {"island": f"{name}.pl"}, "res": {"island": f"{name}.res"}},
        port_nodes={"a": "pl", "b": "pl", "resonator_a": "res", "resonator_b": "res"},
    )
    frag.lines.append(
        Line(
            name,
            "res",
            ("resonator_a", "resonator_b"),
            length,
            _f(p.get("res_a"), 10),
            _f(p.get("res_b"), 6),
            ("short", "short"),
            True,
            [
                {
                    "node": "pl",
                    "coupling_length_um": _f(p.get("coupling_length"), 500),
                    "ground_gap_um": _f(p.get("ground_width"), 10),
                }
            ],
            knob=f"{name}.resonator_length",
        )
    )
    frag.knobs[f"{name}.resonator_length"] = (round(length * 0.8, 1), round(length * 1.25, 1))
    return frag


@register_lom("SpiralResonatorPolygon")
def spiral_resonator_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC polygon spiral resonator: one resonator line from port a to port b (``term1``/``term2`` > 0 = open)."""
    p = cell_params(inst)
    length = _f(p.get("length"), 5000)
    frag = Fragment(nodes={"res": {"island": f"{name}.res"}}, port_nodes={"a": "res", "b": "res"})
    term = tuple("open" if _f(p.get(t), 0) > 0 else "short" for t in ("term1", "term2"))
    frag.lines.append(
        Line(name, "res", ("a", "b"), length, _f(p.get("a"), 10), _f(p.get("b"), 6), term, True, knob=f"{name}.length")
    )
    return frag


# ---- ports, waveguides, wires -------------------------------------------------------------------------------------
@register_lom("Launcher")
def launcher_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC wire-bond launcher: a 50 Ω port on the conductor its port connects to."""
    return Fragment(
        nodes={"pad": {"island": f"{name}.pad"}}, elements=[port_resistor(name)], port_nodes={"port": "pad"}
    )


@register_lom("LauncherDC")
def launcher_dc_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC DC launcher: a pad to the outside world, modelled as a 50 Ω port (a DC bias source impedance)."""
    return Fragment(
        nodes={"pad": {"island": f"{name}.pad"}},
        elements=[port_resistor(name, note="DC launcher (bias source, 50 Ω)")],
        port_nodes={"port": "pad"},
    )


def _path_length(points) -> float:
    pts = [(float(x), float(y)) for x, y in points]
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))


def _points(shape) -> list[tuple[float, float]]:
    if hasattr(shape, "each_point"):
        return [(p.x, p.y) for p in shape.each_point()]
    if isinstance(shape, str):
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", shape)]
        return list(zip(nums[0::2], nums[1::2]))
    return [tuple(p[:2]) for p in shape or []]


def _composite_points(nodes) -> list[tuple[float, float]]:
    if isinstance(nodes, str):
        return [(float(a), float(b)) for a, b in re.findall(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", nodes)]
    out = []
    for n in nodes or []:
        pos = getattr(n, "position", n)
        out.append((pos.x, pos.y) if hasattr(pos, "x") else tuple(pos[:2]))
    return out


def _line_fragment(name: str, p: dict, length: float, resonator: bool, knob: str | None = None) -> Fragment:
    term = tuple("open" if _f(p.get(t), 0) > 0 else "short" for t in ("term1", "term2"))
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(
        Line(name, "line", ("a", "b"), length, _f(p.get("a"), 10), _f(p.get("b"), 6), term, resonator, knob=knob)
    )
    return frag


@register_lom("WaveguideCoplanar")
def waveguide_coplanar_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC CPW: a line along ``path`` (a wire between two connected ports, a stub resonator if an end is free)."""
    p = cell_params(inst)
    return _line_fragment(name, p, _path_length(_points(p.get("path"))), False)


@register_lom("WaveguideCoplanarCurved")
def waveguide_curved_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC curved CPW segment: a line of r·|alpha| between its ends ``a`` (angle 0) and ``b`` (angle alpha; ports
    from :data:`~quantcore_circuits.layouts.registry.KQC_EXTRA_PORTS`), as WaveguideCoplanar: a wire between
    connected ports, a stub with a free end (no termination: the end runs into ground)."""
    p = cell_params(inst)
    return _line_fragment(name, p, _f(p.get("r"), 100) * abs(_f(p.get("alpha"), math.pi)), False)


@register_lom("WaveguideComposite")
def waveguide_composite_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC composite waveguide: a line along its nodes (straight-segment length; inline elements are ignored)."""
    p = cell_params(inst)
    frag = _line_fragment(name, p, _path_length(_composite_points(p.get("nodes"))), False)
    frag.notes.append(f"{name}: WaveguideComposite inline elements (capacitors, tapers) are not modelled")
    return frag


def _through_line(name: str, length: float, a_um: float, b_um: float) -> Fragment:
    """A pass-through CPW section (``Line.through``): part of the line or wire it joins (open ends: shorted, as KQC
    waveguides without a termination)."""
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(Line(name, "line", ("a", "b"), length, a_um, b_um, ("short", "short"), through=True))
    return frag


@register_lom("WaveguideCoplanarTaper")
def waveguide_taper_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC CPW taper: a pass-through section of ``taper_length`` between a and b (inside a resonator it extends
    the line; the width step is not modelled: mean a/b)."""
    p = cell_params(inst)
    a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
    a2, b2 = _f(p.get("a2"), -1), _f(p.get("b2"), -1)
    a2, b2 = a if a2 < 0 else a2, b if b2 < 0 else b2  # KQC eval_a2 / eval_b2
    return _through_line(name, _f(p.get("taper_length"), 10 * math.pi), (a + a2) / 2, (b + b2) / 2)


@register_lom("Meander")
def meander_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC meander: a resonator line of ``length`` (λ/2 bus between two couplers, λ/4 with one grounded end)."""
    p = cell_params(inst)
    length = _f(p.get("length"), 3000)
    frag = _line_fragment(name, p, length, True, knob=f"{name}.length")
    frag.knobs[f"{name}.length"] = (round(length * 0.8, 1), round(length * 1.25, 1))
    return frag


@register_lom("WaveguideCoplanarSplitter")
def splitter_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC CPW splitter (T / multiway junction): all ports are one conductor."""
    p = cell_params(inst)
    n = len(p.get("lengths") or [11, 11, 11])
    ports = list(p.get("port_names") or "abcdefghij")[:n]
    return Fragment(nodes={"t": {"island": f"{name}.t"}}, port_nodes={str(q): "t" for q in ports})


def _wire(name: str, ports=("a", "b")) -> Fragment:
    return Fragment(nodes={"w": {"island": f"{name}.w"}}, port_nodes={q: "w" for q in ports})


@register_lom("AirbridgeConnection")
def airbridge_connection_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC airbridge connection (CPW → bridge → CPW): a pass-through section (length: the builder takes the port
    distance)."""
    p = cell_params(inst)
    return _through_line(name, 0.0, _f(p.get("a"), 10), _f(p.get("b"), 6))


@register_lom("Airbridge")
def airbridge_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC airbridges (rectangular, multi-face): a wire between their two pads; with no port joined, a ground strap
    (``Fragment.straps``: both pads on the ground plane, ports → gnd)."""
    frag = _wire(name)
    frag.straps.append("w")
    return frag


# ---- junctions, flux lines ----------------------------------------------------------------------------------------
def _spaced(cls_name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", cls_name).lower()


@register_lom("Junction")
def junction_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """A stand-alone junction cell (KQC/Quantcore ``Squid`` subclasses): JJ/SQUID from ``common`` to ground.

    The junction's lower electrode is the ground plane edge (its ``origin_squid``); ``Sim`` junctions expose the
    lumped-port ends ``squid_a`` (island side) and ``squid_b`` (ground side). ``NoSquid`` has no junction.
    """
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    cls_name = resolve_cell(inst.cell).__name__
    kind = junction_kind(_spaced(cls_name))
    frag = Fragment(nodes={"j": {"island": f"{name}.island"}}, port_nodes={"common": "j"})
    if cls_name == "Sim":  # the simulation junction's lumped-port ends
        frag.port_nodes |= {"squid_a": "j", "squid_b": "gnd"}
    if kind is None:
        frag.notes.append(f"{name}: {cls_name} has no junction")
        return frag
    from kqcircuits.util.library_helper import to_library_name  # pylint: disable=import-outside-toplevel

    drawn = {"junction_type": to_library_name(cls_name), "junction_params": dict(inst.params or {})}
    frag.elements.append(junction_element(name, "j", "gnd", inst, kind, drawn_params=drawn))
    return frag


@register_lom("Fluxline")
def fluxline_lom(name: str, inst, pdk) -> Fragment:  # noqa: ARG001
    """KQC flux line: its ``flux`` port carries a flux-bias control (no circuit element)."""
    return Fragment(port_nodes={"flux": "control:flux"}, notes=[f"{name}: flux line (control only)"])

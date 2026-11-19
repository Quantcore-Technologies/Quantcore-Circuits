"""LOM models for Quantum Metal components placed through the ``"metal:<Class>"`` wrapper (:mod:`quantcore_circuits.
layouts.metal`): instance ``params`` are Metal options, ports are Metal pin names, junction ends ``squid_a/_b``.

=========================================  ===========================================================================
Metal class                                lumped model (local nodes → FEM labels ``<inst>.<node>``)
=========================================  ===========================================================================
TransmonPocket, …CL, …6, …Teeth            floating: ``island1`` = pad_top, ``island2`` = pad_bot, JJ between; per
                                           connection pad a coupler node (C_g to its pad, a small C to the far pad,
                                           C to ground); CL: ``Charge_Line`` drive port
TransmonCross, TransmonCrossFL,            grounded cross / star: island + JJ (FL: SQUID + ``flux_line`` control);
TransmonStar                               per claw a coupler node
TransmonConcentric, …Type2                 floating: ``island1`` = outer ring, ``island2`` = inner disk, SQUID
                                           (two JJs) between; readout coupler node; flux-bias pins → control
TransmonInterdigitated                     floating: island1 = top pad, island2 = bottom pad; readout (bottom),
                                           bus1/bus2 (top)
StarQubit                                  grounded centre island + JJ; 4 coupler pads + readout pad
TunableCoupler01                           grounded coupler island + SQUID; ``Control`` claw node; ``Flux`` control
TunableCoupler02                           floating pads + SQUID; bus line (pin1–pin2) coupled to both; ``fbl``
CapNInterdigital, Cap3Interdigital,        π network between the two pins
CapFingerInFrame
CapNInterdigitalTee                        primary line (prime_start = prime_end) + IDC to ``second_end``
CoupledLineTee                             primary line + a coupled line (component line with a HANGER section to the
                                           primary): continued by the route on ``second_end`` it becomes the
                                           resonator (λ/4 for a shorted coupler end, λ/2 for an open one)
LineTee                                    one conductor (T-junction)
ResonatorCoilRect, ReadoutResFC,           a resonator line from the pin (the coil / the meander)
ResonatorLumped
LaunchpadWirebond(+Driven)                 50 Ω port on ``tie`` (Driven: ``in`` is the pad itself)
LaunchpadWirebondCoupled                   50 Ω pad + coupling C to ``tie``
OpenToGround / ShortToGround               zero-length line ending open / shorted: a route into it is a λ/2 / λ/4
Airbridge                                  wire
PolylineCPW                                a line (wire, or a stub resonator with a free end)
SNAIL                                      JJ between a and b (linearised SNAIL inductance)
jj_dolan, jj_manhattan, SQUID_LOOP,        no pins: a junction drawn into other metal; no circuit element (declare
BridgeFreeJunction                         it as part of the qubit)
NSquareSpiral                              (sample shape) a spiral trace from ``spiralPin`` to an open inner end (line)
=========================================  ===========================================================================

Metal-only cells (``METAL_ONLY``: TransmonConcentricType2, TunableCoupler02, ResonatorLumped, NSquareSpiral) draw no
pocket: the models above hold on a pocket (a subtracting Metal shape such as metal:Rectangle ``subtract: true``
covering the cell's origin); without one the builder grounds their ports and adds no elements (a note says so).

Estimates: TransmonPocket is the coupled-pad analytic model anchored on the Metal tutorial Q3D matrix of the default
pocket (``docs/tut/4-Analysis/Q1_TwoTransmon_CapMatrix.txt``); cross / star islands on the Xmon Q3D (CPW-arm
model); claws through a ground strip with the Xmon claw's screening. The rest is analytic or rough (see
:mod:`.estimates`). Junction Lj comes from the design's ``junction`` (else Metal's ``hfss_inductance`` option).
"""

from __future__ import annotations

import json
import math
from functools import cache

from quantcore_circuits.lom import estimates as est
from quantcore_circuits.lom.calibration import estimate
from quantcore_circuits.lom.fragment import (
    METAL_PREFIX,
    EffectiveJunction,
    Element,
    Fragment,
    Line,
    effective_junction,
    junction_kind,
    junction_value,
    metal_class,
    port_resistor,
    register_lom,
)

# Metal tutorial Q3D of the default TransmonPocket with two default connection pads (fF; any substrate: only the
# ratios to the analytic model at the same geometry are used)
POCKET_Q3D = {"C12": 30.61, "C_pad": 39.83, "Cg": 19.16, "Cg_far": 2.01, "Cc": 37.29}
POCKET_REF = "Metal tutorial Q3D, TransmonPocket defaults (Q1_TwoTransmon_CapMatrix)"


# ---- options --------------------------------------------------------------------------------------------------
class MetalOptions:
    """A Metal component's options (defaults + the instance's), with µm / number accessors."""

    def __init__(self, cls_name: str, params: dict):
        from quantcore_circuits.layouts.metal import normalise_options, template_options  # pylint: disable=C0415

        tmpl = template_options(cls_name)
        user = {k: v for k, v in params.items() if k in tmpl and not k.startswith("_")}
        self.cls = cls_name
        self.raw = {**tmpl, **normalise_options(cls_name, user)}
        dflt = tmpl.get("_default_connection_pads") or {}
        self.pads = {str(n): {**dflt, **(spec or {})} for n, spec in (self.raw.get("connection_pads") or {}).items()}

    def um(self, key: str, default: float = 0.0, src: dict | None = None) -> float:
        from quantcore_circuits.layouts.metal import parse_um  # pylint: disable=import-outside-toplevel

        v = (src if src is not None else self.raw).get(key)
        if v is None or v == "":
            return default
        try:
            return float(parse_um(v))
        except Exception:  # noqa: BLE001  (Metal's parser raises many types)
            return default

    def num(self, key: str, default: float = 0.0, src: dict | None = None) -> float:
        v = (src if src is not None else self.raw).get(key)
        try:
            return float(str(v).strip())
        except (TypeError, ValueError):
            return default


def metal_mro(cls_name: str) -> list[str]:
    """Metal class names of ``cls_name`` and its bases (for subclasses of qlibrary components)."""
    from quantcore_circuits.layouts.metal.geometry import metal_class as _metal_cls  # pylint: disable=C0415

    try:
        return [k.__name__ for k in _metal_cls(cls_name).__mro__]
    except Exception:  # noqa: BLE001
        return [cls_name]


def _cls(inst) -> str:
    from quantcore_circuits.layouts.metal import canonical_class_name  # pylint: disable=import-outside-toplevel

    return canonical_class_name(metal_class(inst.cell) or inst.cell)


def _opts(inst, cls_name: str | None = None) -> MetalOptions:
    from quantcore_circuits.layouts.metal import flat_options  # pylint: disable=import-outside-toplevel

    return MetalOptions(cls_name or _cls(inst), flat_options(inst.params))


def _C(frag: Fragment, name: str, a: str, b: str, value: dict, knob: str | None = None) -> None:
    frag.elements.append(Element(name, "C", (a, b), value, {"param": knob} if knob else None))


def _junction(
    frag: Fragment, name: str, inst, o: MetalOptions, a: str, b: str, kind: str = "JJ", squid_ends: dict | None = None
) -> None:
    # the wrapper's junction_type (components-pdk): "No Squid" draws none; a trilayer cell sets JJ / SQUID and, with
    # no design value, the drawn junction's L_J / C_J on the PDK rule (effective_junction)
    jtype = str((inst.params or {}).get("junction_type") or "Metal")
    if jtype == "No Squid":
        frag.notes.append(f"{name}: junction_type 'No Squid' → no junction element")
        return
    drawn = {}
    if jtype not in ("Metal", "Sim"):
        from quantcore_circuits.layouts.metal.component import _json_dict  # pylint: disable=C0415

        kind = junction_kind(jtype) or kind
        drawn = {"junction_type": jtype, "junction_params": _json_dict(inst.params.get("junction_params") or "{}")}
    ej = effective_junction(inst, drawn, kind=kind)
    lj, cj, source = ej.lj0_nH, ej.cj_fF, ej.source or "design"
    if lj is None:
        v = o.raw.get("hfss_inductance", o.raw.get("q3d_inductance"))
        try:
            lj = float(str(v).lower().replace("nh", "")) if isinstance(v, str) else float(v) * 1e9
            source = "metal option hfss_inductance"
        except (TypeError, ValueError):
            lj = None
    value = junction_value(EffectiveJunction(lj, cj, ej.flux_phi0, ej.asym, kind, source))
    frag.elements.append(Element(f"J_{name}", kind, (a, b), value, {"param": f"{name}.junction.Lj_nH"}))
    # junction ends (wrapper refpoints): squid_a is the island side of grounded qubits; for the two-pad pockets
    # squid_a lies on pad_bot (island2) and squid_b on pad_top (island1)
    ends = {"squid_a": a, "squid_b": b} if b == "gnd" else squid_ends or {"squid_a": a, "squid_b": b}
    frag.port_nodes.update(ends)
    if lj:
        frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))


# ---- anchors ----------------------------------------------------------------------------------------------------
def _pocket_parts(o: dict, pads: dict, eps: float) -> dict:
    """Analytic pocket model: pads (two_pads) + connection pads (CPS C_g, pad in the pocket + CPW lead to ground)."""
    pw, ph, pg, w_pk, h_pk, cpw = (o[k] for k in ("pad_width", "pad_height", "pad_gap", "pw", "ph", "cpw"))
    c_pad, c12 = est.two_pads(pw, ph, pg, (w_pk - pw) / 2, h_pk / 2 - pg / 2 - ph, eps)
    out = {"C_pad": c_pad, "C12": c12, "pads": {}}
    for name, cp in pads.items():
        cw, chh, cgap = cp["pad_width"], cp["pad_height"], cp["pad_gap"]
        cg = est.coplanar_coupling(cw, chh, ph, cgap, eps)
        top = max(h_pk / 2 - (pg / 2 + ph + cgap + chh), 1.0)
        side = max((w_pk - pw) / 2, 1.0)
        inside = math.hypot(max(side - cp["pocket_extent"] - cp["pad_cpw_extent"], 0.0), cp["pocket_rise"])
        cc = est.pad_to_ground(cw, chh, side, top, eps, open_edges=1)
        cc += est.cpw_line(inside + cp["pad_cpw_extent"], cpw[0], max(top / 2, cpw[1]), eps)
        cc += est.cpw_line(cp["cpw_extend"], cpw[0], cpw[1], eps)
        out["pads"][name] = {"Cg": cg, "Cc": cc}
    return out


_POCKET_DEFAULT = {"pad_width": 455.0, "pad_height": 90.0, "pad_gap": 30.0, "pw": 650.0, "ph": 650.0, "cpw": (10, 6)}
_POCKET_PAD_DEFAULT = {
    "pad_width": 125.0,
    "pad_height": 30.0,
    "pad_gap": 15.0,
    "pocket_extent": 5.0,
    "pad_cpw_extent": 25.0,
    "pocket_rise": 65.0,
    "cpw_extend": 100.0,
}


def _log_distance(geo: dict, ref: dict, keys) -> float:
    """Σ |ln(x / x_ref)| over ``keys``: how far a geometry is from a calibration point (0 = the same)."""
    return sum(abs(math.log(max(float(geo[k]), 1e-9) / float(ref[k]))) for k in keys if ref.get(k))


@cache
def _pocket_anchor() -> dict:
    ref = _pocket_parts(_POCKET_DEFAULT, {"p": _POCKET_PAD_DEFAULT}, 11.45)
    return {
        "C12": POCKET_Q3D["C12"] / ref["C12"],
        "C_pad": POCKET_Q3D["C_pad"] / ref["C_pad"],
        "Cg": POCKET_Q3D["Cg"] / ref["pads"]["p"]["Cg"],
        "Cc": POCKET_Q3D["Cc"] / ref["pads"]["p"]["Cc"],
        "far": POCKET_Q3D["Cg_far"] / POCKET_Q3D["Cg"],
    }


@cache
def _cross_anchor(pdk_name: str) -> float:
    ref, _ = estimate("Xmon", "C_island", {"cross_length": 300.0}, pdk_name)
    ana = est.cross_island([150.0] * 4, 25.0, 25.0, est.substrate_eps(pdk_name))
    return ref / ana if ref else 1.0


@cache
def _claw_screening(pdk_name: str) -> float:
    """Xmon claw Q3D C_g over the unscreened CPS model of the same claw (ground sliver between claw and arm)."""
    cg, _ = estimate("Xmon", "Cg", {"claw_length": 100.0}, pdk_name)
    eps = est.substrate_eps(pdk_name)
    facing = 25.0 + 2 * 25.0 + 2 * 100.0  # arm tip (arm + gaps) + both fingers
    return cg / est.coplanar_coupling(facing, 25.0, 25.0, 25.0 + 2.0 + 2.0, eps) if cg else 0.2


# ---- qubits -----------------------------------------------------------------------------------------------------
def _pocket_lom(name: str, inst, pdk, drive_pin: str | None = None) -> Fragment:
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    geo = {
        "pad_width": o.um("pad_width", 455),
        "pad_height": o.um("pad_height", 90),
        "pad_gap": o.um("pad_gap", 30),
        "pw": o.um("pocket_width", 650),
        "ph": o.um("pocket_height", 650),
    }
    pads, sides = {}, {}
    for pname, cp in o.pads.items():
        pads[pname] = {k: o.um(k, _POCKET_PAD_DEFAULT[k], cp) for k in _POCKET_PAD_DEFAULT}
        sides[pname] = "island1" if o.num("loc_H", 1, cp) >= 0 else "island2"
        geo["cpw"] = (o.um("cpw_width", 10, cp), o.um("cpw_gap", 6, cp))
    geo.setdefault("cpw", (10.0, 6.0))
    parts = _pocket_parts(geo, pads, eps)
    k = _pocket_anchor()
    # the anchor is exact at the calibration geometry; its weight decays with the log-distance from it
    d_q = _log_distance(geo, _POCKET_DEFAULT, ("pad_width", "pad_height", "pad_gap", "pw", "ph"))
    w_q = math.exp(-d_q)
    frag = Fragment(nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}})
    f = f"coupled pads in a pocket (analytic) × Q3D anchor^{w_q:.2f} ({POCKET_REF})"
    c_pad = k["C_pad"] ** w_q * parts["C_pad"]
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(c_pad, "analytic", f), f"{name}.pad_width")
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c_pad, "analytic", f), f"{name}.pad_width")
    c12 = k["C12"] ** w_q * parts["C12"]
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "analytic", f), f"{name}.pad_gap")
    _junction(frag, name, inst, o, "island1", "island2", squid_ends={"squid_a": "island2", "squid_b": "island1"})
    for pname, part in parts["pads"].items():
        near = sides[pname]
        far = "island2" if near == "island1" else "island1"
        frag.nodes[pname] = {"island": f"{name}.{pname}"}
        frag.port_nodes[pname] = pname
        w_p = math.exp(-(d_q + _log_distance(pads[pname], _POCKET_PAD_DEFAULT, ("pad_width", "pad_height", "pad_gap"))))
        cg = k["Cg"] ** w_p * part["Cg"]
        fc = f"connection pad facing its qubit pad (CPS) × Q3D anchor^{w_p:.2f} ({POCKET_REF})"
        _C(frag, f"Cg_{name}_{pname}", near, pname, est.cap(cg, "analytic", fc), f"{name}.connection_pads.{pname}")
        _C(frag, f"Cf_{name}_{pname}", far, pname, est.cap(k["far"] * cg, "rough", "far-pad share of C_g (Q3D ratio)"))
        fcc = f"connection pad + lead to ground × Q3D anchor^{w_p:.2f} ({POCKET_REF})"
        _C(frag, f"Cc_{name}_{pname}", pname, "gnd", est.cap(k["Cc"] ** w_p * part["Cc"], "analytic", fcc))
    if drive_pin:
        frag.port_nodes[drive_pin] = "control:drive"
    return frag


@register_lom(f"{METAL_PREFIX}TransmonPocket")
def transmon_pocket_lom(name, inst, pdk):
    """Metal TransmonPocket: floating two-pad transmon with connection pads (see module table)."""
    return _pocket_lom(name, inst, pdk)


@register_lom(f"{METAL_PREFIX}TransmonPocketCL")
def transmon_pocket_cl_lom(name, inst, pdk):
    """Metal TransmonPocketCL: TransmonPocket + charge line (``Charge_Line`` → drive control)."""
    return _pocket_lom(name, inst, pdk, drive_pin="Charge_Line")


@register_lom(f"{METAL_PREFIX}TransmonPocket6")
def transmon_pocket6_lom(name, inst, pdk):
    """Metal TransmonPocket6: TransmonPocket with up to six connection pads (loc_H picks the pad)."""
    return _pocket_lom(name, inst, pdk)


@register_lom(f"{METAL_PREFIX}TransmonPocketTeeth")
def transmon_pocket_teeth_lom(name, inst, pdk):
    """Metal TransmonPocketTeeth: TransmonPocket with tooth-shaped connection pads (estimated as rectangles)."""
    frag = _pocket_lom(name, inst, pdk)
    frag.notes.append(f"{name}: tooth connection pads estimated as rectangles (rough)")
    return frag


def _claws(frag, name, o: MetalOptions, eps, island: str, arm_w: float, arm_gap: float, pdk) -> None:
    screen = _claw_screening(pdk.name)
    for pname, cp in o.pads.items():
        c_g, c_l, c_w = o.um("claw_gap", 6, cp), o.um("claw_length", 30, cp), o.um("claw_width", 10, cp)
        g_s = o.um("ground_spacing", 5, cp)
        c_c_l = o.um("claw_cpw_length", 40, cp)
        frag.nodes[pname] = {"island": f"{name}.{pname}"}
        frag.port_nodes[pname] = pname
        s = arm_gap + g_s + c_g
        if int(o.num("connector_type", 0, cp)) == 0:
            height = 2 * c_g + 2 * c_w + 2 * g_s + 2 * arm_gap + arm_w
            cg = est.coplanar_coupling(arm_w + 2 * arm_gap + 2 * c_l, c_w, arm_w, s, eps, screen)
            cc = est.cpw_line(height + 2 * c_l + c_c_l, c_w, c_g, eps)
            fg = f"claw around the arm tip (CPS) × {screen:.2f} ground-strip screening (Xmon claw Q3D)"
        else:
            cg = est.coplanar_coupling(c_w, c_w, arm_w, s, eps, screen)
            cc = est.cpw_line(4 * c_w + c_c_l, c_w, c_g, eps)
            fg = "gap connector facing the arm tip (CPS, screened)"
        _C(frag, f"Cg_{name}_{pname}", island, pname, est.cap(cg, "rough", fg), f"{name}.connection_pads.{pname}")
        _C(frag, f"Cc_{name}_{pname}", pname, "gnd", est.cap(cc, "analytic", "claw as CPW (claw width/gap) + stub"))


def _cross_lom(name, inst, pdk, flux_pin: str | None = None) -> Fragment:
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    length, width, gap = o.um("cross_length", 200), o.um("cross_width", 20), o.um("cross_gap", 20)
    anchor = _cross_anchor(pdk.name)
    frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
    c = anchor * est.cross_island([length] * 4, width, gap, eps)
    f = f"CPW-arm cross ({width:g}/{gap:g} µm) × {anchor:.3f} Xmon Q3D anchor"
    _C(frag, f"C_{name}", "island", "gnd", est.cap(c, "analytic", f), f"{name}.cross_length")
    _junction(frag, name, inst, o, "island", "gnd", "SQUID" if flux_pin else "JJ")
    _claws(frag, name, o, eps, "island", width, gap, pdk)
    if flux_pin:
        frag.port_nodes[flux_pin] = "control:flux"
    return frag


@register_lom(f"{METAL_PREFIX}TransmonCross")
def transmon_cross_lom(name, inst, pdk):
    """Metal TransmonCross (Xmon-type): grounded cross, JJ on the south arm, claw connection pads."""
    return _cross_lom(name, inst, pdk)


@register_lom(f"{METAL_PREFIX}TransmonCrossFL")
def transmon_cross_fl_lom(name, inst, pdk):
    """Metal TransmonCrossFL: TransmonCross with a flux line (``flux_line`` control, junction as SQUID)."""
    return _cross_lom(name, inst, pdk, flux_pin="flux_line")


@register_lom(f"{METAL_PREFIX}TransmonStar")
def transmon_star_lom(name, inst, pdk):
    """Metal TransmonStar: grounded star (N arms as CPW sections), JJ on one arm, claw connection pads."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    n = int(o.num("num_points", 6))
    length, width, gap = o.um("arm_length", 150), o.um("arm_width", 20), o.um("arm_gap", 20)
    anchor = _cross_anchor(pdk.name)
    frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
    c = anchor * est.cross_island([length] * n, width, gap, eps)
    f = f"{n} CPW arms ({width:g}/{gap:g} µm) × {anchor:.3f} Xmon Q3D anchor"
    _C(frag, f"C_{name}", "island", "gnd", est.cap(c, "analytic", f), f"{name}.arm_length")
    _junction(frag, name, inst, o, "island", "gnd")
    _claws(frag, name, o, eps, "island", width, gap, pdk)
    return frag


@register_lom(f"{METAL_PREFIX}TransmonConcentric")
def transmon_concentric_lom(name, inst, pdk):
    """Metal TransmonConcentric: floating disk (rad_i) + ring (rad_i + gap … rad_o), two JJs = SQUID between;
    ``pin1`` readout line over the ring (coupler node), ``pin2``/``pin3`` the flux-bias loop (controls)."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    r_i, r_o, gap = o.um("rad_i", 115), o.um("rad_o", 170), o.um("gap", 35)
    w_ring = max(r_o - r_i - gap, 1.0)
    clear = max(min(o.um("pocket_h", 1000), o.um("pocket_w", 1500)) / 2 - r_o, 1.0)
    frag = Fragment(nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}})
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(est.ring_to_ground(r_o, w_ring, clear, eps), "rough", "ring"))
    c2 = est.disk_to_ground(r_i, clear + w_ring + gap, eps) * (gap / (gap + w_ring)) ** 2
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c2, "rough", "disk to ground, screened by the ring"))
    c12 = est.concentric_rings(r_i, r_i + gap, eps)
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "rough", "disk–ring facing edges (CPS)"), f"{name}.gap")
    _junction(frag, name, inst, o, "island1", "island2", "SQUID")
    cpw = o.um("cpw_width", 10)
    s = o.um("res_s", 100)
    frag.nodes["pin1"] = {"island": f"{name}.pin1"}
    frag.port_nodes["pin1"] = "pin1"
    run = o.um("pocket_w", 1500) / 2 + o.um("res_ext", 100)
    cg = est.coplanar_coupling(2 * r_o, cpw, w_ring, s, eps)
    _C(frag, f"Cg_{name}_pin1", "island1", "pin1", est.cap(cg, "rough", "readout line over the ring (CPS)"))
    cc = est.cpw_line(run, cpw, clear / 2, eps)
    _C(frag, f"Cc_{name}_pin1", "pin1", "gnd", est.cap(cc, "rough", "readout line in the pocket (wide-gap CPW)"))
    frag.port_nodes["pin2"] = "control:flux"
    frag.port_nodes["pin3"] = "control:flux"
    return frag


@register_lom(f"{METAL_PREFIX}TransmonConcentricType2")
def transmon_concentric2_lom(name, inst, pdk):
    """Metal TransmonConcentricType2: floating disk (rad_inner) + ring (… rad_outer), SQUID between; pins pin1–3
    are coupler fingers on the ring (rough)."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    r_in, r_out, gap = o.um("rad_inner", 1000), o.um("rad_outer", 2000), o.um("gap", 500)
    clear = max(min(o.um("pocket_w", 10000), o.um("pocket_h", 10000)) / 2 - r_out, 1.0)
    frag = Fragment(nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}})
    w_ring = max(r_out - r_in - gap, 1.0)
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(est.ring_to_ground(r_out, w_ring, clear, eps), "rough", "ring"))
    c2 = est.disk_to_ground(r_in, clear + w_ring + gap, eps) * (gap / (gap + w_ring)) ** 2
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(c2, "rough", "disk to ground, screened by the ring"))
    c12 = est.concentric_rings(r_in, r_in + gap, eps)
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "rough", "disk–ring facing edges (CPS)"))
    _junction(frag, name, inst, o, "island1", "island2", "SQUID")
    for i, corner in enumerate(("NE", "NW", "SW"), start=1):
        pin = f"pin{i}"
        fl, fw = o.um(f"finger_{corner}_length", 500), o.um(f"finger_{corner}_width", 100)
        cgap = o.um(f"coupler_{corner}_gap", 100)
        frag.nodes[pin] = {"island": f"{name}.{pin}"}
        frag.port_nodes[pin] = pin
        cg = est.coplanar_coupling(fl, fw, w_ring, cgap, eps)
        _C(frag, f"Cg_{name}_{pin}", "island1", pin, est.cap(cg, "rough", f"{corner} finger along the ring (CPS)"))
        _C(frag, f"Cc_{name}_{pin}", pin, "gnd", est.cap(est.cpw_line(fl, fw, cgap, eps), "rough", "finger as CPW"))
    return frag


@register_lom(f"{METAL_PREFIX}TransmonInterdigitated")
def transmon_interdigitated_lom(name, inst, pdk):
    """Metal TransmonInterdigitated: floating pads (top = island1, bottom = island2) with 4 fingers each."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    pw, ph = o.um("pad_width", 1000), o.um("pad_height", 300)
    fw, fh, fs = o.um("finger_width", 50), o.um("finger_height", 100), o.um("finger_space", 50)
    frag = Fragment(nodes={"island1": {"island": f"{name}.island1"}, "island2": {"island": f"{name}.island2"}})
    c12 = est.interdigital(8, fw, fs, fh, eps) + est.coplanar_coupling(pw, ph, ph, fh + fs, eps)
    cpad = est.pad_to_ground(pw, ph, fh, fh, eps, open_edges=1)
    f = "4 + 4 interdigital fingers (Igreja & Dias) + pad edges (CPS)"
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "rough", f), f"{name}.finger_height")
    _C(frag, f"C_{name}_1", "island1", "gnd", est.cap(cpad, "rough", "pad in its pocket"))
    _C(frag, f"C_{name}_2", "island2", "gnd", est.cap(cpad, "rough", "pad in its pocket"))
    _junction(frag, name, inst, o, "island1", "island2")
    for pin, isl, pre in (
        ("readout", "island2", "cc"),
        ("bus1", "island1", "cc_topleft"),
        ("bus2", "island1", "cc_topright"),
    ):
        w, h, s = o.um(f"{pre}_width", 100), o.um(f"{pre}_height", 100), o.um(f"{pre}_space", 50)
        frag.nodes[pin] = {"island": f"{name}.{pin}"}
        frag.port_nodes[pin] = pin
        _C(frag, f"Cg_{name}_{pin}", isl, pin, est.cap(est.coplanar_coupling(w, h, ph, s, eps), "rough", "CPS"))
        _C(frag, f"Cc_{name}_{pin}", pin, "gnd", est.cap(est.pad_to_ground(w, h, s, s, eps, 1), "rough", "pad"))
    return frag


@register_lom(f"{METAL_PREFIX}StarQubit")
def star_qubit_lom(name, inst, pdk):
    """Metal StarQubit: grounded star-shaped centre island + JJ, four coupler pads and a readout pad around it."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    r, rc = o.um("radius", 300), o.um("center_radius", 100)
    g_c, g_r = o.um("gap_couplers", 25), o.um("gap_readout", 10)
    n = int(o.num("number_of_connectors", 4))
    frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
    c_is = est.disk_to_ground(rc, (r - rc) / 2, eps)
    _C(frag, f"C_{name}", "island", "gnd", est.cap(c_is, "rough", "centre island as a disk (star arms neglected)"))
    _junction(frag, name, inst, o, "island", "gnd")
    pins = [f"pin_cpl{i + 1}" for i in range(n)] + ["pin_rdout"]
    arc = 2 * math.pi * (rc + (r - rc) / 2) / max(len(pins), 1)
    for pin in pins:
        s = g_r if pin == "pin_rdout" else g_c
        frag.nodes[pin] = {"island": f"{name}.{pin}"}
        frag.port_nodes[pin] = pin
        cg = est.coplanar_coupling(arc, (r - rc) / 2, rc, s, eps)
        _C(frag, f"Cg_{name}_{pin}", "island", pin, est.cap(cg, "rough", "pad sector facing the island (CPS)"))
        cc = arc * est.cpw_c_per_um((r - rc) / 2, s, eps) / 2
        _C(frag, f"Cc_{name}_{pin}", pin, "gnd", est.cap(cc, "rough", "pad outer edge (half CPW)"))
    return frag


@register_lom(f"{METAL_PREFIX}TunableCoupler01")
def tunable_coupler01_lom(name, inst, pdk):
    """Metal TunableCoupler01: grounded coupler island (interdigitated C to ground) + SQUID to ground; ``Control`` is
    the coupler claw (circuit node), ``Flux`` the flux line."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    cw, lw, lg, ah = o.um("c_width", 400), o.um("l_width", 20), o.um("l_gap", 10), o.um("a_height", 60)
    frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
    n = max(int(cw / (2 * (lw + lg))), 2)
    c_is = est.interdigital(n, lw, lg, ah, eps)
    _C(frag, f"C_{name}", "island", "gnd", est.cap(c_is, "rough", f"{n}-finger comb to ground (Igreja & Dias)"))
    _junction(frag, name, inst, o, "island", "gnd", "SQUID")
    arm, aw, gap = o.um("cp_arm_length", 30), o.um("cp_arm_width", 6), o.um("cp_gap", 6)
    frag.nodes["Control"] = {"island": f"{name}.Control"}
    frag.port_nodes["Control"] = "Control"
    cg = est.coplanar_coupling(2 * arm + o.um("cp_height", 15), aw, lw, gap + o.um("cp_gspace", 3), eps)
    _C(frag, f"Cg_{name}_Control", "island", "Control", est.cap(cg, "rough", "coupler arm (CPS)"))
    _C(frag, f"Cc_{name}_Control", "Control", "gnd", est.cap(est.cpw_line(2 * arm, aw, gap, eps), "rough", "arm"))
    frag.port_nodes["Flux"] = "control:flux"
    return frag


@register_lom(f"{METAL_PREFIX}TunableCoupler02")
def tunable_coupler02_lom(name, inst, pdk):
    """Metal TunableCoupler02: two circular pads (floating) + SQUID; a bus CPW (pin1–pin2) passes both pads."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    r = o.um("pad_radius", 300)
    clear = max(min(o.um("pocket_width", 3000), o.um("pocket_height", 2000)) / 2 - r, 1.0)
    jl = o.um("JJ_length", 400)
    frag = Fragment(
        nodes={
            "island1": {"island": f"{name}.island1"},
            "island2": {"island": f"{name}.island2"},
            "bus": {"island": f"{name}.bus"},
        },
        port_nodes={"pin1": "bus", "pin2": "bus", "fbl": "control:flux"},
    )
    for i in (1, 2):
        c = est.disk_to_ground(r, clear, eps)
        _C(frag, f"C_{name}_{i}", f"island{i}", "gnd", est.cap(c, "rough", "pad as a disk in the pocket"))
        bw = o.um("bus_width", 100)
        cg = est.coplanar_coupling(o.um("bus_inner_length", 500), bw, r, o.um("bus_JJ_height", 500) / 4, eps)
        _C(frag, f"Cb_{name}_{i}", f"island{i}", "bus", est.cap(cg, "rough", "bus line past the pad (CPS)"))
    c12 = est.coplanar_coupling(2 * r, r, r, jl, eps)
    _C(frag, f"C_{name}_12", "island1", "island2", est.cap(c12, "rough", "pads across the junction gap (CPS)"))
    _C(
        frag,
        f"Cc_{name}_bus",
        "bus",
        "gnd",
        est.cap(est.cpw_line(2 * o.um("bus_outer_length", 500), o.um("bus_width", 100), 50, eps), "rough", "bus"),
    )
    _junction(frag, name, inst, o, "island1", "island2", "SQUID")
    return frag


# ---- capacitors, tees -------------------------------------------------------------------------------------------
def _pi(name, pa, pb, cab, ca, cb, kind, formula, kind_g="rough", formula_g="pads to ground") -> Fragment:
    frag = Fragment(
        nodes={"a": {"island": f"{name}.{pa}"}, "b": {"island": f"{name}.{pb}"}}, port_nodes={pa: "a", pb: "b"}
    )
    _C(frag, f"C_{name}", "a", "b", est.cap(cab, kind, formula))
    _C(frag, f"C_{name}_a", "a", "gnd", est.cap(ca, kind_g, formula_g))
    _C(frag, f"C_{name}_b", "b", "gnd", est.cap(cb, kind_g, formula_g))
    return frag


@register_lom(f"{METAL_PREFIX}CapNInterdigital")
def cap_n_interdigital_lom(name, inst, pdk):
    """Metal CapNInterdigital: N-finger IDC between ``north_end`` and ``south_end``."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    n, w, g, fl = int(o.num("finger_count", 5)), o.um("cap_width", 10), o.um("cap_gap", 6), o.um("finger_length", 20)
    area = n * w + (n - 1) * g
    cab = est.interdigital(n, w, g, fl, eps) if fl > 0 else est.coplanar_coupling(area, w, w, g, eps)
    cg = est.pad_to_ground(area, fl / 2 + w, o.um("cap_gap_ground", 6), o.um("cap_gap_ground", 6), eps, 1)
    cg += est.cpw_line(o.um("cap_distance", 50), o.um("north_width", 10), o.um("north_gap", 6), eps)
    kind, formula = (
        ("analytic", "interdigital (Igreja & Dias 2004)") if fl > 0 else ("rough", "plates facing across cap_gap (CPS)")
    )
    return _pi(name, "north_end", "south_end", cab, cg, cg, kind, formula)


@register_lom(f"{METAL_PREFIX}Cap3Interdigital")
def cap3_interdigital_lom(name, inst, pdk):
    """Metal Cap3Interdigital: three-finger IDC (finger width = gap = trace width) between ``a`` and ``b``."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    w, fl = o.um("trace_width", 10), o.um("finger_length", 65)
    cab = est.interdigital(3, w, w, fl, eps)
    cg = est.pad_to_ground(
        3 * w + 2 * w, fl / 2, o.um("pocket_buffer_width_x", 10), o.um("pocket_buffer_width_y", 30), eps
    )
    return _pi(name, "a", "b", cab, cg / 2, cg / 2, "analytic", "3-finger interdigital (Igreja & Dias 2004)")


@register_lom(f"{METAL_PREFIX}CapFingerInFrame")
def cap_finger_in_frame_lom(name, inst, pdk):
    """Metal CapFingerInFrame: a finger (pin ``finger``) inside a U frame (pin ``frame``): C along both sides."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    length, width, trace, gap = (
        o.um(k, d) for k, d in (("frame_length", 245), ("frame_width", 72), ("frame_trace", 16), ("cap_gap", 10))
    )
    finger_w = max(width - 2 * trace - 2 * gap, 1.0)
    cab = est.coplanar_coupling(2 * length, finger_w, trace, gap, eps)
    cg = est.cpw_line(2 * length + width, trace, o.um("ground_gap", 10), eps) / 2
    return _pi(name, "frame", "finger", cab, cg, 0.1 * cg, "analytic", "finger sides facing the frame (CPS)")


@register_lom(f"{METAL_PREFIX}CapNInterdigitalTee")
def cap_n_interdigital_tee_lom(name, inst, pdk):
    """Metal CapNInterdigitalTee: primary CPW (prime_start = prime_end, one conductor) + IDC to ``second_end``."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    n, w, g, fl = int(o.num("finger_count", 5)), o.um("cap_width", 10), o.um("cap_gap", 6), o.um("finger_length", 20)
    frag = Fragment(
        nodes={"prime": {"island": f"{name}.prime"}, "second": {"island": f"{name}.second_end"}},
        port_nodes={"prime_start": "prime", "prime_end": "prime", "second_end": "second"},
    )
    if fl > 0:
        c_ps = est.cap(est.interdigital(n, w, g, fl, eps), "analytic", "IDC")
    else:  # no fingers: Metal still draws the two plates (n·w + (n−1)·g wide) facing across cap_gap
        plate = n * w + (n - 1) * g
        c_ps = est.cap(est.coplanar_coupling(plate, w, w, g, eps), "rough", "plates facing across cap_gap (CPS)")
    _C(frag, f"C_{name}", "prime", "second", c_ps)
    cc = est.cpw_line(o.um("cap_distance", 50), o.um("second_width", 10), o.um("second_gap", 6), eps)
    _C(frag, f"C_{name}_second", "second", "gnd", est.cap(cc, "rough", "second-line stub to ground"))
    return frag


@register_lom(f"{METAL_PREFIX}CoupledLineTee")
def coupled_line_tee_lom(name, inst, pdk):  # noqa: ARG001
    """Metal CoupledLineTee: primary CPW + a parallel coupled line (``coupling_length`` at ``coupling_space``) whose
    coupler end is open (``open_termination``) or shorted; the route on ``second_end`` continues it as a resonator."""
    o = _opts(inst)
    open_end = str(o.raw.get("open_termination", True)).lower() in ("true", "1")
    frag = Fragment(
        nodes={"prime": {"island": f"{name}.prime"}, "second": {"island": f"{name}.second_end"}},
        port_nodes={"prime_start": "prime", "prime_end": "prime", "second_end": "second"},
    )
    lc = o.um("coupling_length", 100)
    frag.lines.append(
        Line(
            name,
            "second",
            (None, "second_end"),
            lc + o.um("down_length", 100),
            o.um("second_width", 10),
            o.um("second_gap", 6),
            ("open" if open_end else "short", "open"),
            True,
            [{"node": "prime", "coupling_length_um": lc, "ground_gap_um": o.um("coupling_space", 3)}],
        )
    )
    frag.notes.append(f"{name}: coupled-line κ uses the hanger k for a {o.um('coupling_space', 3):g} µm gap (rough)")
    return frag


@register_lom(f"{METAL_PREFIX}LineTee")
def line_tee_lom(name, inst, pdk):  # noqa: ARG001
    """Metal LineTee: a T-junction, all three pins one conductor."""
    return Fragment(
        nodes={"t": {"island": f"{name}.t"}}, port_nodes={"prime_start": "t", "prime_end": "t", "second_end": "t"}
    )


# ---- resonators -------------------------------------------------------------------------------------------------
@register_lom(f"{METAL_PREFIX}ResonatorCoilRect")
def resonator_coil_lom(name, inst, pdk):  # noqa: ARG001
    """Metal ResonatorCoilRect: a rectangular-spiral resonator of ``length`` (``line_width``/``gap``) from
    ``spiralPin``; its inner end is open."""
    o = _opts(inst)
    frag = Fragment(nodes={"res": {"island": f"{name}.res"}}, port_nodes={"spiralPin": "res"})
    frag.lines.append(
        Line(
            name,
            "res",
            ("spiralPin", None),
            o.um("length", 2000),
            o.um("line_width", 1),
            o.um("gap", 4),
            ("open", "open"),
            True,
        )
    )
    return frag


@register_lom(f"{METAL_PREFIX}ReadoutResFC")
def readout_res_fc_lom(name, inst, pdk):  # noqa: ARG001
    """Metal ReadoutResFC: a CPW resonator from the fork/circle coupler (open) through l1 … 5 × l5 to ``readout``."""
    o = _opts(inst)
    r = o.um("readout_cpw_turnradius", 50)
    length = (
        o.um("readout_l1", 400)
        + o.um("readout_l2", 400)
        + o.um("readout_l3", 400)
        + o.um("readout_l4", 250)
        + 5 * o.um("readout_l5", 400)
        + r * math.pi * (0.25 + 0.5 + 1 + 4)
    )
    frag = Fragment(nodes={"res": {"island": f"{name}.res"}}, port_nodes={"readout": "res"})
    frag.lines.append(
        Line(
            name,
            "res",
            (None, "readout"),
            length,
            o.um("readout_cpw_width", 5),
            o.um("readout_cpw_gap", 5),
            ("open", "open"),
            True,
        )
    )
    return frag


@register_lom(f"{METAL_PREFIX}ResonatorLumped")
def resonator_lumped_lom(name, inst, pdk):  # noqa: ARG001
    """Metal ResonatorLumped: a meandered trace shorted to the (grounded) perimeter, open at ``pin_n``: λ/4."""
    o = _opts(inst)
    w = o.um("box_width", 5000)
    n = o.num("n_turns", 14)
    length = o.um("initial", 100) + n * (w - 2 * o.um("outer_space", 100)) + o.um("final", 2500)
    frag = Fragment(nodes={"res": {"island": f"{name}.res"}}, port_nodes={"pin_n": "res"})
    for pin in ("pin_east", "pin_west", "pin_s", "pin_ne", "pin_nw", "pin_se", "pin_sw"):
        frag.port_nodes[pin] = "gnd"
    frag.lines.append(
        Line(
            name,
            "res",
            ("pin_n", None),
            length,
            o.um("res_width", 10),
            o.um("inner_space", 190) / 2,
            ("open", "short"),
            True,
        )
    )
    frag.notes.append(f"{name}: lumped resonator estimated as a λ/4 line of its trace length (rough)")
    return frag


# ---- ports, terminations, wires, junctions ----------------------------------------------------------------------
@register_lom(f"{METAL_PREFIX}LaunchpadWirebond")
def launchpad_lom(name, inst, pdk):  # noqa: ARG001
    """Metal LaunchpadWirebond: a 50 Ω port on its ``tie`` conductor."""
    return Fragment(nodes={"pad": {"island": f"{name}.pad"}}, elements=[port_resistor(name)], port_nodes={"tie": "pad"})


@register_lom(f"{METAL_PREFIX}LaunchpadWirebondDriven")
def launchpad_driven_lom(name, inst, pdk):  # noqa: ARG001
    """Metal LaunchpadWirebondDriven: a 50 Ω port; ``in`` (the driven pad) and ``tie`` are one conductor."""
    return Fragment(
        nodes={"pad": {"island": f"{name}.pad"}}, elements=[port_resistor(name)], port_nodes={"tie": "pad", "in": "pad"}
    )


@register_lom(f"{METAL_PREFIX}LaunchpadWirebondCoupled")
def launchpad_coupled_lom(name, inst, pdk):
    """Metal LaunchpadWirebondCoupled: a 50 Ω pad coupled to the ``tie`` line through a coupler section (rough C)."""
    o = _opts(inst)
    eps = est.substrate_eps(pdk)
    tw, tg = o.um("trace_width", 10), o.um("trace_gap", 6)
    ck = est.coplanar_coupling(2 * o.um("coupler_length", 62.5), tw, tw, tg, eps)
    frag = Fragment(
        nodes={"pad": {"island": f"{name}.pad"}, "tie": {"island": f"{name}.tie"}},
        elements=[port_resistor(name)],
        port_nodes={"tie": "tie"},
    )
    _C(frag, f"Ck_{name}", "pad", "tie", est.cap(ck, "rough", "coupler section (CPS)"))
    _C(
        frag,
        f"C_{name}_tie",
        "tie",
        "gnd",
        est.cap(est.cpw_line(o.um("lead_length", 25), tw, tg, eps), "rough", "lead"),
    )
    return frag


@register_lom(f"{METAL_PREFIX}OpenToGround")
def open_to_ground_lom(name, inst, pdk):  # noqa: ARG001
    """Metal OpenToGround: an open end; a route into it becomes an open-ended (λ/2 or λ/4) resonator."""
    o = _opts(inst)
    frag = Fragment(nodes={"end": {"island": f"{name}.end"}}, port_nodes={"open": "end"})
    frag.lines.append(Line(name, "end", ("open", None), 0.0, o.um("width", 10), o.um("gap", 6), ("open", "open")))
    return frag


@register_lom(f"{METAL_PREFIX}ShortToGround")
def short_to_ground_lom(name, inst, pdk):  # noqa: ARG001
    """Metal ShortToGround: a shorted end; a route into it becomes a shorted (λ/4) resonator end."""
    o = _opts(inst)
    frag = Fragment(nodes={"end": {"island": f"{name}.end"}}, port_nodes={"short": "end"})
    frag.lines.append(Line(name, "end", ("short", None), 0.0, o.um("width", 10), 6.0, ("short", "short")))
    return frag


@register_lom(f"{METAL_PREFIX}Airbridge")
def airbridge_lom(name, inst, pdk):  # noqa: ARG001
    """Metal Airbridge: a wire between its two landing pads; with no port joined, a ground strap (ports → gnd)."""
    return Fragment(nodes={"w": {"island": f"{name}.w"}}, port_nodes={"a": "w", "b": "w"}, straps=["w"])


@register_lom(f"{METAL_PREFIX}PolylineCPW")
def polyline_cpw_lom(name, inst, pdk):  # noqa: ARG001
    """Metal PolylineCPW: a CPW line along ``points`` (wire between connected pins, stub resonator otherwise)."""
    o = _opts(inst)
    pts = o.raw.get("points") or [[0, 0], [0.5, 0]]
    length = 1000.0 * sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))  # Metal bare numbers are mm
    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"start": "line", "end": "line"})
    frag.lines.append(
        Line(name, "line", ("start", "end"), length, o.um("trace_width", 10), o.um("trace_gap", 6), ("open", "open"))
    )
    taps = o.raw.get("taps") or {}
    if isinstance(taps, str):
        try:
            taps = json.loads(taps)
        except ValueError:
            taps = {}
    for tap in taps if isinstance(taps, dict) else []:
        frag.port_nodes[str(tap)] = "line"  # a tap pin on the line: the same conductor (its position is not a line end)
    if taps:
        frag.notes.append(
            f"{name}: tap pin(s) {sorted(map(str, taps))} on the line's conductor (not split at the taps)"
        )
    return frag


@register_lom(f"{METAL_PREFIX}SNAIL")
def snail_lom(name, inst, pdk):  # noqa: ARG001
    """Metal SNAIL: a JJ between pins a and b with the SNAIL's linear inductance (3 Lj in series ∥ Lj_small) unless
    the design gives ``junction.Lj_nH`` (the SNAIL's third-order nonlinearity is not modelled)."""
    o = _opts(inst)
    frag = Fragment(
        nodes={"a": {"island": f"{name}.a"}, "b": {"island": f"{name}.b"}},
        port_nodes={"a": "a", "b": "b", "squid_a": "a", "squid_b": "b"},
    )
    ej = effective_junction(inst, {}, kind="JJ")
    lj, cj, source = ej.lj0_nH, ej.cj_fF, ej.source or "design"
    if lj is None:
        big = float(str(o.raw.get("Lj", "0.046nH")).lower().replace("nh", ""))
        small = float(str(o.raw.get("Lj_small", "0.165nH")).lower().replace("nh", ""))
        lj, source = 3 * big * small / (3 * big + small), "SNAIL options: 3 Lj ∥ Lj_small"
    frag.elements.append(Element(f"J_{name}", "JJ", ("a", "b"), {"Lj_nH": lj, "Cj_fF": cj, "source": source}))
    frag.notes.append(f"{name}: SNAIL as a single JJ (linear inductance only)")
    return frag


def _bare_junction(name, inst, pdk):  # noqa: ARG001
    return Fragment(notes=[f"{name} ({inst.cell}): junction without pins; model it as part of its qubit"])


for _jj in ("jj_dolan", "jj_manhattan", "SQUID_LOOP", "BridgeFreeJunction"):
    register_lom(f"{METAL_PREFIX}{_jj}")(_bare_junction)


# ---- metal-only cells (no pocket) ---------------------------------------------------------------------------------
# Metal draws these as metal only: without a pocket under them they merge into the ground plane (empty in the
# negative mask, as in Metal's own GDS). Their models describe the cell *on a pocket* (catalog recipe: a
# metal:Rectangle with subtract: true); the builder grounds their ports when no pocket covers them.
METAL_ONLY = {
    "TransmonConcentricType2": "Metal leaves its pocket commented out",
    "TunableCoupler02": "Metal computes its pocket but never adds it",
    "ResonatorLumped": "perimeter and trace are both metal",
    "NSquareSpiral": "a metal spiral path",
}


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def metal_only_without_pocket(design, plan, iname: str) -> str | None:
    """A note when ``iname`` is a metal-only Metal cell that no subtracting Metal shape (a pocket) covers: its metal
    is part of the ground plane, so it has no circuit elements; else None."""
    import klayout.db as pya  # pylint: disable=import-outside-toplevel

    inst = design.instances[iname]
    cls = inst.cell[len(METAL_PREFIX) :] if inst.cell.startswith(METAL_PREFIX) else None
    if cls not in METAL_ONLY:
        return None
    if cls == "NSquareSpiral" and _truthy(_opts(inst).raw.get("subtract")):
        return f"{iname}: etched spiral slot (subtract) in the ground plane: no conductor, its pin is ground"
    placed = plan.instances.get(iname)
    if placed is None:
        return None
    origin = placed.trans * pya.DPoint(0, 0)
    for pname, other in design.instances.items():
        if pname == iname or not other.cell.startswith(METAL_PREFIX) or pname not in plan.instances:
            continue
        o = _opts(other)
        if not _truthy(o.raw.get("subtract")):
            continue
        w, h, r = o.um("width", 0.0), o.um("height", 0.0), o.um("radius", 0.0)
        if w > 0 and h > 0:
            box = pya.DBox(-w / 2, -h / 2, w / 2, h / 2)
        elif r > 0:
            box = pya.DBox(-r, -r, r, r)
        else:
            continue
        if (plan.instances[pname].trans * box).contains(origin):
            return None
    return (
        f"{iname} ({inst.cell}): draws metal only ({METAL_ONLY[cls]}) and no pocket (a subtracting Metal shape, e.g. "
        "metal:Rectangle subtract: true) covers it: its metal is ground plane, so its ports are grounded and it has "
        "no elements"
    )


@register_lom(f"{METAL_PREFIX}NSquareSpiral")
def n_square_spiral_lom(name, inst, pdk):  # noqa: ARG001
    """Metal NSquareSpiral (sample shape) on a pocket: a spiral trace from ``spiralPin`` (outer end) to an open inner
    end, as a line (a route into it ends in a stub of the spiral's length). Rough: the CPW formula with a = width,
    b = gap ignores the turns' mutual coupling. Without a pocket the builder grounds the pin (see METAL_ONLY)."""
    o = _opts(inst)
    n, w, g, r = int(o.num("n", 3)), o.um("width", 1), o.um("gap", 4), o.um("radius", 40)
    pts = []  # Metal's polyline (NSquareSpiral.make)
    for k in range(max(n, 1)):
        v = r / 2 + k * (w + g)
        pts += [(-v, -v), (v, -v), (v, v), (-v - (w + g), v)]
    v = r / 2 + max(n, 1) * (w + g)
    pts.append((-v, -v))
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    frag = Fragment(nodes={"spiral": {"island": f"{name}.spiral"}}, port_nodes={"spiralPin": "spiral"})
    frag.lines.append(Line(name, "spiral", ("spiralPin", None), length, w, g, ("open", "open")))
    frag.notes.append(
        f"{name}: spiral trace of {length:.0f} µm as an open-ended line (rough: turns' mutual coupling not included)"
    )
    return frag

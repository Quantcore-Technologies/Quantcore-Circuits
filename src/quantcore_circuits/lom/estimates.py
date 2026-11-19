"""Analytic element estimates for component LOM models (no FEM): planar capacitances by conformal mapping.

Everything here is a closed-form, quasi-static estimate for thin conductors on a thick substrate (sapphire εr 10.25
in the default PDK), with the field split equally between substrate and air: ε_eff = (εr + 1)/2. It is meant for
a first LOM before any C-matrix exists, and it is labelled as such in every element value (``estimate_source``).

**The one primitive.** Two conductors on the boundary of a half-plane occupy the segments [x1, x2] and [x3, x4]
(the rest of the boundary is a Neumann boundary, i.e. the slot / dielectric interface). Their capacitance per unit
length in a half-space of permittivity ε is ε K(k)/K(k'), with the cross ratio
k² = (x2 − x1)(x4 − x3) / ((x3 − x1)(x4 − x2)). Substrate + air give 2 ε0 ε_eff K(k)/K(k'). The standard results
follow from it, and the unit tests check them against each other:

* CPW (centre a, gaps b): C' = 4 ε0 ε_eff K(k)/K(k'), k = a/(a + 2b)   (Wen 1969; Simons, *Coplanar Waveguide*, ch. 2)
* coplanar strips w1, w2 at spacing s, no ground: C' = 2 ε0 ε_eff K(k)/K(k'), k² = w1 w2/((w1 + s)(w2 + s))
  (equal widths: the textbook CPS K(k')/K(k) with k = s/(s + 2w), by Landen's transformation)
* two equal strips w at spacing s inside a ground slot (ground at distance g beyond each strip), z → z² mapping:
  even mode k_e² = (b² − a²)/(c² − a²), odd mode k_o = (c/b)·√((b² − a²)/(c² − a²)) with a = s/2, b = a + w,
  c = b + g; C_ground = C_e, C_mutual = (C_o − C_e)/2 per unit length (edge-coupled CPW, Simons ch. 7)
* interdigital capacitor (N fingers, width w, gap s, overlap L): Igreja & Dias, Sens. Actuators A 112, 291 (2004):
  C = (N − 3) C_I/2 + 2 C_I C_E/(C_I + C_E), C_I,E = ε0 (εr + 1) L K(k)/K(k'), k_I = sin(πη/2),
  k_E = 2√η/(1 + η), η = w/(w + s); within ~10 % of Alley's (εr + 1) L [(N − 3) A1 + A2] (Bahl, *Lumped elements*)

**Accuracy.** Against Q3D: the Xmon island (cross arms as CPW) comes out 13 % high; the two-pad Metal
``TransmonPocket`` mutual capacitance about 25 % high, its pad-to-ground about 20 % high, and the connection-pad C_g
within 20 % (Metal tutorial 4.01). Each estimate carries an ``uncertainty`` and a ``kind``:

* ``"calibration"`` — power law anchored on a FEM run of the same component (:mod:`.calibration`)
* ``"analytic"`` — a conformal-mapping formula applied to the component's own geometry (±25 % typical)
* ``"rough"`` — a geometry the formulas only approximate: screened couplers, curved or spiral electrodes, a
  calibration borrowed from another component (±50 %, or worse)

Values are rounded to 3 significant figures (analytic) or 2 (rough). Units: µm in, fF out. Inside
:func:`exact_values` they are not rounded (the co-design surrogate takes the LOM's sensitivities from small knob
steps, which the rounding would hide).
"""

from __future__ import annotations

import math
from contextlib import contextmanager

EPS0_fF_per_um = 8.8541878128e-3  # ε0 in fF/µm
UNCERTAINTY = {"calibration": "±10%", "analytic": "±25%", "rough": "±50%"}
_EXACT = [False]  # inside exact_values(): cap() keeps every digit


@contextmanager
def exact_values():
    """Within this block :func:`cap` does not round (sensitivities of the estimates to small parameter changes)."""
    old, _EXACT[0] = _EXACT[0], True
    try:
        yield
    finally:
        _EXACT[0] = old


# ---- primitives ----------------------------------------------------------------------------------------------------
def k_ratio(k: float) -> float:
    """K(k)/K(k') with k' = √(1 − k²) (complete elliptic integrals of the first kind)."""
    from scipy.special import ellipk  # pylint: disable=import-outside-toplevel

    k = min(max(k, 1e-12), 1 - 1e-15)
    return float(ellipk(k * k) / ellipk(1 - k * k))


def eps_eff(eps_r: float) -> float:
    """Quasi-static effective permittivity of a planar structure on a thick substrate: (εr + 1)/2."""
    return (eps_r + 1) / 2


def substrate_eps(pdk) -> float:
    """εr of the PDK substrate (``pdk`` is a PDK object, its name, or a number)."""
    if isinstance(pdk, (int, float)):
        return float(pdk)
    if isinstance(pdk, str):
        from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

        pdk = get_pdk(pdk)
    return float(pdk.stack.substrate_permittivity)


def segments_c_per_um(x1: float, x2: float, x3: float, x4: float, eps_r: float) -> float:
    """C' (fF/µm) between boundary segments [x1, x2] and [x3, x4] (x4 may be ``inf``), substrate + air."""
    if math.isinf(x4):
        k2 = (x2 - x1) / (x3 - x1)
    else:
        k2 = (x2 - x1) * (x4 - x3) / ((x3 - x1) * (x4 - x2))
    return 2 * EPS0_fF_per_um * eps_eff(eps_r) * k_ratio(math.sqrt(k2))


# ---- standard structures (per µm) ---------------------------------------------------------------------------------
def cpw_c_per_um(a: float, b: float, eps_r: float) -> float:
    """CPW (centre width a, gaps b) capacitance per µm, fF/µm."""
    return 4 * EPS0_fF_per_um * eps_eff(eps_r) * k_ratio(a / (a + 2 * b))


def cps_c_per_um(w1: float, w2: float, s: float, eps_r: float) -> float:
    """Mutual capacitance per µm of two coplanar strips (widths w1, w2, spacing s), no ground nearby."""
    return segments_c_per_um(0.0, w1, w1 + s, w1 + s + w2, eps_r)


def coupled_strips_per_um(w: float, s: float, g: float, eps_r: float) -> tuple[float, float]:
    """Two equal strips (width w, spacing s) in a ground slot (gap g beyond each): (C to ground, C mutual), fF/µm."""
    a, b = s / 2, s / 2 + w
    c = b + g
    k_e = math.sqrt((b * b - a * a) / (c * c - a * a))
    k_o = min((c / b) * k_e, 1 - 1e-15)
    pre = 2 * EPS0_fF_per_um * eps_eff(eps_r)
    c_e, c_o = pre * k_ratio(k_e), pre * k_ratio(k_o)
    return c_e, (c_o - c_e) / 2


# ---- component-level estimates (fF) -------------------------------------------------------------------------------
def pad_to_ground(w: float, h: float, gap_w: float, gap_h: float, eps_r: float, open_edges: int = 0) -> float:
    """Rectangular pad w × h in a ground cut-out (clearance ``gap_w`` beyond the w-sides... i.e. along x, ``gap_h``
    along y). Sum of the two CPW cross-sections: w·C'_cpw(h, gap_h) + h·C'_cpw(w, gap_w).

    ``open_edges`` (0–2) removes that many long (length w) edges' share, for edges facing another conductor
    instead of ground (half of the first term each).
    """
    long_edges = w * cpw_c_per_um(h, gap_h, eps_r)
    short_edges = h * cpw_c_per_um(w, gap_w, eps_r)
    return long_edges * (1 - open_edges / 2) + short_edges


def cpw_line(length: float, a: float, b: float, eps_r: float) -> float:
    """Shunt capacitance of a CPW stub of ``length`` (lumped: valid for length ≪ λ/4)."""
    return length * cpw_c_per_um(a, b, eps_r)


def cross_island(arm_lengths: list[float], arm_width: float, gap: float, eps_r: float) -> float:
    """Cross (Xmon/Swissmon) island to ground: arms as CPW sections of centre ``arm_width`` and gap ``gap``.

    ``arm_lengths`` are centre-to-tip lengths; the centre square is counted once. The end caps are not counted
    (they roughly compensate the overestimate of treating the arm junctions as straight CPW).
    """
    total = sum(arm_lengths) - arm_width  # the 4 arms overlap in the centre square
    return total * cpw_c_per_um(arm_width, gap, eps_r)


def two_pads(
    pad_w: float, pad_h: float, pad_gap: float, side_gap: float, back_gap: float, eps_r: float
) -> tuple[float, float]:
    """Two equal pads (w × h) facing each other across ``pad_gap`` along their long sides, in a pocket.

    ``back_gap`` is the clearance from each pad's far long edge to the ground, ``side_gap`` from its short edges.
    Returns (C pad → ground, C pad ↔ pad), fF. Long edges: edge-coupled strips in a ground slot; short edges: the
    CPW cross-section along y.
    """
    cg, cm = coupled_strips_per_um(pad_h, pad_gap, back_gap, eps_r)
    short = pad_h * cpw_c_per_um(pad_w, side_gap, eps_r)
    return pad_w * cg + short, pad_w * cm


def coplanar_coupling(length: float, w1: float, w2: float, s: float, eps_r: float, screening: float = 1.0) -> float:
    """Edge-to-edge coupling of two conductors facing each other over ``length`` across ``s`` (CPS formula).

    ``screening`` < 1 for a ground strip or ground-plane edges close to the gap (rough).
    """
    return screening * length * cps_c_per_um(w1, w2, s, eps_r)


def interdigital(n_fingers: int, finger_w: float, finger_gap: float, overlap: float, eps_r: float) -> float:
    """Interdigital capacitor (Igreja & Dias 2004), N ≥ 2 fingers; for N = 2 the two-strip CPS value is used."""
    if n_fingers <= 2 or overlap <= 0:
        return max(overlap, 0.0) * cps_c_per_um(finger_w, finger_w, finger_gap, eps_r)
    eta = finger_w / (finger_w + finger_gap)
    pre = EPS0_fF_per_um * (eps_r + 1) * overlap
    c_i = pre * k_ratio(math.sin(math.pi * eta / 2))
    c_e = pre * k_ratio(2 * math.sqrt(eta) / (1 + eta))
    return (n_fingers - 3) * c_i / 2 + 2 * c_i * c_e / (c_i + c_e)


def concentric_rings(r_in: float, r_mid_in: float, eps_r: float) -> float:
    """Disk of radius ``r_in`` and a ring starting at ``r_mid_in``: their facing edge as coupled strips, rough.

    Uses the CPS formula along the mean circumference with strip widths = the radial extents (capped).
    """
    s = r_mid_in - r_in
    return 2 * math.pi * (r_in + s / 2) * cps_c_per_um(r_in, r_in, s, eps_r)


def disk_to_ground(r: float, gap: float, eps_r: float) -> float:
    """Disk of radius r in a circular ground cut-out of radius r + gap: a CPW of centre 2r bent into a circle."""
    return math.pi * r * cpw_c_per_um(2 * r, gap, eps_r)


def ring_to_ground(r_out: float, width: float, gap: float, eps_r: float) -> float:
    """Outer edge of a ring (outer radius r_out, radial width w) facing ground across ``gap`` (half-CPW)."""
    return 2 * math.pi * r_out * cpw_c_per_um(2 * width, gap, eps_r) / 2


# ---- value records ------------------------------------------------------------------------------------------------
def _round(v: float, digits: int) -> float:
    if v == 0 or not math.isfinite(v):
        return v
    return round(v, digits - 1 - int(math.floor(math.log10(abs(v)))))


def cap(value: float | None, kind: str, formula: str, fem: bool = True) -> dict:
    """Element value dict for a capacitance estimate: ``{"estimate", "unit", "fem", "estimate_source", ...}``."""
    if value is not None and not _EXACT[0]:
        value = _round(float(value), 3 if kind in ("analytic", "calibration") else 2)
    out = {
        "estimate": value,
        "unit": "fF",
        "estimate_source": f"{kind}: {formula}",
        "estimate_kind": kind,
        "uncertainty": UNCERTAINTY.get(kind, "unknown"),
    }
    if fem:
        out["fem"] = "cmatrix"
    return out


__all__ = [
    "cap",
    "coplanar_coupling",
    "concentric_rings",
    "coupled_strips_per_um",
    "cps_c_per_um",
    "cpw_c_per_um",
    "cpw_line",
    "cross_island",
    "disk_to_ground",
    "eps_eff",
    "exact_values",
    "interdigital",
    "k_ratio",
    "pad_to_ground",
    "ring_to_ground",
    "segments_c_per_um",
    "substrate_eps",
    "two_pads",
]

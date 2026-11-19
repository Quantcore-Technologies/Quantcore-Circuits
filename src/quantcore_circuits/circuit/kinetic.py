"""Kinetic inductance of the superconducting film in the analytic CPW / wire formulas (decision #45).

The film's sheet kinetic inductance ``L_s`` (:class:`quantcore_circuits.pdk.KineticInductance`, μ0 λ_L coth(t/λ_L) ≈
0.116 pH/□ for 200 nm Nb with λ_L = 90 nm) adds in series to the geometric inductance of every current-carrying
conductor: ``L_k = L_s × (number of squares)``.

CPW: ``L'_k = L_s · (g_c + g_g)`` (H/m) with the conformal-mapping geometry factors of a thin-film CPW (centre strip
width s, gaps w, k = s/(s+2w), K = K(k)), Collins 1992 / Watanabe et al., IEEE Trans. Appl. Supercond. 4, 14 (1994)
(also Yoshida et al. 1995; Clem 2013), valid for t ≪ s, w:

    g_c = [π + ln(4π s/t) − k ln((1+k)/(1−k))] / (4 s K²)
    g_g = k [π + ln(4π (s+2w)/t) − (1/k) ln((1+k)/(1−k))] / (4 s K²)

A TL with geometric L' and C' and extra L'_k: v = 1/√((L'+L'_k)C') = v_geo/√(1+L'_k/L'), Z0 = Z0_geo √(1+L'_k/L'),
and a λ/4 or λ/2 resonator of fixed length has f = f_geo/√(1+L'_k/L'). α_k = L'_k/(L'+L'_k) is the kinetic fraction.
"""

from __future__ import annotations

import math

from scipy.special import ellipk

MU0 = 4e-7 * math.pi


def _pdk(pdk):
    if pdk is None or isinstance(pdk, str):
        from quantcore_circuits.pdk import DEFAULT_PDK, get_pdk  # pylint: disable=import-outside-toplevel

        return get_pdk(pdk or DEFAULT_PDK)
    return pdk


def sheet_inductance_pH_sq(pdk=None) -> float:
    """Sheet kinetic inductance L_s of the PDK film in pH/□ (0 when kinetic inductance is switched off)."""
    p = _pdk(pdk)
    return p.kinetic.sheet_pH_sq(p.stack)


def cpw_geometry_factor_per_m(a_um: float, b_um: float, t_um: float) -> float:
    """g_c + g_g (1/m) of a thin-film CPW (centre ``a_um``, gaps ``b_um``, film ``t_um``): L'_k = L_s · g."""
    s, w, t = a_um * 1e-6, b_um * 1e-6, t_um * 1e-6
    k = s / (s + 2 * w)
    kk = float(ellipk(k * k))
    ln = math.log((1 + k) / (1 - k))
    g_c = (math.pi + math.log(4 * math.pi * s / t) - k * ln) / (4 * s * kk * kk)
    g_g = k * (math.pi + math.log(4 * math.pi * (s + 2 * w) / t) - ln / k) / (4 * s * kk * kk)
    return g_c + g_g


def cpw_kinetic_per_m(a_um: float, b_um: float, pdk=None) -> float:
    """Kinetic inductance per length of a CPW on the PDK film, H/m (0 when switched off)."""
    p = _pdk(pdk)
    ls = p.kinetic.sheet_pH_sq(p.stack) * 1e-12
    if ls == 0.0:
        return 0.0
    return ls * cpw_geometry_factor_per_m(a_um, b_um, p.stack.metal_thickness_um)


def kinetic_fraction(l_kinetic: float, l_geometric: float) -> float:
    """α_k = L_k / (L_k + L_geo)."""
    tot = l_kinetic + l_geometric
    return l_kinetic / tot if tot else 0.0


def wire_kinetic_nH(length_um: float, width_um: float, pdk=None) -> float:
    """L_k (nH) of a strip of ``length_um`` × ``width_um``: L_s × squares (0 when switched off).

    Junction leads (≲ 1 µm of ≥ 2 µm-wide film, < 1 square) are negligible and are not counted.
    """
    return sheet_inductance_pH_sq(pdk) * 1e-3 * length_um / width_um


def wire_geometric_nH(length_um: float, width_um: float, thickness_um: float = 0.2) -> float:
    """Geometric (partial self) inductance of a straight strip, nH.

    Grover / Rosa: μ0/2π · l [ln(2l/(w+t)) + ½ + 0.2235 (w+t)/l]."""
    wt = width_um + thickness_um
    return 2e-4 * length_um * (math.log(2 * length_um / wt) + 0.5 + 0.2235 * wt / length_um)


def wire_inductance(length_um: float, width_um: float, pdk=None) -> dict:
    """{L_geo_nH, L_k_nH, L_nH, alpha_k, squares} of a straight (or meandered, by its developed length) strip."""
    p = _pdk(pdk)
    lg = wire_geometric_nH(length_um, width_um, p.stack.metal_thickness_um)
    lk = wire_kinetic_nH(length_um, width_um, p)
    return {
        "L_geo_nH": lg,
        "L_k_nH": lk,
        "L_nH": lg + lk,
        "alpha_k": kinetic_fraction(lk, lg),
        "squares": length_um / width_um,
    }


def route_kinetic_fraction(a_um: float = 10.0, b_um: float = 6.0, pdk=None) -> float:
    """α_k = L'_k/(L'_k+L'_geo) of a CPW route of centre width ``a_um`` and gap ``b_um`` (0 when switched off)."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel

    p = _pdk(pdk)
    return cpw_properties(7.0, a_um, b_um, p.name)["alpha_k"]

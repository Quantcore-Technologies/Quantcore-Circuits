"""LOM-first synthesis: target Hamiltonian → circuit parameters → layout starting values.

This is the "LOM → layout" step of the loop. From targets (f_q, α, f_r, g) it computes EJ/EC → Lj and C_Σ, the
λ/4 resonator length (Metal's CPW model for the PDK stack) and the qubit–resonator coupling capacitance Cg that
gives g. The geometry knobs that realise C_Σ and Cg (cross length, claw length) are then tuned by simulation
(:mod:`quantcore_circuits.optimise`).
"""

from __future__ import annotations

import math

from scipy.constants import e, h, hbar

from quantcore_circuits import track as _track
from quantcore_circuits.analysis._metal import cpw
from quantcore_circuits.analysis.transmon import (
    c_from_ec,
    koch_chi_MHz,
    lj_from_ej,
    n01_matrix_element,
    transmon_from_targets,
)
from quantcore_circuits.pdk import DEFAULT_PDK, get_pdk


def cpw_properties(
    f_GHz: float, a_um: float, b_um: float, pdk_name: str = DEFAULT_PDK, kinetic: bool | None = None
) -> dict:
    """Guided wavelength, phase velocity, ε_eff and Z0 of a CPW on the PDK stack (Metal ``cpw_calculations``).

    The film's kinetic inductance (``pdk.kinetic``, decision #45) adds L'_k to the geometric L' (Metal's values):
    v = v_geo/√(1+L'_k/L'), Z0 = Z0_geo √(1+L'_k/L'), λ and ε_eff (= (c/v)²) follow. ``kinetic=False`` forces the
    purely geometric values (``None``: the PDK's switch). Extra keys: ``L_geo_nH_per_m``, ``L_k_nH_per_m``,
    ``alpha_k`` (L'_k/(L'+L'_k)).
    """
    from quantcore_circuits.circuit.kinetic import cpw_kinetic_per_m  # pylint: disable=import-outside-toplevel

    pdk = get_pdk(pdk_name)
    s = pdk.stack
    m = cpw()
    lam, etf_sqrt, _ = m.guided_wavelength(
        f_GHz * 1e9,
        a_um * 1e-6,
        b_um * 1e-6,
        s.substrate_height * 1e-6,
        s.metal_thickness_um * 1e-6,
        s.substrate_permittivity,
    )
    _, _, _, _, z0, _, _ = m.lumped_cpw(
        f_GHz * 1e9,
        a_um * 1e-6,
        b_um * 1e-6,
        s.substrate_height * 1e-6,
        s.metal_thickness_um * 1e-6,
        s.substrate_permittivity,
        london_penetration_depth=s.london_penetration_depth_um * 1e-6,
    )
    vp = 299792458.0 / float(etf_sqrt)
    z0 = float(z0)
    lam = float(lam)
    l_geo = z0 / vp  # H/m
    l_k = cpw_kinetic_per_m(a_um, b_um, pdk) if kinetic is not False else 0.0
    if kinetic is True and l_k == 0.0:  # forced on although the PDK switch is off: use the PDK's formula values
        from dataclasses import replace  # pylint: disable=import-outside-toplevel

        l_k = cpw_kinetic_per_m(a_um, b_um, replace(pdk, kinetic=replace(pdk.kinetic, enabled=True)))
    scale = math.sqrt(1.0 + l_k / l_geo)
    return {
        "lambda_um": lam * 1e6 / scale,
        "vp_m_s": vp / scale,
        "eps_eff": (float(etf_sqrt) * scale) ** 2,
        "Z0_ohm": z0 * scale,
        "L_geo_nH_per_m": l_geo * 1e9,
        "L_k_nH_per_m": l_k * 1e9,
        "alpha_k": l_k / (l_geo + l_k),
    }


def quarter_wave_length_um(f_r_GHz: float, a_um: float, b_um: float, pdk_name: str = DEFAULT_PDK) -> float:
    return cpw_properties(f_r_GHz, a_um, b_um, pdk_name)["lambda_um"] / 4


def coupling_capacitance_fF(g_MHz: float, f_r_GHz: float, ej_GHz: float, ec_GHz: float, z0: float = 50.0) -> float:
    """Cg giving coupling g to the open end of a λ/4 resonator: ħg = 2e (Cg/C_Σ) V_rms <1|n|0>."""
    w = 2 * math.pi * f_r_GHz * 1e9
    c_r = math.pi / (4 * w * z0)
    v_rms = math.sqrt(hbar * w / (2 * c_r))
    beta = h * g_MHz * 1e6 / (2 * e * v_rms * n01_matrix_element(ej_GHz, ec_GHz))
    return beta * c_from_ec(ec_GHz)


def synthesize_transmon_readout(
    f_q_GHz: float,
    alpha_MHz: float,
    f_r_GHz: float,
    g_MHz: float,
    a_um: float = 10.0,
    b_um: float = 6.0,
    pdk_name: str = DEFAULT_PDK,
) -> dict:
    """Targets → {EJ, EC, Lj, C_Σ, Cg, resonator length, expected χ}."""
    ej, ec = transmon_from_targets(f_q_GHz, alpha_MHz)
    props = cpw_properties(f_r_GHz, a_um, b_um, pdk_name)
    cg = coupling_capacitance_fF(g_MHz, f_r_GHz, ej, ec, props["Z0_ohm"])
    out = {
        "EJ_GHz": ej,
        "EC_GHz": ec,
        "EJ_EC": ej / ec,
        "Lj_nH": lj_from_ej(ej),
        "C_sigma_fF": c_from_ec(ec),
        "Cg_fF": cg,
        "resonator_length_um": float(props["lambda_um"]) / 4,
        "cpw": props,
        "chi_MHz_estimate": koch_chi_MHz(f_q_GHz, alpha_MHz, f_r_GHz, g_MHz),
    }
    _track.emit("synthesis", targets=dict(f_q_GHz=f_q_GHz, alpha_MHz=alpha_MHz, f_r_GHz=f_r_GHz, g_MHz=g_MHz), result=out)
    return out

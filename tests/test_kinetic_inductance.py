"""Kinetic inductance of the film in the analytic CPW / resonator / wire formulas (decision #45)."""

import math
from dataclasses import replace

import pytest

from quantcore_circuits.analysis._metal import cpw as metal_cpw
from quantcore_circuits.analysis.synthesis import cpw_properties, quarter_wave_length_um
from quantcore_circuits.circuit import kinetic
from quantcore_circuits.circuit.bridges import tl_resonator
from quantcore_circuits.pdk import DEFAULT_PDK, KineticInductance, get_pdk, register_pdk


def test_sheet_inductance_formula():
    pdk = get_pdk(DEFAULT_PDK)
    lam, t = 0.09e-6, 0.2e-6
    expect = 4e-7 * math.pi * lam / math.tanh(t / lam) * 1e12
    assert pdk.kinetic.enabled
    assert pdk.kinetic.sheet_pH_sq(pdk.stack) == pytest.approx(expect, rel=1e-12)
    assert 0.11 < expect < 0.12  # Nb 90 nm / 200 nm: 0.1158 pH/sq
    # thin-film limit L_s -> mu0 lam^2 / t
    thin = Stack_like(pdk, lam_um=0.09, t_um=0.01)
    assert thin == pytest.approx(4e-7 * math.pi * 0.09e-6**2 / 0.01e-6 * 1e12, rel=0.01)
    # explicit override and switch
    assert KineticInductance(sheet_inductance_pH_sq=0.5).sheet_pH_sq(pdk.stack) == 0.5
    assert KineticInductance(enabled=False).sheet_pH_sq(pdk.stack) == 0.0


def Stack_like(pdk, lam_um, t_um):
    st = replace(pdk.stack, london_penetration_depth_um=lam_um, metal_thickness_um=t_um)
    return pdk.kinetic.sheet_pH_sq(st)


def test_cpw_kinetic_per_length_vs_independent_formula():
    """10/6 um CPW on 200 nm Nb: L'_k ~ 13.5 nH/m (Watanabe/Collins); Metal's Mohebbi-Majedi implementation of the
    same physics gives 11.0 nH/m for lambda = 90 nm: the two agree within 25 %."""
    lk = kinetic.cpw_kinetic_per_m(10, 6, DEFAULT_PDK) * 1e9
    assert lk == pytest.approx(13.47, rel=0.01)
    lk_metal = float(metal_cpw().lumped_cpw(7e9, 10e-6, 6e-6, 650e-6, 0.2e-6, 10.25, london_penetration_depth=0.09e-6)[0])
    assert lk == pytest.approx(lk_metal * 1e9, rel=0.25)


def test_fr_shift_for_10_6_cpw():
    tl = tl_resonator(4000, 10, 6)
    assert tl["alpha_k"] == pytest.approx(0.0308, abs=0.001)
    assert tl["f_GHz"] == pytest.approx(7.877, abs=0.005)
    assert tl["f_GHz"] == pytest.approx(tl["f_geo_GHz"] / math.sqrt(1 + tl["L_k_nH_per_m"] / tl["L_geo_nH_per_m"]), rel=1e-9)
    assert tl["f_GHz"] / tl["f_geo_GHz"] - 1 == pytest.approx(-0.0153, abs=0.001)
    assert kinetic.route_kinetic_fraction(10, 6) == pytest.approx(tl["alpha_k"], rel=1e-6)
    # lambda/4 length for a target frequency shrinks by the same factor
    assert quarter_wave_length_um(7.0, 10, 6) == pytest.approx(4501.2, abs=1.0)


def test_switch_off_restores_geometric_values():
    off = replace(get_pdk(DEFAULT_PDK), name="_ki_off", kinetic=KineticInductance(enabled=False))
    register_pdk(off)
    base = cpw_properties(7.0, 10, 6, DEFAULT_PDK, kinetic=False)
    p_off = cpw_properties(7.0, 10, 6, "_ki_off")
    for k in ("lambda_um", "vp_m_s", "eps_eff", "Z0_ohm"):
        assert p_off[k] == base[k]  # exactly
    assert p_off["alpha_k"] == 0.0
    assert tl_resonator(4000, 10, 6, "_ki_off")["f_GHz"] == pytest.approx(tl_resonator(4000, 10, 6)["f_geo_GHz"], rel=1e-6)
    assert quarter_wave_length_um(7.0, 10, 6, "_ki_off") == pytest.approx(4501.2 * math.sqrt(1 + 13.474 / 423.92), rel=1e-3)


def test_wire_inductance_squares():
    w = kinetic.wire_inductance(1000, 1.0, DEFAULT_PDK)
    assert w["squares"] == 1000
    assert w["L_k_nH"] == pytest.approx(0.11578 * 1000 * 1e-3, rel=1e-3)  # L_s x squares
    assert w["L_nH"] == pytest.approx(w["L_geo_nH"] + w["L_k_nH"])
    assert kinetic.wire_kinetic_nH(1000, 1.0, replace(get_pdk(DEFAULT_PDK), kinetic=KineticInductance(False))) == 0.0


def test_pdk_has_an_nbn_film():
    """Decision, 2026-11-10: "yes we will do NbN; add it to the PDK" (KI devices: 20 pH/□)."""
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk()
    assert pdk.film() is pdk.kinetic and pdk.film("Nb").sheet_pH_sq(pdk.stack) == pytest.approx(0.1158, rel=1e-3)
    assert pdk.film("NbN").sheet_pH_sq(pdk.stack) == 20.0
    with pytest.raises(KeyError, match="films"):
        pdk.film("Al")

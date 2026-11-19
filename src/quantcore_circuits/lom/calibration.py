"""Component LOM calibration: knob → element value, per component and PDK (no FEM needed to get a first LOM).

Each entry is a power law ``v = v0 (k/k0)^p`` anchored at a reference simulation of the component geometry, the
same form the co-design surrogate refines (:mod:`quantcore_circuits.codesign`). Values are fF. The reference
geometry is the example Xmon (arm width 25 µm, gap 25 µm, claw finger 25 µm, claw gap 6 µm); away from it the
estimate is first-order and is replaced as soon as a C-matrix of the actual design exists.

``hanger_k`` is the voltage coupling coefficient k = (Z0e − Z0o)/(Z0e + Z0o) of the parallel-coupled section of a
hanger coupler, per ground-strip width (µm), used for the external Q of a λ/4 hanger:
Q_ext = π / (2 k² sin²(β l_c)) (Besedin & Menushenkov 2018). Calibrate it from a driven/eigenmode simulation.
"""

from __future__ import annotations

import math

# Q3D of examples/q1_r1_feedline.json group Q1R1 (AEDT 2021 R1, 2026-11-02), simulated on silicon and rescaled to
# sapphire with (εr + 1)/2, port-stub capacitance removed. Replace with a sapphire run when available.
_REF = "Q3D Q1R1 2026-11-02 (Si, rescaled (εr+1)/2)"
CALIBRATION: dict[tuple[str, str], dict] = {
    ("Xmon", "quantcore_nb_sapphire_v1"): {
        "C_island": {"knob": "cross_length", "k0": 300.0, "v0": 64.05, "p": 1.0, "ref": _REF},
        "Cg": {"knob": "claw_length", "k0": 100.0, "v0": 3.17, "p": 1.0, "ref": _REF},
        "C_claw": {"knob": "claw_length", "k0": 100.0, "v0": 76.4, "p": 0.8, "ref": _REF},
    },
}
# ground-strip width µm → k. 6 µm: calibrated 2026-11-03 on examples/q1_r1_feedline.json R1 (λ/4 meander 4200 µm,
# 300 µm coupled section, 6 µm ground strip, claw-loaded) with an HFSS driven S21 (AEDT 2024 R1, sapphire, wave ports
# on FL, Q1 junction as Lj/Cj; 10 µm gap mesh seed, 4 passes / 359k tets, ΔS 0.0026): notch fit f0 6.6008 GHz,
# Q_c 24 698 → κ_ext 0.2673 MHz (Q_i 1.10e6 = the bulk-dielectric limit from EPR). The LOM evaluates
# hanger_kappa_MHz at the bare λ/4 frequency (7.62 GHz), so k is an *effective* value for this hanger family:
# k = 0.06 · √(0.2673 / 0.2189) = 0.0663. Previous uncalibrated estimate: 0.06. Cross-check: eigenmode Q of the same
# resonator (18 passes, not converged, ΔF 0.52 %) gives κ_ext 0.217 MHz → k 0.0597. Job: build/jobs/aedt241/driven_wide.
HANGER_K = {6.0: 0.0663}
HANGER_K_REF = "HFSS driven S21 notch fit, q1_r1_feedline R1, AEDT 2024 R1 (2026-11-03); was 0.06 (estimate)"


def _entry(cell: str, pdk_name: str) -> tuple[dict | None, float]:
    """(calibration, capacitance scale) — other PDKs reuse the sapphire entry rescaled by (εr + 1)/2."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    if (cell, pdk_name) in CALIBRATION:
        return CALIBRATION[(cell, pdk_name)], 1.0
    for (c, p), entry in CALIBRATION.items():
        if c == cell:
            eps_ref = get_pdk(p).stack.substrate_permittivity
            eps = get_pdk(pdk_name).stack.substrate_permittivity
            return entry, (eps + 1) / (eps_ref + 1)
    return None, 1.0


def estimate(cell: str, quantity: str, params: dict, pdk_name: str) -> tuple[float | None, str]:
    """(value fF, provenance) of ``quantity`` for a cell with ``params``; (None, reason) if uncalibrated."""
    entry, scale = _entry(cell, pdk_name)
    if entry is None or quantity not in entry:
        return None, f"no calibration for {cell}.{quantity}"
    c = entry[quantity]
    k = float(params.get(c["knob"], c["k0"]))
    return scale * c["v0"] * (k / c["k0"]) ** c["p"], f"calibration {cell}.{quantity} ({c['ref']})"


def invert(cell: str, quantity: str, value: float, pdk_name: str) -> float | None:
    """Knob value that gives ``value`` (fF) for ``quantity`` (LOM → layout)."""
    entry, scale = _entry(cell, pdk_name)
    if entry is None or quantity not in entry:
        return None
    c = entry[quantity]
    return c["k0"] * (value / (scale * c["v0"])) ** (1 / c["p"])


def hanger_k(ground_gap_um: float) -> float:
    """Coupling coefficient for a hanger with the given ground strip (nearest calibrated width, e^-gap scaling)."""
    g0 = min(HANGER_K, key=lambda g: abs(g - ground_gap_um))
    return HANGER_K[g0] * math.exp(-(ground_gap_um - g0) / 10.0)


def hanger_kappa_MHz(f_GHz: float, vp_m_s: float, coupling_length_um: float, ground_gap_um: float) -> float:
    """External linewidth κ/2π of a λ/4 hanger coupled over ``coupling_length_um`` near its shorted end."""
    beta_l = 2 * math.pi * f_GHz * 1e9 / vp_m_s * coupling_length_um * 1e-6
    k = hanger_k(ground_gap_um)
    q_ext = math.pi / (2 * k**2 * math.sin(beta_l) ** 2)
    return f_GHz * 1e3 / q_ext

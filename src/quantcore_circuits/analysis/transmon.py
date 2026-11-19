"""Transmon parameters: unit conversions, spectrum (scqubits) and the inverse problem (EJ, EC from targets).

Conventions used throughout :mod:`quantcore_circuits.analysis`:

* frequencies in GHz, anharmonicity α / dispersive shift χ / coupling g in MHz, capacitance in fF, inductance in nH;
* α < 0 for a transmon;
* χ is the *full* dispersive shift ``E11 − E10 − E01 + E00`` (= 2χ in Koch et al.), negative for a transmon below
  its resonator — the same convention as Metal LOM ``chi_in_MHz``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from scipy.constants import e, h, hbar

PHI0_RED = hbar / (2 * e)  # reduced flux quantum Φ0/2π


def ec_from_c(c_fF: float) -> float:
    """Charging energy EC = e²/2C in GHz."""
    return e**2 / (2 * c_fF * 1e-15) / h / 1e9


def c_from_ec(ec_GHz: float) -> float:
    return e**2 / (2 * ec_GHz * 1e9 * h) / 1e-15


def ej_from_lj(lj_nH: float) -> float:
    """Josephson energy EJ = (Φ0/2π)²/Lj in GHz."""
    return PHI0_RED**2 / (lj_nH * 1e-9) / h / 1e9


def lj_from_ej(ej_GHz: float) -> float:
    return PHI0_RED**2 / (ej_GHz * 1e9 * h) / 1e-9


def transmon_spectrum(ej_GHz: float, ec_GHz: float, ng: float = 0.0, ncut: int = 31) -> tuple[float, float]:
    """(f01 GHz, α MHz) of a charge-basis transmon (scqubits)."""
    import scqubits as scq  # pylint: disable=import-outside-toplevel

    tmon = scq.Transmon(EJ=ej_GHz, EC=ec_GHz, ng=ng, ncut=ncut, truncated_dim=4)
    ev = tmon.eigenvals(evals_count=3)
    return float(ev[1] - ev[0]), float((ev[2] - 2 * ev[1] + ev[0]) * 1e3)


def transmon_from_targets(f_q_GHz: float, alpha_MHz: float, ng: float = 0.0) -> tuple[float, float]:
    """Solve for (EJ, EC) in GHz giving the target f01 and α (exact charge-basis model, not the asymptotic formula)."""
    from scipy.optimize import fsolve  # pylint: disable=import-outside-toplevel

    ec0 = -alpha_MHz / 1e3
    ej0 = (f_q_GHz + ec0) ** 2 / (8 * ec0)

    def residual(x):
        f, a = transmon_spectrum(x[0], x[1], ng)
        return [f - f_q_GHz, (a - alpha_MHz) / 1e3]

    ej, ec = fsolve(residual, [ej0, ec0], xtol=1e-10)
    return float(ej), float(ec)


@dataclass
class TransmonParams:
    EJ_GHz: float
    EC_GHz: float
    f_q_GHz: float
    alpha_MHz: float
    Lj_nH: float
    C_sigma_fF: float

    @property
    def EJ_EC(self) -> float:
        return self.EJ_GHz / self.EC_GHz

    def as_dict(self) -> dict:
        return {**asdict(self), "EJ_EC": self.EJ_EC}


def transmon_from_circuit(c_sigma_fF: float, lj_nH: float) -> TransmonParams:
    ej, ec = ej_from_lj(lj_nH), ec_from_c(c_sigma_fF)
    f, a = transmon_spectrum(ej, ec)
    return TransmonParams(ej, ec, f, a, lj_nH, c_sigma_fF)


def dressed_transmon_resonator(
    ej_GHz: float, ec_GHz: float, f_r_GHz: float, g_MHz: float, ncut: int = 31, nq: int = 6, nr: int = 8
) -> dict:
    """Dressed f_q, f_r, α, χ from scqubits (charge coupling g_n·n̂(a + a†)).

    ``g_MHz`` is the *exchange* coupling (as everywhere in qcc); it is converted to the charge-operator coupling with
    the exact matrix element, g_n = g / |<1|n̂|0>|.
    """
    import scqubits as scq  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.analysis._metal import apply_scqubits_compat  # pylint: disable=import-outside-toplevel

    apply_scqubits_compat()
    qb = scq.Transmon(EJ=ej_GHz, EC=ec_GHz, ng=0.0, ncut=ncut, truncated_dim=nq, id_str="qubit")
    n01 = abs(qb.matrixelement_table("n_operator", evals_count=2)[0, 1])
    rs = scq.Oscillator(E_osc=f_r_GHz, truncated_dim=nr, id_str="resonator")
    hs = scq.HilbertSpace([qb, rs])
    hs.add_interaction(g=g_MHz / 1e3 / n01, op1=qb.n_operator, op2=rs.creation_operator, add_hc=True)
    hs.generate_lookup()

    def en(q, r):
        return hs.energy_by_bare_index((q, r))

    return {
        "f_q_GHz": en(1, 0) - en(0, 0),
        "f_r_GHz": en(0, 1) - en(0, 0),
        "alpha_MHz": (en(2, 0) - 2 * en(1, 0) + en(0, 0)) * 1e3,
        "chi_MHz": (en(1, 1) - en(1, 0) - en(0, 1) + en(0, 0)) * 1e3,
    }


def koch_chi_MHz(f_q_GHz: float, alpha_MHz: float, f_r_GHz: float, g_MHz: float) -> float:
    """Full dispersive shift 2χ from the transmon perturbative formula (Koch et al. 2007), MHz."""
    delta = (f_q_GHz - f_r_GHz) * 1e3
    a = alpha_MHz
    return 2 * g_MHz**2 * a / (delta * (delta + a))


def n01_matrix_element(ej_GHz: float, ec_GHz: float) -> float:
    """|<1|n|0>| ≈ (EJ/8EC)^(1/4)/√2 (transmon limit)."""
    return (ej_GHz / (8 * ec_GHz)) ** 0.25 / math.sqrt(2)

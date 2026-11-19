"""Circuit-quantisation cross-checks: QuCat (lumped network incl. losses), SQcircuit (exact transmon), QuTiP (model).

All return qcc conventions (GHz / MHz, α < 0, χ = E11 − E10 − E01 + E00).
"""

from __future__ import annotations

import math

import numpy as np


def quarter_wave_lc(f_r_GHz: float, z0: float = 50.0) -> tuple[float, float]:
    """Lumped (C fF, L nH) of a λ/4 resonator near resonance, seen from its open end: C = π/(4 ω Z0)."""
    w = 2 * math.pi * f_r_GHz * 1e9
    c = math.pi / (4 * w * z0)
    return c / 1e-15, 1 / (w**2 * c) / 1e-9


def qucat_from_cmatrix(
    cmatrix_fF,
    labels: list[str],
    island: str,
    lj_nH: float,
    resonators: dict[str, tuple[float, float]] | None = None,
    loads: dict[str, float] | None = None,
) -> dict:
    """Quantise a Maxwell C-matrix (signal nets, ground excluded) + grounded junction with QuCat.

    ``resonators``: ``{node: (f_r_GHz, Z0)}`` — a λ/4 resonator (equivalent parallel LC) from ``node`` to ground.
    ``loads``: ``{node: R_ohm}`` — resistive loads (e.g. 50 Ω feedline) for κ. Returns all modes and the qubit-like
    one (largest anharmonicity) with f, κ, α, χ to every other mode.
    """
    from qucat import C, J, L, Network, R  # pylint: disable=import-outside-toplevel

    c = np.asarray(cmatrix_fF, dtype=float)
    idx = {name: i + 1 for i, name in enumerate(labels)}  # node 0 = ground
    comps = []
    n = len(labels)
    for i in range(n):
        to_ground = c[i].sum()
        if to_ground > 1e-6:
            comps.append(C(0, i + 1, to_ground * 1e-15))
        for j in range(i + 1, n):
            if -c[i, j] > 1e-6:
                comps.append(C(i + 1, j + 1, -c[i, j] * 1e-15))
    comps.append(J(0, idx[island], "Lj"))
    for node, (f_r, z0) in (resonators or {}).items():
        # the coupler pad is the resonator's open end: equivalent parallel LC from that node to ground
        cr, lr = quarter_wave_lc(f_r, z0)
        comps += [C(0, idx[node], cr * 1e-15), L(0, idx[node], lr * 1e-9)]
    for node, r_ohm in (loads or {}).items():
        comps.append(R(0, idx[node], r_ohm))
    import contextlib  # pylint: disable=import-outside-toplevel
    import io  # pylint: disable=import-outside-toplevel
    import warnings  # pylint: disable=import-outside-toplevel

    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        cir = Network(comps)
        f, k, a, chi = cir.f_k_A_chi(Lj=lj_nH * 1e-9)
    f, k, a, chi = np.real(f), np.real(k), np.real(a), np.real(chi)
    q = int(np.argmax(a))
    return {
        "modes_GHz": (f / 1e9).tolist(),
        "kappa_MHz": (k / 1e6).tolist(),
        "qubit_mode": q,
        "f_q_GHz": float(f[q] / 1e9),
        "alpha_MHz": float(-a[q] / 1e6),
        "chi_MHz": [float(-chi[q, m] / 1e6) for m in range(len(f))],
        "kappa_q_MHz": float(k[q] / 1e6),
    }


def sqcircuit_transmon(c_sigma_fF: float, lj_nH: float, ncut: int = 30) -> dict:
    """Grounded transmon (single node) diagonalised with SQcircuit; returns f01 (GHz) and α (MHz)."""
    import SQcircuit as sq  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.analysis.transmon import ej_from_lj  # pylint: disable=import-outside-toplevel

    sq.set_unit_freq("GHz")
    cq = sq.Capacitor(c_sigma_fF, "fF")
    jj = sq.Junction(ej_from_lj(lj_nH), "GHz")
    cr = sq.Circuit({(0, 1): [cq, jj]})
    cr.set_trunc_nums([ncut])
    efreqs, _ = cr.diag(4)
    ev = np.sort(np.real(efreqs)) - np.min(np.real(efreqs))
    return {"f_q_GHz": float(ev[1]), "alpha_MHz": float((ev[2] - 2 * ev[1]) * 1e3)}


def qutip_transmon_resonator(
    f_q_GHz: float, alpha_MHz: float, f_r_GHz: float, g_MHz: float, nq: int = 5, nr: int = 12
) -> dict:
    """Kerr-transmon + resonator with exchange coupling g (QuTiP); dressed f_q, f_r and χ by state overlap."""
    import qutip as qt  # pylint: disable=import-outside-toplevel

    b = qt.tensor(qt.destroy(nq), qt.qeye(nr))
    a = qt.tensor(qt.qeye(nq), qt.destroy(nr))
    alpha = alpha_MHz / 1e3
    g = g_MHz / 1e3
    h = f_q_GHz * b.dag() * b + alpha / 2 * b.dag() * b.dag() * b * b + f_r_GHz * a.dag() * a
    h += g * (b.dag() * a + b * a.dag())
    evals, evecs = h.eigenstates()

    def level(q, r):
        bare = qt.tensor(qt.basis(nq, q), qt.basis(nr, r))
        overlaps = [abs(bare.overlap(v)) for v in evecs]
        return float(evals[int(np.argmax(overlaps))])

    e00, e10, e01, e11, e20 = level(0, 0), level(1, 0), level(0, 1), level(1, 1), level(2, 0)
    return {
        "f_q_GHz": e10 - e00,
        "f_r_GHz": e01 - e00,
        "alpha_MHz": (e20 - 2 * e10 + e00) * 1e3,
        "chi_MHz": (e11 - e10 - e01 + e00) * 1e3,
        "hamiltonian": h,
    }

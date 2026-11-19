"""QuTiP Hamiltonian of a transmon + λ/4 readout pair, and the standard checks (M10).

Model (cyclic frequencies, GHz): the transmon in the charge basis, ``H_t = 4E_C(n̂ − n_g)² − E_J cos φ̂``, truncated
to its ``nq`` lowest eigenstates, plus the resonator ``f_r a†a`` and the charge coupling ``g_n n̂ (a + a†)`` (no
rotating-wave approximation). Inputs come from the filled circuit (:func:`~quantcore_circuits.circuit.fill.
two_node_model`): loaded E_C, E_J from Lj, the claw-loaded λ/4 frequency and g_n.

Checks:

* :func:`dressed` — dressed levels by bare-state overlap → f_q, f_r, α, χ (χ = E11 − E10 − E01 + E00)
* :func:`readout` — simulated resonator transmission with the qubit in |g⟩ or |e⟩: weak coherent probe, steady state
  of the Lindblad equation in the dressed basis (drive and dissipators kept to the ΔN = ±1 terms), peak positions →
  χ_readout. Qubit relaxation (|g⟩) or incoherent pumping (|e⟩) at a rate ≪ κ pins the qubit state.
* :func:`flux_curve` — f01/f12 vs flux of a (possibly asymmetric) SQUID transmon
* :func:`purcell_t1_us` — Purcell limit (Δ/g)²/κ
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class TransmonResonator:
    EJ_GHz: float
    EC_GHz: float
    f_r_GHz: float
    g_n_MHz: float  # charge-operator coupling (exchange g = g_n |⟨1|n|0⟩|)
    nq: int = 6
    nr: int = 8
    ng: float = 0.0
    ncut: int = 20

    def transmon(self):
        """(energies GHz, n̂ in the eigenbasis) of the bare transmon, ``nq`` levels."""
        n = np.arange(-self.ncut, self.ncut + 1)
        h = np.diag(4 * self.EC_GHz * (n - self.ng) ** 2) - self.EJ_GHz / 2 * (
            np.eye(len(n), k=1) + np.eye(len(n), k=-1)
        )
        e, v = np.linalg.eigh(h)
        v = v[:, : self.nq]
        return e[: self.nq] - e[0], v.T @ np.diag(n.astype(float)) @ v

    def operators(self):
        import qutip as qt  # pylint: disable=import-outside-toplevel

        e, nmat = self.transmon()
        hq = qt.Qobj(np.diag(e))
        nq_op = qt.Qobj(nmat)
        a = qt.destroy(self.nr)
        iq, ir = qt.qeye(self.nq), qt.qeye(self.nr)
        H = qt.tensor(hq, ir) + self.f_r_GHz * qt.tensor(iq, a.dag() * a)
        H += self.g_n_MHz / 1e3 * qt.tensor(nq_op, a + a.dag())
        g_e = np.zeros((self.nq, self.nq))
        g_e[0, 1] = 1.0  # |g><e|: relaxation e → g only (pins |g>); its adjoint pumps g → e only (pins |e>)
        return H, qt.tensor(iq, a), qt.tensor(qt.Qobj(g_e), ir)

    @property
    def g_MHz(self) -> float:
        _, nmat = self.transmon()
        return self.g_n_MHz * abs(nmat[0, 1])

    def latex(self) -> str:
        return (
            r"\hat H/h = 4E_C(\hat n-n_g)^2 - E_J\cos\hat\varphi + f_r\,\hat a^\dagger\hat a"
            r" + g_n\,\hat n\,(\hat a+\hat a^\dagger)"
        )


def from_pair(pair, nq: int = 6, nr: int = 8) -> TransmonResonator:
    from quantcore_circuits.circuit.fill import two_node_model  # pylint: disable=import-outside-toplevel

    tn = two_node_model(pair)
    return TransmonResonator(tn["EJ_GHz"], tn["EC_GHz"], tn["f_r_loaded_GHz"], tn["g_n_MHz"], nq=nq, nr=nr)


def _eig(model: TransmonResonator):
    import qutip as qt  # pylint: disable=import-outside-toplevel

    H, _, _ = model.operators()
    evals, evecs = H.eigenstates()
    labels = []
    for v in evecs:
        amps = np.abs(v.full().ravel()) ** 2
        k = int(np.argmax(amps))
        labels.append((k // model.nr, k % model.nr))
    return np.real(evals) - np.real(evals[0]), evecs, labels, qt


def dressed(model: TransmonResonator, n_levels: int = 10) -> dict:
    evals, _, labels, _ = _eig(model)

    def e(q, r):
        return float(evals[labels.index((q, r))])

    names = "gefhijkl"
    levels = [
        {"label": f"|{names[q] if q < len(names) else q},{r}⟩", "energy": float(E), "q": q, "r": r}
        for E, (q, r) in sorted(zip(evals, labels))[:n_levels]
    ]
    return {
        "f_q_GHz": e(1, 0),
        "f_r_GHz": e(0, 1),
        "alpha_MHz": (e(2, 0) - 2 * e(1, 0)) * 1e3,
        "chi_MHz": (e(1, 1) - e(1, 0) - e(0, 1)) * 1e3,
        "g_MHz": model.g_MHz,
        "levels": levels,
    }


def readout(
    model: TransmonResonator,
    kappa_MHz: float = 1.0,
    span_MHz: float | None = None,
    n_points: int = 81,
    drive_over_kappa: float = 0.05,
    qubit_rate_over_kappa: float = 0.05,
    nq: int = 3,
    nr: int = 3,
) -> dict:
    """Simulated transmission ⟨a⟩ vs probe frequency for the qubit in |g⟩ and |e⟩ (see module docstring).

    The master equation uses a reduced ``nq`` × ``nr`` copy of the model (a weak probe only populates the lowest
    levels); the reported ``chi_eigen_MHz`` comes from the full-size model. The qubit pinning rate must beat the
    Purcell decay through the resonator (≈ κ g²/Δ²) but stay ≪ κ; ``P_e_at_peak_*`` reports how well it worked.
    """
    full = dressed(model)
    model = TransmonResonator(model.EJ_GHz, model.EC_GHz, model.f_r_GHz, model.g_n_MHz, nq, nr, model.ng, model.ncut)
    evals, evecs, labels, qt = _eig(model)
    _, a_full, b_full = model.operators()
    U = np.column_stack([v.full().ravel() for v in evecs])
    n_exc = np.array([q + r for q, r in labels])
    A = U.conj().T @ a_full.full() @ U
    B = U.conj().T @ b_full.full() @ U
    keep = (n_exc[:, None] - n_exc[None, :]) == -1  # <j|a|k> with N_j = N_k − 1
    A = qt.Qobj(np.where(keep, A, 0))
    B = qt.Qobj(np.where(keep, B, 0))
    d = dressed(model)
    chi_guess = abs(d["chi_MHz"])
    span = span_MHz or max(8 * kappa_MHz, 6 * chi_guess)
    f0 = d["f_r_GHz"] + d["chi_MHz"] / 2e3
    freqs = f0 + np.linspace(-span / 2, span / 2, n_points) / 1e3
    w = 2 * math.pi
    kappa = w * kappa_MHz / 1e3  # rad/ns
    eps = drive_over_kappa * kappa
    gamma = qubit_rate_over_kappa * kappa
    out = {"f_GHz": freqs.tolist(), "kappa_MHz": kappa_MHz}
    qubit_e = qt.Qobj(np.diag([1.0 if q == 1 else 0.0 for q, _ in labels]))
    for state, qubit_op in (("g", B), ("e", B.dag())):
        trans, pe = [], []
        for fd in freqs:
            H = qt.Qobj(np.diag(w * (evals - n_exc * fd))) + eps * (A + A.dag())
            rho = qt.steadystate(H, [math.sqrt(kappa) * A, math.sqrt(gamma) * qubit_op])
            trans.append(abs(qt.expect(A, rho)) ** 2)
            pe.append(float(np.real(qt.expect(qubit_e, rho))))
        trans = np.asarray(trans) / max(trans)
        out[f"P_e_at_peak_{state}"] = pe[int(np.argmax(trans))]
        out[f"T_{state}"] = trans.tolist()
        i = int(np.argmax(trans))
        if 0 < i < len(freqs) - 1:  # parabolic refinement of the peak
            y0, y1, y2 = trans[i - 1 : i + 2]
            frac = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
        else:
            frac = 0.0
        out[f"peak_{state}_GHz"] = float(freqs[i] + frac * (freqs[1] - freqs[0]))
    out["chi_readout_MHz"] = (out["peak_e_GHz"] - out["peak_g_GHz"]) * 1e3
    out["chi_eigen_MHz"] = full["chi_MHz"]
    out["chi_eigen_reduced_MHz"] = d["chi_MHz"]
    return out


def flux_curve(ej_sum_GHz: float, ec_GHz: float, asym: float = 0.0, phis=None) -> dict:
    """f01 and f12 (GHz) of a SQUID transmon vs flux Φ/Φ0."""
    from quantcore_circuits.analysis.transmon import transmon_spectrum  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.bridges import squid_ej  # pylint: disable=import-outside-toplevel

    phis = np.linspace(-0.45, 0.45, 91) if phis is None else np.asarray(phis)
    f01, f12 = [], []
    for p in phis:
        f, a = transmon_spectrum(max(squid_ej(ej_sum_GHz, asym, float(p)), 1e-6), ec_GHz)
        f01.append(f)
        f12.append(f + a / 1e3)
    return {"phi": phis.tolist(), "f01_GHz": f01, "f12_GHz": f12}


def purcell_t1_us(f_q_GHz: float, f_r_GHz: float, g_MHz: float, kappa_MHz: float) -> float:
    """T1 limit from decay through the readout resonator, (Δ/g)²/κ (κ, Δ, g as cyclic frequencies)."""
    delta = (f_q_GHz - f_r_GHz) * 1e3
    gamma = kappa_MHz * (g_MHz / delta) ** 2  # MHz (cyclic)
    return 1 / (2 * math.pi * gamma)

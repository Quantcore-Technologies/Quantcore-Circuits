"""Energy-participation-ratio Hamiltonian (pyEPR calculation core, no AEDT needed).

Input: linear eigenmode frequencies (HFSS/Palace eigenmode with Lj as a lumped inductor), junction participation
ratios ``p_mj`` (M modes × J junctions), signs ``s_mj`` and junction inductances. pyEPR's ``QuantumAnalysis`` needs a
pickle produced by ``DistributedAnalysis``; the calculation functions below are what it calls internally.

:func:`participations` is pyEPR's ``DistributedAnalysis.calc_p_junction`` + ``QuantumAnalysis`` renormalisation
(``config.epr.renorm_pj = True``) applied to the field integrals that ``qcc_solve.py`` evaluates inside AEDT
(:mod:`quantcore_circuits.sim_tools.aedt_scripts`), method ``line_voltage``:

* V_j = sign(∫Re E·dl) √((∫Re E·dl)² + (∫Im E·dl)²) over the junction line, I_j = V_j / (ω L_j);
* U_E = ∫Re(E·εE*)/2, U_H = ∫Re(H·μH*)/2 (peak energies), U_J = ½ L_j I_j², U_Cj = ½ C_j V_j²;
* p_mj = U_J / (U_E + ΣU_Cj), then rescaled so Σ_j p_mj = |(Ū − U_H)/Ū|, Ū = mean of total capacitive and inductive
  energy; s_mj = sign(V_j).

Sign conventions are converted to qcc's (α < 0, χ = E11 − E10 − E01 + E00 < 0); pyEPR reports positive shifts.
"""

from __future__ import annotations

import numpy as np


def participations(epr: dict, freqs_GHz=None, renorm: bool = True) -> dict:
    """Junction participations from qcc's in-AEDT EPR integrals (``<sim>_project_qcc.json`` ``"epr"``).

    ``freqs_GHz`` (mode order) overrides the per-mode ``freq_Hz`` read in AEDT (e.g. the ``.eig`` export). Returns
    ``{"junctions", "Lj_nH", "Cj_fF", "f_GHz", "p_mj", "s_mj", "p_mj_raw", "U_diff", "p_volume"}`` with M×J lists.
    """
    modes = sorted(epr["modes"], key=lambda m: m["mode"])
    juncs = sorted({j for m in modes for j in m["junctions"]}, key=int)
    lj = {j: next(m["junctions"][j]["Lj_H"] for m in modes if j in m["junctions"]) for j in juncs}
    cj = {j: next(m["junctions"][j].get("Cj_F") or 0.0 for m in modes if j in m["junctions"]) for j in juncs}
    f_ghz = []
    p_raw, p_norm, signs, u_diff, p_vol = [], [], [], [], []
    for i, m in enumerate(modes):
        f = float(freqs_GHz[i]) if freqs_GHz is not None else float(m["freq_Hz"]) / 1e9
        f_ghz.append(f)
        omega = 2 * np.pi * f * 1e9
        u_e, u_h = m["U_E"] / 2.0, m["U_H"] / 2.0  # peak energies (AEDT integrals are 2× peak)
        u_ind, u_cap, s_row = {}, {}, []
        for j in juncs:
            d = m["junctions"].get(j, {"V_re": 0.0, "V_im": 0.0})
            v = float(np.sign(d["V_re"]) * np.hypot(d["V_re"], d["V_im"]))
            i_peak = v / (omega * lj[j])
            u_ind[j] = 0.5 * lj[j] * i_peak**2
            u_cap[j] = 0.5 * cj[j] * v**2
            s_row.append(1 if v > 0 else -1)
        u_tot_cap = u_e + sum(u_cap.values())
        u_tot_ind = u_h + sum(u_ind.values())
        row = [u_ind[j] / u_tot_cap for j in juncs]
        p_raw.append(row)
        u_mode = (u_tot_cap + u_tot_ind) / 2.0
        u_diff.append((u_tot_cap - u_tot_ind) / (u_tot_cap + u_tot_ind))
        if renorm and sum(row) > 0:
            glb = abs((u_mode - u_h) / u_mode)
            row = [p * glb / sum(row) for p in row]
        p_norm.append(row)
        signs.append(s_row)
        p_vol.append({k: v / 2.0 / u_e for k, v in (m.get("U_E_volumes") or {}).items()})
    return {
        "junctions": juncs,
        "Lj_nH": [lj[j] * 1e9 for j in juncs],
        "Cj_fF": [cj[j] * 1e15 for j in juncs],
        "f_GHz": f_ghz,
        "p_mj": p_norm,
        "p_mj_raw": p_raw,
        "s_mj": signs,
        "U_diff": u_diff,
        "p_volume": p_vol,
    }


def junction_self_modes(p: dict, p_min: float = 0.95, rel: float = 0.15) -> list[int]:
    """Modes that are a junction's lumped L_J ‖ C_J resonating on its own: p_mj ≥ ``p_min`` for one junction and
    f within ``rel`` of 1/2π√(L_J C_J) of that junction (with C_J > 0). Seen on coarse / fast meshes (tutorial 00,
    C_J 14.7 fF: a 15.65 GHz mode with p_J 0.9999 beside the real qubit mode, p_J 0.985); a circuit mode has the
    island's capacitance in parallel and sits far below. Returned as mode indices (0-based)."""
    out = []
    for i, (f, row) in enumerate(zip(p["f_GHz"], p["p_mj"])):
        for j, pj in enumerate(row):
            lj, cj = p["Lj_nH"][j] * 1e-9, p["Cj_fF"][j] * 1e-15
            if cj <= 0 or pj < p_min:
                continue
            f_lc = 1 / (2 * np.pi * np.sqrt(lj * cj)) / 1e9
            if abs(f - f_lc) <= rel * f_lc:
                out.append(i)
                break
    return out


def _expand(h: dict, keep: list[int], f_linear: list[float]) -> dict:
    """Hamiltonian results of the kept modes back to all modes: a left-out mode keeps its linear f and no Kerr."""
    n = len(f_linear)
    pos = {m: k for k, m in enumerate(keep)}
    out = {}
    for key in ("f_GHz", "f_O1_GHz"):
        out[key] = [float(h[key][pos[m]]) if m in pos else float(f_linear[m]) for m in range(n)]
    for key in ("chi_MHz", "chi_O1_MHz"):
        out[key] = [[float(h[key][pos[a]][pos[b]]) if a in pos and b in pos else 0.0 for b in range(n)]
                    for a in range(n)]
    return out


def epr_analysis(epr: dict, freqs_GHz=None, Q=None, tan_delta: float | None = None, **kw) -> dict:
    """Participations (:func:`participations`) + EPR Hamiltonian (:func:`epr_hamiltonian`) in one dict.

    Adds ``chi_MHz`` (M×M, diagonal = α), ``f_GHz`` dressed (numerical diagonalisation), the first-order values, and
    with ``tan_delta`` the bulk-dielectric Q per mode (1 / (p_substrate tan δ)); ``Q`` (per mode) is passed through.
    """
    p = participations(epr, freqs_GHz)
    bad = junction_self_modes(p)
    keep = [i for i in range(len(p["f_GHz"])) if i not in bad]
    if bad and keep:  # the Hamiltonian of the circuit modes only; the junction's own LC mode is left out
        h_sub = epr_hamiltonian([p["f_GHz"][i] for i in keep], [p["p_mj"][i] for i in keep], p["Lj_nH"],
                                [p["s_mj"][i] for i in keep], **kw)
        h = _expand(h_sub, keep, p["f_GHz"])
        p = {**p, "p_mj": [[0.0] * len(r) if i in bad else r for i, r in enumerate(p["p_mj"])]}
    else:
        h = epr_hamiltonian(p["f_GHz"], p["p_mj"], p["Lj_nH"], p["s_mj"], **kw)
    out = {
        "method": "pyEPR line_voltage, renormalised (field integrals from qcc_solve.py)",
        **{k: p[k] for k in ("junctions", "Lj_nH", "Cj_fF", "p_mj", "p_mj_raw", "s_mj", "U_diff", "p_volume")},
        "f_linear_GHz": p["f_GHz"],
        "f_GHz": h["f_GHz"],
        "chi_MHz": h["chi_MHz"],
        "f_O1_GHz": h["f_O1_GHz"],
        "chi_O1_MHz": h["chi_O1_MHz"],
    }
    if bad:
        out["junction_self_modes"] = sorted(bad)
    if Q is not None:
        out["Q"] = [None if q is None else float(q) for q in Q]
    if tan_delta:
        out["Q_dielectric"] = [
            (1 / (sum(v.values()) * tan_delta) if v and sum(v.values()) > 0 else None) for v in p["p_volume"]
        ]
    return out


def epr_hamiltonian(
    freqs_GHz,
    p_mj,
    lj_nH,
    s_mj=None,
    cos_trunc: int = 8,
    fock_trunc: int = 9,
    numerical: bool = True,
) -> dict:
    """Dressed frequencies and χ matrix from EPR data.

    Returns ``f_GHz`` (dressed, numerical diagonalisation or 1st-order PT), ``chi_MHz`` (M×M; diagonal = α), and the
    first-order values ``f_O1_GHz`` / ``chi_O1_MHz``.
    """
    import contextlib  # pylint: disable=import-outside-toplevel
    import io  # pylint: disable=import-outside-toplevel

    from pyEPR.calcs import CalcsTransmon, Convert  # pylint: disable=import-outside-toplevel
    from pyEPR.calcs.back_box_numeric import epr_numerical_diagonalization  # pylint: disable=C0415

    f = np.atleast_1d(np.asarray(freqs_GHz, dtype=float))
    p = np.atleast_2d(np.asarray(p_mj, dtype=float))
    if p.shape[0] != len(f):
        p = p.T
    s = np.ones_like(p) if s_mj is None else np.atleast_2d(np.asarray(s_mj, dtype=float)).reshape(p.shape)
    lj_H = np.atleast_1d(np.asarray(lj_nH, dtype=float)) * 1e-9

    phi_zpf, (om, ej, _, _) = Convert.ZPF_from_EPR(f, p, s, lj_H, Lj_units_in="H")
    f_o1, chi_o1 = CalcsTransmon.dispersiveH_params_PT_O1(p, om, ej)
    out = {
        "f_linear_GHz": f.tolist(),
        "f_O1_GHz": np.real(np.asarray(f_o1)).astype(float).tolist(),
        "chi_O1_MHz": (-np.real(np.asarray(chi_o1))).astype(float).tolist(),
        "phi_zpf": np.asarray(phi_zpf).tolist(),
    }
    if numerical:
        with contextlib.redirect_stdout(io.StringIO()):
            f_nd_hz, chi_nd = epr_numerical_diagonalization(
                f, lj_H, phi_zpf, cos_trunc=cos_trunc, fock_trunc=fock_trunc
            )
        out["f_GHz"] = (np.real(np.asarray(f_nd_hz)) / 1e9).astype(float).tolist()
        out["chi_MHz"] = (-np.real(np.asarray(chi_nd))).astype(float).tolist()
    else:
        out["f_GHz"], out["chi_MHz"] = out["f_O1_GHz"], out["chi_O1_MHz"]
    return out


def epr_qutip(freqs_GHz, p_mj, lj_nH, s_mj=None, fock: int = 8) -> dict:
    """Independent QuTiP check of the EPR Hamiltonian (not pyEPR's code path).

    H = sum_m h f_m a_m^+ a_m - sum_j EJ_j [cos(phi_j) + phi_j^2 / 2], phi_j = sum_m s_mj phi_mj (a_m + a_m^+),
    phi_mj^2 = p_mj h f_m / (2 EJ_j), EJ = (hbar / 2e)^2 / Lj. The cosine is exact (``cosm``), so only the Fock
    truncation differs from pyEPR's Taylor series. Returns the dressed single-excitation ``f_GHz`` and ``chi_MHz``
    (M x M, qcc sign: diagonal = alpha, off-diagonal chi_mn = E(1_m 1_n) - E(1_m) - E(1_n) + E(0)).
    """
    import qutip as qt  # pylint: disable=import-outside-toplevel

    h, hbar, e = 6.62607015e-34, 1.054571817e-34, 1.602176634e-19
    f = np.atleast_1d(np.asarray(freqs_GHz, dtype=float))
    p = np.atleast_2d(np.asarray(p_mj, dtype=float))
    if p.shape[0] != len(f):
        p = p.T
    s = np.ones_like(p) if s_mj is None else np.atleast_2d(np.asarray(s_mj, dtype=float)).reshape(p.shape)
    ej = (hbar / (2 * e)) ** 2 / (np.atleast_1d(np.asarray(lj_nH, dtype=float)) * 1e-9)  # J
    m = len(f)
    ops = [qt.tensor([qt.destroy(fock) if k == i else qt.qeye(fock) for k in range(m)]) for i in range(m)]
    ej_ghz = ej / h / 1e9  # build in GHz: QuTiP drops matrix elements as small as SI energies (~1e-24 J)
    ham = sum(f[i] * ops[i].dag() * ops[i] for i in range(m))
    for j in range(p.shape[1]):
        phi = sum(s[i, j] * np.sqrt(p[i, j] * f[i] / (2 * ej_ghz[j])) * (ops[i] + ops[i].dag()) for i in range(m))
        ham = ham - ej_ghz[j] * (phi.cosm() + 0.5 * phi * phi)
    evals, evecs = ham.eigenstates()

    def level(occ):
        bare = qt.tensor([qt.basis(fock, n) for n in occ])
        return float(np.real(evals[int(np.argmax([abs(bare.overlap(v)) for v in evecs]))]))

    e0 = level([0] * m)
    one = [level([1 if k == i else 0 for k in range(m)]) for i in range(m)]
    chi = np.zeros((m, m))
    for i in range(m):
        chi[i, i] = (level([2 if k == i else 0 for k in range(m)]) - 2 * one[i] + e0) * 1e3
        for k in range(i + 1, m):
            occ = [1 if q in (i, k) else 0 for q in range(m)]
            chi[i, k] = chi[k, i] = (level(occ) - one[i] - one[k] + e0) * 1e3
    return {"f_GHz": [x - e0 for x in one], "chi_MHz": chi.tolist()}


def junction_participation_from_energy(freq_GHz: float, lj_nH: float, i_peak_A: float, u_total_J: float) -> float:
    """p_J = ½ Lj I² / U_total for a mode with peak junction current ``i_peak_A`` and total energy ``u_total_J``."""
    return 0.5 * lj_nH * 1e-9 * i_peak_A**2 / u_total_J

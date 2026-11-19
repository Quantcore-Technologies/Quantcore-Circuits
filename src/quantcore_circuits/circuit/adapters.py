"""Estimator adapters (M9): ``solve(filled) -> ParamSet`` with Metal LOM, QuCat, SQcircuit and scqubits.

A ``ParamSet`` is a flat dict keyed like the design targets: ``"<Q>.f_q_GHz"``, ``"<Q>.alpha_MHz"``, ``"<Q>.EJ_GHz"``,
``"<Q>.EC_GHz"``, ``"<R>.f_GHz"`` (dressed resonator), ``"<R>.g_MHz"``, ``"<R>.chi_MHz"`` (χ = E11 − E10 − E01 + E00)
and ``"<R>.kappa_MHz"`` when a feedline coupling is known. Every adapter sees the same filled circuit (same
C-matrix, Lj, λ/4 LC) and quantises it its own way:

* ``metal_lom`` — Quantum Metal LOM 2.0: TRANSMON + TL_RESONATOR subsystems on the Maxwell matrix
* ``qucat`` — QuCat lumped network (C-matrix branches + JJ + λ/4 parallel LC): its circuit Hamiltonian (junction
  Taylor-expanded) diagonalised with QuTiP
* ``sqcircuit`` — SQcircuit exact diagonalisation of the 2-node circuit (charge × harmonic basis)
* ``scqubits`` — scqubits Transmon + Oscillator HilbertSpace with the analytic loaded coupling
* ``pyepr`` — not a LOM: pyEPR's Hamiltonian from an eigenmode job's junction participations (``eigenmode_epr``);
  it runs only when the filled circuit carries EPR results (``filled.results["epr"]``)
"""

from __future__ import annotations

import contextlib
import io
import warnings

import numpy as np

from quantcore_circuits.circuit.fill import FilledCircuit, TransmonReadout, two_node_model

ParamSet = dict[str, float]


def _keys(p: TransmonReadout, out: dict) -> ParamSet:
    q, r = p.qubit, p.resonator
    mapping = {
        "f_q_GHz": f"{q}.f_q_GHz",
        "alpha_MHz": f"{q}.alpha_MHz",
        "EJ_GHz": f"{q}.EJ_GHz",
        "EC_GHz": f"{q}.EC_GHz",
        "f_r_GHz": f"{r}.f_GHz",
        "g_MHz": f"{r}.g_MHz",
        "chi_MHz": f"{r}.chi_MHz",
        "kappa_MHz": f"{r}.kappa_MHz",
    }
    return {mapping[k]: float(v) for k, v in out.items() if k in mapping and v is not None and np.isfinite(v)}


def metal_lom(filled: FilledCircuit) -> ParamSet:
    from quantcore_circuits.analysis.lom import lom_transmon_resonator  # pylint: disable=import-outside-toplevel

    out: ParamSet = {}
    for p in filled.pairs:
        if getattr(p, "kind", "lambda/4") != "lambda/4":
            continue  # Metal's lom_transmon_resonator models a λ/4 line; a λ/2 readout would get the wrong g
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Metal's TL_RESONATOR takes the resonator frequency as given: pass the claw-loaded λ/4 frequency
            f_r = two_node_model(p)["f_r_loaded_GHz"]
            res = lom_transmon_resonator(
                p.cmatrix_fF, p.labels, p.labels[0], p.labels[1], p.lj_nH, f_r, p.cj_fF, z0=p.z0_ohm
            )
        out.update(_keys(p, res))
    return out


def _qucat_network(p: TransmonReadout):
    from qucat import C, J, L, Network  # pylint: disable=import-outside-toplevel

    tn = two_node_model(p)
    comps = [
        C(0, 1, p.c_island_fF * 1e-15),
        J(0, 1, "Lj"),
        C(1, 2, p.cg_fF * 1e-15),
        C(0, 2, (p.c_coupler_fF + tn["C_r_fF"]) * 1e-15),
        L(0, 2, tn["L_r_nH"] * 1e-9),
    ]
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Network(comps), tn


def qucat(filled: FilledCircuit, taylor: int = 8, excitations: tuple[int, int] = (10, 10)) -> ParamSet:
    """QuCat: normal modes + the circuit Hamiltonian (junction cosine Taylor-expanded to ``taylor``), diagonalised
    with QuTiP. States are identified by overlap with the bare Fock states of the (qubit, resonator) modes.

    ``excitations`` per mode: 10 resonator levels (not 6) keep α converged for strongly anharmonic qubits (a Metal
    TransmonPocket with α ≈ −460 MHz: −416 MHz with 6 levels, −457.5 with 10, SQcircuit −459.2)."""
    import qutip as qt  # pylint: disable=import-outside-toplevel

    out: ParamSet = {}
    for p in filled.pairs:
        net, tn = _qucat_network(p)
        lj = p.lj_nH * 1e-9
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f, _, a, _ = (np.real(x) for x in net.f_k_A_chi(Lj=lj))
            h = net.hamiltonian(modes="all", taylor=taylor, excitations=list(excitations), Lj=lj)
        qm = int(np.argmax(a))  # modes are ordered by frequency; the qubit is the most anharmonic one
        rm = 1 - qm
        evals, evecs = h.eigenstates()
        evals = np.real(evals) / 1e9
        dims = list(excitations)

        def level(nq, nr, qm=qm, rm=rm, dims=dims, evals=evals, evecs=evecs):
            occ = [0, 0]
            occ[qm], occ[rm] = nq, nr
            bare = qt.tensor(qt.basis(dims[0], occ[0]), qt.basis(dims[1], occ[1]))
            return float(evals[int(np.argmax([abs(bare.overlap(v)) for v in evecs]))])

        e00, e10, e01, e20, e11 = level(0, 0), level(1, 0), level(0, 1), level(2, 0), level(1, 1)
        entry = {
            "f_q_GHz": e10 - e00,
            "alpha_MHz": (e20 - 2 * e10 + e00) * 1e3,
            "f_r_GHz": e01 - e00,
            "chi_MHz": (e11 - e10 - e01 + e00) * 1e3,
            "EJ_GHz": tn["EJ_GHz"],
            "EC_GHz": tn["EC_GHz"],
        }
        out.update(_keys(p, entry))
        out[f"{p.qubit}.f_linear_GHz"] = float(f[qm] / 1e9)
    return out


def _sq_levels(p: TransmonReadout, n_levels: int = 14):
    import SQcircuit as sq  # pylint: disable=import-outside-toplevel

    tn = two_node_model(p)
    sq.set_unit_freq("GHz")
    c1 = sq.Capacitor(p.c_island_fF, "fF")
    cg = sq.Capacitor(p.cg_fF, "fF")
    c2 = sq.Capacitor(p.c_coupler_fF + tn["C_r_fF"], "fF")
    lr = sq.Inductor(tn["L_r_nH"], "nH")
    jj = sq.Junction(tn["EJ_GHz"], "GHz")
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cr = sq.Circuit({(0, 1): [c1, jj], (1, 2): [cg], (0, 2): [c2, lr]})
        cr.set_trunc_nums([12 if w > 0 else 30 for w in np.atleast_1d(cr.omega)])
        efreqs, _ = cr.diag(n_levels)
    ev = np.sort(np.real(np.asarray(efreqs, dtype=float)))
    return ev - ev[0], tn


def sqcircuit(filled: FilledCircuit) -> ParamSet:
    from quantcore_circuits.analysis.transmon import transmon_spectrum  # pylint: disable=import-outside-toplevel

    out: ParamSet = {}
    for p in filled.pairs:
        ev, tn = _sq_levels(p)
        fq0, a0 = transmon_spectrum(tn["EJ_GHz"], tn["EC_GHz"])
        fr0 = tn["f_r_loaded_GHz"]
        used: set[int] = {0}

        def take(guess, ev=ev, used=used):
            i = min((k for k in range(len(ev)) if k not in used), key=lambda k: abs(ev[k] - guess))
            used.add(i)
            return ev[i]

        e10 = take(fq0)
        e01 = take(fr0)
        e20 = take(2 * fq0 + a0 / 1e3)
        e11 = take(fq0 + fr0)
        out.update(
            _keys(
                p,
                {
                    "f_q_GHz": e10,
                    "alpha_MHz": (e20 - 2 * e10) * 1e3,
                    "f_r_GHz": e01,
                    "chi_MHz": (e11 - e10 - e01) * 1e3,
                    "EJ_GHz": tn["EJ_GHz"],
                    "EC_GHz": tn["EC_GHz"],
                },
            )
        )
    return out


def scqubits(filled: FilledCircuit) -> ParamSet:
    from quantcore_circuits.analysis.transmon import dressed_transmon_resonator  # pylint: disable=C0415

    out: ParamSet = {}
    for p in filled.pairs:
        tn = two_node_model(p)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = dressed_transmon_resonator(tn["EJ_GHz"], tn["EC_GHz"], tn["f_r_loaded_GHz"], tn["g_MHz"])
        out.update(_keys(p, {**res, "g_MHz": tn["g_MHz"], "EJ_GHz": tn["EJ_GHz"], "EC_GHz": tn["EC_GHz"]}))
    return out


def _epr_results(filled: FilledCircuit) -> list[dict]:
    """Every EPR result the filled circuit carries: ``filled.results`` and, for a subset fill with several eigenmode
    jobs, each job's own (``filled.jobs``), once each."""
    out, seen = [], set()
    for res in [filled.results or {}] + [j.get("results") or {} for j in getattr(filled, "jobs", [])]:
        if (res.get("epr") or {}).get("p_mj") and id(res) not in seen:
            seen.add(id(res))
            out.append(res)
    return out


def epr_modes(filled: FilledCircuit, results: dict | None = None) -> dict[str, dict]:
    """Qubit and resonator mode of each pair in the job's EPR result (``filled.results["epr"]``, or ``results``).

    The qubit mode is the one with the largest participation of the qubit's junction; the resonator mode is the
    remaining mode closest to the pair's claw-loaded λ/4 (LOM) frequency. Returns qubit → {"qm", "rm", "junction"}.
    A pair whose qubit has no junction in this result (a subset job without it) is left out.
    """
    epr = ((filled.results if results is None else results) or {}).get("epr") or {}
    if "p_mj" not in epr:
        return {}
    p = np.asarray(epr["p_mj"], dtype=float)  # modes × junctions
    names = epr.get("junction_names") or [f"junction_{j}" for j in epr["junctions"]]
    f_lin = np.asarray(epr["f_linear_GHz"], dtype=float)
    out = {}
    for pair in filled.pairs:
        j = next((k for k, n in enumerate(names) if n.split(".", 1)[0] == pair.qubit), None)
        if j is None:
            continue
        qm = int(np.argmax(p[:, j]))
        f_guess = two_node_model(pair)["f_r_loaded_GHz"]
        rest = [m for m in range(len(f_lin)) if m != qm]
        rm = min(rest, key=lambda m: abs(f_lin[m] - f_guess)) if rest else None
        out[pair.qubit] = {"qm": qm, "rm": rm, "junction": j, "resonator": pair.resonator}
    return out


def _epr_plausible(f_linear: float, f_dressed: float, alpha_MHz: float) -> bool:
    """A pyEPR mode is usable when its dressed frequency stays within 30 % of the linear eigenfrequency and |α| is
    below a quarter of f (a transmon's α is a few % of f_q; the Lamb / Kerr shifts are far below 30 %)."""
    try:
        f_linear, f_dressed, alpha_MHz = float(f_linear), float(f_dressed), float(alpha_MHz)
    except (TypeError, ValueError):
        return False
    if not all(np.isfinite([f_linear, f_dressed, alpha_MHz])) or f_linear <= 0:
        return False
    return abs(f_dressed - f_linear) <= 0.3 * f_linear and abs(alpha_MHz) <= 250.0 * f_linear


def pyepr(filled: FilledCircuit) -> ParamSet:
    """pyEPR on eigenmode data (``eigenmode_epr`` job): dressed f_q, α, f_r and χ from the EPR Hamiltonian
    (pyEPR numerical diagonalisation of the junction participations, :func:`quantcore_circuits.analysis.epr.
    epr_analysis`), κ = f/Q of the resonator mode (50 Ω-terminated feedline). Empty without EPR results."""
    out: ParamSet = {}
    for res in _epr_results(filled) or [filled.results or {}]:
        for k, v in _pyepr_one(filled, res).items():
            out.setdefault(k, v)  # a qubit in two subset jobs: the first job's values
    return out


def _pyepr_one(filled: FilledCircuit, results: dict) -> ParamSet:
    epr = (results or {}).get("epr") or {}
    out: ParamSet = {}
    chi = np.asarray(epr.get("chi_MHz", []), dtype=float)
    f_nd = epr.get("f_GHz") or []
    q = epr.get("Q") or []
    f_lin = epr.get("f_linear_GHz") or []
    for qubit, m in epr_modes(filled, results).items():
        qm, rm = m["qm"], m["rm"]
        if not _epr_plausible(f_lin[qm], f_nd[qm], chi[qm, qm]):
            # an unconverged mesh (e.g. a capped fast run) can leave the junction resonating on its own (p_J ≈ 1 at
            # 1/2π√(L_J C_J)) and the diagonalisation then returns nonsense: never let that win the consensus
            warnings.warn(f"pyepr: {qubit} mode {qm + 1} dropped (linear {f_lin[qm]:.3f} GHz, dressed {f_nd[qm]:.3f} "
                          f"GHz, α {chi[qm, qm]:.4g} MHz: not a transmon; mesh not converged?)", stacklevel=2)
            continue
        if rm is not None and not _epr_plausible(f_lin[rm], f_nd[rm], 0.0):
            rm = None
        out[f"{qubit}.f_q_GHz"] = float(f_nd[qm])
        out[f"{qubit}.alpha_MHz"] = float(chi[qm, qm])
        out[f"{qubit}.f_linear_GHz"] = float(epr["f_linear_GHz"][qm])
        out[f"{qubit}.p_junction"] = float(epr["p_mj"][qm][m["junction"]])
        if rm is not None:
            r = m["resonator"]
            out[f"{r}.f_GHz"] = float(f_nd[rm])
            out[f"{r}.chi_MHz"] = float(chi[qm, rm])
            out[f"{r}.f_linear_GHz"] = float(epr["f_linear_GHz"][rm])
            hv = filled.values.get(f"K_{r}")
            if hv is not None and hv.extracted is not None:  # FEM κ_ext of the hanger (driven fit preferred, fill)
                out[f"{r}.kappa_MHz"] = float(hv.extracted)
            elif len(q) > rm and q[rm]:  # κ_ext: the 50 Ω feedline load only (bulk-dielectric loss removed)
                qd = (epr.get("Q_dielectric") or [None] * len(q))[rm]
                q_ext = 1 / (1 / q[rm] - 1 / qd) if qd and 1 / q[rm] > 1 / qd else q[rm]
                out[f"{r}.kappa_MHz"] = float(epr["f_linear_GHz"][rm] / q_ext * 1e3)
        if len(q) > qm and q[qm]:
            out[f"{qubit}.Q"] = float(q[qm])
    return out


ADAPTERS = {"metal_lom": metal_lom, "qucat": qucat, "sqcircuit": sqcircuit, "scqubits": scqubits, "pyepr": pyepr}


def solve_all(filled: FilledCircuit, names: list[str] | None = None) -> dict[str, ParamSet]:
    """Run each adapter; a failing estimator is reported as ``{"error": message}`` instead of aborting the rest.

    ``pyepr`` joins the model's estimators automatically when the filled circuit carries EPR results."""
    out: dict[str, ParamSet] = {}
    names = list(names or filled.model.estimators)
    if "pyepr" not in names and _epr_results(filled):
        names.append("pyepr")
    for name in names:
        fn = ADAPTERS.get(name)
        if fn is None:
            continue
        try:
            out[name] = fn(filled)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    return out

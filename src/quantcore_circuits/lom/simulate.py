"""LOM simulation of any circuit: ``circuit.json`` (+ values) → QuCat network → modes, κ → QuTiP Hamiltonian.

This is the "simulate the lumped circuit later" path: it needs no FEM. Give it a circuit exported from a layout
(component estimates), or one filled from HFSS/Q3D/Sonnet results, and it returns per-mode frequencies, linewidths
and anharmonicities, the cross-Kerr matrix, and the dressed spectrum from diagonalising QuCat's circuit Hamiltonian
(junction cosine Taylor-expanded) with QuTiP. Modes are named after the element that stores most of their
inductive energy: a junction (``Q1``) or a resonator's λ/4 inductance (``R1``).

Element mapping: ``C`` → capacitor, ``JJ``/``SQUID`` → junction (Lj, + Cj in parallel), ``TLres`` λ/4 or λ/2 →
parallel LC at its node (fundamental mode), ``HANGER`` → the coupling capacitance that gives the hanger's κ into the
feedline load (κ = ω² C_k² R_load / C_r), ``R`` → port resistor, ``L`` → inductor.

Before QuCat, nodes that only capacitors touch (unused couplers, the far plate of a coupling capacitor, a merged
coupler bus) are eliminated exactly by Kron reduction of the capacitance matrix: such a node carries no charge, so
C_red = C_kk − C_ke C_ee⁻¹ C_ek changes nothing physical. It removes QuCat's spurious ω ≈ 0 roots and keeps its
polynomial solve small (a 4-qubit ring: 12 → 4 nodes). The QuTiP space is capped at ``max_dim`` states (fewer levels
per mode when many modes are kept); modes are labelled one-to-one with their dominant inductive element.

**ZZ** (static, between qubit modes): ζ = E11 − E10 − E01 + E00 on the dressed levels (bare normal-mode states
matched by overlap), in ``LomResult.zz_MHz`` for qubit pairs that are circuit *neighbours* (a path of elements
between their junction nodes that crosses no other qubit and no port/feedline load) whose modes are not
hybridised, and in ``dressed["zz"]`` for every pair (with ``neighbours`` / ``hybridised`` flags). It is exact within
the Taylor-expanded junction cosine and the truncation: it equals a charge-basis diagonalisation of two coupled
transmons, and second-order perturbation theory with the transmon matrix elements (tests). The textbook
2g²(α1 + α2)/((Δ + α1)(Δ − α2)) with the harmonic g is ≈ 15 % larger for E_J/E_C ≈ 57. When two qubit modes
hybridise (|Δ| ≲ g), per-qubit ZZ is not defined.

**Validation.** Every network is also solved as a lossless normal-mode problem (K v = ω² C v, junctions
linearised). When QuCat's roots or zero-point fluctuations disagree with it (degenerate or near-degenerate roots:
identical coupled qubits, a floating transmon between strongly coupled resonators), the modes and the Hamiltonian
come from that solve (same form as QuCat's), κ from the nearest QuCat mode, and a note says so.
"""

from __future__ import annotations

import contextlib
import io
import math
import re
import warnings
from dataclasses import dataclass, field

import numpy as np

from quantcore_circuits import track as _track


@dataclass
class Mode:
    index: int
    label: str  # element holding most inductive energy (qubit or resonator name)
    kind: str  # "qubit" | "resonator" | "other"
    f_GHz: float  # linear (normal-mode) frequency
    kappa_MHz: float
    anharmonicity_MHz: float  # QuCat first-order A (positive)
    participation: dict[str, float] = field(default_factory=dict)


@dataclass
class LomResult:
    modes: list[Mode]
    chi_MHz: list[list[float]]  # cross-Kerr (QuCat first order, qcc sign: χ = E11 − E10 − E01 + E00)
    dressed: dict  # from the QuTiP diagonalisation
    params: dict  # ParamSet keyed like the targets
    notes: list[str] = field(default_factory=list)
    netlist: list[dict] = field(default_factory=list)  # the circuit's elements, then what was handed to QuCat
    zz_MHz: dict[str, float] = field(default_factory=dict)  # "Q1-Q2" → static ZZ of neighbouring qubits (QuTiP)


def _resonator_lc(f_GHz: float, z0: float, kind: str) -> tuple[float, float]:
    """(C fF, L nH) of the parallel LC equivalent of a TL resonator's fundamental seen from its open end:
    C = π/(4 ω Z0) for λ/4, π/(2 ω Z0) for λ/2 (half the line capacitance in both cases), L = 1/(ω² C)."""
    from quantcore_circuits.circuit.bridges import quarter_wave_lc  # pylint: disable=import-outside-toplevel

    if kind != "lambda/2":
        return quarter_wave_lc(f_GHz, z0)
    w = 2 * math.pi * f_GHz * 1e9
    cr = math.pi / (2 * w * z0)
    return cr / 1e-15, 1 / (w**2 * cr) / 1e-9


def _elements(filled, notes):
    """QuCat components + a readable netlist from the filled circuit's chosen values."""
    from qucat import C, J, L, R  # pylint: disable=import-outside-toplevel

    model = filled.model
    order = [model.ground] + [n for n in model.nodes if n != model.ground]
    idx = {n: i for i, n in enumerate(order)}
    comps, netlist, inductive = [], [], {}
    lj = {}
    for name, v in filled.values.items():
        a, b = (idx[n] for n in v.nodes)
        val = v.value
        if v.type == "C" and val:
            comps.append(C(a, b, val * 1e-15))
            netlist.append({"element": name, "qucat": "C", "nodes": list(v.nodes), "value": val, "unit": "fF"})
        elif v.type in ("JJ", "SQUID") and val:
            label = f"Lj_{name}"
            j = J(a, b, label)
            comps.append(j)
            lj[label] = val * 1e-9
            inductive[name] = (j, val * 1e-9, "qubit")
            netlist.append({"element": name, "qucat": "J", "nodes": list(v.nodes), "value": val, "unit": "nH"})
            cj = v.extra.get("Cj_fF") or 0.0
            if cj:
                comps.append(C(a, b, cj * 1e-15))
        elif v.type == "TL":
            kind = v.extra.get("kind", "lambda/4")
            f, z0 = v.extra["f_GHz"], v.extra["Z0_ohm"]
            cr, lr = _resonator_lc(f, z0, kind)
            comps += [C(a, b, cr * 1e-15)]
            ind = L(a, b, lr * 1e-9)
            comps.append(ind)
            inductive[name] = (ind, lr * 1e-9, "resonator")
            netlist.append(
                {
                    "element": name,
                    "qucat": "C‖L",
                    "nodes": list(v.nodes),
                    "value": [cr, lr],
                    "unit": "fF, nH",
                    "kind": kind,
                    "f_GHz": f,
                    # kinetic inductance of the film (decision #45): the share of the equivalent L_r it provides
                    **(
                        {
                            "alpha_k": v.extra["alpha_k"],
                            "L_k_nH": v.extra["alpha_k"] * lr,
                            "L_geo_nH": (1 - v.extra["alpha_k"]) * lr,
                        }
                        if "alpha_k" in v.extra
                        else {}
                    ),
                }
            )
        elif v.type == "HANGER" and val:
            res = next((r for r, x in filled.values.items() if x.type == "TL" and x.nodes[0] in v.nodes), None)
            if res is None:
                notes.append(f"{name}: no resonator on its nodes; skipped")
                continue
            f, z0 = filled.values[res].extra["f_GHz"], filled.values[res].extra["Z0_ohm"]
            cr = _resonator_lc(f, z0, filled.values[res].extra.get("kind", "lambda/4"))[0]
            r_load = 25.0  # feedline both ways
            w = 2 * math.pi * f * 1e9
            ck = math.sqrt(val * 1e6 * 2 * math.pi * cr * 1e-15 / (w**2 * r_load))
            comps.append(C(a, b, ck))
            netlist.append(
                {
                    "element": name,
                    "qucat": "C",
                    "nodes": list(v.nodes),
                    "value": ck / 1e-15,
                    "unit": "fF",
                    "note": f"hanger κ {val:.3g} MHz → equivalent C_k",
                }
            )
        elif v.type == "R" and val:
            comps.append(R(a, b, val))
            netlist.append({"element": name, "qucat": "R", "nodes": list(v.nodes), "value": val, "unit": "Ω"})
        elif v.type == "L" and val:
            ind = L(a, b, val * 1e-9)
            comps.append(ind)
            inductive[name] = (ind, val * 1e-9, "other")
            netlist.append({"element": name, "qucat": "L", "nodes": list(v.nodes), "value": val, "unit": "nH"})
    comps = _kron_reduce(comps, order, netlist, notes)
    # QuCat rejects a node that touches only one other node (it calls the circuit "open"), e.g. a floating island
    # whose capacitance to ground was neglected: give such nodes a negligible parasitic capacitance to ground
    neighbours: dict[int, set[int]] = {}
    for comp in comps:
        a, b = comp.node_minus, comp.node_plus
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    if len(neighbours) > 2:
        for n_idx, nbrs in sorted(neighbours.items()):
            if len(nbrs) == 1 and n_idx != 0:
                comps.append(C(0, n_idx, 0.01e-15))
                node = order[n_idx]
                netlist.append({"element": f"Cpar_{node}", "qucat": "C", "nodes": [node, model.ground], "value": 0.01})
                notes.append(f"{node}: no capacitance to ground in the circuit; 0.01 fF parasitic added for QuCat")
    return comps, netlist, inductive, lj


def _qucat_value(c) -> float:
    """A QuCat component's value: ``values[0]`` on QuCat's main branch, ``value`` in the 1.0.3 release on PyPI."""
    vals = getattr(c, "values", None)
    return float(vals[0] if vals is not None else c.value)


def _kron_reduce(comps, order, netlist, notes):
    """Eliminate nodes that only capacitors touch (exact: they hold no charge); see the module docstring."""
    from qucat import C  # pylint: disable=import-outside-toplevel

    caps = [c for c in comps if isinstance(c, C)]
    others = [c for c in comps if not isinstance(c, C)]
    touched = {n for c in comps for n in (c.node_minus, c.node_plus)}
    held = {n for c in others for n in (c.node_minus, c.node_plus)} | {0}
    elim = sorted(touched - held)
    if not elim:
        return comps
    nodes = sorted(touched | {0})
    pos = {n: i for i, n in enumerate(nodes)}
    m = np.zeros((len(nodes), len(nodes)))
    for c in caps:
        i, j, v = pos[c.node_minus], pos[c.node_plus], _qucat_value(c)
        m[i, i] += v
        m[j, j] += v
        m[i, j] -= v
        m[j, i] -= v
    e = [pos[n] for n in elim]
    k = [pos[n] for n in nodes if n not in elim]
    m_ee = m[np.ix_(e, e)]
    if np.linalg.cond(m_ee) > 1e12:  # a capacitor-only island with no capacitance out of it: leave it to QuCat
        notes.append(f"Kron reduction skipped: capacitor-only nodes {[order[n] for n in elim]} are isolated")
        return comps
    red = m[np.ix_(k, k)] - m[np.ix_(k, e)] @ np.linalg.solve(m_ee, m[np.ix_(e, k)])
    kept = [nodes[i] for i in k]
    new = []
    for a in range(len(kept)):
        for b in range(a + 1, len(kept)):
            v = -red[a, b]
            if v > 1e-21:  # 1e-6 fF
                new.append(C(kept[a], kept[b], v))
                netlist.append(
                    {
                        "element": f"Cred_{order[kept[a]]}_{order[kept[b]]}",
                        "qucat": "C",
                        "nodes": [order[kept[a]], order[kept[b]]],
                        "value": v / 1e-15,
                        "unit": "fF",
                        "note": "Kron-reduced capacitance handed to QuCat",
                    }
                )
    notes.append(
        f"capacitor-only node(s) {[order[n] for n in elim]} eliminated exactly (Kron reduction) before QuCat; the "
        "`Cred_*` netlist rows are the capacitances it was given"
    )
    return others + new


def _unique_labels(part_rows: list[dict[str, float]]) -> list[str | None]:
    """One inductive element per mode, one-to-one: the assignment with the largest total participation (identical
    hybridised qubits: the lower mode takes the first name). Modes left over when there are more modes than
    elements get None (the caller names them ``mode<i>``)."""
    names = sorted({k for row in part_rows for k in row}, key=_natural)
    if not names:
        return [None] * len(part_rows)

    def top(row: dict[str, float]) -> str | None:  # None on a tie (to 1e-3): left to the assignment below
        best = max(round(v, 3) for v in row.values())
        tied = [k for k, v in row.items() if round(v, 3) == best]
        return tied[0] if len(tied) == 1 else None

    argmax = [top(row) if row else None for row in part_rows]
    if len(set(argmax)) == len(argmax) and None not in argmax:
        return argmax
    from scipy.optimize import linear_sum_assignment  # pylint: disable=import-outside-toplevel

    # participations equal to 1e-3 are a tie (symmetric / antisymmetric pair): the tiny (r − c)² term then gives the
    # lower mode the first name, deterministically
    cost = np.array(
        [
            [-round(row.get(nm, 0.0), 3) + 1e-9 * (r - c) ** 2 for c, nm in enumerate(names)]
            for r, row in enumerate(part_rows)
        ]
    )
    rows, cols = linear_sum_assignment(cost)
    out: list[str | None] = [None] * len(part_rows)
    for r, c in zip(rows, cols):
        out[r] = names[c]
    return out


def _levels_budget(kinds: list[str], max_dim: int) -> list[int]:
    """Fock levels per kept mode: 10 per qubit, 5 per resonator, reduced (largest first) to ≤ max_dim states,
    never below 4 (qubit) / 3 (other)."""
    exc = [10 if k == "qubit" else 5 for k in kinds]
    floor = [4 if k == "qubit" else 3 for k in kinds]
    while math.prod(exc) > max_dim:
        i = max((j for j in range(len(exc)) if exc[j] > floor[j]), key=lambda j: exc[j], default=None)
        if i is None:
            break
        exc[i] -= 1
    return exc


def _neighbours(filled, qubit_nodes: dict[str, set[str]]) -> set[frozenset[str]]:
    """Qubit pairs joined by a path of elements that crosses no other qubit's junction node and no port load."""
    model = filled.model
    gnd = model.ground
    ports = {n for v in filled.values.values() if v.type == "R" for n in v.nodes if n != gnd}
    adj: dict[str, set[str]] = {}
    for v in filled.values.values():
        a, b = v.nodes
        if gnd in (a, b):
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    owner = {n: q for q, ns in qubit_nodes.items() for n in ns}
    out = set()
    for q, start in qubit_nodes.items():
        seen, stack = set(start), list(start)
        while stack:
            n = stack.pop()
            for m in adj.get(n, ()):
                if m in seen or m in ports:
                    continue
                seen.add(m)
                other = owner.get(m)
                if other and other != q:
                    out.add(frozenset((q, other)))
                    continue
                stack.append(m)
    return out


PHI0_RED = 1.054571817e-34 / (2 * 1.602176634e-19)  # ħ/2e, Wb
H_PLANCK = 6.62607015e-34


def _stamp(m: np.ndarray, pos: dict, a: int, b: int, v: float) -> None:
    ia, ib = pos.get(a), pos.get(b)
    for i in (ia, ib):
        if i is not None:
            m[i, i] += v
    if ia is not None and ib is not None:
        m[ia, ib] -= v
        m[ib, ia] -= v


def _linear_modes(comps, inductive) -> dict | None:
    """Lossless normal modes of the network, independent of QuCat: K v = ω² C v (C: node capacitances, K: inverse
    inductances, junctions linearised; port loads ≤ 1 kΩ ground their node, other resistors are dropped).
    Returns {"f": Hz per mode, "zpf": {element: φ_zpf per mode in units of ħ/2e}} or None when C is singular."""
    import scipy.linalg as sla  # pylint: disable=import-outside-toplevel
    from qucat import C, R  # pylint: disable=import-outside-toplevel

    # a port load (R ≤ 1 kΩ to ground: 25–50 Ω feedlines, pads) holds its node at AC ground; other resistors are open
    held = {
        n
        for c in comps
        if isinstance(c, R) and 0 in (c.node_minus, c.node_plus) and _qucat_value(c) <= 1e3
        for n in (c.node_minus, c.node_plus)
    }
    nodes = sorted({n for c in comps for n in (c.node_minus, c.node_plus)} - {0} - held)
    pos = {n: i for i, n in enumerate(nodes)}
    cm, km = np.zeros((len(nodes),) * 2), np.zeros((len(nodes),) * 2)
    for c in comps:
        if isinstance(c, C):
            _stamp(cm, pos, c.node_minus, c.node_plus, _qucat_value(c))
    for comp, ind, _ in inductive.values():
        _stamp(km, pos, comp.node_minus, comp.node_plus, 1.0 / ind)
    try:
        w2, vec = sla.eigh(km, cm)
    except (np.linalg.LinAlgError, ValueError):
        return None
    good = [i for i, x in enumerate(w2) if x > (2 * math.pi * 1e6) ** 2]
    w = np.sqrt(w2[good])
    vec = vec[:, good]
    hbar = 1.054571817e-34
    zpf = {}
    for name, (comp, _, _) in inductive.items():
        va = vec[pos[comp.node_minus]] if comp.node_minus in pos else 0.0
        vb = vec[pos[comp.node_plus]] if comp.node_plus in pos else 0.0
        zpf[name] = (va - vb) * np.sqrt(hbar / (2 * w)) / PHI0_RED
    return {"f": w / (2 * math.pi), "zpf": zpf}


def _qucat_unreliable(f, a, inductive, lj, lin) -> str | None:
    """Why QuCat's zero-point fluctuations cannot be used (degenerate / near-degenerate roots), or None."""
    if lin is None or not lj:
        return None
    junctions = [nm for nm, (_, _, kd) in inductive.items() if kd == "qubit"]
    a_lin = [
        sum(PHI0_RED**2 / (inductive[j][1] * H_PLANCK) * lin["zpf"][j][m] ** 4 / 2 for j in junctions)
        for m in range(len(lin["f"]))
    ]
    real = [i for i, x in enumerate(f) if x > 1e6]
    if any(not np.isfinite(a[i]) for i in real):
        return "QuCat returned undefined zero-point fluctuations (degenerate modes)"
    if len(real) != len(lin["f"]):
        return f"QuCat found {len(real)} modes, the lossless normal-mode solve {len(lin['f'])}"
    for i in real:
        m = int(np.argmin(abs(lin["f"] - f[i])))
        if abs(lin["f"][m] - f[i]) > 1e-3 * f[i] or abs(a[i] - a_lin[m]) > 0.05 * max(abs(a_lin[m]), 1e3):
            return (
                f"QuCat mode at {f[i] / 1e9:.4f} GHz has A = {a[i] / 1e6:.4g} MHz, the lossless normal-mode solve "
                f"{a_lin[m] / 1e6:.4g} MHz at {lin['f'][m] / 1e9:.4f} GHz (QuCat root/derivative inaccurate)"
            )
    return None


def _modes_from_linear(lin, f_q, k_q, inductive):
    """(f, κ, A, χ, participations) from the lossless solve; κ from the QuCat mode nearest in frequency."""
    f = np.asarray(lin["f"])
    k = np.array([k_q[int(np.argmin(abs(f_q - x)))] if len(f_q) else 0.0 for x in f])
    ej = {j: PHI0_RED**2 / (ind * H_PLANCK) for j, (_, ind, kd) in inductive.items() if kd == "qubit"}
    p2 = {j: lin["zpf"][j] ** 2 for j in ej}
    chi = sum(ej[j] * np.outer(p2[j], p2[j]) for j in ej) if ej else np.zeros((len(f), len(f)))
    a = np.diag(chi) / 2 if ej else np.zeros(len(f))
    chi = np.array(chi, dtype=float)
    np.fill_diagonal(chi, a)
    parts = []
    for m in range(len(f)):
        energy = {nm: lin["zpf"][nm][m] ** 2 / (2 * ind) for nm, (_, ind, _) in inductive.items()}
        tot = sum(energy.values()) or 1.0
        parts.append({nm: v / tot for nm, v in energy.items()})
    return f, k, a, chi, parts


def _hamiltonian(lin, modes, exc, taylor, inductive) -> np.ndarray:
    """QuCat's Hamiltonian (Hz) built from the lossless solve: Σ f_m a†a + Σ_j Σ_{2n≤taylor, n≥2} (−1)^{n+1} E_j
    φ_j^{2n}/(2n)!, φ_j = Σ_m φ_zpf,jm (a_m + a_m†)."""
    import scipy.sparse as sp  # pylint: disable=import-outside-toplevel

    ops = []
    for i, d in enumerate(exc):
        a = sp.diags(np.sqrt(np.arange(1, d)), 1, format="csr")
        mats = [sp.identity(x, format="csr") for x in exc]
        mats[i] = a
        op = mats[0]
        for mt in mats[1:]:
            op = sp.kron(op, mt, format="csr")
        ops.append(op)
    h = sum(lin["f"][m] * (op.T @ op) for m, op in zip(modes, ops))
    for j, (_, ind, kd) in inductive.items():
        if kd != "qubit":
            continue
        ej = PHI0_RED**2 / (ind * H_PLANCK)
        phi = sum(lin["zpf"][j][m] * (op + op.T) for m, op in zip(modes, ops))
        p2 = phi @ phi
        power = p2
        for n in range(2, taylor // 2 + 1):
            power = power @ p2
            h = h + (-1) ** (n + 1) * ej / math.factorial(2 * n) * power
    return np.asarray(h.todense(), dtype=float)


def _lowest_states(hmat: np.ndarray, needed: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """(eigenvalues, |eigenvector|² [basis, state]) of the lowest states, enough to contain the ``needed`` bare
    states (≥ 95 % of each one's weight); the full spectrum when the partial one does not."""
    import scipy.linalg as sla  # pylint: disable=import-outside-toplevel

    if np.abs(hmat.imag).max(initial=0.0) <= 1e-9 * np.abs(hmat.real).max(initial=1.0):
        hmat = np.ascontiguousarray(hmat.real)  # QuCat's H is real for lossless zero-point fluctuations
    dim = hmat.shape[0]
    count = min(dim, max(4 * len(needed), 60))
    while True:
        if count >= dim:
            evals, evecs = np.linalg.eigh(hmat)
        else:
            evals, evecs = sla.eigh(hmat, subset_by_index=[0, count - 1], driver="evr")
        weights = np.abs(evecs) ** 2
        if count >= dim or all(weights[i, :].sum() >= 0.95 for i in needed):
            return np.real(evals), weights
        count = min(dim, 3 * count)


def _natural(label: str) -> list:
    """Sort key: ``Q2`` before ``Q10``."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", label)]


def _spurious(mode: Mode) -> bool:
    """A QuCat root that is not an oscillator: (near) zero frequency or a non-physical anharmonicity."""
    return (
        not np.isfinite(mode.f_GHz)
        or mode.f_GHz < 1e-3
        or not np.isfinite(mode.anharmonicity_MHz)
        or abs(mode.anharmonicity_MHz) > 1e6
    )


def simulate(
    filled,
    taylor: int = 8,
    excitations: list[int] | None = None,
    max_modes: int = 4,
    max_dim: int = 2500,
) -> LomResult:
    """Normal modes + QuTiP dressed spectrum of ``filled`` (see module docstring).

    ``max_modes`` modes (qubits first, then by frequency) enter the QuTiP Hamiltonian, with ``excitations`` Fock
    levels each (default: 10 per qubit, 5 per resonator, reduced to keep ≤ ``max_dim`` states).
    """
    from qucat import Network  # pylint: disable=import-outside-toplevel

    notes: list[str] = []
    comps, netlist, inductive, lj = _elements(filled, notes)
    lin = _linear_modes(comps, inductive)  # before Network(): QuCat renumbers the components' nodes
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        net = Network(comps)
        f, k, a, chi = (np.real(x) for x in net.f_k_A_chi(**lj))
    n = len(f)
    parts = []
    for m in range(n):
        energy = {}
        for name, (comp, ind, _) in inductive.items():
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                phi = float(np.real(comp.zpf(m, "flux", **lj)))
            energy[name] = phi**2 / (2 * ind) if math.isfinite(phi) else 0.0
        tot = sum(energy.values()) or 1.0
        parts.append({k_: v / tot for k_, v in energy.items()})
    fallback = _qucat_unreliable(f, a, inductive, lj, lin)
    if fallback:
        notes.append(fallback)
        f, k, a, chi, parts = _modes_from_linear(lin, f, k, inductive)
        n = len(f)
    modes = [
        Mode(m, f"mode{m}", "other", float(f[m] / 1e9), float(k[m] / 1e6), float(a[m] / 1e6), parts[m])
        for m in range(n)
    ]
    chi_q = [[float(-chi[i, j] / 1e6) for j in range(n)] for i in range(n)]
    # QuCat can return a degenerate root at ω ≈ 0 (with an absurd anharmonicity) when the network has nodes held
    # only by capacitors; the Kron reduction removes those nodes, this guard stays for anything left
    spurious = [m for m in range(n) if _spurious(modes[m])]
    # labels: one inductive element per real mode, one-to-one (spurious roots take no label)
    real = [m for m in range(n) if m not in spurious]
    for m, label in zip(real, _unique_labels([parts[m] for m in real])):
        label = label or f"mode{m}"
        modes[m].kind = inductive[label][2] if label in inductive else "other"
        modes[m].label = label[2:] if label.startswith("J_") else label
    for m in spurious:
        notes.append(
            f"QuCat mode {m} ({modes[m].f_GHz:.3g} GHz, A={modes[m].anharmonicity_MHz:.3g} MHz) is a zero-frequency "
            "artefact of capacitor-only nodes; dropped"
        )
    good = [m for m in range(n) if m not in spurious]
    modes = [modes[m] for m in good]
    expected = len(inductive)
    if len(modes) < expected:
        notes.append(
            f"QuCat found {len(modes)} modes for {expected} inductive elements: degenerate or overdamped modes are "
            "missing (identical coupled qubits: detune one slightly, or simulate pairs)"
        )
    a_max = max((abs(md.anharmonicity_MHz) for md in modes if md.kind == "qubit"), default=0.0)
    for md in modes:
        p_j = sum(v for nm, v in md.participation.items() if nm in inductive and inductive[nm][2] == "qubit")
        if a_max and p_j > 0.1 and abs(md.anharmonicity_MHz) < 1e-3 * a_max:
            notes.append(
                f"mode {md.label} ({md.f_GHz:.4f} GHz): QuCat anharmonicity {md.anharmonicity_MHz:.3g} MHz is "
                f"inconsistent with its junction participation {p_j:.2f} (near-degenerate roots): its QuTiP values "
                "are unreliable; simulate the qubits in pairs or detune them"
            )
        if md.participation and max(md.participation.values()) < 0.6:
            notes.append(
                f"mode {md.label} ({md.f_GHz:.4f} GHz) is hybridised (largest inductive participation "
                f"{max(md.participation.values()):.2f}); its per-element values are not those of one element"
            )
    keep = sorted(range(len(modes)), key=lambda i: (modes[i].kind != "qubit", modes[i].f_GHz))[:max_modes]
    keep = sorted(keep)
    chi_q = [[chi_q[i][j] for j in good] for i in good]
    for i, md in enumerate(modes):
        md.index = i
    keep_qucat = [good[i] for i in keep]
    exc = list(excitations) if excitations else _levels_budget([modes[m].kind for m in keep], max_dim)
    if not excitations and math.prod(exc) < math.prod(10 if modes[m].kind == "qubit" else 5 for m in keep):
        notes.append(f"QuTiP space capped at {math.prod(exc)} states: levels per mode {exc}")
    if fallback:
        hmat = _hamiltonian(lin, keep_qucat, exc, taylor, inductive)
    else:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            hmat = net.hamiltonian(modes=keep_qucat, taylor=taylor, excitations=exc, **lj).full()
    dims = list(exc)
    needed = [[0] * len(keep)]
    for i in range(len(keep)):
        needed += [[int(j == i) for j in range(len(keep))], [2 * int(j == i) for j in range(len(keep))]]
        needed += [[int(j in (i, i2)) for j in range(len(keep))] for i2 in range(i + 1, len(keep))]
    evals, weights = _lowest_states(hmat, [np.ravel_multi_index(tuple(o), dims) for o in needed])
    evals = (evals - evals[0]) / 1e9

    def level(occ):
        return float(evals[int(np.argmax(weights[np.ravel_multi_index(tuple(occ), dims), :]))])

    zero = [0] * len(keep)

    def occ(*pairs):
        o = list(zero)
        for pos, val in pairs:
            o[pos] = val
        return o

    dressed = {"modes": [modes[m].label for m in keep], "levels": [], "excitations": dims, "zz": []}
    params: dict[str, float] = {}
    qubit_nodes = {
        modes[m].label: {n for n in filled.values[f"J_{modes[m].label}"].nodes if n != filled.model.ground}
        for m in keep
        if modes[m].kind == "qubit" and f"J_{modes[m].label}" in filled.values
    }
    nbrs = _neighbours(filled, qubit_nodes)
    zz: dict[str, float] = {}
    for pos, m in enumerate(keep):
        md = modes[m]
        e1 = level(occ((pos, 1)))
        dressed[f"{md.label}.f01_GHz"] = e1
        if md.kind == "qubit":
            e2 = level(occ((pos, 2)))
            params[f"{md.label}.f_q_GHz"] = e1
            params[f"{md.label}.alpha_MHz"] = (e2 - 2 * e1) * 1e3
        else:
            params[f"{md.label}.f_GHz"] = e1
            params[f"{md.label}.kappa_MHz"] = md.kappa_MHz
        for pos2, m2 in enumerate(keep):
            if pos2 <= pos:
                continue
            e11 = level(occ((pos, 1), (pos2, 1)))
            e01 = level(occ((pos2, 1)))
            chi_d = (e11 - e1 - e01) * 1e3
            q, r = (md, modes[m2]) if md.kind == "qubit" else (modes[m2], md)
            # a resonator's χ is the dispersive shift from the qubit it reads out (the largest |χ|); all pairs are in
            # ``dressed`` as chi_<a>_<b>_MHz
            key = f"{r.label}.chi_MHz"
            if q.kind == "qubit" and r.kind == "resonator" and abs(chi_d) > abs(params.get(key, 0.0)):
                params[key] = chi_d
            dressed[f"chi_{md.label}_{modes[m2].label}_MHz"] = chi_d
            if md.kind == "qubit" and modes[m2].kind == "qubit":
                pair = "-".join(sorted((md.label, modes[m2].label), key=_natural))
                neighbour = frozenset((md.label, modes[m2].label)) in nbrs
                hyb = min(max(md.participation.values(), default=0), max(modes[m2].participation.values(), default=0))
                hybrid = bool(hyb < 0.8)
                dressed["zz"].append({"pair": pair, "zz_MHz": chi_d, "neighbours": neighbour, "hybridised": hybrid})
                if neighbour and not hybrid:  # hybridised qubit modes have no per-qubit ZZ
                    zz[pair] = chi_d
    names = "gefhijkl"
    for idx in np.argsort(evals)[:10]:
        flat = int(np.argmax(weights[:, idx]))
        occs = list(np.unravel_index(flat, dims))
        label = ",".join(
            (names[o] if modes[keep[i]].kind == "qubit" and o < len(names) else str(o)) for i, o in enumerate(occs)
        )
        dressed["levels"].append({"label": f"|{label}⟩", "energy": float(evals[idx])})
    out = LomResult(modes, chi_q, dressed, params, notes + filled.notes, netlist, zz)
    _track.emit("lom", result=out, filled=filled)
    return out

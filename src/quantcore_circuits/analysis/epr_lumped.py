"""Energy participation ratios of *lumped* junctions, without field integrals.

A junction in a layout is a lumped inductor (L_J, plus C_J), so its participation in a mode can be had without the
pyEPR line integral of the fields (:mod:`quantcore_circuits.analysis.epr`, ``qcc_solve.py``). Three routes give the
same quantity p_mj, the fraction of mode m's inductive energy stored in junction j:

``eigenmode-dL``
    Hellmann-Feynman on the eigenmode frequencies. Solve the eigenmode problem again with the inductance of *one*
    junction changed by a few percent (the other junctions and the mesh as before); then
    ``p_mj = -2 (L_j / omega_m) d omega_m / d L_j = -2 d ln f_m / d ln L_j`` (:func:`eigenmode_dL`). One extra solve
    per junction and perturbation; no field export. For a lumped LC with the junction in series with the rest of the
    inductance it is exactly ``L_J / L_total``.
``lom``
    The LOM's normal modes (QuCat) already hold each mode's inductive energy per element
    (``LomResult.modes[m].participation``): :func:`epr_from_lom`. Free, but only as good as the component estimates.
``energy``
    The field-solver route: peak junction current and total energy, ``p = 1/2 L_J I^2 / U``
    (:func:`epr_from_energy`).

Every route returns the same dict (:func:`epr_result`) built with the standard EPR formulas
(:func:`quantcore_circuits.analysis.epr.epr_hamiltonian`: phi_zpf from p_mj, the cosine expanded, numerical
diagonalisation): ``{"method", "modes": [{"label", "f_GHz", "kind"}], "junctions", "p", "alpha_MHz", "chi_MHz",
"lamb_MHz", "notes", ...}``. ``chi_MHz`` is the M x M matrix with the self-Kerr (alpha) on the diagonal and the
cross-Kerr off it, ``lamb_MHz`` the dressed minus the linear frequency (Lamb shift, includes the zero-point term).
:func:`compare_epr` lines two results up mode by mode (LOM against eigenmode).

Sign. The dL and LOM routes give |p|; the relative sign ``s_mj`` of a junction's phase in a mode only matters when
one mode touches two junctions (cross-Kerr between them). It defaults to +1 and can be passed in.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

# modes whose largest participation is below this are left out of the numerical Hamiltonian (they stay at their
# linear frequency with zero Kerr terms); the space grows as fock ** modes
P_MIN = 1e-4
MAX_NUMERIC_MODES = 4


# ---- the common result -----------------------------------------------------------------------------------------
def epr_result(
    method: str,
    f_GHz,
    p,
    lj_nH,
    labels: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    junctions: Sequence[str] | None = None,
    s_mj=None,
    notes: Sequence[str] = (),
    p_min: float = P_MIN,
    numerical: bool = True,
    **kw,
) -> dict:
    """The EPR-result dict from linear frequencies ``f_GHz`` (M), participations ``p`` (M x J) and ``lj_nH`` (J).

    ``kinds`` defaults to "qubit" for a mode with a participation above 0.5 and "other" otherwise. ``kw`` goes to
    :func:`~quantcore_circuits.analysis.epr.epr_hamiltonian` (``cos_trunc``, ``fock_trunc``).
    """
    from quantcore_circuits.analysis.epr import _expand, epr_hamiltonian  # pylint: disable=import-outside-toplevel

    f = np.atleast_1d(np.asarray(f_GHz, dtype=float))
    pm = np.atleast_2d(np.asarray(p, dtype=float))
    if pm.shape[0] != len(f):
        pm = pm.T
    lj = np.atleast_1d(np.asarray(lj_nH, dtype=float))
    m, nj = pm.shape
    labels = list(labels) if labels is not None else [f"mode{i + 1}" for i in range(m)]
    junctions = list(junctions) if junctions is not None else [f"J{j + 1}" for j in range(nj)]
    s = np.ones_like(pm) if s_mj is None else np.asarray(s_mj, dtype=float).reshape(pm.shape)
    notes = list(notes)
    if kinds is None:
        kinds = ["qubit" if pm[i].max(initial=0.0) > 0.5 else "other" for i in range(m)]
    if (pm < -1e-3).any():
        notes.append(f"negative participation down to {pm.min():.2g} (solver noise): clipped to 0 for the Hamiltonian")
    over = pm.sum(axis=1)
    for i in np.where(over > 1.05)[0]:
        notes.append(f"mode {labels[i]}: participations add up to {over[i]:.3g} > 1 (check the perturbation size)")
    pc = np.clip(pm, 0.0, None)
    keep = [i for i in range(m) if pc[i].max(initial=0.0) >= p_min]
    chi = [[0.0] * m for _ in range(m)]
    f_dressed = f.tolist()
    if keep:
        # first order for every coupled mode; the numerical diagonalisation (dimension fock ** modes) for the
        # MAX_NUMERIC_MODES modes with the largest participation, written over their block
        h1 = epr_hamiltonian(f[keep], pc[keep], lj, s[keep], numerical=False)
        full = _expand(h1, keep, f.tolist())
        chi, f_dressed = full["chi_MHz"], full["f_GHz"]
        if numerical:
            sub = sorted(sorted(keep, key=lambda i: -pc[i].max())[:MAX_NUMERIC_MODES])
            if len(sub) < len(keep):
                notes.append(
                    f"{len(keep)} coupled modes: diagonalised the {len(sub)} with the largest participation, the "
                    "others at first order"
                )
            kw.setdefault("fock_trunc", {1: 12, 2: 9, 3: 8}.get(len(sub), 6))
            hn = epr_hamiltonian(f[sub], pc[sub], lj, s[sub], **kw)
            for a_, ia in enumerate(sub):
                f_dressed[ia] = float(hn["f_GHz"][a_])
                for b_, ib in enumerate(sub):
                    chi[ia][ib] = float(hn["chi_MHz"][a_][b_])
        else:
            notes.append("first-order perturbation theory (no diagonalisation)")
    return {
        "method": method,
        "modes": [{"label": labels[i], "f_GHz": float(f[i]), "kind": kinds[i]} for i in range(m)],
        "junctions": junctions,
        "p": pm.tolist(),
        "alpha_MHz": [float(chi[i][i]) for i in range(m)],
        "chi_MHz": [[float(x) for x in row] for row in chi],
        "lamb_MHz": [float((f_dressed[i] - f[i]) * 1e3) for i in range(m)],
        "f_linear_GHz": f.tolist(),
        "f_GHz": [float(x) for x in f_dressed],
        "Lj_nH": lj.tolist(),
        "s_mj": s.tolist(),
        "notes": notes,
    }


# ---- route 1: eigenmode L_J sensitivity -------------------------------------------------------------------------
def _freqs(x) -> list[float]:
    """Mode frequencies (GHz) from a list, a ``results.json`` dict (``eigenmodes``), or a path to one (or its job)."""
    if isinstance(x, (str, Path)):
        path = Path(x)
        for cand in (path, path / "results.json", path / "results" / "results.json"):
            if cand.is_file():
                x = json.loads(cand.read_text(encoding="utf-8"))
                break
        else:
            raise FileNotFoundError(f"no results.json at {path}")
    if isinstance(x, Mapping):
        return [float(m["f_GHz"]) for m in sorted(x["eigenmodes"], key=lambda m: m.get("mode", 0))]
    return [float(v) for v in x]


def _match(f_ref: np.ndarray, f_new: np.ndarray, notes: list[str], where: str) -> np.ndarray:
    """``f_new`` reordered to ``f_ref``: by order when the counts agree and the shifts are small, else by nearest."""
    if len(f_new) == len(f_ref) and np.all(np.abs(f_new / f_ref - 1) < 0.2):
        order = np.argsort(f_new)[np.argsort(np.argsort(f_ref))]
        return f_new[order]
    notes.append(f"{where}: mode count or order changed; matched each mode to the nearest frequency")
    return np.array([f_new[int(np.argmin(np.abs(f_new - f)))] for f in f_ref])


def dL_participation(lj0_nH: float, points: Sequence[tuple[float, float]]) -> float:
    """p of one mode from ``(L_J, f)`` points that include the nominal one (at least two points).

    ``p = -2 d ln f / d ln L_J``: the log-log slope at the nominal L_J. Two points: the finite difference (the slope
    at their geometric mean, error ~ the relative step); three or more: a quadratic fit in ln L_J, evaluated at the
    nominal value (error ~ the step cubed).
    """
    pts = sorted(points)
    x = np.log([p[0] for p in pts])
    y = np.log([p[1] for p in pts])
    if len(pts) < 2:
        raise ValueError("need at least two (L_J, f) points")
    if len(pts) == 2:
        return float(-2 * (y[1] - y[0]) / (x[1] - x[0]))
    c = np.polyfit(x - math.log(lj0_nH), y, 2)
    return float(-2 * c[1])


def eigenmode_dL(
    f0_GHz,
    lj_nH,
    perturbed: Mapping,
    labels: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    junctions: Sequence[str] | None = None,
    s_mj=None,
    **kw,
) -> dict:
    """EPR from eigenmode solves at different L_J (route ``eigenmode-dL``).

    ``f0_GHz``: the nominal eigenmode frequencies (a list, a ``results.json`` dict or a path to it). ``lj_nH``: the
    nominal L_J of each junction. ``perturbed``: ``{junction (index or name): [(L_J_new_nH, solve), ...]}``, one or
    more solves in which only that junction's L_J was changed (``solve``: frequencies, a results dict or a path).
    Symmetric steps of 1-5 % (two solves: -d and +d) are best; keep the mesh the same across the solves, because the
    adaptive mesh noise of separate runs is of the order of the frequency shift for weakly participating modes.
    A junction without perturbed solves gets p = 0 and a note.
    """
    f0 = np.asarray(_freqs(f0_GHz), dtype=float)
    lj = np.atleast_1d(np.asarray(lj_nH, dtype=float))
    names = list(junctions) if junctions is not None else [f"J{j + 1}" for j in range(len(lj))]
    notes: list[str] = []
    p = np.zeros((len(f0), len(lj)))
    for key, runs in perturbed.items():
        j = names.index(key) if isinstance(key, str) else int(key)
        pts_f = [(float(lj[j]), f0)] + [
            (float(new), _match(f0, np.asarray(_freqs(sol), dtype=float), notes, f"junction {names[j]}"))
            for new, sol in runs
        ]
        for i in range(len(f0)):
            p[i, j] = dL_participation(float(lj[j]), [(L, f[i]) for L, f in pts_f])
        steps = [abs(new / lj[j] - 1) for new, _ in runs]
        if steps and min(steps) > 0.1:
            notes.append(f"junction {names[j]}: smallest L_J step is {min(steps):.0%}; the slope is less local")
        if steps and max(steps) < 5e-4:
            notes.append(f"junction {names[j]}: L_J step below 0.05 %; solver noise may dominate the slope")
    for j, n in enumerate(names):
        if n not in perturbed and j not in perturbed:
            notes.append(f"junction {n}: no perturbed solve, participation set to 0")
    return epr_result("eigenmode-dL", f0, p, lj, labels, kinds, names, s_mj, notes, **kw)


# ---- route 2: the LOM ------------------------------------------------------------------------------------------
def epr_from_lom(lom, s_mj=None, max_modes: int | None = None, **kw) -> dict:
    """EPR from a LOM result (``lom.simulate.simulate`` / ``Designer.simulate``): each normal mode's inductive-energy
    fraction in each junction is its participation, the linear frequencies are the LOM's. ``max_modes``: keep only
    the first modes (qubits first, then by frequency); default all that couple to a junction."""
    junctions = {}
    for e in lom.netlist:
        if e.get("qucat") == "J" and e["element"] not in junctions:
            junctions[e["element"]] = float(e["value"])
    if not junctions:
        raise ValueError("the LOM result has no junction")
    names = list(junctions)
    modes = [md for md in lom.modes if any(md.participation.get(n, 0.0) > 0 for n in names)]
    order = sorted(range(len(modes)), key=lambda i: (modes[i].kind != "qubit", modes[i].f_GHz))
    if max_modes:
        order = order[:max_modes]
    modes = [modes[i] for i in sorted(order)]
    p = [[md.participation.get(n, 0.0) for n in names] for md in modes]
    notes = [n for n in lom.notes if "hybridised" in n or "degenerate" in n]
    return epr_result(
        "lom",
        [md.f_GHz for md in modes],
        p,
        [junctions[n] for n in names],
        [md.label for md in modes],
        [md.kind for md in modes],
        [n[2:] if n.startswith("J_") else n for n in names],
        s_mj,
        notes,
        **kw,
    )


# ---- route 3: the field energy -----------------------------------------------------------------------------------
def epr_from_energy(
    f_GHz, lj_nH, i_peak_A, u_total_J, labels=None, kinds=None, junctions=None, s_mj=None, **kw
) -> dict:
    """EPR from the field solution: ``i_peak_A`` (M x J, peak current through each junction in each mode) and
    ``u_total_J`` (M, total energy of the mode), ``p = 1/2 L_J I^2 / U`` (the existing
    :func:`~quantcore_circuits.analysis.epr.junction_participation_from_energy`)."""
    from quantcore_circuits.analysis.epr import junction_participation_from_energy  # pylint: disable=C0415

    f = np.atleast_1d(np.asarray(f_GHz, dtype=float))
    lj = np.atleast_1d(np.asarray(lj_nH, dtype=float))
    i = np.atleast_2d(np.asarray(i_peak_A, dtype=float)).reshape(len(f), len(lj))
    u = np.atleast_1d(np.asarray(u_total_J, dtype=float))
    p = [
        [junction_participation_from_energy(f[m], lj[j], i[m, j], u[m]) for j in range(len(lj))] for m in range(len(f))
    ]
    return epr_result("energy", f, p, lj, labels, kinds, junctions, s_mj, **kw)


def epr_from_job(results: Mapping | str | Path, **kw) -> dict:
    """The contract dict from a solved eigenmode job's ``results.json`` that already holds pyEPR values (``epr``): the
    energy route as the solver ran it, with the participations, Lj and frequencies it recorded."""
    if isinstance(results, (str, Path)):
        path = Path(results)
        path = (
            path
            if path.is_file()
            else next(c for c in (path / "results.json", path / "results" / "results.json") if c.is_file())
        )
        results = json.loads(path.read_text(encoding="utf-8"))
    e = results["epr"]
    modes = results.get("eigenmodes") or []
    f = e.get("f_linear_GHz") or [m["f_GHz"] for m in modes]
    p = e["p_mj"]
    names = [n.split(".", 1)[0] for n in e.get("junction_names") or e.get("junctions") or []]
    labels = [names[int(np.argmax(row))] if names and max(row) > 0.5 else f"mode{i + 1}" for i, row in enumerate(p)]
    out = epr_result("energy", f, p, e["Lj_nH"], labels, None, names or None, e.get("s_mj"), **kw)
    out["notes"].append("participations from the solver's field integral (pyEPR line voltage), Hamiltonian recomputed")
    return out


# ---- comparing two results -------------------------------------------------------------------------------------
def compare_epr(a: dict, b: dict, max_df: float = 0.05) -> list[dict]:
    """Line two EPR results up mode by mode (``a`` against ``b``, e.g. LOM against eigenmode).

    Each mode of ``a`` is paired with the mode of ``b`` of the same label if there is one, else the nearest in
    frequency (within ``max_df`` relative). Row: ``label``, ``f_a`` / ``f_b`` (GHz), ``p_a`` / ``p_b`` (the largest
    participation), ``dp``, ``alpha_a`` / ``alpha_b`` (MHz) and ``d_alpha_pct``; ``None`` when there is no partner.
    """
    rows = []
    fb = np.array([m["f_GHz"] for m in b["modes"]])
    lb = [m["label"] for m in b["modes"]]
    used: set[int] = set()
    for i, md in enumerate(a["modes"]):
        k = lb.index(md["label"]) if md["label"] in lb and lb.index(md["label"]) not in used else None
        if k is None and len(fb):
            cand = [n for n in np.argsort(np.abs(fb - md["f_GHz"])) if n not in used]
            if cand and abs(fb[cand[0]] / md["f_GHz"] - 1) <= max_df:
                k = int(cand[0])
        row = {
            "label": md["label"],
            "f_a": md["f_GHz"],
            "p_a": max(a["p"][i], default=0.0),
            "alpha_a": a["alpha_MHz"][i],
        }
        if k is None:
            row.update(f_b=None, p_b=None, dp=None, alpha_b=None, d_alpha_pct=None)
        else:
            used.add(k)
            pb, ab = max(b["p"][k], default=0.0), b["alpha_MHz"][k]
            row.update(
                f_b=b["modes"][k]["f_GHz"],
                p_b=pb,
                dp=row["p_a"] - pb,
                alpha_b=ab,
                d_alpha_pct=(100 * (row["alpha_a"] - ab) / abs(ab)) if ab else None,
            )
        rows.append(row)
    return rows


def compare_md(a: dict, b: dict, **kw) -> str:
    """:func:`compare_epr` as a markdown table (``a`` is the first column group)."""
    ra, rb = a["method"], b["method"]
    out = [
        f"| mode | f {ra} (GHz) | f {rb} (GHz) | p {ra} | p {rb} | alpha {ra} (MHz) | alpha {rb} (MHz) | diff (%) |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def fmt(v, spec):
        return "–" if v is None else format(v, spec)

    for r in compare_epr(a, b, **kw):
        out.append(
            f"| {r['label']} | {r['f_a']:.4f} | {fmt(r['f_b'], '.4f')} | {r['p_a']:.4f} | {fmt(r['p_b'], '.4f')} | "
            f"{r['alpha_a']:.1f} | {fmt(r['alpha_b'], '.1f')} | {fmt(r['d_alpha_pct'], '.1f')} |"
        )
    return "\n".join(out)


def epr_md(res: dict) -> str:
    """One EPR result as markdown: a row per mode (f linear and dressed, p per junction, alpha, Lamb shift) and the
    cross-Kerr matrix of the modes that couple to a junction."""
    jn = res["junctions"]
    out = [
        f"EPR from `{res['method']}`:",
        "",
        "| mode | kind | f linear (GHz) | f dressed (GHz) | "
        + " | ".join(f"p {j}" for j in jn)
        + " | alpha (MHz) | Lamb (MHz) |",
        "|---|---|---|---|" + "---|" * len(jn) + "---|---|",
    ]
    for i, m in enumerate(res["modes"]):
        out.append(
            f"| {m['label']} | {m['kind']} | {m['f_GHz']:.4f} | {res['f_GHz'][i]:.4f} | "
            + " | ".join(f"{v:.4g}" for v in res["p"][i])
            + f" | {res['alpha_MHz'][i]:.2f} | {res['lamb_MHz'][i]:.2f} |"
        )
    act = [i for i, row in enumerate(res["p"]) if max(row, default=0.0) > P_MIN]
    if len(act) > 1:
        names = [res["modes"][i]["label"] for i in act]
        out += ["", "Cross-Kerr chi (MHz):", "", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(act)]
        for i in act:
            out.append(
                f"| {res['modes'][i]['label']} | " + " | ".join(f"{res['chi_MHz'][i][k]:.3g}" for k in act) + " |"
            )
    out += ["", *[f"- {n}" for n in res.get("notes", [])]]
    return "\n".join(out)

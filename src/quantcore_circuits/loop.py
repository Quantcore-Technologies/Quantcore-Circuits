"""The analysis half of the design loop, step by step, recording everything for the dashboard.

:func:`analyse` — job results → ``circuit.json`` (filled: design vs extracted values) → Metal LOM / QuCat /
SQcircuit / scqubits → QuTiP Hamiltonian (dressed levels, simulated readout χ, flux curve) → consensus vs targets.
The design is planned once for the circuit and its fill; with ``out_dir`` the four estimators' results are kept in
``estimates_cache.json`` and reused while the circuit they read is the same (a second analysis of the same design and
jobs, e.g. Propose after Simulate or Import, skips them).
:func:`feedback` — a surrogate per qubit–readout pair anchored on that point (FEM or the layout's estimates; every
qubit class with a LOM model, λ/4 and λ/2 readouts, :mod:`quantcore_circuits.codesign`) → proposed knobs → design
revision (rebuilt and checked, or only written for a preview), with notes on what could not be tuned.

Both update a :class:`~quantcore_circuits.track.Run` (``build/<design>/state.json``) when given one, and return
plain data for notebooks and plots (:mod:`quantcore_circuits.plots`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from quantcore_circuits import plots as P
from quantcore_circuits import track as _track
from quantcore_circuits.autotrack import _fem_compare

BRANCH_TYPE = {"C": "C", "L": "L", "JJ": "JJ", "SQUID": "SQUID", "TLres": "TL", "R": "R", "HANGER": "HANGER"}
TARGET_LABEL = {
    "f_q_GHz": "frequency",
    "alpha_MHz": "anharmonicity",
    "f_GHz": "frequency",
    "g_MHz": "coupling",
    "chi_MHz": "dispersive shift",
    "kappa_MHz": "linewidth",
}


@dataclass
class Analysis:
    model: object  # CircuitModel
    filled: object  # FilledCircuit
    estimates: dict
    rows: list
    goal: dict
    hamiltonian: object | None = None  # TransmonResonator
    dressed: dict | None = None
    readout: dict | None = None
    flux: dict | None = None
    plots: list[dict] = field(default_factory=list)
    # every transmon–resonator pair solved in QuTiP: qubit → {resonator, hamiltonian, dressed, readout, flux};
    # ``hamiltonian`` / ``dressed`` / ``readout`` / ``flux`` above are the first pair's (the Hamiltonian tab)
    pair_results: dict[str, dict] = field(default_factory=dict)
    plan: object | None = None  # the design's build plan the circuit was derived from (feedback reuses it)


def pair_plot_id(kind: str, qubit: str, an: Analysis) -> str:
    """Plot id of a per-pair plot (``levels``, ``readout``, ``flux``): bare for the first pair, ``<kind>_<qubit>``
    for the others."""
    first = next(iter(an.pair_results), None)
    return kind if qubit == first else f"{kind}_{qubit}"


def dashboard_circuit(filled) -> dict:
    model = filled.model
    nodes = [n for n in model.nodes if not model.nodes[n].ground]
    qubits = [
        n
        for n in nodes
        if "." not in n and any(b.type in ("JJ", "SQUID") and n in b.nodes for b in model.branches.values())
    ]
    couplers = [n for n in nodes if "." in n]
    others = [n for n in nodes if n not in qubits and n not in couplers]
    order = qubits + couplers + others
    pos = {n: [round((i + 1) / (len(order) + 1), 3), 0.35] for i, n in enumerate(order)}
    out_nodes = [{"id": model.ground, "label": "ground", "ground": True, "pos": [0.5, 0.95]}]
    for n in order:
        isl = model.nodes[n].island
        label = f"{n} island" if n in qubits else (f"{n.replace('.', ' ')}" if n in couplers else n)
        out_nodes.append({"id": n, "label": label, "island": isl, "pos": pos[n]})
    labels = {"C_": "C", "Cg_": "C_g", "Cc_": "C_c", "K_": "κ hanger", "J_": "L_J", "Port_": "port"}
    branches = []
    for name, v in filled.values.items():
        b = model.branches[name]
        label = next((lab for pre, lab in labels.items() if name.startswith(pre)), f"λ/4 {name}")
        if name.startswith("C_"):
            label = f"C_{name[2:]}"
        branches.append(
            {
                "id": name,
                "type": BRANCH_TYPE[b.type],
                "nodes": list(b.nodes),
                "value": v.value,
                "designValue": v.design,
                "unit": v.unit,
                "label": label,
                "source": f"{v.origin}: {v.source}",
            }
        )
    return {"name": model.name, "nodes": out_nodes, "branches": branches}


def dashboard_targets(rows) -> list[dict]:
    out = []
    for r in rows:
        if r.target is None:
            continue
        inst = r.param.split(".", 1)[0]
        out.append(
            {
                "key": r.param,
                "label": f"{inst} {TARGET_LABEL.get(r.quantity, r.quantity)}",
                "symbol": r.symbol,
                "unit": r.unit,
                "target": r.target,
                "tol": r.tol,
                "value": r.chosen,
                "source": r.chosen_by,
                "status": r.status,
            }
        )
    return out


def dashboard_consensus(rows) -> list[dict]:
    return [
        {
            "param": r.param,
            "label": r.symbol,
            "unit": r.unit,
            "target": r.target,
            "values": r.values,
            "chosen": r.chosen,
            "chosenBy": r.chosen_by,
            "spreadRel": r.spread_rel,
            "flagged": r.flagged,
        }
        for r in rows
        if r.quantity not in ("EJ_GHz", "EC_GHz")
    ]


def analyse(
    design,
    job_dir=None,
    group: str | None = None,
    run=None,
    readout: bool = True,
    kappa_MHz: float | None = None,
    out_dir: str | Path | None = None,
) -> Analysis:
    """Job → circuit → estimators → QuTiP → consensus (module docstring). ``run`` None: the dashboard tracking
    session's run (:func:`quantcore_circuits.track.start`), if there is one."""
    run = run or _track.run_for(design if not isinstance(design, dict) else None)
    # this function records fill / LOM / targets itself; state.json is written per step, not per plot / note
    with _track.quiet(), _deferred(run):
        return _analyse(design, job_dir, group, run, readout, kappa_MHz, out_dir)


def _deferred(run):
    """``run.deferred()`` (:meth:`quantcore_circuits.track.Run.deferred`), or nothing without a run."""
    import contextlib  # pylint: disable=import-outside-toplevel

    fn = getattr(run, "deferred", None)
    return fn() if callable(fn) else contextlib.nullcontext()


def _analyse(design, job_dir, group, run, readout, kappa_MHz, out_dir) -> Analysis:
    from quantcore_circuits.circuit import hamiltonian as H  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.adapters import solve_all  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.consensus import (  # pylint: disable=import-outside-toplevel
        consensus,
        flag_near_resonance,
        goal,
        report_markdown,
        save,
    )
    from quantcore_circuits.circuit.derive import circuit_from_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.fill import fill, load_results  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.schema import save_circuit  # pylint: disable=import-outside-toplevel

    # a list of jobs (subset jobs): the whole chip's netlist, each job filling its own components (circuit.fill)
    many = isinstance(job_dir, (list, tuple))
    first = (job_dir[0] if job_dir else None) if many else job_dir
    results, job = load_results(first) if first is not None else ({}, None)
    group = group or ("chip" if many else None) or results.get("group") or (job or {}).get("group") or "chip"
    if run:
        run.start("extract")
    from quantcore_circuits.assembly.last_good import plan_for_lom  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    plan = plan_for_lom(load_design(design), design)  # planned once: the circuit and its fill read the same plan
    model = circuit_from_design(design, group, plan=plan)
    # job_dir None: layout → LOM estimates only
    filled = fill(model, design, list(job_dir) if many else job_dir, plan=plan)
    if run:
        for note in filled.notes:
            run.log(note, "warn" if note.startswith("stack") else "info")
        p0 = filled.pairs[0] if filled.pairs else None
        summary = (
            f"C_Σ {p0.c_island_fF + p0.cg_fF:.1f} fF · C_g {p0.cg_fF:.2f} fF · claw {p0.c_coupler_fF:.1f} fF"
            if p0
            else "no transmon–resonator pair in the C-matrix"
        )
        run.set(
            circuit=dashboard_circuit(filled),
            cmatrix={**filled.cmatrix, "unit": "fF", "job": filled.job} if filled.cmatrix else None,
            femCompare=_fem_compare(filled) if filled.cmatrix else [],
        )
        run.done("extract", summary)
        run.start("hamiltonian")
    estimates = _solve_cached(filled, out_dir, solve_all)
    an = Analysis(model, filled, estimates, [], {}, plan=plan)
    qutip_est = {}
    for pair in filled.pairs:  # one QuTiP model per transmon–resonator pair (multi-qubit chips)
        if pair.qubit in an.pair_results:
            continue  # a qubit with two resonators: the first (readout) pair defines its Hamiltonian
        ham = H.from_pair(
            pair, nq=model.truncation.get("qubit_levels", 8), nr=model.truncation.get("resonator_levels", 6)
        )
        dressed = H.dressed(ham)
        qutip_est.update(
            {
                f"{pair.qubit}.f_q_GHz": dressed["f_q_GHz"],
                f"{pair.qubit}.alpha_MHz": dressed["alpha_MHz"],
                f"{pair.resonator}.f_GHz": dressed["f_r_GHz"],
                f"{pair.resonator}.chi_MHz": dressed["chi_MHz"],
                f"{pair.resonator}.g_MHz": dressed["g_MHz"],
            }
        )
        kappa = kappa_MHz or getattr(pair, "kappa_MHz", None) or 1.0
        an.pair_results[pair.qubit] = {
            "resonator": pair.resonator,
            "hamiltonian": ham,
            "dressed": dressed,
            "readout": H.readout(ham, kappa_MHz=kappa) if readout else None,
            # the SQUID's curve from its zero-flux E_J (ham.EJ_GHz is at the design flux) and its asymmetry
            "flux": H.flux_curve(ham.EJ_GHz * pair.ej_sum_ratio, ham.EC_GHz, pair.asym) if pair.squid else None,
        }
    if an.pair_results:
        first = next(iter(an.pair_results.values()))
        an.hamiltonian, an.dressed, an.readout, an.flux = (
            first["hamiltonian"],
            first["dressed"],
            first["readout"],
            first["flux"],
        )
        estimates["qutip"] = qutip_est
    an.rows = consensus(estimates, model.targets)
    for note in flag_near_resonance(an.rows, an.filled.pairs):
        if run:
            run.log(note, "warn")
    an.goal = goal(an.rows)
    an.plots = _plots(an)
    if out_dir:
        out = Path(out_dir)
        save_circuit(model, out / "circuit.json")
        save(an.rows, out / "consensus.json")
        (out / "consensus.md").write_text(report_markdown(an.rows, f"Consensus — {model.name}"), encoding="utf-8")
        (out / "estimates.json").write_text(json.dumps(estimates, indent=2, default=float), encoding="utf-8")
    if run:
        d = an.dressed or {}
        tr = model.truncation
        run.set(
            hamiltonian=_dashboard_hamiltonian(an, tr),
            consensus=dashboard_consensus(an.rows),
            targets=dashboard_targets(an.rows),
            goal=an.goal,
        )
        for spec in an.plots:
            run.plot(spec)
        chi_r = an.readout["chi_readout_MHz"] if an.readout else None
        run.done(
            "hamiltonian",
            f"QuTiP {tr.get('qubit_levels', 8)}×{tr.get('resonator_levels', 6)}: f_q "
            f"{d.get('f_q_GHz', 0):.4f} GHz · α {d.get('alpha_MHz', 0):.1f} MHz · χ {d.get('chi_MHz', 0):.3f} MHz"
            + (f" (readout {chi_r:.3f})" if chi_r is not None else ""),
        )
        run.start("compare")
        flagged = [r.param for r in an.rows if r.flagged]
        if flagged:
            run.log(f"estimator spread above tolerance (modelling, not design): {', '.join(flagged)}", "warn")
        run.done("compare", an.goal["summary"])
        update_cards(run, design, an)
    return an


ESTIMATES_CACHE = "estimates_cache.json"


def _estimates_key(filled) -> str:
    """What the estimators read — every pair's 2-node network, junction, line and κ, the EPR / eigenmode results and
    the hanger values a FEM job filled — plus the estimators' own code (this package's ``circuit`` / ``analysis``
    modules, the libraries' versions): equal keys give equal estimates."""
    import hashlib  # pylint: disable=import-outside-toplevel
    from importlib import metadata  # pylint: disable=import-outside-toplevel

    import numpy as np  # pylint: disable=import-outside-toplevel

    pairs = [[p.qubit, p.resonator, list(p.labels), np.asarray(p.cmatrix_fF, dtype=float).tolist(), p.lj_nH, p.cj_fF,
              p.f_r_GHz, p.z0_ohm, p.ck_fF, p.feedline, p.asym, p.flux_phi0, p.squid, p.kappa_MHz, p.kind]
             for p in filled.pairs]
    hangers = {n: [v.extracted, v.estimate] for n, v in filled.values.items() if v.type == "HANGER"}
    fem = [filled.results or {}] + [j.get("results") or {} for j in getattr(filled, "jobs", [])]
    fem = [{k: r[k] for k in ("epr", "eigenmodes", "sparams") if k in r} for r in fem]
    pkg = Path(__file__).resolve().parent
    code = max((f.stat().st_mtime_ns for d in ("circuit", "analysis") for f in (pkg / d).glob("*.py")), default=0)
    libs = {}
    for lib in ("SQcircuit", "qucat", "scqubits", "qiskit-metal", "qutip", "pyEPR-quantum", "numpy", "scipy"):
        try:
            libs[lib] = metadata.version(lib)
        except metadata.PackageNotFoundError:
            libs[lib] = None
    payload = {"v": 1, "estimators": list(filled.model.estimators), "pairs": pairs, "hangers": hangers, "fem": fem,
               "code": code, "libs": libs}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _solve_cached(filled, out_dir, solve_all):
    """``solve_all(filled)``, or the estimates of an earlier analysis of the same circuit (``<out_dir>/
    estimates_cache.json``, keyed by :func:`_estimates_key`): Propose after Simulate / Import, or a second Propose,
    does not run the four estimators again. Without ``out_dir`` there is no cache."""
    if not out_dir:
        return solve_all(filled)
    path = Path(out_dir) / ESTIMATES_CACHE
    try:
        key = _estimates_key(filled)
    except Exception:  # noqa: BLE001  (an unusual circuit: no cache)
        return solve_all(filled)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("key") == key:
            return data["estimates"]
    except (OSError, ValueError, KeyError):
        pass
    estimates = solve_all(filled)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "estimates": estimates}, default=float), encoding="utf-8")
    except OSError:
        pass
    return estimates


def update_cards(run, design, an, proposal=None) -> None:
    """Parameter cards + design summary for the dashboard (see :mod:`quantcore_circuits.cards`)."""
    from quantcore_circuits import cards  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    run.set(**cards.build(load_design(design), an, proposal, run.state.get("jobs")))


def _dashboard_hamiltonian(an: Analysis, truncation: dict) -> dict | None:
    if an.hamiltonian is None:
        return None
    import qutip  # pylint: disable=import-outside-toplevel

    ham, d = an.hamiltonian, an.dressed
    terms = [
        {"symbol": "E_J", "label": "Josephson energy", "value": ham.EJ_GHz, "unit": "GHz"},
        {"symbol": "E_C", "label": "charging energy (loaded)", "value": ham.EC_GHz, "unit": "GHz"},
        {"symbol": "E_J/E_C", "label": "transmon ratio", "value": ham.EJ_GHz / ham.EC_GHz, "unit": ""},
        {"symbol": "f_r", "label": "λ/4 (claw-loaded, bare)", "value": ham.f_r_GHz, "unit": "GHz"},
        {"symbol": "g_n", "label": "charge coupling", "value": ham.g_n_MHz, "unit": "MHz"},
        {"symbol": "g", "label": "exchange coupling", "value": d["g_MHz"], "unit": "MHz"},
        {"symbol": "f_{01}", "label": "dressed qubit", "value": d["f_q_GHz"], "unit": "GHz"},
        {"symbol": "\\alpha", "label": "anharmonicity", "value": d["alpha_MHz"], "unit": "MHz"},
        {"symbol": "\\chi", "label": "dispersive shift (eigen)", "value": d["chi_MHz"], "unit": "MHz"},
    ]
    if an.readout:
        terms.append(
            {
                "symbol": "\\chi_{ro}",
                "label": "dispersive shift (simulated readout)",
                "value": an.readout["chi_readout_MHz"],
                "unit": "MHz",
            }
        )
    first_q = next(iter(an.pair_results), None)
    return {
        "pair": [first_q, an.pair_results[first_q]["resonator"]] if first_q else None,
        "model": "Transmon (charge basis) + λ/4 resonator, charge coupling, no RWA",
        "latex": ham.latex(),
        "terms": terms,
        "levels": [{"label": lv["label"], "energy": lv["energy"]} for lv in d["levels"][:8]],
        "truncation": {"qubit": truncation.get("qubit_levels", 8), "resonator": truncation.get("resonator_levels", 6)},
        "solver": f"QuTiP {qutip.__version__} eigenstates; readout: steady-state Lindblad",
    }


def _plots(an: Analysis) -> list[dict]:
    specs = []
    if an.filled.cmatrix:
        cm = an.filled.cmatrix
        specs.append(
            P.heatmap_spec(
                "cmatrix",
                "Maxwell C-matrix (as used)",
                "simulation",
                cm["labels"],
                cm["labels"],
                [[round(v, 3) for v in row] for row in cm["matrix"]],
                "fF",
                caption=f"{an.filled.job}; " + "; ".join(an.filled.notes)[:300],
            )
        )
    multi = len(an.pair_results) > 1
    for q, res in an.pair_results.items():
        specs += _pair_plots(an, q, res, f" — {q}–{res['resonator']}" if multi else "")
    specs += _estimator_plots(an)
    # the solved jobs' convergence per adaptive pass, S21 notch fits and EPR (plots.fem_specs): Plots tab
    specs += P.fem_specs(an.filled.jobs or ([{"results": an.filled.results}] if an.filled.results else []))
    return specs


def _pair_plots(an: Analysis, q: str, res: dict, suffix: str) -> list[dict]:
    specs = []
    if res["dressed"]:
        specs.append(
            P.levels_spec(
                pair_plot_id("levels", q, an),
                "Dressed spectrum" + suffix,
                "hamiltonian",
                [
                    {"label": lv["label"], "energy": round(lv["energy"], 5), "group": "dressed"}
                    for lv in res["dressed"]["levels"][:8]
                ],
                caption="QuTiP, charge-basis transmon + λ/4",
            )
        )
    if res["readout"]:
        r = res["readout"]
        x = [round((f - r["peak_g_GHz"]) * 1e3, 5) for f in r["f_GHz"]]
        specs.append(
            P.xy_spec(
                pair_plot_id("readout", q, an),
                "Simulated readout: transmission vs qubit state" + suffix,
                "hamiltonian",
                [
                    {"name": "qubit |g⟩", "x": x, "y": r["T_g"]},
                    {"name": "qubit |e⟩", "x": x, "y": r["T_e"], "dashed": True},
                ],
                "Probe detuning (MHz)",
                "|⟨a⟩|² (norm.)",
                [
                    {"axis": "x", "value": 0.0, "label": "g"},
                    {"axis": "x", "value": round(r["chi_readout_MHz"], 4), "label": "e"},
                ],
                caption=f"χ readout {r['chi_readout_MHz']:.3f} MHz vs eigen {r['chi_eigen_MHz']:.3f} MHz "
                f"(κ {r['kappa_MHz']} MHz)",
            )
        )
    if res["flux"]:
        fl = res["flux"]
        specs.append(
            P.xy_spec(
                pair_plot_id("flux", q, an),
                "Qubit spectrum vs flux (symmetric SQUID)" + suffix,
                "hamiltonian",
                [
                    {"name": "f01", "x": fl["phi"], "y": fl["f01_GHz"]},
                    {"name": "f12", "x": fl["phi"], "y": fl["f12_GHz"], "dashed": True},
                ],
                "Flux Φ/Φ0",
                "Frequency (GHz)",
                caption="EJ(Φ) = EJΣ|cos πΦ/Φ0|",
            )
        )
    return specs


def _estimator_plots(an: Analysis) -> list[dict]:
    specs = []
    est = {n: v for n, v in an.estimates.items() if "error" not in v}
    bars = []
    for r in an.rows:
        if r.quantity in ("f_q_GHz", "alpha_MHz", "chi_MHz", "f_GHz", "g_MHz"):
            bars.append(
                {
                    "label": f"{r.param.split('.')[0]} {r.symbol} ({r.unit})",
                    "values": {n: est[n].get(r.param) for n in est},
                }
            )
    if bars:
        specs.append(P.bar_spec("estimators", "Estimator values per parameter", "plots", bars, "value"))
        devs = []
        for r in an.rows:
            if r.chosen and r.values and r.quantity not in ("EJ_GHz", "EC_GHz"):
                devs.append(
                    {
                        "label": f"{r.param.split('.')[0]} {r.symbol}",
                        "values": {n: round(100 * (v - r.chosen) / abs(r.chosen), 4) for n, v in r.values.items()},
                    }
                )
        specs.append(
            P.bar_spec(
                "estimator_spread",
                "Deviation from chosen value",
                "plots",
                devs,
                "deviation (%)",
                caption="0 % = the policy's chosen estimator; spread above tolerance is flagged",
            )
        )
    return specs


def feedback(an: Analysis, run=None, design_source=None, iteration: int = 1, bounds=None, build_revision: bool = True):
    """Surrogate from this FEM point → knobs → revision ``iteration`` (built + netlist-checked). Returns
    ``(proposal, revision_path, build_result)``.

    Every transmon–readout pair of the circuit gets a surrogate (:func:`quantcore_circuits.codesign.
    surrogate_from_fill`: any qubit class with a LOM model, λ/4 and λ/2 readouts); what cannot be tuned (no pair, no
    clean knob, a drawn junction) is listed in ``proposal.notes``. ``build_revision=False`` (a preview, e.g. ``qcc
    results propose``) writes the revision without building it: ``build_result`` is then None."""
    run = run or _track.run_for(an.filled.design)
    with _deferred(run):
        return _feedback(an, run, design_source, iteration, bounds, build_revision)


def _feedback(an: Analysis, run, design_source, iteration: int, bounds, build_revision: bool):
    from quantcore_circuits import codesign as cd  # pylint: disable=import-outside-toplevel

    if run:
        run.start("feedback")
        run.state["history"] = [h for h in run.state["history"] if h.get("kind") != "lom"]  # (FEM rows follow)
    notes = cd.unpaired_notes(an.filled)
    surrogates = cd.surrogates_from_fill(an.filled, notes)  # one per qubit–resonator pair
    b = {**an.model.knobs, **(bounds or {})}
    for s in surrogates:
        if s.cg.knob:
            b.setdefault(s.cg.knob, (s.cg.k0 * 0.4, s.cg.k0 * 2.2) if s.cg.p >= 0 else (s.cg.k0 * 0.5, s.cg.k0 * 2.5))
    measured = {r.param: r.chosen for r in an.rows if r.chosen is not None}  # what the consensus reports
    prop = cd.propose_all(surrogates, an.model.targets, b, anchor=measured)
    prop.notes = list(dict.fromkeys(notes + prop.notes))
    same = design_source is None or getattr(an, "plan", None) is not None and _same_design(design_source, an)
    design = cd.apply(design_source or an.filled.design, prop.knobs, plan=an.plan if same else None)
    run_dir = run.dir if run else Path("build") / design.name
    rev = cd.write_revision(design, run_dir, iteration)
    result = net = None
    if build_revision:
        from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.assembly.netlist import check_netlist  # pylint: disable=import-outside-toplevel

        result = build(rev)
        net = check_netlist(result)
    if run:
        measured = {r.param: r.residual for r in an.rows if r.residual is not None}
        run.iteration(
            {
                "iteration": iteration - 1,
                "objective": _norm(measured),
                "residuals": measured,
                "knobs": prop.start_knobs,
                "accepted": True,
            }
        )
        run.iteration(
            {
                "iteration": iteration,
                "objective": prop.objective,
                "residuals": prop.residuals,
                "knobs": prop.knobs,
                "accepted": False,
            }
        )
        hist = run.state["history"]
        run.plot(
            P.xy_spec(
                "residual",
                "Residual vs iteration",
                "history",
                [
                    {
                        "name": "‖r‖ (tolerances)",
                        "x": [h["iteration"] for h in hist],
                        "y": [max(h["objective"], 1e-3) for h in hist],
                        "kind": "line",
                    }
                ],
                "Iteration",
                "‖r‖ (tolerances)",
                [{"axis": "y", "value": 1.0, "label": "tolerance"}],
                log_y=True,
                caption="filled: FEM-extracted; last point: surrogate prediction, awaiting FEM",
            )
        )
        changes = ", ".join(f"{k} {prop.start_knobs[k]:g}→{v:g}" for k, v in prop.knobs.items())
        if prop.at_bounds:
            run.log(
                f"feedback: knob(s) at their bound: {', '.join(prop.at_bounds)} — widen the bounds or add knobs", "warn"
            )
        for note in prop.notes:
            run.log(f"feedback: {note}", "info")
        checked = "not built (preview)" if net is None else ("netlist OK" if net.ok else "netlist FAILED")
        run.done("feedback", f"rev{iteration}: {changes} · predicted ‖r‖ {prop.objective:.2g} · {checked}")
        update_cards(run, design_source or an.filled.design, an, prop)
    return prop, rev, result


def _same_design(source, an: Analysis) -> bool:
    """Whether ``source`` is the design ``an`` analysed (then its plan holds the ports :func:`codesign.apply` needs)."""
    from quantcore_circuits.design import design_hash, load_design  # pylint: disable=import-outside-toplevel

    try:
        return design_hash(load_design(source)) == design_hash(an.filled.design)
    except Exception:  # noqa: BLE001
        return False


def _norm(res: dict) -> float:
    return float(sum(v * v for v in res.values()) ** 0.5)

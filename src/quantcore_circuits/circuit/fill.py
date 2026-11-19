"""Fill a :class:`CircuitModel` with element values (M9): component estimates, FEM results, design values.

Each branch carries three numbers side by side, never overwriting one another:

* ``estimate`` — from the layout's LOM (component calibration, CPW formulas, coupled-line κ),
* ``extracted`` — from a simulation (C-matrix nets matched to node islands), when a job is given,
* ``design`` — what the design asked for (LOM synthesis of the targets).

The *chosen* value is ``extracted`` when present, else ``estimate``; estimators always use the chosen value, so the
same analysis runs on a circuit exported from KLayout (estimates only) and on one filled from HFSS/Q3D.

Stack correction: if the job was simulated on another substrate than the design's PDK (e.g. an old silicon run of
a design that moved to sapphire), capacitances are rescaled by (εr,design + 1)/(εr,job + 1) and a note says so.
A cut coupler port's CPW stub is removed from the pad capacitance (it is part of the routed λ/4 length).

Subsets (phase C, :mod:`quantcore_circuits.sim_tools.subset`): a job fills only the branches *owned* by the components
its sim group selected (a branch's owner is the instance or route that put it in the netlist; a declared coupling is
owned by both ends and needs both ends chosen, or one end on a feedline). Every other branch keeps its estimate and
its ``source`` says it was outside the subset. ``fill(model, design, [job_a, job_b])`` merges several subset jobs into
one whole-chip circuit; each branch's ``source`` names the job it came from (``cmatrix:<simulation>``). Two more
read-back rules apply to every job:

* **line nets** — a C-matrix net that carries a distributed line (a route the box cuts, labelled with the route's name,
  or a route the job keeps whole, e.g. the whole-chip ``chip`` group) has the line's own capacitance in its row sum,
  which the LOM already models as a transmission line: its branches to ground keep their estimates (a note says so),
  its mutual capacitances are taken from the FEM. This is the fix for tutorial 02's whole-chip readouts (f_r −49 %:
  a λ/2 line's ≈ 1060 fF landed on a lumped branch).
* **one FEM value, several branches** — branches on the same node pair (e.g. a capacitor pad and the qubit's readout
  pad on one node, both to ground) share the FEM value in proportion to their estimates, instead of each getting the
  whole of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from quantcore_circuits import track as _track

from quantcore_circuits.circuit.bridges import (
    branch_capacitances,
    quarter_wave_lc,
    stack_capacitance_scale,
    tl_resonator,
)
from quantcore_circuits.circuit.schema import CircuitModel


@dataclass
class BranchValue:
    type: str
    nodes: tuple[str, str]
    unit: str
    extracted: float | None = None
    design: float | None = None
    source: str = ""
    extra: dict = field(default_factory=dict)
    estimate: float | None = None

    @property
    def value(self) -> float | None:
        """Chosen value: FEM if available, else the component estimate."""
        return self.extracted if self.extracted is not None else self.estimate

    @property
    def origin(self) -> str:
        return "fem" if self.extracted is not None else ("estimate" if self.estimate is not None else "none")


@dataclass
class TransmonReadout:
    """Everything the estimator adapters need for one grounded transmon + λ/4 readout pair."""

    qubit: str
    resonator: str
    labels: list[str]  # [island net, coupler net]
    cmatrix_fF: np.ndarray  # 2×2 Maxwell sub-matrix for those nets
    lj_nH: float
    cj_fF: float
    f_r_GHz: float  # bare λ/4 frequency from the routed length (CPW model)
    z0_ohm: float
    ck_fF: float | None = None
    feedline: str | None = None
    asym: float = 0.0
    flux_phi0: float = 0.0  # lj_nH is the SQUID's L at this flux; lj0_nH its zero-flux value
    squid: bool = False
    kappa_MHz: float | None = None  # external linewidth (hanger estimate or simulation)
    kind: str = "lambda/4"  # readout line: "lambda/4" or "lambda/2" (f_r_GHz is that mode's frequency)
    lj0_nH: float | None = None  # a flux-biased SQUID's L_J at zero flux (None: lj_nH)

    @property
    def ej_sum_ratio(self) -> float:
        """E_J(Φ = 0) / E_J at the bias, = L(Φ) / L_J0 (1 without a flux bias): scales an E_J to the SQUID's sum."""
        return self.lj_nH / self.lj0_nH if self.lj0_nH else 1.0

    @property
    def c_island_fF(self) -> float:  # island → ground (incl. junction capacitance)
        return float(self.cmatrix_fF[0].sum()) + self.cj_fF

    @property
    def cg_fF(self) -> float:
        return float(-self.cmatrix_fF[0, 1])

    @property
    def c_coupler_fF(self) -> float:  # coupler pad → ground (without the resonator)
        return float(self.cmatrix_fF[1].sum())


@dataclass
class FilledCircuit:
    model: CircuitModel
    design: object
    values: dict[str, BranchValue]
    cmatrix: dict | None
    pairs: list[TransmonReadout]
    job: str | None = None
    notes: list[str] = field(default_factory=list)
    # the job's results.json (sim agent, additive): estimators that read solver output directly, e.g. pyEPR on
    # eigenmode data (``results["epr"]``, ``results["eigenmodes"]``, ``results["sparams"]``)
    results: dict = field(default_factory=dict)
    # subset read-back (phase C, additive): one entry per job used, {"job", "group", "analysis", "scope", "filled",
    # "results"}; ``scope`` the components it may fill (None: all), ``filled`` the branches it did fill
    jobs: list[dict] = field(default_factory=list)

    def branch_table(self) -> list[dict]:
        rows = []
        for name, v in self.values.items():
            delta = None
            if v.value is not None and v.design:
                delta = 100 * (v.value - v.design) / abs(v.design)
            rows.append(
                {
                    "branch": name,
                    "type": v.type,
                    "nodes": list(v.nodes),
                    "extracted": v.extracted,
                    "estimate": v.estimate,
                    "value": v.value,
                    "origin": v.origin,
                    "design": v.design,
                    "unit": v.unit,
                    "delta_pct": delta,
                    "source": v.source,
                }
            )
        return rows


def load_results(job_or_results) -> tuple[dict, dict | None]:
    """(results.json dict, job.json dict or None) from a job directory, results file or dict."""
    if isinstance(job_or_results, dict):
        return job_or_results, None
    p = Path(job_or_results)
    if p.is_dir():
        res = json.loads((p / "results" / "results.json").read_text(encoding="utf-8"))
        job = json.loads((p / "job.json").read_text(encoding="utf-8")) if (p / "job.json").exists() else None
        return res, job
    return json.loads(p.read_text(encoding="utf-8")), None


def _job_permittivity(job: dict | None) -> float | None:
    if not job:
        return None
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    name = job.get("versions", {}).get("pdk", "").split("@", 1)[0]
    try:
        return get_pdk(name).stack.substrate_permittivity
    except ValueError:
        return None


def _synthesis(model: CircuitModel, design, pdk) -> dict:
    from quantcore_circuits.analysis.synthesis import synthesize_transmon_readout  # pylint: disable=C0415

    out = {}
    for rname, b in model.branches.items():
        if b.type != "TLres":
            continue
        q = b.nodes[0].split(".", 1)[0]
        tq, tr = design.targets.get(q, {}), design.targets.get(rname, {})
        if {"f_q_GHz", "alpha_MHz"} <= set(tq) and {"f_GHz", "g_MHz"} <= set(tr):
            out[q] = synthesize_transmon_readout(
                tq["f_q_GHz"], tq["alpha_MHz"], tr["f_GHz"], tr["g_MHz"], pdk.cpw_a, pdk.cpw_b, design.pdk
            )
    return out


def _merge_node_nets(model, labels: list[str], matrix: np.ndarray, extra: dict[str, list[str]] | None = None
                     ) -> tuple[list[str], np.ndarray, dict[str, str]]:
    """Sum the Maxwell rows / columns of C-matrix nets that belong to one circuit node (e.g. a λ/2 readout modelled as
    one parallel-LC node: its pad at the qubit and its pad at the coupling capacitor are both nets of a box that cuts
    the line at both ends; tutorial 02 ``Q2_read``). Without this the node took whichever net came first — the far
    capacitor pad — and the qubit's readout coupling came out as 0.002 fF. Returns (labels, matrix, {merged: kept})."""
    index = {lab: i for i, lab in enumerate(labels)}
    groups: list[list[int]] = []
    seen: set[int] = set()
    merged: dict[str, str] = {}
    for name, spec in model.nodes.items():
        if name == model.ground or spec.ground:
            continue
        nets = list(spec.nets) + list((extra or {}).get(name, []))
        idx = [index[n] for n in nets if n in index and index[n] not in seen]
        if len(idx) > 1:
            groups.append(idx)
            seen.update(idx)
            merged.update({labels[i]: labels[idx[0]] for i in idx[1:]})
    if not groups:
        return labels, matrix, {}
    keep = [i for i in range(len(labels)) if i not in seen or any(i == g[0] for g in groups)]
    rows = {i: [i] for i in keep}
    for g in groups:
        rows[g[0]] = g
    agg = np.zeros((len(keep), len(labels)))
    for k, i in enumerate(keep):
        agg[k, rows[i]] = 1.0
    return [labels[i] for i in keep], agg @ matrix @ agg.T, merged


def fill(
    model: CircuitModel,
    design_source,
    job_or_results=None,
    synthesis: dict | None = None,
    stack_correction: str = "auto",
    scope="auto",
    plan=None,
) -> FilledCircuit:
    """Values for every branch of ``model`` (see module docstring); ``job_or_results`` is optional, or a list of jobs
    (subset jobs: each fills its own components, merged into one circuit).

    ``scope``: ``"auto"`` (default) — a job fills only the branches owned by its sim group's selection (all of them for
    the whole-chip ``chip`` group or a bare results dict); ``None`` — every branch whose nodes have FEM nets (the
    behaviour before subsets); or a set of component names.

    ``design_source=None`` fills a stand-alone ``circuit.json`` (e.g. exported from KLayout) from its own stored
    estimates: resonators use their stored f/Z0, no design values. ``plan``: the design's build plan when the caller
    has it already (``plan_for_lom``), so it is not planned again.
    """
    if design_source is None:
        out = _fill_standalone(model)
        _track.emit("fill", filled=out)
        return out
    jobs = list(job_or_results) if isinstance(job_or_results, (list, tuple)) else [job_or_results]
    if not jobs:
        jobs = [None]
    parts = [_fill_one(model, design_source, j, synthesis, stack_correction, scope, plan) for j in jobs]
    out = parts[0] if len(parts) == 1 else _merge_fills(model, parts)
    _mark_outside(out)
    _track.emit("fill", filled=out)
    return out


def _copy_value(v: BranchValue) -> BranchValue:
    return BranchValue(v.type, v.nodes, v.unit, v.extracted, v.design, v.source, dict(v.extra), v.estimate)


def _merge_fills(model: CircuitModel, parts: list[FilledCircuit]) -> FilledCircuit:
    """One circuit from several subset fills: a branch takes the first job that extracted it."""
    base = parts[0]
    values = {k: _copy_value(v) for k, v in base.values.items()}
    notes = list(base.notes)
    for part in parts[1:]:
        notes += [f"[{part.job}] {n}" for n in part.notes]
        for k, v in part.values.items():
            if v.extracted is None:
                continue
            if values[k].extracted is None:
                values[k] = _copy_value(v)
            elif abs(values[k].extracted - v.extracted) > 1e-9:
                notes.append(f"{k}: two subset jobs fill it ({values[k].source} {values[k].extracted:.4g}, "
                             f"{v.source} {v.extracted:.4g}); the first is kept")
    pairs = _pairs(model, values, notes)
    first = next((p for p in parts if p.cmatrix), base)
    epr = next((p for p in parts if (p.results or {}).get("epr")), first)
    jobs = [j for p in parts for j in p.jobs]
    name = " + ".join(str(p.job) for p in parts if p.job) or None
    return FilledCircuit(model, base.design, values, first.cmatrix, pairs, name, notes, epr.results, jobs)


def _mark_outside(filled: FilledCircuit) -> None:
    """Branches no job filled keep their estimate; when a job had a scope (a subset), say so in ``source``."""
    scoped = [j for j in filled.jobs if j.get("scope") is not None]
    if not scoped:
        return
    groups = ", ".join(dict.fromkeys(str(j.get("group")) for j in scoped))
    for name, v in filled.values.items():
        if v.type not in ("C", "HANGER") or v.extracted is not None:
            continue
        if any(name in (j.get("in_scope") or ()) for j in scoped):
            continue  # inside a subset, but the FEM had no (physical) value for it: its own note says why
        v.extra = {**v.extra, "subset": "outside"}
        v.source = f"{v.source or 'estimate'} (estimate: outside subset {groups})"


def branch_owners(model: CircuitModel, design) -> dict[str, set[str]]:
    """Which design components each branch belongs to: the instance whose LOM model made it (``C_Q1``, ``Cg_Q2_bus``,
    ``C_C_Q0_a`` → ``C_Q0``, ``Port_P_Q0`` → ``P_Q0``), the route for a resonator (``R1``) or its hanger
    (``K_R1``), both ends for a declared coupling (``C_<coupling>`` or the coupling's own name). Unknown names fall
    back to the components named by the branch's nodes."""
    import re  # pylint: disable=import-outside-toplevel

    insts = sorted(design.instances, key=len, reverse=True)
    pats = [(i, re.compile(rf"^[A-Za-z]+_{re.escape(i)}(_.*)?$")) for i in insts]
    couplings = design.couplings
    out: dict[str, set[str]] = {}

    def head(end: str) -> str:
        return end if end in design.routes else end.split(".", 1)[0]

    for bname, b in model.branches.items():
        if bname in design.routes:
            out[bname] = {bname}
            continue
        c = couplings.get(bname) or (couplings.get(bname.split("_", 1)[1]) if "_" in bname else None)
        if c is not None:
            out[bname] = {head(e) for e in c.between}
            continue
        if bname.startswith("K_") and bname[2:] in design.routes:
            out[bname] = {bname[2:]}
            continue
        hit = next((i for i, pat in pats if pat.match(bname)), None)
        if hit is not None:
            out[bname] = {hit}
            continue
        own = set()
        for n in b.nodes:
            if n == model.ground:
                continue
            n = n.split(":", 1)[1] if n.startswith("route:") else n
            own.add(n.split(".", 1)[0])
        out[bname] = own
    return out


def _route_nets(model: CircuitModel, design) -> dict[str, list[str]]:
    """node → the route names whose conductor it is (a C-matrix net labelled with a route name: an edge port where the
    box cuts the line, or a route probe on a line the job keeps whole)."""
    port_node: dict[str, str] = {}
    for name, spec in model.nodes.items():
        for net in spec.nets:
            port_node.setdefault(net, name)
    out: dict[str, list[str]] = {}
    for rname, r in design.routes.items():
        if rname in model.branches:  # a resonator: its TLres sits on its coupler-end node
            out.setdefault(model.branches[rname].nodes[0], []).append(rname)
            continue
        node = next((port_node[e] for e in (r.from_, r.to) if isinstance(e, str) and e in port_node), None)
        if node is None and f"route:{rname}" in model.nodes:
            node = f"route:{rname}"
        if node is not None:
            out.setdefault(node, []).append(rname)
    return out


def _sim_routes(design, group: str | None, analysis: str | None) -> set[str] | None:
    """Routes present (uncut) in a job's simulated geometry, or None when unknown."""
    if not group:
        return None
    try:
        from quantcore_circuits.sim_tools.builder import simulation_design  # pylint: disable=import-outside-toplevel

        sim, _ = simulation_design(design, group, analysis or "q3d_cmatrix")
    except Exception:  # noqa: BLE001  (an old job whose group is gone: no line-net rule from the routes)
        return None
    return set(sim.routes)


def _fill_one(model, design_source, job_or_results, synthesis, stack_correction, scope, plan=None) -> FilledCircuit:
    from quantcore_circuits.assembly.last_good import plan_for_lom  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    design = load_design(design_source)
    pdk = get_pdk(design.pdk)
    if plan is None:  # the caller's plan of this design (loop.analyse plans once), else plan it here
        plan = plan_for_lom(design, design_source)  # a failed route: its last good one, with a warning
    notes: list[str] = list(plan.warnings)
    results, job = load_results(job_or_results) if job_or_results is not None else ({}, None)
    group = (job or {}).get("group") or results.get("group")
    if scope == "auto":
        from quantcore_circuits.sim_tools.subset import subset_scope  # pylint: disable=import-outside-toplevel

        if job and "select" in job:  # the job records its selection (None: the whole chip)
            scope = job["select"]
        else:
            scope = subset_scope(design, group) if group else None
    scope_set = set(scope) if scope is not None else None
    owners = branch_owners(model, design) if scope_set is not None else {}
    feedlines: set[str] = set()
    if scope_set is not None:
        from quantcore_circuits.sim_tools.subset import _Graph  # pylint: disable=import-outside-toplevel

        feedlines = _Graph(design).feedlines

    def in_scope(bname: str) -> bool:
        if scope_set is None:
            return True
        own = owners.get(bname) or set()
        return bool(own & scope_set) and own <= scope_set | feedlines

    cm = results.get("cmatrix")
    labels = cm["labels"] if cm else []
    matrix = np.asarray(cm["matrix"], dtype=float) if cm else np.zeros((0, 0))
    eps_job = _job_permittivity(job)
    eps_design = pdk.stack.substrate_permittivity
    if cm and stack_correction == "auto" and eps_job and abs(eps_job - eps_design) > 1e-6:
        scale = stack_capacitance_scale(eps_job, eps_design)
        matrix = matrix * scale
        notes.append(
            f"stack correction: job simulated with εr={eps_job:g}, design PDK εr={eps_design:g}; capacitances × "
            f"{scale:.4f} ((ε+1)/2 scaling) until the job is re-run on {design.pdk}"
        )
    route_nets = _route_nets(model, design) if cm else {}
    merged_into: dict[str, str] = {}
    if cm:
        labels, matrix, merged_into = _merge_node_nets(model, labels, matrix, route_nets)
        if merged_into:
            notes.append("C-matrix nets of one circuit node merged (a line ties them together): "
                         + ", ".join(f"{a} → {b}" for a, b in merged_into.items()))
    branch_c = branch_capacitances(matrix, labels) if cm else {}
    if cm and job:
        stub = float(job.get("waveguide_length_um", 100.0))
        for port in job.get("ports", []):
            net = port.get("excitation")
            net = merged_into.get(net, net)
            if port.get("kind") == "waveguide" and (net, "ground") in branch_c and stub > 0:
                from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=C0415

                props = cpw_properties(7.0, pdk.cpw_a, pdk.cpw_b, design.pdk)
                c_stub = stub * 1e-6 / (props["vp_m_s"] * props["Z0_ohm"]) / 1e-15
                branch_c[(net, "ground")] -= c_stub
                notes.append(f"{net}: removed {c_stub:.2f} fF of the {stub:g} µm port stub (counted in the λ/4 line)")

    def fem_net(node: str) -> str | None:
        if node == model.ground:
            return "ground"
        spec = model.nodes.get(node)
        nets = (list(spec.nets) if spec else []) + route_nets.get(node, [])
        return next((n for n in nets if n in labels), None)

    # line nets: a net carrying a distributed line has the line's own capacitance in its row sum (module docstring)
    line_nodes: dict[str, list[str]] = {}
    if cm:
        present = (set(job["routes_in_sim"]) if job and "routes_in_sim" in job
                   else _sim_routes(design, group, (job or {}).get("analysis")))
        if present is not None and scope_set is not None:
            # a subset box: a route counts when it is selected and kept whole; one that crosses the box is a net
            # labelled with its name (above); other routes left in the geometry lie outside the box
            present &= scope_set
        for node, routes in route_nets.items():
            if fem_net(node) is None:
                continue
            lines = [r for r in routes if r in labels or (present is not None and r in present)]
            if lines:
                line_nodes[node] = lines

    # missing nets: a chosen component with some nodes in the C-matrix and others not (surface-17's StarQubit: its
    # coupler / readout pins got no excitation, so the FEM treats them as ground) — the ground C of its present nodes
    # then includes the capacitance to the missing ones: keep their estimates
    partial: dict[str, list[str]] = {}
    if cm and scope_set is not None:
        for inst in sorted(scope_set & set(design.instances)):
            own = [n for n in model.nodes if n != model.ground and not model.nodes[n].ground
                   and (n == inst or n.startswith(f"{inst}."))]
            missing = [n for n in own if fem_net(n) is None]
            if missing and len(missing) < len(own):
                for n in own:
                    if n not in missing:
                        partial[n] = missing
                notes.append(f"{inst}: nodes {missing} have no C-matrix net (their conductors are ground in this FEM "
                             "job: no port / excitation reached them); the ground capacitances of its other nodes keep "
                             "their estimates")

    syn = _synthesis(model, design, pdk) if synthesis is None else synthesis
    sim = (job or {}).get("simulation_name", "")
    values: dict[str, BranchValue] = {}
    shared: dict[tuple[str, str], list[str]] = {}  # FEM net pair → in-scope C branches on it
    for bname, b in model.branches.items():
        a, c = b.nodes
        v = b.value
        if b.type == "C":
            na, nc = fem_net(a), fem_net(c)
            ext = None
            if na and nc and in_scope(bname):
                ext = branch_c.get((na, nc), branch_c.get((nc, na)))
            if ext is not None and "ground" in (na, nc) and any(n in partial for n in (a, c)):
                ext = None
            if ext is not None and "ground" in (na, nc):
                line = next((n for n in (a, c) if n in line_nodes), None)
                if line is not None:
                    notes.append(f"{bname}: {fem_net(line)} is a line net ({', '.join(line_nodes[line])} in the "
                                 f"box): its ground C {ext:.4g} fF includes the line's own capacitance, which the LOM "
                                 "models as a transmission line; estimate kept")
                    ext = None
            if ext is not None and ext <= 0:
                # a Maxwell row that is not diagonally dominant (an unconverged mesh: tutorial 02's pocket pads at
                # Q3D 2 %, island → ground −35 fF) would make the circuit unsolvable: keep the estimate for it
                notes.append(f"{bname}: FEM gave {ext:.3g} fF ({na}–{nc}), not physical (mesh not converged?); "
                             "estimate kept")
                ext = None
            if ext is not None:
                shared.setdefault(tuple(sorted((na, nc))), []).append(bname)
            q = a.split(".", 1)[0]
            s = syn.get(q, {}) if a == q else {}  # design values for grounded islands (node named after the qubit)
            des = None
            if bname == f"C_{q}" and s:
                cj = (
                    next(
                        (
                            x.value.get("Cj_fF", 0)
                            for x in model.branches.values()
                            if x.type in ("JJ", "SQUID") and x.nodes[0] == a
                        ),
                        0,
                    )
                    or 0
                )
                des = s["C_sigma_fF"] - s["Cg_fF"] - cj  # island → ground part of C_Σ
            elif bname.startswith(f"Cg_{q}_") and s:
                des = s["Cg_fF"]
            values[bname] = BranchValue(
                "C",
                (a, c),
                "fF",
                ext,
                des,
                f"cmatrix:{sim}" if ext is not None else v.get("estimate_source", "estimate"),
                {},
                v.get("estimate", v.get("C_fF")),
            )
        elif b.type in ("JJ", "SQUID"):
            s = syn.get(a, {})
            lj, extra = junction_branch(b.type, v)
            values[bname] = BranchValue(b.type, (a, c), "nH", None, s.get("Lj_nH"), "design", extra, lj)
        elif b.type == "TLres":
            rp = plan.routes.get(bname)
            length = (rp.length if rp else None) or v.get("length_um")
            if rp and rp.length and v.get("extra_length_um"):  # wires / lines / tapers the builder put in the line
                length = rp.length + v["extra_length_um"]
            a_um = rp.params.get("a", pdk.cpw_a) if rp else v.get("a_um", pdk.cpw_a)
            b_um = rp.params.get("b", pdk.cpw_b) if rp else v.get("b_um", pdk.cpw_b)
            tl = _tl_kind(tl_resonator(length, a_um, b_um, design.pdk), v.get("kind", "lambda/4"))
            q = a.split(".", 1)[0]
            values[bname] = BranchValue(
                "TL", (a, c), "µm", None, syn.get(q, {}).get("resonator_length_um"), "layout", tl, length
            )
        elif b.type == "HANGER":
            values[bname] = BranchValue(
                "HANGER", (a, c), "MHz", None, None, v.get("estimate_source", "estimate"), dict(v), v.get("kappa_MHz")
            )
        elif b.type == "R":
            values[bname] = BranchValue(
                "R", (a, c), "Ω", None, v.get("R_ohm", 50.0), "design", {}, v.get("R_ohm", 50.0)
            )
        elif b.type == "L":
            values[bname] = BranchValue("L", (a, c), "nH", None, v.get("L_nH"), "design", {}, v.get("L_nH"))

    # one FEM value, several branches on the same net pair: share it in proportion to the estimates
    for pair_nets, names in shared.items():
        if len(names) < 2:
            continue
        total = values[names[0]].extracted
        est = [max(values[n].estimate or 0.0, 0.0) for n in names]
        weights = [e / sum(est) for e in est] if sum(est) > 0 else [1 / len(names)] * len(names)
        for n, w in zip(names, weights):
            values[n].extracted = total * w
            values[n].extra = {**values[n].extra, "shared_with": [x for x in names if x != n], "fem_total": total}
        notes.append(f"{'–'.join(pair_nets)}: FEM {total:.4g} fF shared by {', '.join(names)} in proportion to their "
                     "estimates")

    # FEM κ (sim agent, additive): a driven S21 notch fit or the eigenmode Q fills the hanger branches' extracted value
    hangers = {n[2:]: n for n, v in values.items() if v.type == "HANGER" and n.startswith("K_") and n[2:] in values}
    hangers = {r: h for r, h in hangers.items() if in_scope(h)}
    if hangers and (results.get("sparams") or results.get("eigenmodes")):
        from quantcore_circuits.analysis.results import fem_kappa  # pylint: disable=import-outside-toplevel

        guess = {r: values[r].extra.get("f_GHz", 7.0) for r in hangers}
        for r, k in fem_kappa(results, guess).items():
            hv = values[hangers[r]]
            hv.extracted, hv.source = k["kappa_MHz"], k["source"]
            hv.extra = {**hv.extra, "fem": k}
            notes.append(f"{r}: κ_ext {k['kappa_MHz']:.4g} MHz from {k['source']} (LOM estimate {hv.estimate:.4g})")

    pairs = _pairs(model, values, notes)
    if cm:
        known = set(model.islands()) | {r for rs in route_nets.values() for r in rs}
        unmapped = [lab for lab in labels if lab not in known]
        if unmapped:
            notes.append(f"C-matrix nets not in the circuit (ignored): {unmapped}")
        missing = [n for n, v in values.items() if v.type == "C" and v.extracted is None and in_scope(n)]
        if missing:
            notes.append(f"no FEM value (estimate used): {missing}")
    if scope_set is not None:
        outside = sorted(n for n, v in values.items() if v.type in ("C", "HANGER") and not in_scope(n))
        notes.append(f"subset {group}: fills the branches of {sorted(scope_set)}; {len(outside)} branches outside it "
                     "keep their estimates")
    cmat = {"labels": labels, "matrix": matrix.tolist()} if cm else None
    jobs = []
    if job_or_results is not None:
        jobs.append({
            "job": (job or {}).get("simulation_name") or group,
            "group": group,
            "analysis": (job or {}).get("analysis"),
            "scope": sorted(scope_set) if scope_set is not None else None,
            "in_scope": sorted(n for n in values if in_scope(n)) if scope_set is not None else None,
            "filled": sorted(n for n, v in values.items() if v.extracted is not None),
            "results": results,
        })
    return FilledCircuit(model, design, values, cmat, pairs, (job or {}).get("simulation_name"), notes, results, jobs)


def _fill_standalone(model: CircuitModel) -> FilledCircuit:
    values: dict[str, BranchValue] = {}
    for bname, b in model.branches.items():
        v, (a, c) = b.value, b.nodes
        if b.type == "C":
            val = v.get("C_fF", v.get("value", v.get("estimate")))
            values[bname] = BranchValue(
                "C", (a, c), "fF", None, None, v.get("estimate_source", "circuit.json"), {}, val
            )
        elif b.type in ("JJ", "SQUID"):
            lj, extra = junction_branch(b.type, v)
            values[bname] = BranchValue(b.type, (a, c), "nH", None, None, "circuit.json", extra, lj)
        elif b.type == "TLres":
            if "f_GHz" not in v or "Z0_ohm" not in v:
                tl = _tl_kind(
                    tl_resonator(v["length_um"], v.get("a_um", 10.0), v.get("b_um", 6.0)), v.get("kind", "lambda/4")
                )
            else:  # stored f is already the mode's (λ/2 doubled by the builder)
                keys = ("f_GHz", "Z0_ohm", "vp_m_s", "L_geo_nH_per_m", "L_k_nH_per_m", "alpha_k")
                tl = {k: v[k] for k in keys if k in v}
            tl["kind"] = v.get("kind", "lambda/4")
            values[bname] = BranchValue("TL", (a, c), "µm", None, None, "circuit.json", tl, v.get("length_um"))
        elif b.type == "HANGER":
            values[bname] = BranchValue(
                "HANGER", (a, c), "MHz", None, None, "circuit.json", dict(v), v.get("kappa_MHz")
            )
        elif b.type == "R":
            values[bname] = BranchValue("R", (a, c), "Ω", None, None, "circuit.json", {}, v.get("R_ohm", 50.0))
        elif b.type == "L":
            values[bname] = BranchValue("L", (a, c), "nH", None, None, "circuit.json", {}, v.get("L_nH"))
    notes: list[str] = []
    return FilledCircuit(model, None, values, None, _pairs(model, values, notes), None, notes)


def _tl_kind(tl: dict, kind: str) -> dict:
    """Resonator values for its mode: ``tl_resonator`` gives the λ/4 fundamental; a λ/2 line of the same length
    resonates at twice that (and has the λ/2 equivalent LC)."""
    tl = dict(tl, kind=kind)
    if kind == "lambda/2":
        tl["f_GHz"] = tl["f_GHz"] * 2
        tl.pop("C_fF", None)
        tl.pop("L_nH", None)
    return tl


def _c_between(model: CircuitModel, values: dict[str, BranchValue], a: str, b: str) -> float:
    """Sum of the chosen values of all C branches between nodes a and b (0 if none or unknown)."""
    tot = 0.0
    for n, x in model.branches.items():
        if x.type == "C" and set(x.nodes) == {a, b} and values[n].value is not None:
            tot += values[n].value
    return tot


def _c_total(model: CircuitModel, values: dict[str, BranchValue], a: str) -> float:
    """All capacitance on node ``a`` (to ground and to every other node): its Maxwell diagonal with the rest of the
    circuit held at ground (the usual LOM reduction; Metal does the same)."""
    tot = 0.0
    for n, x in model.branches.items():
        if x.type == "C" and a in x.nodes and values[n].value is not None:
            tot += values[n].value
    return tot


def _floating_maxwell(model, values, n1: str, n2: str, cnode: str) -> tuple[np.ndarray, bool]:
    """Effective 2-node Maxwell matrix (qubit mode, coupler) of a floating transmon (islands n1, n2).

    The 3-node network (n1, n2, coupler) has a common mode φ_s = (φ1 + φ2)/2 with no potential energy, so its charge
    is conserved (zero); the qubit mode is φ_d = φ1 − φ2. With φ = T ψ, ψ = (φ_d, φ_s, φ_c), the Hamiltonian's inverse
    capacitance for (φ_d, φ_c) is the (d, c) block of (Tᵀ C T)⁻¹; its inverse is the equivalent grounded 2-node
    Maxwell matrix that the transmon–resonator adapters use. The result does not depend on how φ_s is defined.
    Returns (matrix, flipped): the sign of φ_d is chosen so the island–coupler mutual capacitance is positive.
    """
    idx = [n1, n2, cnode]
    m = np.zeros((3, 3))
    for i, a in enumerate(idx):
        m[i, i] = _c_total(model, values, a)  # nodes outside the pair are held at ground
        for j, b in enumerate(idx):
            if i != j:
                m[i, j] = -_c_between(model, values, a, b)
    t = np.array([[0.5, 1.0, 0.0], [-0.5, 1.0, 0.0], [0.0, 0.0, 1.0]])
    inv = np.linalg.inv(t.T @ m @ t)
    eff = np.linalg.inv(inv[np.ix_([0, 2], [0, 2])])
    flipped = eff[0, 1] > 0
    if flipped:
        eff[0, 1] = eff[1, 0] = -eff[0, 1]
    return eff, flipped


def _pairs(model: CircuitModel, values: dict[str, BranchValue], notes: list[str]) -> list[TransmonReadout]:
    """Transmon + readout pairs: a λ/4 or λ/2 ``TLres`` on a coupler node that one JJ/SQUID island reaches through a C.

    Grounded transmons (JJ island → ground) and floating ones (JJ between two islands, reduced to the equivalent
    grounded 2-node model, :func:`_floating_maxwell`). Every other conductor is held at ground (its capacitance to
    the pair's nodes loads them). A resonator that several qubits reach (a coupling bus) is not a readout pair.
    """
    pairs = []
    gnd = model.ground
    junctions = {n: j for n, j in model.branches.items() if j.type in ("JJ", "SQUID")}
    for rname, b in model.branches.items():
        kind = values[rname].extra.get("kind", "lambda/4")
        if b.type != "TLres" or kind not in ("lambda/4", "lambda/2"):
            continue
        cnode = b.nodes[0]
        reach = [
            jn for jn, j in junctions.items() if any(_c_between(model, values, n, cnode) for n in j.nodes if n != gnd)
        ]
        if len(reach) > 1:
            notes.append(f"{rname}: reached by {len(reach)} qubits ({', '.join(reach)}): a bus, not a readout pair")
            continue
        for jname in reach:
            j = junctions[jname]
            if values[jname].value is None:
                notes.append(f"{jname}/{rname}: missing junction value, pair skipped")
                continue
            floating = gnd not in j.nodes
            if floating:
                n1, n2 = j.nodes
                maxwell, flipped = _floating_maxwell(model, values, n1, n2, cnode)
                q = jname[2:] if jname.startswith("J_") else n1
                isl_q = model.nodes[n2 if flipped else n1].island or q
            else:
                q = j.nodes[0] if j.nodes[1] == gnd else j.nodes[1]
                c_g = _c_between(model, values, q, cnode)
                if not _c_between(model, values, q, gnd):
                    continue
                maxwell = np.array(
                    [[_c_total(model, values, q), -c_g], [-c_g, _c_total(model, values, cnode)]], dtype=float
                )
                isl_q = model.nodes[q].island or q
            tl = values[rname].extra
            hanger = next((h for h, x in model.branches.items() if x.type == "HANGER" and cnode in x.nodes), None)
            isl_c = model.nodes[cnode].island or cnode
            pairs.append(
                TransmonReadout(
                    qubit=q,
                    resonator=rname,
                    labels=[isl_q, isl_c],
                    cmatrix_fF=maxwell,
                    lj_nH=values[jname].value,
                    lj0_nH=values[jname].extra.get("Lj0_nH"),
                    cj_fF=values[jname].extra.get("Cj_fF", 0.0) or 0.0,
                    f_r_GHz=tl["f_GHz"],
                    z0_ohm=tl["Z0_ohm"],
                    feedline=next((n for n in model.branches[hanger].nodes if n != cnode), None) if hanger else None,
                    squid=values[jname].type == "SQUID",
                    asym=values[jname].extra.get("asym", 0.0),
                    flux_phi0=values[jname].extra.get("flux_phi0", 0.0),
                    kappa_MHz=values[hanger].value if hanger else None,
                    kind=kind,
                )
            )
            if floating:
                notes.append(f"{q}/{rname}: floating transmon reduced to its equivalent grounded 2-node model")
            if kind == "lambda/2":
                notes.append(f"{q}/{rname}: λ/2 readout (its fundamental as a parallel LC, C_r = π/(2 ω Z0))")
    return pairs


def junction_branch(kind: str, v: dict) -> tuple[float | None, dict]:
    """(L nH, extra) of a ``JJ`` / ``SQUID`` branch value: a SQUID's L at its ``flux_phi0`` and ``asym``
    (:func:`~quantcore_circuits.lom.fragment.squid_l_eff`; ``Lj_nH`` is L_J0 and is kept as ``extra["Lj0_nH"]`` when
    the flux changes it). The estimators, QuCat and the pairs use this L."""
    lj = v.get("Lj_nH")
    extra = {"Cj_fF": v.get("Cj_fF", 0), **{k: v[k] for k in ("asym", "flux_phi0") if k in v}}
    if kind == "SQUID" and lj and (v.get("flux_phi0") or 0.0):
        from quantcore_circuits.lom.fragment import squid_l_eff  # pylint: disable=import-outside-toplevel

        extra["Lj0_nH"] = lj
        lj = squid_l_eff(lj, v.get("flux_phi0") or 0.0, v.get("asym") or 0.0)
    return lj, extra


def resonator_lc(f_GHz: float, z0_ohm: float, kind: str = "lambda/4") -> tuple[float, float]:
    """(C fF, L nH) of the parallel LC equivalent of a TL resonator's fundamental at its open end:
    C = π/(4 ω Z0) for λ/4, π/(2 ω Z0) for λ/2, L = 1/(ω² C)."""
    if kind != "lambda/2":
        return quarter_wave_lc(f_GHz, z0_ohm)
    w = 2 * np.pi * f_GHz * 1e9
    cr = np.pi / (2 * w * z0_ohm)
    return float(cr / 1e-15), float(1 / (w**2 * cr) / 1e-9)


def two_node_model(p: TransmonReadout) -> dict:
    """Analytic loaded transmon–resonator model from the 2-node capacitance network + λ/4 LC.

    Island (1) and coupler/resonator node (2): C = [[C1 + Cg, −Cg], [−Cg, C2 + Cg]] with C1 = island→ground (+Cj),
    C2 = coupler→ground + C_r. Then EC = e²(C⁻¹)₁₁/2h, f_r = 1/(2π√(L_r/(C⁻¹)₂₂)), and the exchange coupling
    g = 2e(C⁻¹)₁₂ Q_zpf ⟨1|n|0⟩/h with Q_zpf = √(ħω_r/(2(C⁻¹)₂₂)).
    """
    from quantcore_circuits.analysis.transmon import ej_from_lj, n01_matrix_element  # pylint: disable=C0415

    e, hbar, h = 1.602176634e-19, 1.054571817e-34, 6.62607015e-34
    cr_fF, lr_nH = resonator_lc(p.f_r_GHz, p.z0_ohm, p.kind)
    c1, cg, c2 = p.c_island_fF, p.cg_fF, p.c_coupler_fF + cr_fF
    cmat = np.array([[c1 + cg, -cg], [-cg, c2 + cg]]) * 1e-15
    inv = np.linalg.inv(cmat)
    ec = e**2 * inv[0, 0] / 2 / h / 1e9
    ej = ej_from_lj(p.lj_nH)
    w_r = 1 / np.sqrt(lr_nH * 1e-9 / inv[1, 1])
    q_zpf = np.sqrt(hbar * w_r / (2 * inv[1, 1]))
    g_n = 2 * e * inv[0, 1] * q_zpf / h / 1e6  # MHz, charge (n̂) coupling
    n01 = n01_matrix_element(ej, ec)
    return {
        "EJ_GHz": float(ej),
        "EC_GHz": float(ec),
        "C_sigma_fF": float(1 / inv[0, 0] / 1e-15),
        "f_r_loaded_GHz": float(w_r / 2 / np.pi / 1e9),
        "g_MHz": float(abs(g_n) * n01),
        "g_n_MHz": float(abs(g_n)),
        "C_r_fF": cr_fF,
        "L_r_nH": lr_nH,
    }

"""Shared helpers for the design notebooks in ``examples/designs/<group>/<id>.ipynb``.

Each notebook lays a chip out with :class:`~quantcore_circuits.designer.Designer`, then calls these helpers to keep
the cells short: the LOM netlist as Markdown tables, the LOM simulation (QuCat normal modes + QuTiP dressed values)
as a mode table and a per-qubit summary, and a headless KLayout snapshot shown inline.

Usage (first code cell of a notebook)::

    import os, sys
    from pathlib import Path
    ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists())
    os.chdir(ROOT); sys.path.insert(0, str(ROOT / "examples" / "designs"))
    from _common import *
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from IPython.display import Image, Markdown, display

__all__ = [
    "HERE",
    "add_aligned",
    "Image",
    "LIVE",
    "Markdown",
    "display",
    "export_sims",
    "groups_md",
    "jobs_md",
    "lom_summary",
    "modes_md",
    "kqc_meanders",
    "netlist_md",
    "pairs_md",
    "port_info",
    "port_xy",
    "shift_away",
    "show_netlist",
    "show_snapshot",
    "simulate_groups",
    "simulate_lom",
    "summary_md",
    "upstream_path",
    "xor_vs_kqc",
    "zz_md",
]

LIVE = os.environ.get("QCC_LIVE", "1") == "1"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# upstream repo → (local other-libs/ folder, importable package whose repo holds the sources)
_UPSTREAM = {
    "qiskit-metal": ("qiskit-metal-main", "qiskit_metal"),
    "KQCircuits": ("KQCircuits-main", "kqcircuits"),
    "qucat": ("qucat-master", "qucat"),
    "SQcircuit": ("SQcircuit-main", "SQcircuit"),
}


def upstream_path(name: str, rel: str = "") -> Path:
    """A file or folder of an upstream library's source tree, wherever this machine has it.

    Tried in order: ``third_party/<name>/`` (cloud / CI: ``scripts/fetch_other_libs.sh``), the local copy
    ``other-libs/<name>-<branch>/<name>-<branch>/``, and the repository of the installed (editable) package.
    """
    folder, package = _UPSTREAM.get(name, (f"{name}-main", None))
    candidates = [REPO / "third_party" / name, REPO / "other-libs" / folder / folder]
    if package:
        import importlib.util  # pylint: disable=import-outside-toplevel

        spec = importlib.util.find_spec(package)
        if spec is not None and spec.submodule_search_locations:
            pkg = Path(list(spec.submodule_search_locations)[0]).resolve()
            candidates += [pkg.parent, pkg.parent.parent, pkg.parents[2] if len(pkg.parents) > 2 else pkg.parent]
    for base in candidates:
        if (base / rel).exists():
            return base / rel
    raise FileNotFoundError(
        f"{name}: {rel or 'source tree'} not found in {[str(c) for c in candidates]}; "
        f"run `bash scripts/fetch_other_libs.sh {name}`"
    )


# ---- netlist ---------------------------------------------------------------------------------------------------------
def _value(b) -> str:
    v = b.value or {}
    if b.type == "C":
        x = v.get("estimate", v.get("C_fF"))
        return "–" if x is None else f"{x:.3g} fF"
    if b.type in ("JJ", "SQUID"):
        lj, cj = v.get("Lj_nH"), v.get("Cj_fF")
        if lj is None:
            return "Lj –"
        return f"Lj {lj:.3g} nH" + (f", Cj {cj:.3g} fF" if cj else "")
    if b.type == "TLres":
        f, length = v.get("f_GHz"), v.get("length_um")
        parts = [v.get("kind", "")]
        if length:
            parts.append(f"{length:.0f} µm")
        if f:
            parts.append(f"{f:.3f} GHz")
        return ", ".join(p for p in parts if p)
    if b.type == "HANGER":
        k = v.get("kappa_MHz")
        return f"κ {k:.3g} MHz (L {v.get('coupling_length_um', 0):.0f} µm)" if k else "κ –"
    if b.type == "R":
        return f"{v.get('R_ohm', 50):.3g} Ω"
    if b.type == "L":
        x = v.get("L_nH")
        return "–" if x is None else f"{x:.3g} nH"
    return "–"


def netlist_md(lb, max_notes: int = 12) -> str:
    """Markdown for a :class:`~quantcore_circuits.lom.LomBuild`: nodes, branches, controls, unconnected ports."""
    m = lb.model
    out = [
        f"**{len(m.nodes)} nodes · {len(m.branches)} branches · {len(m.controls)} controls · "
        f"{len(lb.unconnected)} unconnected ports**",
        "",
    ]
    out += ["| node | FEM nets |", "|---|---|"]
    for n, s in m.nodes.items():
        out.append(f"| `{n}` | {'ground' if s.ground else (', '.join(f'`{x}`' for x in s.nets) or '–')} |")
    out += ["", "| branch | type | nodes | estimate |", "|---|---|---|---|"]
    for n, b in m.branches.items():
        out.append(f"| `{n}` | {b.type} | `{b.nodes[0]}` – `{b.nodes[1]}` | {_value(b)} |")
    if m.controls:
        out += ["", "| control | kind | target | line | length (µm) |", "|---|---|---|---|---|"]
        for n, c in m.controls.items():
            c = c if isinstance(c, dict) else c.model_dump()
            length = c.get("length_um")
            out.append(
                f"| `{n}` | {c.get('kind', '')} | `{c.get('target', '')}` | `{c.get('line', '')}` | "
                f"{'–' if length is None else f'{length:.0f}'} |"
            )
    out += ["", "**Unconnected ports:** " + (", ".join(f"`{p}`" for p in lb.unconnected) or "none")]
    notes = list(dict.fromkeys(lb.notes))
    if notes:
        out += ["", "**Builder notes:**", ""]
        out += [f"- {x}" for x in notes[:max_notes]]
        if len(notes) > max_notes:
            out.append(f"- … {len(notes) - max_notes} more")
    return "\n".join(out)


def show_netlist(lb) -> None:
    display(Markdown(netlist_md(lb)))


def lom_summary(lb) -> dict:
    """Counts used in the status table: nodes (without ground), branches, controls, unconnected ports."""
    m = lb.model
    return {
        "nodes": sum(1 for s in m.nodes.values() if not s.ground),
        "branches": len(m.branches),
        "controls": len(m.controls),
        "unconnected": len(lb.unconnected),
    }


# ---- LOM simulation ----------------------------------------------------------------------------------------------------
def simulate_lom(lb, design, max_modes: int = 2, **kw):
    """``simulate(fill(lb.model, design))``: QuCat normal modes of the whole circuit, QuTiP on ``max_modes``."""
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    return simulate(fill(lb.model, design), max_modes=max_modes, **kw)


def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    return f"{x:.{nd}g}"


def modes_md(res) -> str:
    """Normal-mode table (QuCat, first order): frequency, κ, anharmonicity, main participations."""
    out = ["| mode | kind | f (GHz) | κ (MHz) | A (MHz) | participation |", "|---|---|---|---|---|---|"]
    for m in res.modes:
        part = ", ".join(
            f"{k} {v:.2f}" for k, v in sorted(m.participation.items(), key=lambda t: -t[1])[:3] if v > 0.01
        )
        out.append(
            f"| {m.label} | {m.kind} | {m.f_GHz:.4f} | {_fmt(m.kappa_MHz, 3)} | {m.anharmonicity_MHz:.1f} | {part} |"
        )
    return "\n".join(out)


def pairs_md(res) -> str:
    """Per qubit: its most strongly coupled resonator (largest |χ|, QuCat first order)."""
    modes = res.modes
    rows = [
        "| qubit | f_q (GHz) | A (MHz) | resonator | f_r (GHz) | κ_r (MHz) | χ (MHz) |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, q in enumerate(modes):
        if q.kind != "qubit":
            continue
        res_modes = [j for j, r in enumerate(modes) if r.kind == "resonator"]
        if res_modes:
            j = max(res_modes, key=lambda j: abs(res.chi_MHz[i][j]))
            r = modes[j]
            rows.append(
                f"| {q.label} | {q.f_GHz:.4f} | {q.anharmonicity_MHz:.1f} | {r.label} | {r.f_GHz:.4f} | "
                f"{_fmt(r.kappa_MHz, 3)} | {res.chi_MHz[i][j]:.3g} |"
            )
        else:
            rows.append(f"| {q.label} | {q.f_GHz:.4f} | {q.anharmonicity_MHz:.1f} | – | – | – | – |")
    return "\n".join(rows)


def simulate_groups(d, groups: dict[str, list[str]], max_modes: int = 2, **kw) -> dict:
    """LOM simulation per sub-circuit (``d.lom(select=...)``): ``{group: LomResult}``.

    QuCat's normal-mode solve grows steeply with the node count (≈ 7 s for three transmon + λ/4 pairs, minutes
    for six), so multi-qubit chips are simulated per qubit/readout pair or per coupled group. A hanger whose feedline
    is outside the selection keeps the feedline as a 25 Ω load (both ports in parallel).
    """
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    design = d.design
    return {g: simulate(fill(d.lom(select=sel).model, design), max_modes=max_modes, **kw) for g, sel in groups.items()}


def groups_md(results: dict, targets: dict | None = None) -> str:
    """One row per simulated group: QuTiP dressed qubit and resonator values (+ targets in brackets)."""
    targets = targets or {}
    out = [
        "| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def with_target(key, val, nd):
        inst, _, q = key.partition(".")
        t = targets.get(inst, {}).get(q)
        s = _fmt(val, nd)
        return s if t is None else f"{s} ({t:g})"

    for g, res in results.items():
        qs = [m.label for m in res.modes if m.kind == "qubit" and f"{m.label}.f_q_GHz" in res.params]
        rs = [m.label for m in res.modes if m.kind == "resonator" and f"{m.label}.f_GHz" in res.params]
        for i in range(max(len(qs), len(rs), 1)):
            q = qs[i] if i < len(qs) else None
            r = rs[i] if i < len(rs) else None
            p = res.params
            out.append(
                f"| {g if i == 0 else ''} | {q or '–'} | "
                + (with_target(f"{q}.f_q_GHz", p.get(f"{q}.f_q_GHz"), 5) if q else "–")
                + " | "
                + (with_target(f"{q}.alpha_MHz", p.get(f"{q}.alpha_MHz"), 4) if q else "–")
                + f" | {r or '–'} | "
                + (with_target(f"{r}.f_GHz", p.get(f"{r}.f_GHz"), 5) if r else "–")
                + " | "
                + (with_target(f"{r}.kappa_MHz", p.get(f"{r}.kappa_MHz"), 3) if r else "–")
                + " | "
                + (with_target(f"{r}.chi_MHz", p.get(f"{r}.chi_MHz"), 3) if r else "–")
                + " |"
            )
    return "\n".join(out)


def zz_md(results: dict) -> str:
    """Static ZZ between qubit modes of each group (``LomResult.dressed["zz"]``, QuTiP): every pair, with whether the
    two qubits are circuit neighbours (then ``LomResult.zz_MHz`` holds the value) and whether their modes hybridise
    (then per-qubit ZZ is not defined)."""
    if not isinstance(results, dict):
        results = {"": results}
    out = ["| group | pair | ZZ (kHz) | neighbours | hybridised |", "|---|---|---|---|---|"]
    for g, res in results.items():
        for z in res.dressed.get("zz", []):
            val = "–" if z["hybridised"] else f"{z['zz_MHz'] * 1e3:.4g}"
            out.append(
                f"| {g} | {z['pair']} | {val} | {'yes' if z['neighbours'] else 'no'} | "
                f"{'yes' if z['hybridised'] else 'no'} |"
            )
    if len(out) == 2:
        out.append("| – | (no qubit pairs) | – | – | – |")
    return "\n".join(out)


def summary_md(res, targets: dict | None = None) -> str:
    """QuTiP dressed values (``res.params``) next to the design targets, when there are any."""
    flat = {}
    for inst, tgt in (targets or {}).items():
        for k, v in tgt.items():
            flat[f"{inst}.{k}"] = v
    keys = list(res.params) + [k for k in flat if k not in res.params]
    out = ["| parameter | LOM (QuTiP) | target |", "|---|---|---|"]
    for k in keys:
        out.append(f"| `{k}` | {_fmt(res.params.get(k), 5)} | {_fmt(flat.get(k), 5)} |")
    return "\n".join(out)


# ---- FEM jobs (simulate step: export only, AEDT/Palace run elsewhere) --------------------------------------------------
def export_sims(design_path, groups=None, analysis: str = "q3d_cmatrix", root: str | Path = "build/jobs") -> dict:
    """Export one FEM job per sim group: ``build_simulation`` + ``export_job`` → ``{group: job_dir}``.

    ``groups`` defaults to every ``sim_groups`` entry of the saved design. Jobs land in
    ``build/jobs/<design>_<group>_<analysis>`` (overwritten); run them with ``qcc sim run <job>`` where a solver is
    installed, then ``fill(model, design, job)`` replaces the LOM estimates by the C-matrix.
    """
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel

    from quantcore_circuits import track  # pylint: disable=import-outside-toplevel

    design = load_design(design_path)
    jobs = {}
    names = [f"{design.name}_{g}_{analysis}" for g in (groups or list(design.sim_groups))]
    with track.stage("render", ", ".join(names)) as st:  # dashboard: Render running -> done / failed, with the names
        for group in groups or list(design.sim_groups):
            setup = build_simulation(design_path, group, analysis)
            job = export_job(setup, Path(root) / f"{design.name}_{group}_{analysis}", overwrite=True)
            jobs[group] = (job, setup)
        st.note = f"{len(jobs)} job(s) exported"
    return jobs


def jobs_md(jobs: dict) -> str:
    """Ports and C-matrix nets of exported jobs (from :func:`export_sims`)."""
    out = ["| group | job | ports (number · kind · name) | C-matrix nets |", "|---|---|---|---|"]
    for group, (job, setup) in jobs.items():
        ports = "<br>".join(f"{p.number} · {p.kind} · `{p.name}`" for p in setup.ports) or "–"
        nets = ", ".join(f"`{n}`" for _, n in sorted(setup.nets.items())) or "–"
        out.append(f"| {group} | `{Path(job).as_posix()}` | {ports} | {nets} |")
    return "\n".join(out)


# ---- layout helpers ------------------------------------------------------------------------------------------------------
def port_xy(d, ref: str) -> tuple[float, float]:
    """Absolute position of ``"<instance>.<port>"`` (or ``"chip.<launcher>"``) in the current design (µm)."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    p = plan_design(d.design).port(ref)
    return (p.pos.x, p.pos.y)


def port_info(d, ref: str) -> tuple[float, float, float | None]:
    """``(x, y, outward direction in degrees or None)`` of a port in the current design."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    p = plan_design(d.design).port(ref)
    return (p.pos.x, p.pos.y, p.angle)


def add_aligned(d, name: str, cell, port: str, xy, rot: float = 0.0, mirror: bool = False, **kw):
    """``d.add`` with the cell's ``port`` (not its origin) at ``xy`` — KQC's ``insert_cell(..., align=port)``."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    h = d.add(name, cell, at=(0.0, 0.0), rot=rot, mirror=mirror, **kw)
    local = h.ports[port].pos
    p = pya.DCplxTrans(1, rot, mirror, 0, 0) * local
    return h.move(at=(xy[0] - p.x, xy[1] - p.y))


def shift_away(p, base, dist: float) -> tuple[float, float]:
    """KQC ``point_shift_along_vector(p, base, -dist)``: ``p`` moved ``dist`` further away from ``base``."""
    dx, dy = p[0] - base[0], p[1] - base[1]
    n = math.hypot(dx, dy)
    return (p[0] + dx / n * dist, p[1] + dy / n * dist)


def kqc_meanders(length: float, r: float, width: float) -> int:
    """KQC chips' meander count for a ``Meander`` of ``length`` (``_get_num_meanders`` in single_xmons.py)."""
    return int((length - r * (math.pi - 2)) / (width + r * (math.pi - 2)))


def xor_vs_kqc(d, kqc_cls, trans=None, skip=("refpoints", "instance_names"), **params) -> tuple[str, float]:
    """Compare the Designer output with the source: ``kqc_cls`` (a KQC chip/element PCell class) built with
    ``params`` in a fresh layout (placed with ``trans``, default identity), XOR-ed layer by layer (by layer name) with
    ``d.out``. ``skip`` layers are annotation, not mask. Returns ``(markdown table, total XOR area in µm²)``."""
    import klayout.db as kdb  # pylint: disable=import-outside-toplevel
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    ref = pya.Layout()
    ref_top = ref.create_cell("ref")
    ref_top.insert(pya.DCellInstArray(kqc_cls.create(ref, **params).cell_index(), trans or pya.DTrans()))
    ly = kdb.Layout()
    ly.read(str(d.out))
    top = ly.top_cell()
    by_name = {ly.get_info(i).name: i for i in ly.layer_indexes()}
    rows, total = ["| layer | XOR area (µm²) |", "|---|---|"], 0.0
    for li in ref.layer_indexes():
        info = ref.get_info(li)
        a = kdb.Region(ref_top.begin_shapes_rec(li)).merged()
        if a.is_empty() or info.name in skip:
            continue
        b = kdb.Region(top.begin_shapes_rec(by_name[info.name])).merged() if info.name in by_name else kdb.Region()
        x = (a ^ b).area() * ref.dbu**2
        total += x
        rows.append(f"| {info.name} ({info.layer}/{info.datatype}) | {x:.3g} |")
    return "\n".join(rows) + f"\n\n**Total XOR area: {total:.3g} µm²**", total


# ---- snapshot ------------------------------------------------------------------------------------------------------------
def show_snapshot(d, png, box=None, size=(1600, 1600), width: int = 640) -> Path:
    """Headless KLayout render of ``d.out`` (built if needed) to ``png``, shown inline."""
    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    if d.result is None or not Path(d.out).exists():
        d.show()
    png = snapshot(d.out, png, size=size, box=box)
    display(Image(filename=str(png), width=width))
    return png


# ---- coupling extraction: exchange J, tunable-coupler sweeps (designs-ibm-google) ------------------------------------
def _qubit_f(res, label: str) -> float | None:
    """Dressed (QuTiP) f_q of ``label`` in a :class:`LomResult`, else its normal-mode frequency."""
    f = res.params.get(f"{label}.f_q_GHz")
    if f is None:
        f = next((m.f_GHz for m in res.modes if m.label == label), None)
    return f


def _simulate_model(model, design, max_modes: int, lj: dict | None = None):
    """``simulate(fill(model))`` with the L_J of some junction branches replaced (``{"J_Q1": 7.0}``)."""
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    m = model.model_copy(deep=True)
    for branch, value in (lj or {}).items():
        m.branches[branch].value["Lj_nH"] = value
    return simulate(fill(m, design), max_modes=max_modes)


def exchange_coupling(d, select: list[str], qa: str, qb: str, span: float = 0.04, n: int = 3, max_modes: int = 3):
    """Effective exchange coupling J (MHz) between qubits ``qa`` and ``qb`` of the sub-circuit ``select`` (e.g. two
    qubits and their bus), from the avoided crossing: ``qb``'s junction L_J is moved so that its frequency crosses
    ``qa``'s and the dressed splitting s of the two qubit levels is fitted with s² = a(L − L0)² + 4J². A coarse pass
    (``n`` points within ±``span`` of the first estimate) locates the crossing L0 and the slope; a fine pass (three
    points ±10 MHz of detuning around L0) resolves the minimum. Bus-mediated and direct couplings are both included
    (it is the circuit's own splitting); about 2n + 4 LOM simulations.

    Returns ``dict(J_MHz, f_a_GHz, f_b_GHz, lj_b_nH, lj_cross_nH, s_min_MHz, zz_kHz)``: the as-designed frequencies of
    both qubits in this sub-circuit and their static ZZ (QuTiP; None when hybridised), ``qb``'s design L_J and the
    L_J at the crossing.
    """
    import numpy as np  # pylint: disable=import-outside-toplevel

    model, design = d.lom(select=select).model, d.design
    jb = f"J_{qb}"
    lj0 = float(model.branches[jb].value["Lj_nH"])
    base = _simulate_model(model, design, max_modes)
    fa, fb = _qubit_f(base, qa), _qubit_f(base, qb)
    z = next((z for z in base.dressed.get("zz", []) if set(z["pair"].split("-")) == {qa, qb}), None)

    def split(lj):
        r = _simulate_model(model, design, max_modes, {jb: float(lj)})
        return abs(_qubit_f(r, qa) - _qubit_f(r, qb)) * 1e3

    def fit(xs):
        ys = [split(x) for x in xs]
        a2, a1, a0 = np.polyfit(np.array(xs), np.array(ys) ** 2, 2)
        return a2, a1, a0, ys

    guess = lj0 * (fb / fa) ** 2  # f ≈ 1/√(L C): first estimate of the crossing
    a2, a1, a0, ys = fit(list(np.linspace(guess * (1 - span), guess * (1 + span), max(n, 3))))
    x0 = -a1 / (2 * a2) if a2 > 0 else guess
    slope = math.sqrt(a2) if a2 > 0 else 1.0  # MHz per nH, far from the crossing
    h = 10.0 / slope  # ±10 MHz of detuning
    a2, a1, a0, ys_f = fit([x0 - h, x0, x0 + h])
    x0 = -a1 / (2 * a2) if a2 > 0 else x0
    s2 = max(a0 - a1**2 / (4 * a2), 0.0) if a2 > 0 else min(ys_f) ** 2
    return {
        "J_MHz": math.sqrt(s2) / 2,
        "f_a_GHz": fa,
        "f_b_GHz": fb,
        "lj_b_nH": lj0,
        "lj_cross_nH": float(x0),
        "s_min_MHz": min(ys + ys_f),
        "zz_kHz": None if z is None or z["hybridised"] else z["zz_MHz"] * 1e3,
    }


def exchange_md(rows: dict, targets: dict | None = None) -> str:
    """Table of :func:`exchange_coupling` results ``{pair: result}`` (+ a target J per pair, MHz)."""
    targets = targets or {}
    out = ["| pair | f_a (GHz) | f_b (GHz) | J (MHz) | target J (MHz) | ZZ (kHz) |", "|---|---|---|---|---|---|"]
    for pair, r in rows.items():
        t = targets.get(pair)
        zz = r.get("zz_kHz")
        out.append(
            f"| {pair} | {r['f_a_GHz']:.4f} | {r['f_b_GHz']:.4f} | {r['J_MHz']:.3g} | "
            f"{'–' if t is None else f'{t:.3g}'} | {'–' if zz is None else f'{zz:.3g}'} |"
        )
    return "\n".join(out)


def _maxwell(model, nodes: list[str]):
    """Maxwell capacitance matrix (fF) of ``nodes`` from the model's C branches and junction C_J, every other
    non-ground node Kron-reduced (use a sub-circuit without resonators or ports)."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    names = [n for n, s in model.nodes.items() if not s.ground]
    idx = {n: i for i, n in enumerate(names)}
    c = np.zeros((len(names), len(names)))
    for b in model.branches.values():
        v = b.value or {}
        val = v.get("estimate", v.get("C_fF")) if b.type == "C" else (v.get("Cj_fF") or 0.0)
        if b.type not in ("C", "JJ", "SQUID") or not val:
            continue
        i, j = (idx.get(x) for x in b.nodes)
        for k in (i, j):
            if k is not None:
                c[k, k] += val
        if i is not None and j is not None:
            c[i, j] -= val
            c[j, i] -= val
    keep = [idx[n] for n in nodes]
    rest = [i for i in range(len(names)) if i not in keep]
    if rest:
        ckr = c[np.ix_(keep, rest)]
        c = c[np.ix_(keep, keep)] - ckr @ np.linalg.solve(c[np.ix_(rest, rest)], ckr.T)
    else:
        c = c[np.ix_(keep, keep)]
    return c


def yan_coupling(cm, f1: float, fc: float, f2: float) -> float:
    """Effective qubit–qubit coupling g̃ (MHz) of a qubit–coupler–qubit chain, Yan et al., PR Applied 10, 054062
    (2018), Eq. (5): ½[ω_c η/2Δ − ω_c η/2Σ + η + 1] C12/√(C1C2) √(ω1ω2), η = C1c C2c / (C12 C_c),
    1/Δ = (1/Δ1 + 1/Δ2)/2, 1/Σ = (1/Σ1 + 1/Σ2)/2. ``cm`` = Maxwell matrix of (qubit 1, coupler, qubit 2) in fF."""
    c1, cc, c2 = cm[0, 0], cm[1, 1], cm[2, 2]
    c1c, c2c, c12 = -cm[0, 1], -cm[1, 2], -cm[0, 2]
    eta = c1c * c2c / (c12 * cc)
    inv_d = (1 / (f1 - fc) + 1 / (f2 - fc)) / 2
    inv_s = (1 / (f1 + fc) + 1 / (f2 + fc)) / 2
    bracket = fc * eta * inv_d / 2 - fc * eta * inv_s / 2 + eta + 1
    return 0.5 * bracket * c12 / math.sqrt(c1 * c2) * math.sqrt(f1 * f2) * 1e3


def coupler_sweep(
    d,
    select: list[str],
    q1: str,
    q2: str,
    coupler: str,
    lj_values,
    detune_lj: float | None = None,
    max_modes: int = 3,
) -> list[dict]:
    """Tunable-coupler sweep of the sub-circuit ``select`` (two qubits + coupler): the coupler's SQUID L_J takes each
    value of ``lj_values`` (L_J = L_J0/|cos πΦ|: the flux Φ is reported against the first value).

    * **g̃**: with both qubits at their design L_J (identical qubits are degenerate), the dressed splitting of the two
      qubit levels is 2|g̃|; the sign comes from :func:`yan_coupling` on the Kron-reduced capacitances (also listed).
    * **ZZ**: with ``q2``'s L_J set to ``detune_lj`` (detuned qubits), the static ZZ of the pair (QuTiP,
      ``LomResult.dressed["zz"]``; None when the modes hybridise).

    Rows: ``lj_nH, flux_phi0, f_c_GHz, alpha_c_MHz, f_q1_GHz, f_q2_GHz, two_g_MHz, g_MHz`` (signed), ``g_yan_MHz``
    and, with ``detune_lj``, ``f_q2_detuned_GHz, zz_kHz``.
    """
    model, design = d.lom(select=select).model, d.design
    jc = f"J_{coupler}"
    cm = _maxwell(model, [q1, coupler, q2])
    lj_ref = float(lj_values[0])
    rows = []
    for lj in lj_values:
        r = _simulate_model(model, design, max_modes, {jc: float(lj)})
        fa, fb, fc = _qubit_f(r, q1), _qubit_f(r, q2), _qubit_f(r, coupler)
        two_g = abs(fa - fb) * 1e3
        g_yan = yan_coupling(cm, (fa + fb) / 2, fc, (fa + fb) / 2)
        row = {
            "lj_nH": float(lj),
            "flux_phi0": math.acos(min(lj_ref / float(lj), 1.0)) / math.pi,
            "f_c_GHz": fc,
            "alpha_c_MHz": r.params.get(f"{coupler}.alpha_MHz"),
            "f_q1_GHz": fa,
            "f_q2_GHz": fb,
            "two_g_MHz": two_g,
            "g_MHz": math.copysign(two_g / 2, g_yan),
            "g_yan_MHz": g_yan,
        }
        if detune_lj is not None:
            rz = _simulate_model(model, design, max_modes, {jc: float(lj), f"J_{q2}": float(detune_lj)})
            z = next((z for z in rz.dressed.get("zz", []) if set(z["pair"].split("-")) == {q1, q2}), None)
            row["f_q2_detuned_GHz"] = _qubit_f(rz, q2)
            row["zz_kHz"] = None if z is None or z["hybridised"] else z["zz_MHz"] * 1e3
        rows.append(row)
    return rows


def coupler_sweep_md(rows: list[dict]) -> str:
    """Markdown table of :func:`coupler_sweep` rows."""
    head = (
        "| L_J,c (nH) | Φ/Φ0 | f_c (GHz) | α_c (MHz) | f_q1 (GHz) | f_q2 (GHz) | 2·abs(g̃) (MHz) | g̃ (MHz) | "
        "g̃ Yan Eq. 5 (MHz) | ZZ (kHz), q2 detuned |"
    )
    out = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        zz = r.get("zz_kHz")
        out.append(
            f"| {r['lj_nH']:.2f} | {r['flux_phi0']:.3f} | {r['f_c_GHz']:.4f} | {_fmt(r['alpha_c_MHz'], 4)} | "
            f"{r['f_q1_GHz']:.4f} | {r['f_q2_GHz']:.4f} | {r['two_g_MHz']:.3g} | {r['g_MHz']:.3g} | "
            f"{r['g_yan_MHz']:.3g} | {'–' if zz is None else f'{zz:.4g}'} |"
        )
    return "\n".join(out)


def off_point(rows: list[dict]) -> dict | None:
    """Where g̃ changes sign (linear interpolation between sweep rows): ``lj_nH, flux_phi0, f_c_GHz``; or None."""
    for a, b in zip(rows, rows[1:]):
        if a["g_MHz"] * b["g_MHz"] <= 0 and a["g_MHz"] != b["g_MHz"]:
            t = a["g_MHz"] / (a["g_MHz"] - b["g_MHz"])
            return {k: a[k] + t * (b[k] - a[k]) for k in ("lj_nH", "flux_phi0", "f_c_GHz")}
    return None


def plot_coupler_sweep(rows: list[dict], png, title: str = "") -> Path:
    """g̃ (LOM splitting with the Yan sign, and Yan Eq. 5) and ZZ against the coupler frequency → ``png``."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    fc = [r["f_c_GHz"] for r in rows]
    zz = [(r["f_c_GHz"], r["zz_kHz"]) for r in rows if r.get("zz_kHz") is not None]
    fig, axes = plt.subplots(1, 2 if zz else 1, figsize=(9.5 if zz else 5, 3.4))
    axes = list(axes) if zz else [axes]
    ax = axes[0]
    ax.axhline(0, color="0.75", lw=0.8)
    ax.plot(fc, [r["g_MHz"] for r in rows], "o-", color="#2a6fdb", label="LOM: half the splitting (sign: Eq. 5)")
    ax.plot(fc, [r["g_yan_MHz"] for r in rows], "--", color="#d4492a", label="Yan Eq. 5 on the LOM capacitances")
    ax.set_xlabel("coupler frequency $f_c$ (GHz)")
    ax.set_ylabel(r"$\tilde g/2\pi$ (MHz)")
    ax.legend(fontsize=8, frameon=False)
    if zz:
        ax = axes[1]
        ax.axhline(0, color="0.75", lw=0.8)
        ax.plot([p[0] for p in zz], [p[1] for p in zz], "s-", color="#3a9d5d")
        ax.set_xlabel("coupler frequency $f_c$ (GHz)")
        ax.set_ylabel(r"static ZZ/$2\pi$ (kHz), qubits detuned")
        ax.set_yscale("symlog", linthresh=10)
    if title:
        fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    png = Path(png)
    fig.savefig(png, dpi=130)
    plt.close(fig)
    display(Image(filename=str(png), width=760))
    return png


__all__ += [
    "coupler_sweep",
    "coupler_sweep_md",
    "exchange_coupling",
    "exchange_md",
    "off_point",
    "plot_coupler_sweep",
    "yan_coupling",
]


# ---- Quantcore PDK conformance (design rules, 2026-11-03) ---------------------------------------------------------
def _pad_instances(d) -> list[str]:
    """Bond pads / launchers of a design (the cells the PDK pad rule puts ``frame.pad_edge``, 100 µm, from the edge)."""
    from quantcore_circuits.assembly.drc import _bond_pad  # pylint: disable=import-outside-toplevel

    return [n for n, spec in d.data["instances"].items() if _bond_pad(spec["cell"])]


def pin_hangers(d) -> list[str]:
    """Turn every hanger end given by arclength ``s`` into ``near=(x, y)`` at its current coupler centre, so the
    couplers stay where they are when a feedline's start moves (e.g. :func:`pads_to_edge`). Returns the routes."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    plan = plan_design(d.design)
    done = []
    with d._change("pin hangers"):  # pylint: disable=protected-access
        for name, spec in d.data["routes"].items():
            for key in ("from", "to"):
                end = spec.get(key)
                if not (isinstance(end, dict) and "hanger" in end and end.get("s") is not None):
                    continue
                nodes = plan.routes[name].nodes
                a, b = (nodes[-1], nodes[-2]) if key == "to" else (nodes[0], nodes[1])
                mid = a.position + (b.position - a.position) * 0.5
                end = dict(end)
                end.pop("s")
                end["near"] = [round(mid.x, 4), round(mid.y, 4)]
                spec[key] = end
                done.append(name)
    return done


def pads_to_edge(d, pin: bool = True) -> list[str]:
    """Quantcore pad rule: every bond pad / launcher instance gets ``place.edge="auto"`` (outer etch ``frame.pad_edge``,
    100 µm, from the nearest die edge). ``pin`` first pins the hangers (:func:`pin_hangers`) so the
    resonator couplers do not slide along the feedlines. Snapped pads are left alone. Returns the pads moved."""
    if pin:
        pin_hangers(d)
    moved = []
    with d.batch():
        for name in _pad_instances(d):
            place = d.data["instances"][name]["place"]
            if place.get("at") is None:
                continue  # snapped: it follows its target
            d[name].move(edge="auto")
            moved.append(name)
    return moved


def content_box(d, labels: bool = False):
    """Bounding box (µm) of what is placed on the chip: instances and routes, from the built sidecar. Free text
    labels (``TextLabel``) are left out unless ``labels`` (they move with the circuit but should not centre it)."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    side = sidecar_dict(build(d.design), overlays=False)
    cells = {n: spec["cell"] for n, spec in d.data["instances"].items()}
    box = pya.DBox()
    for name, inst in side["instances"].items():
        if not labels and cells.get(name, "").split(".")[-1] == "TextLabel":
            continue
        if inst.get("bbox"):
            box += pya.DBox(*inst["bbox"])
    for route in side["routes"].values():
        for x, y in route.get("polyline") or []:
            box += pya.DPoint(x, y)
    return box


def translate_design(d, dx: float, dy: float, skip_pads: bool = False) -> None:
    """Shift every absolute position of a design by (dx, dy) µm: instance ``at``, route waypoints, free ends and
    hanger ``near`` points (snapped instances follow their targets; hangers given by ``s`` follow their feedline)."""

    def move(p):
        return [p[0] + dx, p[1] + dy]

    pads = set(_pad_instances(d)) if skip_pads else set()
    with d._change(f"translate ({dx:g}, {dy:g})"):  # pylint: disable=protected-access
        for name, spec in d.data["instances"].items():
            if spec["place"].get("at") is not None and name not in pads:
                spec["place"]["at"] = move(spec["place"]["at"])
        for spec in d.data["routes"].values():
            nodes = []
            for n in spec.get("nodes") or []:
                if isinstance(n, dict):
                    n = dict(n, at=move(n["at"]))
                else:
                    n = move(n)
                nodes.append(n)
            if nodes:
                spec["nodes"] = nodes
            for key in ("from", "to"):
                end = spec.get(key)
                if isinstance(end, dict) and end.get("at") is not None:
                    spec[key] = dict(end, at=move(end["at"]))
                elif isinstance(end, dict) and end.get("near") is not None:
                    spec[key] = dict(end, near=move(end["near"]))


def center_in_die(d, tol: float = 50.0) -> tuple[float, float]:
    """Centre the design's content in the die (it should not sit in a corner). Returns the shift applied (µm)."""
    x0, y0, x1, y1 = d.design.chip.box
    box = content_box(d)
    dx = round((x0 + x1) / 2 - box.center().x, 1)
    dy = round((y0 + y1) / 2 - box.center().y, 1)
    if abs(dx) <= tol and abs(dy) <= tol:
        return (0.0, 0.0)
    translate_design(d, dx, dy)
    return (dx, dy)


def pdk_report(d) -> str:
    """Markdown summary of the PDK checks of a design: pads at the edge, cheese source, junction types, margin
    warnings (the DRC's design warnings: flagged, never enforced)."""
    from collections import Counter  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.plan import default_junction_type, pdk_cheese  # pylint: disable=C0415

    design = d.design
    result = build(design)
    issues = check(result, netlist=False).issues
    margin = [i for i in issues if i.rule == "pad_edge" or i.rule.startswith("pdk_")]
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    def draws_junction(spec) -> bool:  # qubits / couplers / junction cells, or anything given junction values
        if spec.junction is not None:
            return True
        try:
            return getattr(resolve_cell(spec.cell), "qcc_category", "") in ("qubit", "junction")
        except Exception:  # noqa: BLE001
            return False

    jt = Counter(
        (spec.params or {}).get("junction_type") or default_junction_type(spec.cell) or "—"
        for spec in design.instances.values()
        if default_junction_type(spec.cell) is not None and draws_junction(spec)
    )
    box = content_box(d)
    x0, y0, x1, y1 = design.chip.box
    cheese = "PDK band (drawn in the build)" if pdk_cheese(design) else "the original design's own (or none)"
    rule = design.chip.params.get("cheese")
    if isinstance(rule, dict):  # a design-chosen (original) cheese rule, drawn by the build (notebooks-metal)
        cheese = "the original design's rule (drawn in the build): " + ", ".join(f"{k} {v:g}" for k, v in rule.items())
    dx, dy = box.center().x - (x0 + x1) / 2, box.center().y - (y0 + y1) / 2
    junctions = ", ".join(f"{k} × {v}" for k, v in jt.items()) or "—"
    kinds = ", ".join(f"{k} × {v}" for k, v in Counter(i.rule for i in margin).items()) or "none"
    lines = [
        "| check | value |",
        "|---|---|",
        f"| cheese | {cheese} |",
        f"| content centre − die centre | ({dx:+.0f}, {dy:+.0f}) µm |",
        f"| junction types | {junctions} |",
        f"| PDK design warnings | {len(margin)} ({kinds}) |",
    ]
    for i in margin[:12]:
        lines.append(f"| {i.rule} | {i.message} |")
    return "\n".join(lines)


__all__ += ["center_in_die", "content_box", "pads_to_edge", "pdk_report", "pin_hangers", "translate_design"]


# ---- educative design-notebook steps (2026-11-03) ---------------
def pdk_facts_md(d=None) -> str:
    """The Quantcore PDK facts a design notebook relies on (stack, die frame, pad rule, junction rule, cheese, 3/0
    keep-outs, fab-only corner rounding), from :func:`quantcore_circuits.pdk.get_pdk`, plus this chip's die box."""
    from quantcore_circuits.pdk import DEFAULT_PDK, get_pdk  # pylint: disable=import-outside-toplevel

    pdk = get_pdk(d.design.pdk if d is not None else DEFAULT_PDK)
    s, f, j, k, c, r = pdk.stack, pdk.frame, pdk.junction, pdk.keepout, pdk.cheese, pdk.rounding
    w, h = pdk.die_size
    rows = [
        "| PDK rule | value |",
        "|---|---|",
        f"| process | `{pdk.name}` v{pdk.version} |",
        f"| stack | {s.substrate_material} {s.substrate_height:g} µm, εr {s.substrate_permittivity:g}, "
        f"Nb film (λ_L {s.london_penetration_depth_um:g} µm) |",
        f"| CPW default | centre {pdk.cpw_a:g} µm, gap {pdk.cpw_b:g} µm, bend radius {pdk.turn_radius:g} µm |",
    ]
    if f is not None:
        rows += [
            f"| die frame | standard die {w / 1e3:g} × {h / 1e3:g} mm; L dicing markers (1000/0, {f.dicing_width:g} µm "
            f"wide), 3 × 3 alignment grids (1001/0) in {f.marker_area:g} µm corner areas, boundary 100/0, device ID |",
            f"| pad rule | bond pads / launchers: outer etch edge **{f.pad_edge:g} µm** (`frame.pad_edge`) from the "
            'die edge (`edge="auto"`) |',
        ]
    rows += [
        f"| junctions | {j.material}, Nb Δ {j.gap_meV:g} meV, R_n {j.rn_target_kohm[0]:g}–{j.rn_target_kohm[1]:g} kΩ "
        f"(nominal {j.rn_nominal_kohm:g} kΩ = {j.nominal_fingers_um[0]:g} × {j.nominal_fingers_um[1]:g} µm), "
        f"C_J {j.cj_fF_per_um2:g} fF/µm²; fingers 2/0 + 4/0, spacer 50/0 (+ 51–53/0 dose gradient) |",
        f"| qubit band | f_q {j.f_q_range_GHz[0]:g}–{j.f_q_range_GHz[1]:g} GHz (outside: DRC design warning `pdk_fq`) |",
    ]
    if c is not None:
        rows.append(
            f"| cheese | the original design's own if it has one, else the PDK band: {c.size:g} µm squares, {c.gap:g} µm "
            f"gaps, {c.rows} rows around the 3/0 keep-outs (chip param `cheese`: auto / pdk / original) |"
        )
    rows.append(
        f"| 3/0 keep-out | filled second-metal etch: routes CPW footprint + {k.route_margin:g} µm, components etch bbox "
        f"+ {k.component_margin:g} µm (or the cell's own) |"
    )
    if r is not None:
        rows.append(
            f"| corner rounding | fab only: r = {r.fraction:g} × the shortest dimension, ≤ {r.max_radius:g} µm |"
        )
    if d is not None:
        x0, y0, x1, y1 = d.design.chip.box
        rows.append(
            f"| this chip | die box ({x0:g}, {y0:g}) – ({x1:g}, {y1:g}) µm = {(x1 - x0) / 1e3:g} × {(y1 - y0) / 1e3:g} mm |"
        )
    return "\n".join(rows)


def pads_md(d) -> str:
    """Bond pads and launchers with the distance of their outer etch edge from the nearest die edge (PDK pad rule:
    ``frame.pad_edge``, 100 µm). KQC sample-holder launchers are listed by port (their indent comes from the rule)."""
    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.plan import pad_edge  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    design = d.design
    result = d.result if d.result is not None else build(design)
    side = sidecar_dict(result, overlays=False)
    x0, y0, x1, y1 = design.chip.box
    edge = pad_edge(design)
    rows = [
        "| pad | cell / launcher | nearest die edge | outer etch → die edge (µm) | PDK rule |",
        "|---|---|---|---|---|",
    ]
    for name in _pad_instances(d):
        b = (side["instances"].get(name) or {}).get("bbox")
        if not b:
            continue
        gaps = {"w": b[0] - x0, "s": b[1] - y0, "e": x1 - b[2], "n": y1 - b[3]}
        side_, gap = min(gaps.items(), key=lambda kv: kv[1])
        ok = "✓" if abs(gap - edge) <= 1.0 else '✗ (`edge="auto"`)'
        rows.append(f"| {name} | `{design.instances[name].cell.split('.')[-1]}` | {side_} | {gap:.1f} | {ok} |")
    for ref, port in (side.get("ports") or {}).items():
        if not ref.startswith("chip."):
            continue
        px, py = port["pos"] if isinstance(port, dict) and "pos" in port else (None, None)
        if px is None:
            continue
        gaps = {"w": px - x0, "s": py - y0, "e": x1 - px, "n": y1 - py}
        side_, gap = min(gaps.items(), key=lambda kv: kv[1])
        rows.append(f"| {ref} | launcher port | {side_} | port {gap:.0f} µm in (indent from the rule) | ✓ |")
    if len(rows) == 2:
        rows.append("| – | no bond pads or launchers | – | – | – |")
    return "\n".join(rows)


def fab_layers_md(d, path=None, cheese=False, rounding=False) -> str:
    """``export_fab`` of the current build → Markdown: fab layer, PDK name, polygon count (+ cheese source and hole
    count, and the device layers with no PDK fab layer). ``cheese``/``rounding`` off (the default) is the quick
    layer check; on, it is the full fab file (``qcc mask``)."""
    from quantcore_circuits.layouts.wafers.fab_export import export_fab  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    if d.result is None:
        d.show()
    fab, layers = {}, get_pdk(d.design.pdk).fab_layers
    path = Path(path) if path else Path("build") / f"{d.design.name}_fab.oas"
    export_fab(d.result, path, report=fab, cheese=cheese, rounding=rounding)
    rows = ["| fab layer | PDK name | polygons |", "|---|---|---|"]
    rows += [
        f"| {layers[k].layer}/{layers[k].datatype} | {k} | {n} |"
        for k, n in sorted(fab["written"].items(), key=lambda kv: (layers[kv[0]].layer, layers[kv[0]].datatype))
    ]
    out = "\n".join(rows)
    if cheese is not False:
        out += f"\n\n**Cheese:** source `{fab.get('cheese_source')}`, {fab.get('cheese_holes', 0)} holes on the mask."
    dropped = ", ".join(f"{k} ({n})" for k, n in (fab.get("dropped") or {}).items())
    if dropped:
        out += f"\n\n**Not in the mask (no PDK fab layer):** {dropped}"
    return out + f"\n\n→ `{path.as_posix()}`"


def send_fem_jobs(
    design_path,
    groups=None,
    analyses=None,
    run: bool = False,
    timeout: float | None = None,
    root: str | Path = "build/jobs",
) -> dict:
    """Export the FEM jobs of the design's sim groups (each group's own ``analyses`` unless given) and, with ``run``,
    solve the Ansys ones in a **new batch, non-graphical** AEDT (2024 R1 or later, found by
    :func:`~quantcore_circuits.sim_tools.ansys.find_ansys_executable`; a user's open AEDT is never touched, and KQC's
    pyEPR T1 script is never run). Returns ``{"<group> · <analysis>": (job_dir, setup)}`` (the :func:`jobs_md`
    format)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.export import solver_of  # pylint: disable=import-outside-toplevel

    design = load_design(design_path)
    jobs = {}
    for group in groups or list(design.sim_groups):
        for analysis in analyses or list(design.sim_groups[group].analyses or ["q3d_cmatrix"]):
            setup = build_simulation(design_path, group, analysis)
            job = export_job(setup, Path(root) / f"{design.name}_{group}_{analysis}", overwrite=True)
            jobs[f"{group} · {analysis}"] = (job, setup)
    if not run:
        print(f"{len(jobs)} job(s) exported; RUN_FEM is False, nothing solved.")
        return jobs
    from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.hfss import solve_job  # pylint: disable=import-outside-toplevel

    exe = find_ansys_executable()
    if exe is None:
        print("AEDT 2024 R1 (or later) not found: jobs exported, not solved.")
        return jobs
    for key, (job, setup) in jobs.items():
        if solver_of(setup.analysis) != "ansys":
            print(f"{key}: {setup.analysis} is not an Ansys analysis; run it with `qcc sim run {Path(job).as_posix()}`")
            continue
        r = solve_job(job, executable=exe, graphical=False, timeout=timeout)
        print(f"{key}: {'solved' if r.ok else 'FAILED'} in {r.seconds:.0f} s → {Path(job).as_posix()}/results")
    return jobs


def fem_back(model, design_path, jobs: dict):
    """Bring FEM results back into the LOM: for every job with ``results/results.json``, ``fill(model, design, job)``
    (C-matrix values replace the component estimates, matched by net name). Returns ``(filled, markdown)``:
    ``filled`` maps job key → :class:`~quantcore_circuits.circuit.fill.FilledCircuit`; the Markdown compares the
    estimate with the extracted value per branch, or says which jobs have no results yet."""
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel

    filled, rows, missing = {}, [], []
    for key, (job, _setup) in jobs.items():
        if not (Path(job) / "results" / "results.json").exists():
            missing.append(key)
            continue
        fc = fill(model, design_path, job)
        filled[key] = fc
        for r in fc.branch_table():
            if r["extracted"] is None:
                continue
            est, ext = r["estimate"], r["extracted"]
            delta = f"{100 * (ext - est) / abs(est):+.1f} %" if isinstance(est, (int, float)) and est else "–"
            rows.append(f"| {key} | {r['branch']} | {r['type']} | {_fmt(est)} | {_fmt(ext)} | {delta} |")
    out = []
    if rows:
        out += ["| job | branch | type | LOM estimate | FEM extracted | Δ |", "|---|---|---|---|---|---|", *rows]
    if missing:
        out.append(
            ("\n" if rows else "")
            + f"No FEM results yet for {', '.join(missing)}: after a solve, `results/results.json` appears in each job "
            "folder and this cell shows the C-matrix (or eigenmode) values next to the LOM estimates; "
            "`simulate(filled)` then re-runs the LOM on the extracted values."
        )
    return filled, "\n".join(out)


def params_delta_md(before, after, keys=None) -> str:
    """Before/after table of LOM parameters (``LomResult.params``; a dict of group → LomResult is flattened as
    ``group: key``). ``keys`` limits the rows (substring match)."""

    def flat(res):
        if isinstance(res, dict):
            return {f"{g}: {k}": v for g, r in res.items() for k, v in r.params.items()}
        return dict(res.params)

    a, b = flat(before), flat(after)
    rows = ["| parameter | before | after | Δ |", "|---|---|---|---|"]
    for k in a:
        if keys and not any(s in k for s in keys):
            continue
        x, y = a.get(k), b.get(k)
        delta = f"{y - x:+.4g}" if isinstance(x, (int, float)) and isinstance(y, (int, float)) else "–"
        rows.append(f"| `{k}` | {_fmt(x, 5)} | {_fmt(y, 5)} | {delta} |")
    return "\n".join(rows)


def design_copy(design_path, suffix: str = "_iter"):
    """A second, non-live Designer on a saved design (for "change one property and re-simulate" steps): it writes
    ``build/<name><suffix>.oas`` when shown and never saves over the design file."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.designer import Designer  # pylint: disable=import-outside-toplevel

    name = load_design(design_path).name
    return Designer.load(design_path, live=False, autosave=False, out=Path("build") / f"{name}{suffix}.oas")


__all__ += ["design_copy", "fab_layers_md", "fem_back", "pads_md", "params_delta_md", "pdk_facts_md", "send_fem_jobs"]


# ---- design-notebook helpers, part 2 (notebooks-rest part 2, 2026-11-03): stale-build guard, step snapshots, DRC table
def rebuild(d):
    """Build the design again if it changed since the last build (a ``live=False`` Designer does not rebuild on
    each change; ``d.result``, ``d.drc()`` and the snapshots would show the previous build). Returns the result."""
    if d.result is None or getattr(d, "_dirty", False) or not Path(d.out).exists():
        d.show()
    return d.result


def snap(d, png, box=None, size=(1600, 1600), width: int = 640) -> Path:
    """:func:`show_snapshot` of the current state of the design (rebuilt first if it changed)."""
    rebuild(d)
    return show_snapshot(d, png, box=box, size=size, width=width)


def drc_md(rep, width: int = 110) -> str:
    """A DRC report as a table: errors, warnings and PDK design warnings (severity ``design``, flagged, never
    enforced) by rule, with a count and the first message of each."""
    from collections import Counter  # pylint: disable=import-outside-toplevel

    kind = {"error": "error", "warning": "warning", "design": "PDK design warning"}
    order = {"error": 0, "warning": 1, "design": 2}
    count = Counter((i.severity, i.rule) for i in rep.issues)
    first = {}
    for i in rep.issues:
        first.setdefault((i.severity, i.rule), i.message)
    n = Counter(i.severity for i in rep.issues)
    head = (
        f"**{n.get('error', 0)} errors · {n.get('warning', 0)} warnings · {n.get('design', 0)} PDK design warnings**"
        f" ({'DRC clean' if rep.ok else 'NOT clean'})"
    )
    rows = ["| kind | rule | count | first message |", "|---|---|---|---|"]
    for (sev, rule), cnt in sorted(count.items(), key=lambda kv: (order.get(kv[0][0], 3), kv[0][1])):
        msg = first[(sev, rule)].replace("|", "/")
        rows.append(f"| {kind.get(sev, sev)} | `{rule}` | {cnt} | {msg[:width]}{'…' if len(msg) > width else ''} |")
    return head + "\n\n" + "\n".join(rows)


def original_cheese(size: float, pitch: float, clearance: float = 0.0, d=None):
    """A :class:`~quantcore_circuits.pdk.CheeseRule` that reproduces a source's own whole-chip ground cheese in the
    fab export (``export_fab(result, path, cheese=rule)`` / ``fab_layers_md(d, cheese=rule)``): ``size`` µm squares
    on a ``pitch`` µm grid, at least ``clearance`` µm from the 3/0 keep-outs, over the whole design area (the band
    is made wide enough to cross the die). Used with chip ``cheese: "original"`` (the build then draws no PDK band;
    the build itself cannot draw a design-chosen rule yet)."""
    from quantcore_circuits.pdk import CheeseRule  # pylint: disable=import-outside-toplevel

    x0, y0, x1, y1 = d.design.chip.box if d is not None else (0.0, 0.0, 30000.0, 30000.0)
    rows = int(max(x1 - x0, y1 - y0) / pitch) + 1
    return CheeseRule(size=size, gap=pitch - size, rows=rows, clearance=clearance)


def snap_file(path, png, box=None, size=(1600, 1600), width: int = 640) -> Path:
    """Headless snapshot of a layout file (e.g. the fab mask written by ``export_fab``), shown inline."""
    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    png = snapshot(str(path), png, size=size, box=box)
    display(Image(filename=str(png), width=width))
    return png


__all__ += ["drc_md", "original_cheese", "rebuild", "snap", "snap_file"]


# ---- Quantum Metal sources (notebooks-metal, 2026-11-03) -------------------------------------------------------------
def metal_cheese(d, buffer: float = 25.0, size: float = 25.0, pitch: float = 100.0):
    """:func:`original_cheese` for a Quantum Metal source exported to GDS: Metal's ``QGDSRenderer`` cheeses the whole
    ground by default (``cheese.view_in_file = {main: {1: True}}``) with ``size`` µm squares (``cheese_0_x/y``,
    default 25 µm) every ``pitch`` µm (``delta_x/y``, 100 µm), ``buffer`` µm (``no_cheese.buffer``, default 25 µm;
    several tutorials set 50 µm) clear of every etched shape. The 3/0 keep-out already adds the PDK route margin
    round each CPW, so the clearance from 3/0 is ``buffer`` minus that margin."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    margin = get_pdk(d.design.pdk).keepout.route_margin
    return original_cheese(size, pitch, clearance=max(buffer - margin, 0.0), d=d)


def metal_cheese_rule(buffer: float = 25.0, size: float = 25.0, pitch: float = 100.0, edge: float = 200.0) -> dict:
    """Quantum Metal's GDS-renderer cheese as a chip ``cheese`` rule (``chip={"cheese": metal_cheese_rule(...)}``):
    the build draws it instead of the PDK band (layout, snapshots, KLive) and ``export_fab`` / ``qcc mask`` keep it.

    ``QGDSRenderer`` defaults (``cheese``: ``cheese_0_x/y`` 25 µm squares every ``delta_x/y`` 100 µm,
    ``edge_nocheese`` 200 µm; ``no_cheese.buffer`` 25 µm round every etched shape) give
    ``{"size": 25, "gap": 75, "rows": 1000, "clearance": 25, "edge": 200}``; a source that sets
    ``no_cheese.buffer = 50um`` passes ``buffer=50``. ``rows`` 1000 fills the whole free ground; ``clearance`` is
    measured from the 3/0 keep-out, which already adds the PDK route margin round each CPW (so the holes sit a few
    µm further from the etch than in Metal). Supersedes :func:`metal_cheese` (a fab-export-only rule)."""
    return {"size": float(size), "gap": float(pitch - size), "rows": 1000, "clearance": float(buffer),
            "edge": float(edge)}


__all__ += ["metal_cheese", "metal_cheese_rule"]


# ---- v2 design notebooks (nb-plan, 2026-11-18): layout segments, then the plugin's Flow steps --------------------------
# The v2 form: the layout is built segment by segment (die →
# pads → readout line → qubits → readout resonators → coupling → control lines → the whole chip), each segment with a
# snapshot of the chip so far; then the KLayout plugin's Flow strip, Check → LOM → Simulate → Results → Fab. Additive:
# nothing above changed (the <id>.v1.ipynb notebooks keep using it). Nothing here solves unless asked (RUN_FEM).
def _tut_module():
    """``examples/tutorials/_tut.py``, loaded once under its own name: its FEM tables (C-matrix, eigenmodes / pyEPR,
    S21 notches, convergence) are the tutorials' and are reused here unchanged."""
    import importlib.util  # pylint: disable=import-outside-toplevel
    import sys  # pylint: disable=import-outside-toplevel

    mod = sys.modules.get("_qcc_tut")
    if mod is None:
        spec = importlib.util.spec_from_file_location("_qcc_tut", REPO / "examples" / "tutorials" / "_tut.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_qcc_tut"] = mod
        spec.loader.exec_module(mod)
    return mod


def _with_plot(draw) -> None:
    """Show a Results plot next to its table; a missing or odd result must never break the table."""
    try:
        draw()
    except Exception as exc:  # noqa: BLE001
        print(f"(plot skipped: {type(exc).__name__}: {exc})")


def _epr_from_keep(keep):
    """The EPR result of a kept eigenmode job that holds pyEPR values, else None."""
    import json  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.analysis import epr_lumped as L  # pylint: disable=import-outside-toplevel

    res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
    return L.epr_from_job(res) if (res.get("epr") or {}).get("p_mj") else None


def cmatrix_md(keep) -> str:
    """The solved Maxwell C-matrix (fF) of a kept Q3D job, with its net names (``_tut.cmatrix_md``)."""
    return _tut_module().cmatrix_md(keep)


def eigen_md(keep) -> str:
    """Eigenmodes (f, Q) and the pyEPR values (p_J, dressed f, self- and cross-Kerr) of a kept eigenmode job."""
    _with_plot(lambda: plot_epr(_epr_from_keep(keep)))
    return _tut_module().eigen_md(keep)


def driven_md(keep) -> str:
    """The S21 notch fits (f0, κ_ext, Q_c, Q_i) of a kept driven job (``_tut.driven_md``)."""
    _with_plot(lambda: plot_s21_fit(keep))
    return _tut_module().driven_md(keep)


def convergence_md(keeps: dict) -> str:
    """``{label: kept folder or None}`` → passes, mesh, criterion, last Δ / target, converged, wall time."""
    _with_plot(lambda: plot_convergence(keeps))
    return _tut_module().convergence_md(keeps)


def epr_values(keep, readouts: dict, f_guess: dict) -> dict:
    """Target-style values (``Q1.f_q_GHz``, ``Q1.alpha_MHz``, ``R1.f_GHz``, ``R1.chi_MHz``, ``R1.kappa_MHz``, pair
    ZZ) from a kept eigenmode/EPR job: ``readouts`` maps each qubit to its readout, ``f_guess`` gives the expected
    readout frequencies (GHz, e.g. the LOM's). See ``_tut.epr_values``."""
    return _tut_module().epr_values(keep, readouts, f_guess)


def fem_vs_lom_md(rows) -> str:
    """Rows ``(quantity, LOM value, FEM value, note)`` as a table with the difference in %."""
    return _tut_module().fem_vs_lom_md(rows)


def before_after_md(before: dict, after: dict, units: dict | None = None) -> str:
    """Before / after table (same keys) of a feedback or iterate step."""
    return _tut_module().before_after_md(before, after, units)


def fem_fast(flag: bool = True) -> bool:
    """The ``FEM_FAST`` switch: every job exported from here on gets the library's fast test settings (few passes,
    coarse mesh, values not converged) when True; the settings as written when False. Returns the flag."""
    return _tut_module().fem_fast(flag)


# ---- layout segments ---------------------------------------------------------------------------------------------------
def on_chip(d) -> dict:
    """What is placed so far, by kind: ``{"pads", "qubits", "components", "routes", "couplings", "sim_groups"}``
    (counts; pads = bond pads / launchers by the PDK pad rule, qubits = cells of category ``qubit``)."""
    from quantcore_circuits.assembly.drc import _bond_pad  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    out = {"pads": 0, "qubits": 0, "components": 0}
    for spec in d.data["instances"].values():
        cell = spec["cell"]
        if _bond_pad(cell):
            out["pads"] += 1
            continue
        try:
            qubit = getattr(resolve_cell(cell), "qcc_category", "") == "qubit"
        except Exception:  # noqa: BLE001  (static cells, unknown wrappers: counted as components)
            qubit = False
        out["qubits" if qubit else "components"] += 1
    out["routes"] = len(d.data["routes"])
    out["couplings"] = len(d.data.get("couplings") or {})
    out["sim_groups"] = len(d.data.get("sim_groups") or {})
    return out


def layout_step(d, png, box=None, size=(1200, 1200), width: int = 480, note: str = "") -> Path:
    """One layout segment's picture: rebuild if the design changed, snapshot (``box`` zooms in), and one line saying
    what is on the chip so far and what this segment added."""
    seen = getattr(d, "_v2_seen", {"instances": set(), "routes": set()})
    new_i = [n for n in d.data["instances"] if n not in seen["instances"]]
    new_r = [n for n in d.data["routes"] if n not in seen["routes"]]
    d._v2_seen = {"instances": set(d.data["instances"]), "routes": set(d.data["routes"])}  # pylint: disable=W0212
    n = on_chip(d)

    def names(xs):
        return ", ".join(f"`{x}`" for x in xs[:8]) + (f" … (+{len(xs) - 8})" if len(xs) > 8 else "")

    added = [f"{len(new_i)} component(s) {names(new_i)}" if new_i else "", f"{len(new_r)} route(s) {names(new_r)}"
             if new_r else ""]
    added = " and ".join(a for a in added if a) or "nothing new to the layout"
    line = (f"**On the chip so far:** {n['pads']} pads · {n['qubits']} qubits · {n['components']} other components · "
            f"{n['routes']} routes · {n['couplings']} declared couplings. **This step added** {added}."
            + (f" {note}" if note else ""))
    png = snap(d, png, box=box, size=size, width=width)
    display(Markdown(line))
    return png


def _like(new, old):
    """``new`` with its dict keys in ``old``'s order where both have them (new keys last), recursively."""
    if isinstance(new, dict) and isinstance(old, dict):
        keys = [k for k in old if k in new] + [k for k in new if k not in old]
        return {k: _like(new[k], old.get(k)) for k in keys}
    if isinstance(new, list) and isinstance(old, list) and len(new) == len(old):
        return [_like(a, b) for a, b in zip(new, old)]
    return new


def design_diff(new: dict, old: dict, show: int = 8) -> list[str]:
    """What differs between two design JSON dicts (content, not order): one line per section."""
    out = []
    for key in sorted(set(new) | set(old)):
        a, b = new.get(key), old.get(key)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            added = [k for k in a if k not in b]
            removed = [k for k in b if k not in a]
            changed = [k for k in a if k in b and a[k] != b[k]]
            parts = [f"{label} {', '.join(f'`{x}`' for x in xs[:show])}{' …' if len(xs) > show else ''}"
                     for label, xs in (("added", added), ("removed", removed), ("changed", changed)) if xs]
            out.append(f"- `{key}`: " + "; ".join(parts))
        else:
            out.append(f"- `{key}`: {str(b)[:80]} → {str(a)[:80]}")
    return out


def save_design(d, path) -> tuple[Path, str]:
    """``d.save(path)``, compared with the file it replaces (the previous run's, e.g. the ``.v1`` notebook's).

    The saved file keeps the previous file's key order (instances, routes, parameters …: a segmented build adds things
    in another order than a one-cell build), so it is byte-identical when nothing changed and ``git diff`` shows only
    real changes. Returns ``(path, markdown)``: identical, or the sections that differ."""
    import json  # pylint: disable=import-outside-toplevel

    path = Path(path)
    old_text = path.read_text(encoding="utf-8") if path.exists() else None
    try:
        old = json.loads(old_text) if old_text is not None else None
    except ValueError:
        old = None
    d.save(path)
    new = json.loads(path.read_text(encoding="utf-8"))
    if old is None:
        return path, f"`{path.as_posix()}` written (no earlier file to compare with)."
    text = json.dumps(_like(new, old), indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    if new == old:
        same = "byte for byte" if text == old_text else "in content (number formatting differs)"
        return path, (f"**Same design as before:** `{path.as_posix()}` is identical to the file it replaces "
                      f"({same}). The segments changed how the chip is built, not the chip.")
    return path, (f"**The design differs from the file it replaced** (`{path.as_posix()}`):\n\n"
                  + "\n".join(design_diff(new, old)))


# ---- Simulate: solve or load kept FEM results ----------------------------------------------------------------------
TIMEOUT_S = {"q3d_cmatrix": 900.0, "eigenmode_epr": 2400.0, "hfss_eigenmode": 2400.0, "hfss_driven": 2700.0}


def fem_keep_dir(design_path) -> Path:
    """Where a design notebook keeps solved FEM results: ``<design folder>/fem/`` (``results.json`` + ``job.json``
    per job; ``build/`` is not kept in the repo, this folder survives it)."""
    return Path(design_path).parent / "fem"


def _job_meta(folder) -> dict:
    import json  # pylint: disable=import-outside-toplevel

    try:
        return json.loads((Path(folder) / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def kept_fem(job_dir, keep_root) -> Path | None:
    """The solved results of an exported job: the kept copy ``keep_root/<job>/``, else the job folder itself when a
    solve outside the notebook (``qcc hfss solve``, the plugin, AEDT) left ``results/results.json`` in it."""
    for folder in (Path(keep_root) / Path(job_dir).name, Path(job_dir)):
        if (folder / "results" / "results.json").exists():
            return folder
    return None


def fem_matches(job_dir, keep) -> bool:
    """Whether kept results belong to this export: same design (or sim-group) hash, group and analysis, and solver
    settings the same or tighter (``sim_tools.export.tighter_or_equal``)."""
    from quantcore_circuits.sim_tools.export import tighter_or_equal  # pylint: disable=import-outside-toplevel

    new, old = _job_meta(job_dir), _job_meta(keep)
    if not new or not old:
        return False
    key = "group_hash" if new.get("group_hash") and old.get("group_hash") else "design_hash"
    return (all(new.get(k) == old.get(k) for k in (key, "group", "analysis"))
            and tighter_or_equal(old.get("settings") or {}, new.get("settings") or {}))


def fem_solve_or_load(job_dir, run_fem, keep_root, timeout: float | None = None, force=False,
                      aedt: str | None = None) -> Path | None:
    """The Simulate step of one exported job (``build/jobs/<job>``).

    ``run_fem`` (True, or a set of analyses such as ``{"q3d_cmatrix"}``): solve it with ``sim_tools.hfss.solve_job``
    in AEDT 2024 R1+ the ``aedt`` way (``"batch"``: a new non-graphical AEDT, the default; ``"gui"``: a new AEDT window,
    left open; ``"attach"``: the window you have open) and keep ``results.json`` + ``job.json`` in
    ``keep_root/<job>/`` (the notebooks pass :func:`fem_keep_dir`). Kept results of the same job are not solved again
    unless ``force`` (True or a set of analyses). ``run_fem`` False: nothing is solved;
    the kept results are returned when there are any, else None with a one-line message. Never KQC's
    ``run_pyepr_t1_estimate.py``; a timeout stops only what qcc started."""
    import shutil  # pylint: disable=import-outside-toplevel

    job_dir, keep_root = Path(job_dir), Path(keep_root)
    analysis = _job_meta(job_dir).get("analysis", "")
    if run_fem and not isinstance(run_fem, bool):
        run_fem = analysis in set(run_fem)
    if force and not isinstance(force, bool):
        force = analysis in set(force)
    keep = kept_fem(job_dir, keep_root)
    if run_fem and keep is not None and not force and fem_matches(job_dir, keep):
        print(f"{job_dir.name}: kept results match this job (same design, same or tighter settings): not solved "
              "again (RESOLVE = True re-solves)")
        run_fem = False
    if run_fem:
        from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=C0415

        exe = find_ansys_executable()
        if exe is None:
            print(f"{job_dir.name}: RUN_FEM, but no AEDT 2024 R1+ found (set QCC_ANSYS_EXECUTABLE): nothing solved")
        else:
            from quantcore_circuits.sim_tools.aedt_session import resolve_mode  # pylint: disable=C0415
            from quantcore_circuits.sim_tools.hfss import solve_job  # pylint: disable=import-outside-toplevel

            mode = resolve_mode(aedt)
            t = timeout or TIMEOUT_S.get(analysis, 1800.0)
            print(f"solving {job_dir.name} with {exe} ({mode} AEDT; timeout {t:.0f} s; a progress line every 30 s) …")
            r = solve_job(job_dir, timeout=t, aedt=mode)
            print(f"  {'ok' if r.ok else 'FAILED'} in {r.seconds:.0f} s; log {r.log}" + (f"; {r.note}" if r.note else ""))
            res = job_dir / "results" / "results.json"
            if r.ok and res.exists():
                dest = keep_root / job_dir.name
                (dest / "results").mkdir(parents=True, exist_ok=True)
                shutil.copy2(res, dest / "results" / "results.json")
                shutil.copy2(job_dir / "job.json", dest / "job.json")
            keep = kept_fem(job_dir, keep_root)
    if keep is None:
        print(f"{job_dir.name}: no solved results yet (RUN_FEM = True solves it; kept in "
              f"{(keep_root / job_dir.name).as_posix()}/): the cells below say what would appear")
    elif not fem_matches(job_dir, keep):
        print(f"{job_dir.name}: the kept results were solved for another revision of this job (design or settings "
              "differ): shown as they are; RUN_FEM = True with RESOLVE = True solves the current one")
    return keep


def fem_stage(jobs: dict, run_fem, keep_root, force=False, aedt: str | None = None) -> dict:
    """:func:`fem_solve_or_load` for every job of ``jobs`` (the ``{key: (job_dir, setup)}`` of :func:`export_sims` /
    :func:`send_fem_jobs`), one AEDT job after the other. Returns ``{key: kept folder or None}``."""
    return {key: fem_solve_or_load(job, run_fem, keep_root, force=force, aedt=aedt) for key, (job, _) in jobs.items()}


def driven_from_eigenmode(design_path, group: str, eig_job, eig_keep=None, f_guess: float | None = None,
                          span=(-0.4, 0.2), points: int = 10001, root: str | Path = "build/jobs"):
    """The full-wave (HFSS driven, S21) job of ``group``, set up from its eigenmode job.

    The library cannot hand a solved eigenmode mesh to a driven setup (no such option in ``sim_tools``: a gap, see
    the plan), so this is the nearest honest step: the same sim group and box, the eigenmode job's mesh seeds
    (``settings.mesh_size``: the gap and junction-island seeds that resolved the modes), the adaptive-mesh frequency at
    the eigenmode's resonator mode (the solved mode nearest ``f_guess`` with Q > 100; without results, ``f_guess``
    itself), and a fast sweep from f + ``span[0]`` to f + ``span[1]`` GHz with ``points`` points. Returns
    ``{group: (job_dir, setup)}`` (the :func:`jobs_md` format)."""
    import json  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.export import MAX_SWEEP_POINTS  # pylint: disable=import-outside-toplevel

    f0, how = f_guess, "the LOM's resonator frequency (no eigenmode results yet)"
    if eig_keep is not None:
        res = json.loads((Path(eig_keep) / "results" / "results.json").read_text(encoding="utf-8"))
        modes = [m for m in res.get("eigenmodes") or [] if (m.get("Q") or 0) > 100]
        if modes and f_guess is not None:
            m = min(modes, key=lambda m: abs(m["f_GHz"] - f_guess))
            f0, how = m["f_GHz"], f"eigenmode {m['mode']} ({m['f_GHz']:.4f} GHz, the mode nearest {f_guess:.3f} GHz)"
    settings = {"sweep_type": "fast", "sweep_count": min(int(points), MAX_SWEEP_POINTS)}
    seeds = (_job_meta(eig_job).get("settings") or {}).get("mesh_size")
    if seeds:
        settings["mesh_size"] = dict(seeds)
    if f0 is not None:
        settings.update(frequency=round(f0, 4), sweep_start=round(f0 + span[0], 4), sweep_end=round(f0 + span[1], 4))
    name = load_design(design_path).name
    setup = build_simulation(design_path, group, "hfss_driven")
    job = export_job(setup, Path(root) / f"{name}_{group}_hfss_driven", overwrite=True, **settings)
    print(f"{group} · hfss_driven: adaptive mesh at {how}; mesh seeds "
          f"{seeds if seeds else '(none in the eigenmode job: the analysis defaults)'}; sweep "
          f"{settings.get('sweep_start', '?')}–{settings.get('sweep_end', '?')} GHz")
    return {group: (job, setup)}


def driven_values(keep, resonator: str, f_guess: float | None = None) -> dict:
    """``{"<resonator>.f_GHz", "<resonator>.kappa_MHz"}`` from the S21 notch of a kept driven job nearest
    ``f_guess`` (κ = κ_ext of the notch fit); ``{}`` without a notch."""
    import json  # pylint: disable=import-outside-toplevel

    res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
    notches = list(((res.get("sparams") or {}).get("notch") or {}).values())
    if not notches:
        return {}
    n = min(notches, key=lambda n: abs(n["f0_GHz"] - (f_guess or n["f0_GHz"])))
    return {f"{resonator}.f_GHz": n["f0_GHz"], f"{resonator}.kappa_MHz": n["kappa_ext_MHz"]}


# ---- plots (LOM, eigenmodes, the iterate loop) ---------------------------------------------------------------------
def _axes(ax, xminor: int = 5):
    try:
        from quantcore_circuits.plots import thesis_axes  # pylint: disable=import-outside-toplevel

        thesis_axes(ax, xminor=xminor)
    except Exception:  # noqa: BLE001  (style only)
        pass


def _colors():
    try:
        from quantcore_circuits.plots import COLORS  # pylint: disable=import-outside-toplevel

        return COLORS
    except Exception:  # noqa: BLE001
        return ["#185adb", "#f9813a", "#da0037", "#206a5d", "#444444"]


def _show_fig(fig, png, width):
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    png = Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(png, dpi=130)
    plt.close(fig)
    display(Image(filename=str(png), width=width))
    return png


def plot_lom(results: dict, png, targets: dict | None = None, title: str = "", width: int = 760) -> Path:
    """The LOM simulation as two plots: (a) every normal mode of each simulated group (QuCat: circle = qubit, square =
    resonator, triangle = other; filled = the QuTiP dressed value when there is one; a red bar = the target), (b) the
    dispersive shift |χ| of each resonator (QuTiP, log scale)."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    targets = targets or {}
    c = _colors()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(9.5, 3.6), gridspec_kw={"width_ratios": [3, 2]})
    marker = {"qubit": "o", "resonator": "s"}
    chis = []
    for i, (g, res) in enumerate(results.items()):
        for m in res.modes:
            key = f"{m.label}.f_q_GHz" if m.kind == "qubit" else f"{m.label}.f_GHz"
            dressed = res.params.get(key)
            ax.plot([i], [m.f_GHz], marker.get(m.kind, "^"), mfc="none", color=c[0 if m.kind == "qubit" else 1])
            if dressed is not None:
                ax.plot([i], [dressed], marker.get(m.kind, "^"), color=c[0 if m.kind == "qubit" else 1])
            q = "f_q_GHz" if m.kind == "qubit" else "f_GHz"
            t = (targets.get(m.label) or {}).get(q)
            if t is not None:
                ax.plot([i], [t], "_", ms=16, mew=2, color=c[2])
            if m.kind == "resonator" and res.params.get(f"{m.label}.chi_MHz") is not None:
                chis.append((f"{g}: {m.label}", abs(res.params[f"{m.label}.chi_MHz"])))
    ax.set_xticks(range(len(results)), list(results), rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("frequency (GHz)")
    ax.set_title("(a) LOM modes: o qubit, □ resonator; filled = dressed; red = target", fontsize=9)
    _axes(ax, xminor=1)
    if chis:
        bx.barh(range(len(chis)), [max(v, 1e-4) for _, v in chis], color=c[3])
        bx.set_yticks(range(len(chis)), [k for k, _ in chis], fontsize=8)
        bx.set_xscale("log")
        bx.set_xlabel("|χ| (MHz)")
    else:
        bx.text(0.5, 0.5, "no qubit–resonator χ", ha="center", va="center", transform=bx.transAxes)
    bx.set_title("(b) dispersive shift per resonator", fontsize=9)
    if title:
        fig.suptitle(title, fontsize=10)
    return _show_fig(fig, png, width)


def plot_eigenmodes(keeps: dict, png, lom: dict | None = None, title: str = "", width: int = 760) -> Path | None:
    """The solved eigenmode jobs as two plots: (a) each mode's frequency per adaptive pass (the convergence the mesh
    went through), (b) the final modes, frequency against Q (log), the colour the junction participation p_J; the
    LOM's frequencies of the same components (``lom``: ``{label: GHz}``) as dashed lines. ``keeps``: ``{label: kept
    folder or None}``. Returns None (and says so) when nothing is solved."""
    import json  # pylint: disable=import-outside-toplevel

    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    done = {k: v for k, v in keeps.items() if v}
    if not done:
        display(Markdown("**No eigenmode results yet** (`RUN_FEM = True` solves them): this plot would show each "
                         "mode's frequency per mesh pass and the final modes against Q and p_J, next to the LOM."))
        return None
    c = _colors()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(9.5, 3.6))
    for j, (label, keep) in enumerate(done.items()):
        res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
        conv = res.get("convergence") or {}
        per_pass = conv.get("mode_GHz") or {}
        for i, (mode, fs) in enumerate(per_pass.items()):
            ax.plot(range(1, len(fs) + 1), fs, "o-", ms=3, color=c[(j * 3 + i) % len(c)], label=f"{label} m{mode}")
        epr = res.get("epr") or {}
        pj = [row[0] if row else 0.0 for row in epr.get("p_mj") or []]
        modes = res.get("eigenmodes") or []
        sc = bx.scatter([m["f_GHz"] for m in modes], [max(m.get("Q") or 1.0, 1.0) for m in modes],
                        c=(pj + [0.0] * len(modes))[: len(modes)], cmap="viridis", vmin=0, vmax=1, marker="os^D"[j % 4],
                        label=label)
    for name, f in (lom or {}).items():
        if f:
            bx.axvline(f, ls="--", lw=0.8, color=c[4])
            bx.text(f, bx.get_ylim()[1], f" {name}", rotation=90, va="top", fontsize=7)
    ax.set_xlabel("adaptive pass")
    ax.set_ylabel("mode frequency (GHz)")
    ax.set_title("(a) convergence of each mode", fontsize=9)
    if per_pass:
        ax.legend(fontsize=7, frameon=False)
    bx.set_yscale("log")
    bx.set_xlabel("frequency (GHz)")
    bx.set_ylabel("Q")
    bx.set_title("(b) final modes (colour: p_J), LOM dashed", fontsize=9)
    fig.colorbar(sc, ax=bx, label="p_J")
    from matplotlib.ticker import MaxNLocator  # pylint: disable=import-outside-toplevel

    _axes(ax, xminor=1)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    if title:
        fig.suptitle(title, fontsize=10)
    return _show_fig(fig, png, width)


# ---- Results: feedback to a target, and the iterate loop -----------------------------------------------------------
def target_copy(design_path, targets: dict, suffix: str = "_target") -> Path:
    """The saved design plus ``targets`` (``{instance: {quantity: value}}``, e.g. ``{"Q1": {"f_q_GHz": 6.8}}``;
    tolerances: the LOM defaults, f_q ± 20 MHz, f_r ± 10 MHz) written to ``build/<name><suffix>.json``. The feedback
    and iterate steps work on it, so the design file (the deliverable) keeps its own targets. Targets do not enter
    the design hash, so kept FEM results of the design still match it."""
    d2 = design_copy(design_path, suffix)
    d2.targets(**targets)
    return d2.save(Path("build") / f"{d2.design.name}{suffix}.json")


def pdk_lj_bounds(design_path) -> dict:
    """``{"<instance>.junction.Lj_nH": (lo, hi)}`` for every instance with a design L_J: the L_J range of the PDK R_n
    window (40–50 kΩ), so the feedback keeps the junctions inside it."""
    from quantcore_circuits.circuit.bridges import lj_from_rn  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    design = load_design(design_path)
    lo_k, hi_k = get_pdk(design.pdk).junction.rn_target_kohm
    a, b = sorted((round(lj_from_rn(lo_k * 1e3), 4), round(lj_from_rn(hi_k * 1e3), 4)))
    return {f"{n}.junction.Lj_nH": (a, b) for n, spec in design.instances.items()
            if getattr(spec.junction, "Lj_nH", None) is not None}


def consensus_md(an, only_targets: bool = False) -> str:
    """The consensus of a ``loop.analyse`` (one row per parameter: the chosen value and which estimator gave it, the
    spread between estimators, the target ± tolerance, the residual in tolerances, pass / fail)."""
    rows = [r for r in an.rows if r.target is not None] if only_targets else list(an.rows)
    out = ["| parameter | chosen | by | spread | target | residual / tol | status |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        tgt = f"{r.target:g} ± {r.tol:g}" if r.target is not None else "–"
        spread = f"{100 * r.spread_rel:.1f} %" if r.spread_rel is not None else "–"
        out.append(f"| `{r.param}` ({r.unit}) | {_fmt(r.chosen, 5)} | {r.chosen_by or '–'} | {spread} | {tgt} | "
                   f"{'–' if r.residual is None else f'{r.residual:+.2f}'} | {r.status} |")
    if len(out) == 2:
        out.append("| – | no parameters (no qubit–readout pair, or no targets) | | | | | |")
    return "\n".join(out)


def proposal_md(prop) -> str:
    """A ``loop.feedback`` proposal: each knob now → proposed, the predicted residuals, knobs at a bound, notes."""
    out = ["| knob | now | proposed |", "|---|---|---|"]
    out += [f"| `{k}` | {_fmt(prop.start_knobs.get(k), 6)} | **{_fmt(v, 6)}** |" for k, v in prop.knobs.items()]
    if not prop.knobs:
        out.append("| – | no knob moves (no target set, or every target already met) | – |")
    if prop.residuals:
        out += ["", "Predicted residuals (in tolerances): "
                + ", ".join(f"`{k}` {v:+.2f}" for k, v in prop.residuals.items())]
    if prop.at_bounds:
        out += ["", f"**At a bound:** {', '.join(prop.at_bounds)} (widen the bound or add a target for another knob)."]
    if prop.notes:
        out += ["", "**Notes:**", *[f"- {n}" for n in list(dict.fromkeys(prop.notes))[:10]]]
    return "\n".join(out)


def iterate_to_target(design_t, fem=None, max_iter: int = 3, bounds: dict | None = None, solve=None,
                      readout: bool = False, an=None, start: int = 0, group: str | None = None):
    """The feedback cell, repeated until every target is inside its tolerance or ``max_iter`` revisions are made.

    Each pass: ``loop.analyse`` (the estimators on the circuit; the first point on the FEM values of ``fem`` — a kept
    folder or a list of them — when given) → on target? stop → ``loop.feedback`` (a surrogate anchored on that point →
    knobs → revision k, built and netlist-checked, ``build/<name>/revisions/rev<k>.json``) → analyse the revision.
    ``solve(rev_path, k)`` may return FEM results for a revision (the notebook's ``RUN_FEM`` path: export and solve its
    jobs); without it the revisions are judged on the LOM, so the FEM − LOM offset of the first point is not carried
    on (say so when there was one). Returns ``(history, last design path, last analysis)``; a history row is
    ``{"iteration", "design", "fem", "objective", "values", "targets", "on_target", "knobs", "notes"}``.
    ``an``: the analysis of ``design_t`` when the notebook already has it (the feedback cell's), so it is not run
    again; ``start``: the number of ``design_t``'s iteration (its next revision is ``rev<start + 1>``); ``group``: a
    sim group whose circuit alone is analysed (``loop.analyse(..., group=)``: big chips, where the estimators on every
    qubit–readout pair take too long)."""
    from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel

    src, job, history = Path(design_t), fem, []
    if an is None:
        an = loop.analyse(str(src), job, group=group, readout=readout)
    for k in range(start, start + max_iter + 1):
        rows = [r for r in an.rows if r.target is not None]
        res = {r.param: r.residual for r in rows if r.residual is not None}
        entry = {
            "iteration": k, "design": src, "fem": job is not None,
            "objective": math.sqrt(sum(x * x for x in res.values())) if res else None,
            "values": {r.param: r.chosen for r in rows}, "targets": {r.param: (r.target, r.tol) for r in rows},
            "on_target": bool(res) and all(abs(x) <= 1 for x in res.values()), "knobs": {}, "notes": [],
        }
        history.append(entry)
        if entry["on_target"] or k == start + max_iter or not res:
            if not res:
                entry["notes"].append("no target reached the consensus (no qubit–readout pair with a target?)")
            break
        prop, rev, _ = loop.feedback(an, design_source=str(src), iteration=k + 1, bounds=bounds)
        entry["knobs"] = {name: (prop.start_knobs.get(name), v) for name, v in prop.knobs.items()}
        entry["notes"] = list(dict.fromkeys(prop.notes)) + ([f"at a bound: {', '.join(prop.at_bounds)}"]
                                                             if prop.at_bounds else [])
        src = Path(rev)
        job = solve(src, k + 1) if solve is not None else None
        an = loop.analyse(str(src), job, group=group, readout=readout)
    return history, src, an


def history_md(history: list[dict]) -> str:
    """The iterate loop as a table: per iteration the design, LOM or FEM, ‖residual‖, each target's value, the knobs
    the feedback moved next, on target or not; the notes below."""
    params = list(dict.fromkeys(p for h in history for p in h["targets"]))
    head = "| it. | design | on | ‖r‖ | " + " | ".join(
        f"`{p}` ({_fmt(history[0]['targets'][p][0], 5)} ± {_fmt(history[0]['targets'][p][1], 3)})"
        if p in history[0]["targets"] else f"`{p}`" for p in params) + " | knobs moved next | on target |"
    out = [head, "|" + "---|" * (len(params) + 6)]
    for h in history:
        knobs = "<br>".join(f"`{k}` {_fmt(a, 5)} → {_fmt(b, 5)}" for k, (a, b) in h["knobs"].items()) or "–"
        out.append(f"| {h['iteration']} | `{Path(h['design']).name}` | {'FEM' if h['fem'] else 'LOM'} | "
                   f"{_fmt(h['objective'], 3)} | " + " | ".join(_fmt(h["values"].get(p), 5) for p in params)
                   + f" | {knobs} | {'yes' if h['on_target'] else 'no'} |")
    notes = list(dict.fromkeys(n for h in history for n in h["notes"]))
    if notes:
        out += ["", "**Notes:**", *[f"- {n}" for n in notes[:10]]]
    return "\n".join(out)


def plot_iterations(history: list[dict], png, width: int = 420) -> Path | None:
    """‖residual‖ (in tolerances) against the iteration, log scale, with the tolerance line at 1."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    pts = [(h["iteration"], h["objective"]) for h in history if h["objective"] is not None]
    if not pts:
        return None
    c = _colors()
    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    ax.plot([p[0] for p in pts], [max(p[1], 1e-3) for p in pts], "o-", color=c[0])
    ax.axhline(1.0, ls="--", color=c[2], lw=0.8)
    ax.set_yscale("log")
    ax.set_xlabel("iteration")
    ax.set_ylabel("‖residual‖ (tolerances)")
    ax.set_xticks([p[0] for p in pts])
    _axes(ax, xminor=1)
    return _show_fig(fig, png, width)


__all__ += [
    "TIMEOUT_S",
    "before_after_md",
    "cmatrix_md",
    "consensus_md",
    "convergence_md",
    "design_diff",
    "driven_from_eigenmode",
    "driven_md",
    "driven_values",
    "eigen_md",
    "epr_lumped",
    "epr_values",
    "fem_fast",
    "fem_keep_dir",
    "fem_matches",
    "fem_solve_or_load",
    "fem_stage",
    "fem_vs_lom_md",
    "history_md",
    "iterate_to_target",
    "kept_fem",
    "layout_step",
    "on_chip",
    "pdk_lj_bounds",
    "plot_convergence",
    "plot_eigenmodes",
    "plot_epr",
    "plot_iterations",
    "plot_lom",
    "plot_s21_fit",
    "proposal_md",
    "save_design",
    "target_copy",
]


def pcell_params_md(cell: str, values: dict | None = None, only=None, noparents: bool = True) -> str:
    """The parameters of a PCell (KQC ``get_schema``) as a table: name, default, the value this design passes
    (``values``, e.g. ``d.data["instances"]["CHIP"]["params"]``) and the PCell's own description. For a chip drawn by
    one KQC chip PCell, these parameters are what its layout segments are made of. ``only``: the names to list;
    ``noparents=False`` adds the inherited ones (chip frame, faces …)."""
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    cls = resolve_cell(cell)
    try:
        schema = cls.get_schema(noparents=noparents)
    except Exception:  # noqa: BLE001  (not a KQC element: no schema)
        schema = {}
    values = values or {}

    def short(v):
        s = "–" if v is None else str(v)
        return (s[:60] + "…") if len(s) > 60 else s

    out = [f"**`{getattr(cls, '__name__', cell)}`** parameters:", "", "| parameter | default | this design | meaning |",
           "|---|---|---|---|"]
    for name, p in schema.items():
        if only and name not in only:
            continue
        used = short(values[name]) if name in values else "(default)"
        desc = str(getattr(p, "description", "") or "").replace("|", "/")
        out.append(f"| `{name}` | {short(getattr(p, 'default', None))} | {used} | {desc} |")
    if len(out) == 4:
        out.append("| – | no own parameters | – | – |")
    return "\n".join(out)


__all__ += ["pcell_params_md"]


# ---- v2 design notebooks, part B (nb-v2-B, 2026-11-18): kept eigenmodes, and a one-knob rule with its iterate loop ----
# For chips whose feedback ``loop.feedback`` cannot do (no qubit–readout pair: resonator test chips, a bus between two
# qubits, a qubit pair without readout, a readout the LOM sees as a wire): a first-order rule on one knob, iterated
# with a secant. Additive: nothing above changed. Nothing here builds a design or runs a solver on its own.
def eig_modes(keep) -> list[dict]:
    """The solved eigenmodes of a kept eigenmode job (``[{"mode", "f_GHz", "Q", …}]``); ``[]`` without results."""
    import json  # pylint: disable=import-outside-toplevel

    if not keep:
        return []
    path = Path(keep) / "results" / "results.json"
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("eigenmodes") or [])


def _monotone(a: list[float], b: list[float]) -> list[tuple[int, int]]:
    """Order-preserving matching of every value of the sorted list ``a`` to one of the sorted list ``b``
    (``len(a) <= len(b)``) with the least squared difference: ``[(i, j)]``."""
    n, m = len(a), len(b)
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]  # cost[i][j]: the first i of a on the first j of b
    take = [[False] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        cost[0][j] = 0.0
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            skip = cost[i][j - 1]
            use = cost[i - 1][j - 1] + (b[j - 1] - a[i - 1]) ** 2
            cost[i][j], take[i][j] = (use, True) if use <= skip else (skip, False)
    out, i, j = [], n, m
    while i > 0 and j > 0:
        if take[i][j]:
            out.append((i - 1, j - 1))
            i -= 1
        j -= 1
    return out[::-1]


def match_modes(keep, guesses: dict, q_min: float = 100.0) -> dict:
    """Each label of ``guesses`` (``{label: expected f in GHz}``, e.g. the LOM's resonator frequencies) → the kept
    eigenmode it is (``{label: mode dict}``). Order-preserving, as ``epr_values``: the k-th lowest guess gets the k-th
    lowest of the chosen modes (Q > ``q_min``: the low-Q modes of a cut line are left out), the choice with the least
    squared detuning (a greedy nearest-mode choice can swap two neighbours). With fewer modes than guesses each mode
    gets the guess it fits best and the other labels are missing from the result. ``{}`` without results."""
    modes = sorted((m for m in eig_modes(keep) if (m.get("Q") or 0) > q_min), key=lambda m: m["f_GHz"])
    labels = sorted((k for k, v in guesses.items() if v is not None), key=lambda k: guesses[k])
    if not labels or not modes:
        return {}
    fs, gs = [m["f_GHz"] for m in modes], [guesses[k] for k in labels]
    if len(labels) <= len(modes):
        pairs = _monotone(gs, fs)
    else:
        pairs = [(i, j) for j, i in _monotone(fs, gs)]
    return {labels[i]: modes[j] for i, j in pairs}


def rule_step(knob: float, value: float, target: float, exponent: float) -> float:
    """The first-order rule ``value ∝ knob ** exponent`` solved for the knob that puts ``value`` on ``target``
    (e.g. a λ/4 or λ/2 line: f ∝ 1/length, exponent −1; a transmon's α ∝ 1/C_Σ; f_q ≈ ∝ L_J^−1/2)."""
    return knob * (target / value) ** (1.0 / exponent)


def rule_iterate(evaluate, param: str, knob: str, k0: float, target: float, tol: float, exponent: float,
                 max_iter: int = 3, start=None, fem: bool = False, bounds=None) -> list[dict]:
    """The one-knob feedback repeated until ``param`` is within ``tol`` of ``target`` or ``max_iter`` steps are made.

    ``evaluate(k, it)`` builds revision ``it`` with the knob at ``k`` and returns ``(value, design path)`` (the
    notebook's cell: a ``design_copy`` with the knob set, saved, simulated — LOM, or FEM with ``RUN_FEM``);
    ``start``: ``(value, design path)`` of the knob at ``k0`` when the notebook already has it (not evaluated again).
    Each step is :func:`rule_step` with ``exponent`` first, then the exponent of the last two points (a secant in
    log–log; kept only when it has the prior's sign). ``bounds``: ``(lo, hi)`` of the knob (a step beyond is clamped
    and noted). Returns history rows in the :func:`iterate_to_target` format (``history_md``, ``plot_iterations``)."""
    history, pts, k = [], [], float(k0)
    for it in range(max_iter + 1):
        value, path = start if (it == 0 and start is not None) else evaluate(k, it)
        res = None if value is None else (value - target) / tol
        entry = {
            "iteration": it, "design": Path(path) if path else Path("-"), "fem": bool(fem),
            "objective": None if res is None else abs(res), "values": {param: value},
            "targets": {param: (target, tol)}, "on_target": res is not None and abs(res) <= 1, "knobs": {},
            "notes": [],
        }
        history.append(entry)
        if value is None:
            entry["notes"].append(f"no value of `{param}` for this revision: the loop stops here")
            break
        pts.append((k, value))
        if entry["on_target"] or it == max_iter:
            break
        p = exponent
        if len(pts) >= 2:
            (ka, fa), (kb, fb) = pts[-2], pts[-1]
            if ka > 0 and kb > 0 and fa * fb > 0 and abs(math.log(kb / ka)) > 1e-9:
                q = math.log(fb / fa) / math.log(kb / ka)
                if q * exponent > 0 and abs(q) > 1e-3:
                    p = q
        k_new = rule_step(k, value, target, p)
        if bounds:
            lo, hi = bounds
            if not lo <= k_new <= hi:
                entry["notes"].append(f"`{knob}` {k_new:.5g} is outside {lo:g}–{hi:g}: clamped")
                k_new = min(max(k_new, lo), hi)
                if abs(k_new - k) <= 1e-12 * max(abs(k), 1.0):
                    entry["notes"].append(f"`{knob}` is at its bound: the target is out of reach inside it")
                    break
        entry["knobs"] = {knob: (k, k_new)}
        if p != exponent:
            entry["notes"].append(f"exponent from the last two points: {p:.3f} (prior {exponent:g})")
        k = k_new
    return history


__all__ += ["eig_modes", "match_modes", "rule_iterate", "rule_step"]


# ---- FEM results as plots, and lumped-junction EPR (plots.py / analysis/epr_lumped.py) -----------------------------
def _results_png(name: str) -> Path:
    import re  # pylint: disable=import-outside-toplevel

    return REPO / "build" / "plots" / (re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() + ".png")


def _show_png(fig, png, width) -> Path:
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    png = Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=130)
    plt.close(fig)
    display(Image(filename=str(png), width=width))
    return png


def plot_convergence(keeps, png=None, width: int = 760) -> Path | None:
    """The adaptive-pass convergence of kept jobs: ``keeps`` is a kept job folder or ``{label: folder or None}``
    (what ``convergence_md`` takes). Drawn: the criterion per pass with its target, against the mesh size, and the
    eigenmode frequencies per pass. Shows the picture and returns its path (None when nothing is solved)."""
    from quantcore_circuits import plots as P  # pylint: disable=import-outside-toplevel

    items = {k: v for k, v in keeps.items() if v} if isinstance(keeps, dict) else {"job": keeps}
    if not items:
        return None
    src = next(iter(items.values())) if len(items) == 1 else {k: Path(v) for k, v in items.items()}
    try:
        ax = P.plot_convergence(Path(src) if not isinstance(src, dict) else src)
    except ValueError:  # no convergence data in these jobs
        return None
    return _show_png(ax.figure, png or _results_png("convergence_" + "_".join(items)[:60]), width)


def plot_s21_fit(keep, png=None, width: int = 620, **kw) -> Path | None:
    """|S21| with the notch fit(s) of a kept driven job (f0, kappa_ext, Q_i on the panel). ``kw``: ``f_GHz`` / ``s21`` or
    ``job_dir`` (the folder with the raw ``*_SMatrix.s2p``) to draw the data too; the kept results hold the fit only."""
    from quantcore_circuits import plots as P  # pylint: disable=import-outside-toplevel

    if not keep:
        return None
    try:
        ax = P.plot_s21_fit(Path(keep), **kw)
    except ValueError:  # no notch in the sweep
        return None
    return _show_png(ax.figure, png or _results_png("s21_" + Path(keep).name), width)


def plot_epr(res, png=None, width: int = 760) -> Path | None:
    """Participation bars (mode x junction) and the chi matrix of an EPR result (``epr_lumped`` returns one)."""
    from quantcore_circuits import plots as P  # pylint: disable=import-outside-toplevel

    if not res:
        return None
    ax = P.plot_epr(res)
    return _show_png(ax.figure, png or _results_png(f"epr_{res['method']}"), width)


def epr_lumped(method: str = "lom", *, lom=None, keep=None, lj_nH=None, perturbed=None, plot: bool = True,
               compare=None, **kw) -> dict:
    """Energy participation of the lumped junctions, no field integrals (``analysis/epr_lumped.py``); shows the table
    and, with ``plot``, the picture, and returns the EPR-result dict.

    ``method``: ``"lom"`` (``lom``: the LOM result, e.g. ``simulate_lom(...)`` / ``res``), ``"eigenmode-dL"``
    (``keep``: the nominal kept eigenmode job, ``lj_nH``: each junction's L_J, ``perturbed``: ``{junction: [(L_J, job),
    ...]}`` from solves with one junction's L_J changed by a few percent) or ``"energy"`` (``keep``: a job whose
    results hold the solver's pyEPR participations). ``compare``: another EPR result; adds the mode-by-mode table.
    """
    from quantcore_circuits.analysis import epr_lumped as L  # pylint: disable=import-outside-toplevel

    if method == "lom":
        res = L.epr_from_lom(lom, **kw)
    elif method == "eigenmode-dL":
        res = L.eigenmode_dL(Path(keep), lj_nH, {j: [(v, Path(s)) for v, s in runs] for j, runs in perturbed.items()}, **kw)
    elif method == "energy":
        res = L.epr_from_job(Path(keep) / "results" / "results.json", **kw)
    else:
        raise ValueError("method: 'lom', 'eigenmode-dL' or 'energy'")
    display(Markdown(L.epr_md(res)))
    if compare:
        display(Markdown(L.compare_md(res, compare)))
    if plot:
        plot_epr(res)
    return res

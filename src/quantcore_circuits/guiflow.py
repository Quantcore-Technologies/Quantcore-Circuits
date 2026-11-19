"""The KLayout plugin's Simulate / Results / Fab steps as library functions (the CLI and the plugin call these).

* **Subset** (:func:`resolve_selection`, :func:`plan_subset_groups`): for a capacitance analysis (Q3D) the qubits
  among the components selected in KLayout (a selected readout route names its qubit), each with its couplers; the
  resonators are cut to a short stub port (:mod:`quantcore_circuits.sim_tools.subset`). For an eigenmode / driven
  analysis :func:`selection_group`: exactly what is selected (qubit, resonator, feedline, pads), plus the routes that
  join two selected parts and the pads at the ends of a selected line; junctions are lumped L‖C ports, lines leaving
  the box end in 50 Ω. Nothing selected: ``default`` takes the first qubit with a readout; ``whole`` the built-in
  ``chip`` group (slow).
* **Solver settings**: :func:`solver_settings` (fast / accurate / custom), passed to the export; after a solve
  :func:`convergence_feedback` reads AEDT's convergence table and proposes the next run's passes / criterion
  (``build/<name>/convergence.json``, which the plugin's Simulate dialog offers).
* **Automatic** (:func:`run_auto`, ``qcc sim auto``): subset → export → solve in a *new* non-graphical AEDT (never the
  user's open one) → ``loop.analyse`` → the dashboard run state that the plugin's Results tab reads. Progress goes to a
  small status file the plugin polls.
* **Manual** (:func:`export_manual`, ``qcc sim subset``): the job folder plus a README that says what to run and what to
  bring back; :func:`import_results` (``qcc results import``) reads a solved job folder or a ``results.json`` back.
* **Tune** (:func:`propose`, :func:`apply_knobs`; ``qcc results propose`` / ``apply``): ``loop.feedback`` as a
  preview of old → new knob values, and the design with those knobs set.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

RESULTS_FORMAT = """\
results/results.json  (what `qcc results import` reads; every key except "analysis" is optional)

{
  "analysis": "q3d_cmatrix",              # q3d_cmatrix | hfss_eigenmode | eigenmode_epr | hfss_driven | ...
  "group": "gui_sim",                     # the sim group the job simulated (default: the job.json's, else "chip")
  "cmatrix": {                            # capacitance matrix, MAXWELL form, one row / column per metal net
    "labels": ["Q1.island", "Q1.claw_n", "FL"],   # net names: <instance>.island, <instance>.<port>, or a route name
    "unit": "fF",
    "matrix": [[ 85.2, -4.1, -1.2],       # positive diagonal, non-positive off-diagonal; ground = the rest
               [ -4.1, 22.0, -0.3],
               [ -1.2, -0.3, 310.0]]
  },
  "eigenmodes": [                         # linear modes of an eigenmode run (GHz; Q optional)
    {"mode": 1, "f_GHz": 5.31, "Q": 1.2e6},
    {"mode": 2, "f_GHz": 7.04, "Q": 4.0e4}
  ]
}

The labels must be the net names of the design's circuit (`qcc results template DESIGN` writes them, with a zero
matrix, as a starting point). Row / column order is yours. Matrices in "mutual" form (positive off-diagonals) are
converted. A whole solved job folder works too: `qcc results import DESIGN JOB_FOLDER` (it collects the raw AEDT
outputs itself when results/results.json is missing).
"""


# ---- helpers ------------------------------------------------------------------------------------------------------
def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json_path(design) -> Path:
    path = Path(design)
    if path.suffix != ".json":
        raise ValueError(f"{path.name}: the GUI flow needs the design as a .json file (qcc design to-python writes .py)")
    return path


def jobs_root(design) -> Path:
    """``<design folder>/build/jobs``."""
    return Path(design).resolve().parent / "build" / "jobs"


AEDT_PATH_LIMIT = 250  # AEDT's own folders add name + ~70 characters to the job folder path (Windows MAX_PATH is 259)


def aedt_path_too_long(job_dir, analysis: str = "q3d_cmatrix") -> bool:
    """AEDT fails with "Failed to copy local file ... The system cannot find the path specified" when the project's
    ``*.aedtresults`` folders pass Windows' 260-character limit; the job folder name is repeated in them."""
    name = Path(job_dir).name
    return os.name == "nt" and len(str(Path(job_dir).resolve())) + len(name) + 75 > AEDT_PATH_LIMIT


def short_job_dir(design, group: str, analysis: str) -> Path:
    """The job folder: ``<design folder>/build/jobs/<design>_<group>_<analysis>``, or, when that path is too long for
    AEDT, a short one under the temp folder (``qcc_jobs/<design>_<group>_<analysis>``)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    name = f"{load_design(design).name}_{group}_{analysis}"
    job = jobs_root(design) / name
    if aedt_path_too_long(job, analysis):
        job = Path(tempfile.gettempdir()) / "qcc_jobs" / name
    return job


def run_dir(design) -> Path:
    """``<design folder>/build/<name>``: where the GUI flow keeps its run (the sidecar finds ``state.json`` there)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    return Path(design).resolve().parent / "build" / load_design(design).name


# ---- the subset -----------------------------------------------------------------------------------------------------
def _by_selection(design, names, analysis: str) -> bool:  # noqa: ARG001  (design: kept for a later rule)
    """Whether ``names`` are simulated as they are (:func:`selection_group`): eigenmode / driven runs. A capacitance
    run is the qubit subset (:func:`plan_subset_groups`)."""
    from quantcore_circuits.sim_tools.builder import analysis_kind  # pylint: disable=import-outside-toplevel

    return analysis_kind(analysis) in ("eigenmode", "driven")


def junctions(design, names=None) -> dict[str, dict]:
    """The resolved junction of each component that has one (``names``: only those): the sidecar's
    ``instances.<name>.junction`` — ``{"kind", "Lj0_nH", "Cj_fF", "flux_phi0", "asym", "Lj_eff_nH", "source"}`` (the
    LOM's values, which the eigenmode / driven exports put on the lumped sheet)."""
    from quantcore_circuits.assembly.sidecar import instance_junction_entry  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    pdk = get_pdk(d.pdk)
    out = {}
    for n in d.instances if names is None else [n for n in names if n in d.instances]:
        entry = instance_junction_entry(n, d.instances[n], pdk)
        if entry is not None:
            out[n] = entry
    return out


def missing_junctions(design, names=None) -> dict[str, str]:
    """``{name: message}``: the components among ``names`` (None: all) whose junction has no L_J for an eigenmode /
    driven run (no design value and no drawn trilayer junction, or a symmetric SQUID at Φ = ½); the message says where
    to set it (the plugin's pre-check; ``qcc design junctions``)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.fragment import missing_junction_message  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    return {n: missing_junction_message(n, d.instances[n]) if "error" not in j else f"{n}: {j['error']}"
            for n, j in junctions(d, names).items() if j.get("Lj_eff_nH") is None}


def placement_junction(cell: str, params: dict | None = None, pdk=None) -> dict | None:
    """The simulation / LOM junction a new ``cell`` gets when it is placed: ``{"Lj_nH", "Cj_fF", "source"}``, or None
    for a component without a junction, plus ``drawn``: the trilayer junction the cell draws (same keys), or None. A
    drawn trilayer junction gives its PDK-rule value (also a KQC cell left at its default junction: the build draws it
    as the PDK trilayer); a chosen non-trilayer type (KQC Manhattan, Sim, ...) has no PDK value, so it gets the PDK
    nominal SQUID (``"Quantcore Squid"``). The plugin writes
    it into ``design.json`` at placement (the value is a simulation value, fixed per component)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.fragment import (  # pylint: disable=import-outside-toplevel
        cell_params,
        drawn_junction,
        instance_junction,
    )

    d = load_design({"name": "placement", **({"pdk": pdk} if pdk else {}),
                     "instances": {"X": {"cell": cell, "place": {"at": [0, 0]}, "params": dict(params or {})}}})
    ej = instance_junction("X", d.instances["X"], d.pdk)
    if ej is None or ej.kind is None:
        return None
    shown = drawn_junction(cell_params(d.instances["X"]), getattr(d.pdk, "junction", None))
    drawn = None if shown is None else {"Lj_nH": float(shown[0]), "Cj_fF": float(shown[1]), "source": shown[2]}
    if ej.lj0_nH is not None:
        return {"Lj_nH": float(ej.lj0_nH), "Cj_fF": float(ej.cj_fF), "source": "drawn trilayer junction, PDK rule",
                "drawn": drawn}
    nominal = drawn_junction({"junction_type": "Quantcore Squid"})
    if nominal is None:
        return None
    return {"Lj_nH": float(nominal[0]), "Cj_fF": float(nominal[1]), "source": "PDK nominal SQUID", "drawn": drawn}


def resolve_selection(design, names, default: bool = False) -> tuple[list[str], list[str]]:
    """``(qubits, notes)`` from ``names`` (instance and route names, e.g. what is selected in KLayout). A qubit stands for
    itself, a readout route for its qubit; pads, couplers and other lines come in with their qubit and are ignored.
    ``default``: with no qubit in ``names``, the first qubit that has a readout resonator."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.subset import has_junction, readout_of  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    qubits_all = sorted((n for n in d.instances if has_junction(d, n)), key=_natural)
    chosen, notes = [], []
    for n in names:
        if n in d.instances and n in qubits_all:
            chosen.append(n)
        elif n in d.routes:
            owner = next((q for q in qubits_all if readout_of(d, q) == n), None)
            if owner:
                chosen.append(owner)
            else:
                notes.append(f"{n}: not a readout line of a qubit; it comes in with its qubit if it needs to")
        elif n in d.instances:
            notes.append(f"{n}: not a qubit; it comes in with its qubit if it needs to")
        else:
            notes.append(f"{n}: not in the design")
    chosen = list(dict.fromkeys(chosen))
    if not chosen and default:
        with_ro = [q for q in qubits_all if readout_of(d, q)]
        pick = (with_ro or qubits_all)[:1]
        if pick:
            notes.append(f"default subset: {pick[0]} with its readout")
            chosen = pick
    return chosen, notes


def _natural(name: str):
    import re  # pylint: disable=import-outside-toplevel

    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def plan_subset_groups(design, qubits, name: str = "gui_sim", margin_um: float = 300.0, analysis: str = "q3d_cmatrix",
                       split: str = "auto"):
    """``(group names, {group: spec dict}, SubsetGroup plan)`` for ``qubits``; the design file is not changed."""
    from quantcore_circuits.designer import Designer  # pylint: disable=import-outside-toplevel

    d = Designer.load(design, autosave=False)
    names = d.sim_subset(name, qubits=list(qubits), margin_um=margin_um, analyses=[analysis], split=split)
    return names, {g: d.data["sim_groups"][g] for g in names}, d.subset_plan


def write_groups(design, specs: dict, prefix: str = "gui_sim") -> bool:
    """Put the sim groups ``specs`` into the design.json (only that key is touched) and drop the earlier ``prefix``
    groups that are not in ``specs``. Returns whether the file changed."""
    path = _json_path(design)
    data = json.loads(path.read_text(encoding="utf-8"))
    groups = data.setdefault("sim_groups", {})
    before = json.dumps(groups, sort_keys=True)
    for g in [g for g in groups if (g == prefix or g.startswith(prefix + "_")) and g not in specs]:
        del groups[g]
    groups.update(specs)
    if json.dumps(groups, sort_keys=True) == before:
        return False
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def selection_group(design, names, analysis: str = "hfss_eigenmode", margin_um: float = 300.0) -> tuple[dict, list[str]]:
    """The sim group of exactly the selected components (``names``: instances and routes) for ``analysis``: plus the
    routes that join two selected parts (a hanger from a selected qubit onto a selected line counts) and the
    instances at the ends of a selected route (a feedline's bond pads). Returns ``(spec, notes)``."""
    from quantcore_circuits.design import load_design, split_port_ref  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design.schema import FreeEnd, HangerEnd  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    notes, sel = [], []
    for n in names:
        if n in d.instances or n in d.routes:
            sel.append(n)
        else:
            notes.append(f"{n}: not in the design")
    if not sel:
        raise ValueError("nothing to simulate: select components (KLayout's select tool) or choose the whole chip")

    def ends(route):
        out = []
        for e in (route.from_, route.to):
            if isinstance(e, str):
                out.append(split_port_ref(e)[0])
            elif isinstance(e, HangerEnd):
                out.append(e.hanger)
            elif not isinstance(e, FreeEnd):
                out.append(None)
        return out

    chosen = set(sel)
    for rname, route in d.routes.items():  # routes joining selected parts
        e = ends(route)
        if rname not in chosen and e and all(x in chosen for x in e):
            sel.append(rname)
            chosen.add(rname)
            notes.append(f"{rname}: joins {' and '.join(e)}, comes in")
    for rname in [n for n in sel if n in d.routes]:  # the instances at a selected route's ends (pads)
        for x in ends(d.routes[rname]):
            if x and x in d.instances and x not in chosen:
                sel.append(x)
                chosen.add(x)
                notes.append(f"{x}: at an end of {rname}, comes in")
    return {"select": sel, "margin_um": float(margin_um), "analyses": [analysis]}, notes


SOLVER_MODES = ("fast", "accurate", "custom")


def solver_settings(analysis: str, mode: str = "fast", custom: dict | None = None) -> tuple[bool, dict]:
    """``(fast, settings)`` for the export: ``fast`` = :data:`~quantcore_circuits.sim_tools.export.FAST_SETTINGS`
    (minutes, not converged), ``accurate`` = the analysis defaults (``DEFAULT_SETTINGS``), ``custom`` = the defaults
    with ``custom`` on top (e.g. what :func:`convergence_feedback` proposed, or the plugin's Settings)."""
    if mode not in SOLVER_MODES:
        raise ValueError(f"solver mode {mode!r}: one of {', '.join(SOLVER_MODES)}")
    if mode == "fast":
        return True, {}
    return False, dict(custom or {}) if mode == "custom" else {}


_CRITERION = {"q3d_cmatrix": "percent_error", "hfss_eigenmode": "max_delta_f", "eigenmode_epr": "max_delta_f",
              "hfss_driven": "max_delta_s"}


def convergence_feedback(job_dir) -> dict:
    """What AEDT's adaptive meshing did in a solved job and what the next run should use: ``{"analysis",
    "converged", "passes", "last_delta", "target", "settings" (the job's), "next" (proposed settings, empty when it
    converged), "message"}``. Not converged: one and a half times the passes (at least +4), and the criterion kept;
    converged in fewer passes than allowed: the settings stay. Never raises (a job without a convergence table says
    so)."""
    from quantcore_circuits.analysis.results import collect_results, parse_convergence  # noqa  pylint: disable=C0415

    job_dir = Path(job_dir)
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"converged": None, "next": {}, "message": f"{job_dir.name}: no job.json"}
    analysis, settings = job.get("analysis", ""), dict(job.get("settings") or {})
    tables = sorted(job_dir.glob("*_project_convergence.txt"))
    try:
        conv = parse_convergence(tables[0]) if tables else (collect_results(job_dir).get("convergence") or {})
    except Exception as e:  # noqa: BLE001
        conv = {"error": f"{type(e).__name__}: {e}"}
    passes = conv.get("passes") or []
    deltas = [x for x in (conv.get("delta") or []) if x is not None]
    key = _CRITERION.get(analysis)
    out = {"analysis": analysis, "job": str(job_dir), "converged": conv.get("converged"), "passes": len(passes),
           "last_delta": deltas[-1] if deltas else None, "target": conv.get("target") or settings.get(key),
           "settings": settings, "next": {}}
    if not passes:
        out["message"] = f"{job_dir.name}: no convergence table (did the solve finish?)"
        return out
    if not conv.get("converged") and out["last_delta"] is not None and out["target"] is not None and             out["last_delta"] <= float(out["target"]):  # Q3D's table has no "Converged" line: Δ below the target
        out["converged"] = conv["converged"] = True
    if conv.get("converged"):
        out["message"] = (f"converged in {len(passes)} passes (last Δ {out['last_delta']:.3g} vs "
                          f"{out['target']}): the settings stay")
        return out
    max_p = int(settings.get("maximum_passes") or len(passes))
    nxt = {"maximum_passes": max(max_p + 4, int(round(max_p * 1.5)))}
    if key and settings.get(key) is not None:
        nxt[key] = settings[key]
    out["next"] = nxt
    last = f"{out['last_delta']:.3g}" if out["last_delta"] is not None else "?"
    out["message"] = (f"NOT converged after {len(passes)} passes (last Δ {last} vs target {out['target']}): raise the "
                      f"maximum passes (e.g. {nxt['maximum_passes']}) in AEDT, solve there and import the job folder")
    return out


def pick_groups(design, names=None, default: bool = False, whole: bool = False, name: str = "gui_sim",
                margin_um: float = 300.0, analysis: str = "q3d_cmatrix", write: bool = True) -> dict:
    """Decide what to simulate and (``write``) store the sim groups in the design.json. Returns ``{"groups": [...],
    "whole": bool, "notes": [...], "describe": markdown}``."""
    if whole:
        return {"groups": ["chip"], "whole": True, "notes": ["the whole chip: slow and memory hungry"], "describe": ""}
    if names and _by_selection(design, names, analysis):
        spec, notes = selection_group(design, names, analysis, margin_um)
        group = f"{name}_sel"
        if write:
            write_groups(design, {group: spec}, name)
        return {"groups": [group], "whole": False, "notes": notes, "specs": {group: spec},
                "describe": "renders: " + ", ".join(spec["select"])}
    qubits, notes = resolve_selection(design, names or [], default=default)
    if not qubits:
        raise ValueError("no qubit to simulate: a Q3D run is a qubit's islands and couplers; select a qubit, or choose "
                         "eigenmode for lines / resonators / pads (or the default subset / the whole chip)\n"
                         + "\n".join(notes))
    groups, specs, plan = plan_subset_groups(design, qubits, name, margin_um, analysis)
    if write:
        write_groups(design, specs, name)
    from quantcore_circuits.sim_tools.subset import describe  # pylint: disable=import-outside-toplevel

    notes += [n for sg in plan for n in sg.notes]
    return {"groups": groups, "whole": False, "qubits": qubits, "notes": list(dict.fromkeys(notes)),
            "describe": describe(plan)}


# ---- status file (the plugin polls it) --------------------------------------------------------------------------------
class Status:
    """``{"state": running|done|failed, "step", "n", "of", "message", ...}`` written atomically."""

    def __init__(self, path, steps: int = 4):
        self.path = Path(path) if path else None
        self.data = {"state": "running", "step": "starting", "n": 0, "of": steps, "message": "", "started": now()}
        self.write()

    def set(self, **kw) -> None:
        self.data.update(kw)
        self.write()

    def step(self, n: int, name: str, message: str = "") -> None:
        self.set(n=n, step=name, message=message)

    def write(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


# ---- automatic -------------------------------------------------------------------------------------------------------
def run_auto(design, names=None, default: bool = False, whole: bool = False, analysis: str = "q3d_cmatrix",
             name: str = "gui_sim", margin_um: float = 300.0, aedt: str | None = "batch", fast: bool = True,
             timeout: float = 3600.0, status=None, progress: float = 10.0, readout: bool = True, say=print,
             settings: dict | None = None) -> dict:
    """Subset → export → solve in a new AEDT → analyse. Returns ``{"groups", "jobs", "seconds", "rows", "run_dir"}``;
    raises on a failed step (the ``status`` file then says which)."""
    from quantcore_circuits.circuit.consensus import report_markdown  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation, export_job, hfss  # pylint: disable=C0415
    from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=import-outside-toplevel

    st = status if isinstance(status, Status) else Status(status, steps=4)
    t0 = time.time()
    try:
        design = _json_path(design).resolve()
        if find_ansys_executable() is None:
            raise RuntimeError("AEDT 2024 R1 or newer was not found (set QCC_ANSYS_EXECUTABLE); use Export sim job "
                               "and solve it on a machine that has AEDT")
        st.step(1, "subset", "choosing what to simulate")
        plan = pick_groups(design, names, default, whole, name, margin_um, analysis)
        for n in plan["notes"]:
            say(f"note: {n}")
        groups = plan["groups"]
        say(f"simulating {', '.join(groups)} ({analysis}, {'fast' if fast else 'full'} settings) in a new "
            f"{'non-graphical ' if (aedt or 'batch') == 'batch' else ''}AEDT")
        root = jobs_root(design)
        jobs = []
        for i, g in enumerate(groups):
            st.step(2, "solve", f"{g} ({i + 1}/{len(groups)}): export, then solve in AEDT")
            job_dir = short_job_dir(design, g, analysis)
            if not str(job_dir).startswith(str(root)):
                say(f"note: the design folder is too deep for AEDT (Windows paths over 260 characters); the job goes "
                    f"to {job_dir}")
            if aedt_path_too_long(job_dir, analysis):
                raise RuntimeError(f"the path {job_dir} is too long for AEDT; move the design to a shorter folder")
            # export, check the geometry AEDT would get (touching nets, junction ports without a polygon, metal to the
            # box top), and only then solve: a broken export stops here instead of after minutes in AEDT
            setup = build_simulation(design, g, analysis)
            export_job(setup, job_dir, overwrite=True, fast=fast, **(settings or {}))
            check_export(job_dir, say)
            r = hfss.solve_job(job_dir, aedt=aedt, timeout=timeout, progress=progress)
            say(f"{g}: {'ok' if r.ok else 'FAILED'} in {r.seconds:.0f} s (log {r.log})")
            fb = convergence_feedback(job_dir)
            say(f"{g}: mesh {fb['message']}")
            save_feedback(design, fb)
            if not r.ok:
                raise RuntimeError(f"the AEDT solve of {g} failed or timed out; see {r.log}")
            jobs.append(job_dir)
        out = analyse_jobs(design, jobs, st=st, readout=readout, source="auto", say=say)
        out.update(groups=groups, seconds=round(time.time() - t0, 1))
        st.set(state="done", n=4, step="done", message=out["summary"], finished=now(), rows=out["rows"])
        say(report_markdown(out.pop("_rows"), "Consensus"))
        return out
    except BaseException as e:  # noqa: BLE001
        st.set(state="failed", message=f"{type(e).__name__}: {e}", finished=now())
        raise


def check_export(job_dir, say=print, strict: bool = True) -> dict:
    """:func:`~quantcore_circuits.sim_tools.geometry_check.check_job` on an exported job: warnings become notes; errors
    (what AEDT would reject or solve wrongly) raise ``RuntimeError`` (``strict``) or are printed as warnings."""
    from quantcore_circuits.sim_tools.geometry_check import check_job  # pylint: disable=import-outside-toplevel

    job_dir = Path(job_dir)
    try:
        rep = check_job(job_dir)
    except Exception as e:  # noqa: BLE001  (the check must never block on its own failure)
        say(f"note: {job_dir.name}: geometry check skipped ({type(e).__name__}: {e})")
        return {"errors": [], "warnings": []}
    for w in rep["warnings"]:
        say(f"note: {job_dir.name}: {w}")
    if rep["errors"]:
        text = "; ".join(rep["errors"][:6])
        if strict:
            raise RuntimeError(f"{job_dir.name}: the exported geometry would fail in AEDT, so nothing was solved: "
                               f"{text} (scripts/check_sim_export.py check \"{job_dir}\")")
        for e in rep["errors"]:
            say(f"warning: {job_dir.name}: {e}")
    return rep


def save_feedback(design, feedback: dict) -> Path:
    """``build/<name>/convergence.json``: the last solve's convergence and the proposed next settings, per analysis
    (the plugin's Simulate dialog shows it and can use the proposal)."""
    path = run_dir(design) / "convergence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[feedback.get("analysis") or "unknown"] = {**feedback, "when": now()}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def analyse_jobs(design, jobs, st: Status | None = None, readout: bool = True, source: str = "auto", say=print) -> dict:
    """``loop.analyse`` of the whole-chip circuit filled from ``jobs`` (subset jobs fill their own components, the rest
    keeps the layout's estimates), recorded in ``<design>/build/<name>/state.json`` and ``flow.json``."""
    from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import design_hash, load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.track import Run  # pylint: disable=import-outside-toplevel

    if st:
        st.step(3, "analyse", "extracting values, LOM and QuTiP, comparing with the targets")
    rd = run_dir(design)
    run = Run(design, rd)
    jobs = [Path(j) for j in jobs]
    an = loop.analyse(design, jobs if len(jobs) > 1 else jobs[0], "chip", run=run, readout=readout, out_dir=rd)
    d = load_design(design)
    rows = [{"param": r.param, "target": r.target, "tol": r.tol, "value": r.chosen, "by": r.chosen_by,
             "status": r.status, "unit": r.unit} for r in an.rows if r.target is not None or r.chosen is not None]
    record = {"schema": "qcc-flow/0.1", "when": now(), "source": source, "jobs": [str(j) for j in jobs],
              "group": "chip", "design_hash": design_hash(d), "goal": an.goal.get("summary")}
    (rd / "flow.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for note in an.filled.notes:
        say(f"note: {note}")
    saved = save_results_copies(design, jobs, say=say) if source == "auto" else []
    return {"run_dir": str(rd), "jobs": [str(j) for j in jobs], "rows": rows, "summary": an.goal.get("summary", ""),
            "_rows": an.rows, "results_files": [str(p) for p in saved]}


def save_results_copies(design, jobs, say=print) -> list[Path]:
    """Keep what a solve returned under a name that says what it is: ``build/<name>/<name>_<group>_results.json`` (a
    copy of the job's ``results/results.json``; the plugin's Simulate > Open results file… reads it back)."""
    out = []
    rd = run_dir(design)
    for job in jobs:
        job = Path(job)
        src = job / "results" / "results.json"
        if not src.exists():
            continue
        group = ""
        for f in (job / "job.json", src):
            try:
                group = str(json.loads(f.read_text(encoding="utf-8")).get("group") or "")
            except (OSError, ValueError):
                group = ""
            if group:
                break
        group = "".join(c if c.isalnum() or c in "-_." else "_" for c in (group or job.name))
        dest = rd / f"{rd.name}_{group}_results.json"
        try:
            rd.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
        except OSError as e:
            say(f"note: could not save {dest.name}: {e}")
            continue
        say(f"results saved: {dest}")
        out.append(dest)
    return out


def flow_record(design) -> dict | None:
    """What the last automatic run / import analysed (``flow.json``), plus whether the design changed since."""
    from quantcore_circuits.design import design_hash, load_design  # pylint: disable=import-outside-toplevel

    path = run_dir(design) / "flow.json"
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["stale"] = rec.get("design_hash") != design_hash(load_design(design))
    return rec


# ---- manual --------------------------------------------------------------------------------------------------------
README = """\
# Simulation job: {design} / {group} ({analysis})

Made by Quantcore (`qcc sim subset`) on {when}. The design is `{design}`, the box simulates: {select}.
Settings: {settings}.

## Solve it

**On this machine, in AEDT {aedt}:**

1. Double-click `simulation.bat` (Windows) or run `bash simulation.sh`. It starts a new non-graphical AEDT, solves
   the job and writes `results/results.json`. (Or: `qcc hfss solve "{job}"`.)
2. By hand: open AEDT, *Tools > Run Script...* and run `scripts/qcc_solve.py` with the argument
   `{sim}.json` (the script is in the `scripts` folder; it imports the geometry, adds the ports, solves and
   exports the results next to it). `scripts/qcc_render.py` does the same without solving: it saves the project so
   you can look at the mesh and ports first.

**A finer solve:** open `{sim}_project.aedt` in AEDT, change the setup (passes, convergence, mesh), solve, then run
`scripts/qcc_collect.py` there (*Tools > Run Script...*, no arguments): it exports what you solved (results and the
convergence table) into this folder without solving again or saving. Or close the project and run
`qcc hfss collect "{job}"`. Then import the folder (below).

**On another machine:** copy this whole folder over, run `scripts/qcc_solve.py` in AEDT as above (AEDT 2024 R1 or newer;
quantcore-circuits is only needed for `simulation.bat`'s last line, the results collection), and bring the folder back.

## Bring back

The whole job folder (you can leave out the `*.aedtresults` folders, they are large), or at least:

- `results/results.json` (written by `simulation.bat` / `qcc results collect`), or
- `{sim}_project_results.json`, `{sim}_project_qcc.json` and the `.eig` / `.sNp` files AEDT exported (then Quantcore
  collects the results itself).

Then in KLayout: *Quantcore > Simulate > Import results...* and pick the folder or the `results.json`, or on the
command line: `qcc results import "{design_path}" "<folder or results.json>"`.

## Your own results script

Any extraction that writes this JSON works (see `results_template.json` here for the net names of this job):

```
{fmt}
```
"""


def export_manual(design, names=None, default: bool = False, whole: bool = False, out=None,
                  analysis: str = "q3d_cmatrix", name: str = "gui_sim", margin_um: float = 300.0, fast: bool = True,
                  write_group: bool = True, say=print, settings: dict | None = None,
                  group: str | None = None) -> list[Path]:
    """Write the job folder(s) of the subset (no solve): KQC export, AEDT scripts, ``job.json``, ``README.md`` and
    ``results_template.json``. ``out``: the folder for one box, or the parent of several. ``group``: a saved ``sim_groups``
    entry, exported as it is (nothing is written to the design). Returns the job folders."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.aedt_scripts import write_scripts  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.export import tighter_or_equal  # noqa: F401  pylint: disable=C0415

    design = Path(design).resolve()
    is_json = design.suffix == ".json"
    d = load_design(design)
    if group:
        if group not in d.sim_groups:
            raise ValueError(f"no sim group {group!r}; available: {sorted(d.sim_groups)}")
        groups, source, notes = [group], d, []
    elif whole:
        groups, source = ["chip"], design
        notes = ["the whole chip: slow and memory hungry"]
    else:
        if names and _by_selection(design, names, analysis):
            spec, notes = selection_group(design, names, analysis, margin_um)
            groups, specs = [f"{name}_sel"], {f"{name}_sel": spec}
        else:
            qubits, notes = resolve_selection(design, names or [], default=default)
            if not qubits:
                raise ValueError("no qubit to simulate: name a qubit (--instances Q1,R1), or use --default / --whole")
            groups, specs, plan = plan_subset_groups(design, qubits, name, margin_um, analysis)
            notes += [n for sg in plan for n in sg.notes]
        if write_group and is_json:
            write_groups(design, specs, name)
            source = design
        else:  # a .py design, or no write: simulate an in-memory copy with the groups
            data = d.to_json_dict()
            data["sim_groups"].update(specs)
            source = load_design(data)
    jobs = []
    for g in groups:
        job = (Path(out) if out and len(groups) == 1 else (Path(out) if out else jobs_root(design)) /
               f"{d.name}_{g}_{analysis}")
        setup = build_simulation(source, g, analysis)
        export_job(setup, job, overwrite=True, fast=fast, **(settings or {}))
        write_scripts(job)
        job = job.resolve()
        check_export(job, say, strict=False)
        meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
        exe = find_ansys_executable()
        (job / "README.md").write_text(README.format(
            design=d.name, design_path=design, group=g, analysis=analysis, when=now(), job=job,
            select=", ".join(meta.get("select") or []) or "the whole chip", sim=meta["simulation_name"],
            settings=", ".join(f"{k} {v}" for k, v in (meta.get("settings") or {}).items()) or "defaults",
            aedt=("(found here: " + str(exe) + ")") if exe else "(not found on this machine)", fmt=RESULTS_FORMAT),
            encoding="utf-8")
        (job / "results_template.json").write_text(
            json.dumps(results_template(source, g, analysis, meta), indent=2) + "\n", encoding="utf-8")
        say(f"job {job}")
        if aedt_path_too_long(job, analysis):  # the automatic run relocates such a job; a manual export only warns
            say(f"warning: the job folder path is too long for AEDT on Windows ({len(str(job))} characters; AEDT's "
                "result folders would pass 260): solve it from a shorter folder, e.g. "
                f"{Path(tempfile.gettempdir()) / 'qcc_jobs' / job.name}")
        jobs.append(job)
    for n in notes:
        say(f"note: {n}")
    return jobs


def preview_groups(design, names=None, default: bool = False, whole: bool = False, analysis: str = "q3d_cmatrix",
                   margin_um: float = 300.0, name: str = "gui_sim", group: str | None = None) -> dict:
    """What an export of the same arguments renders, for drawing it in KLayout (``qcc sim preview``): per box its
    rectangle, the components and routes in it, and every port (50 Ω edge ports, cut stubs, junction ports) with its
    position. It runs :func:`~quantcore_circuits.sim_tools.build_simulation` exactly as :func:`export_manual` does (same
    group, same box, same ports; ``export_job`` then writes them as files), and writes nothing.

    ``group`` previews a saved ``sim_groups`` entry as it is (``analysis`` None: its first analysis). Otherwise the
    group comes from ``names`` / ``default`` / ``whole`` and ``analysis`` like in :func:`export_manual`."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.builder import CHIP_GROUP, group_spec  # pylint: disable=import-outside-toplevel

    design = Path(design).resolve()
    d = load_design(design)
    notes: list[str] = []
    if group:
        if group not in d.sim_groups and group != CHIP_GROUP:
            raise ValueError(f"no sim group {group!r}; available: {sorted(d.sim_groups)}")
        groups, source = [group], d
        if not analysis:
            analysis = (group_spec(d, group).analyses or ["eigenmode_epr"])[0]
    elif whole:
        groups, source = [CHIP_GROUP], d
        notes.append("the whole chip: slow and memory hungry")
    else:
        if names and _by_selection(design, names, analysis):
            spec, notes = selection_group(design, names, analysis, margin_um)
            groups, specs = [f"{name}_sel"], {f"{name}_sel": spec}
        else:
            qubits, notes = resolve_selection(design, names or [], default=default)
            if not qubits:
                raise ValueError("no qubit to simulate: name a qubit (--instances Q1,R1), or use --default / --whole")
            groups, specs, plan = plan_subset_groups(design, qubits, name, margin_um, analysis)
            notes += [n for sg in plan for n in sg.notes]
        data = d.to_json_dict()
        data["sim_groups"].update(specs)  # in memory: the design file is not touched
        source = load_design(data)
    out = []
    for g in groups:
        spec = group_spec(source, g)
        rec = {"name": g, "analysis": analysis, "select": list(spec.select), "margin_um": spec.margin_um,
               "group_ports": dict(spec.ports), "ports": [], "routes": [], "notes": []}
        if g == CHIP_GROUP and g not in source.sim_groups:  # the die: no cut, no ports, nothing to build here
            rec.update(box=[float(v) for v in source.chip.box], whole=True, select=[*source.instances, *source.routes])
        else:
            setup = build_simulation(source, g, analysis)
            box = setup.box
            data = {row["number"]: row for row in setup.simulation.get_port_data()}  # what the exported KQC json holds
            ports = []
            for info in setup.ports:
                row = data.get(info.number, {})
                at, gnd = row.get("signal_location"), row.get("ground_location")
                ports.append({"number": info.number, "kind": info.kind, "name": info.name, "net": info.excitation,
                              "at": [round(at[0], 3), round(at[1], 3)] if at else None,
                              "ground": [round(gnd[0], 3), round(gnd[1], 3)] if gnd else None,
                              "junction": bool(row.get("junction")),
                              "polygon": [[round(q[0], 3), round(q[1], 3)] for q in row.get("polygon", [])]})
            rec.update(box=[box.left, box.bottom, box.right, box.top], whole=False, ports=ports,
                       routes=list(setup.routes), notes=list(setup.notes))
        out.append(rec)
    return {"design": d.name, "analysis": analysis, "groups": out, "notes": list(dict.fromkeys(notes))}


def results_template(design, group: str = "chip", analysis: str = "q3d_cmatrix", meta: dict | None = None) -> dict:
    """A ``results.json`` skeleton: the net names of the design's circuit, a zero matrix (see :data:`RESULTS_FORMAT`)."""
    from quantcore_circuits.circuit.derive import circuit_from_design  # pylint: disable=import-outside-toplevel

    nets = list((meta or {}).get("nets", {}).values())
    if not nets:
        model = circuit_from_design(design, group)
        nets = [n for node, spec in model.nodes.items() if not spec.ground for n in spec.nets]
    nets = list(dict.fromkeys(nets))
    out = {"analysis": analysis, "group": group,
           "cmatrix": {"labels": nets, "unit": "fF", "matrix": [[0.0] * len(nets) for _ in nets]}}
    if analysis in ("hfss_eigenmode", "eigenmode_epr"):
        out["eigenmodes"] = [{"mode": 1, "f_GHz": 0.0, "Q": None}]
    return out


# ---- import --------------------------------------------------------------------------------------------------------
def validate_results(design, results: dict, group: str | None = None) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` of a results dict against the design's circuit nets."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.circuit.derive import circuit_from_design  # pylint: disable=import-outside-toplevel

    errors, warns = [], []
    if not isinstance(results, dict) or "analysis" not in results:
        return ['no "analysis" key: not a results.json (qcc results template DESIGN shows the format)'], warns
    cm = results.get("cmatrix")
    if cm is not None:
        labels = cm.get("labels") or []
        try:
            mat = np.asarray(cm.get("matrix"), dtype=float)
        except (TypeError, ValueError):
            return ['cmatrix.matrix is not a number matrix'], warns
        if mat.ndim != 2 or mat.shape[0] != mat.shape[1] or mat.shape[0] != len(labels):
            errors.append(f"cmatrix: {len(labels)} labels but the matrix is {mat.shape[0]}×{mat.shape[-1]}"
                          if mat.ndim == 2 else "cmatrix.matrix must be a square matrix")
        else:
            if (np.diag(mat) <= 0).any():
                warns.append("cmatrix: a diagonal entry is not positive (is this the Maxwell matrix, in fF?)")
            if mat.size and np.abs(mat - mat.T).max() > 1e-3 * (np.abs(mat).max() or 1.0):
                warns.append("cmatrix is not symmetric")
            if cm.get("unit", "fF") != "fF":
                warns.append(f"cmatrix.unit is {cm.get('unit')!r}; Quantcore reads fF")
        try:
            model = circuit_from_design(design, group or results.get("group") or "chip")
            known = {n for spec in model.nodes.values() for n in spec.nets} | set(
                load_routes(design))
            hit = [lab for lab in labels if lab in known]
            if labels and not hit:
                errors.append("none of the cmatrix labels is a net of this design; expected names like "
                              f"{sorted(known)[:6]} (qcc results template DESIGN lists them)")
            elif len(hit) < len(labels):
                warns.append("cmatrix labels not in the design (ignored): "
                             f"{[lab for lab in labels if lab not in known]}")
        except Exception as e:  # noqa: BLE001
            warns.append(f"could not check the net names ({type(e).__name__}: {e})")
    modes = results.get("eigenmodes")
    if modes is not None and not all(isinstance(m, dict) and "f_GHz" in m for m in modes):
        errors.append('eigenmodes must be a list of {"f_GHz": ..., "Q": ...}')
    if cm is None and not modes and not results.get("sparams") and not results.get("epr"):
        errors.append("no cmatrix, eigenmodes, epr or sparams in the results: nothing to read")
    return errors, warns


def load_routes(design) -> list[str]:
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    return list(load_design(design).routes)


def stage_import(design, source, group: str | None = None) -> tuple[Path, list[str], list[str]]:
    """Make ``source`` (a solved job folder, its results/ folder or a results.json) an analysable job folder:
    ``(job dir, errors, warnings)``. A folder without ``results/results.json`` is collected from its raw AEDT outputs; a
    loose results file is copied into ``<design folder>/build/jobs/<design>_imported_<stem>/``."""
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import design_hash, load_design  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    src = Path(source)
    if not src.exists():
        return src, [f"{src} does not exist"], []
    if src.is_file() and src.parent.name == "results" and (src.parent.parent / "job.json").exists():
        src = src.parent.parent
    warns: list[str] = []
    if src.is_dir() and src.name == "results" and (src.parent / "job.json").exists():
        src = src.parent
    if src.is_dir():
        res_file = src / "results" / "results.json"
        raw = [p for pat in ("*_project_results.json", "*_project_qcc.json", "*_project_convergence.txt", "*.eig",
                             "*.s*p") for p in src.glob(pat)]
        stale = res_file.exists() and raw and max(p.stat().st_mtime for p in raw) > res_file.stat().st_mtime
        if not res_file.exists() or stale:  # e.g. re-exported after a finer solve in AEDT (scripts/qcc_collect.py)
            try:
                collect_results(src)
            except Exception as e:  # noqa: BLE001
                return src, [f"{src}: no results/results.json and the raw outputs could not be read ({e})"], []
            if stale:
                warns.append(f"{src.name}: read again from the AEDT outputs (newer than results/results.json)")
        job_dir = src
    else:
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except ValueError as e:
            return src, [f"{src.name} is not JSON ({e})"], []
        job_dir = jobs_root(design) / f"{d.name}_imported_{src.stem}"
        (job_dir / "results").mkdir(parents=True, exist_ok=True)
        data.setdefault("group", group or "chip")
        (job_dir / "results" / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        (job_dir / "job.json").write_text(json.dumps({
            "schema": "qcc-job/0.1", "design": d.name, "design_hash": design_hash(d), "group": data["group"],
            "analysis": data.get("analysis"), "imported_from": str(src.resolve()), "created": now(),
            "status": "imported"}, indent=2) + "\n", encoding="utf-8")
    results = json.loads((job_dir / "results" / "results.json").read_text(encoding="utf-8"))
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8")) if (job_dir / "job.json").exists() else {}
    errors, w = validate_results(design, results, group or job.get("group"))
    warns += w
    if job.get("design") and job["design"] != d.name:
        warns.append(f"the job was made for the design {job['design']!r}, this is {d.name!r}")
    ours = design_hash(d)
    if job.get("design_hash") and job["design_hash"] not in (ours,) and job.get("group_hash") != ours:
        warns.append("the design has changed since this job was exported (the values may not match the layout)")
    grp = group or results.get("group") or job.get("group")
    if grp and grp != "chip" and grp not in d.sim_groups:
        warns.append(f"sim group {grp!r} is not in this design; its values are used for the whole chip")
    return job_dir, errors, warns


def import_results(design, sources, group: str | None = None, readout: bool = True, say=print) -> dict:
    """Read solved job folders / results files back: validate, then :func:`analyse_jobs`."""
    jobs, all_warns = [], []
    for s in sources:
        job_dir, errors, warns = stage_import(design, s, group)
        if errors:
            raise ValueError("\n".join(errors))
        all_warns += warns
        jobs.append(job_dir)
    for w in all_warns:
        say(f"warning: {w}")
    for job_dir in jobs:  # the convergence of what was imported (a finer solve made in AEDT, too)
        fb = convergence_feedback(job_dir)
        if fb.get("converged") is not None:
            say(f"{Path(job_dir).name}: mesh {fb['message']}")
            save_feedback(design, fb)
    out = analyse_jobs(design, jobs, readout=readout, source="import", say=say)
    out["warnings"] = all_warns
    return out


# ---- tune --------------------------------------------------------------------------------------------------------
def _diff(a, b, path=()):
    """Leaf changes between two JSON-like values: ``[(path, old, new)]``."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in dict.fromkeys([*a, *b]):
            if k not in a or k not in b:
                out.append(((*path, k), a.get(k), b.get(k)))
            else:
                out += _diff(a[k], b[k], (*path, k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [c for i, (x, y) in enumerate(zip(a, b)) for c in _diff(x, y, (*path, i))]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if abs(a - b) <= 1e-9 * max(1.0, abs(a)) else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


def propose(design, jobs=None, out=None, say=print) -> dict:
    """``loop.analyse`` + ``loop.feedback``: the next revision as a preview. ``jobs`` None: the last run's jobs
    (``flow.json``), else the layout's estimates. Returns ``{"tunable", "message", "knobs": [{knob, old, new}],
    "moved": [...], "predicted": {...}, "objective", "revision", "basis", "notes": [...]}``; ``out`` also gets it as
    JSON. Every qubit with a LOM model and a λ/4 or λ/2 readout pair is tuned; ``notes`` say what is not and why. The
    revision is written but not built (Apply rebuilds)."""
    from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.optimise import knob_path  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.track import Run  # pylint: disable=import-outside-toplevel

    rd = run_dir(design)
    rec = flow_record(design)
    if jobs is None and rec and rec.get("jobs"):
        jobs = [j for j in rec["jobs"] if Path(j).exists()] or None
    run = Run(design, rd)
    basis = ("the FEM results of " + ", ".join(Path(j).name for j in jobs)) if jobs else "the layout's own estimates"
    an = loop.analyse(design, (jobs if len(jobs) > 1 else jobs[0]) if jobs else None, "chip", run=run,
                      readout=False, out_dir=rd)
    res = {"tunable": False, "message": "", "knobs": [], "moved": [], "predicted": {}, "objective": None,
           "revision": None, "basis": basis, "stale": bool(rec and rec.get("stale")), "notes": []}
    if not any(r.target is not None for r in an.rows):
        res["message"] = "There are no targets to tune towards: set targets (f_q, alpha, f_r, g) for the qubit and resonator."
    elif not an.filled.pairs:
        res["message"] = ("Nothing can be tuned automatically yet: no qubit has a readout resonator in the circuit (a "
                          "lambda/4 or lambda/2 line on a coupler of one qubit). Change the layout by hand and re-run "
                          "the simulation.")
    else:
        try:
            prop, rev, _ = loop.feedback(an, run, design, build_revision=False)
        except Exception as e:  # noqa: BLE001
            res["message"] = f"Nothing can be tuned automatically for this design yet ({type(e).__name__}: {e})."
            prop = None
        if prop is not None:
            d_old = load_design(design)
            old = d_old.to_json_dict()
            new = json.loads(Path(rev).read_text(encoding="utf-8"))
            res["knobs"] = [{"knob": k, "old": prop.start_knobs.get(k), "new": v} for k, v in prop.knobs.items()
                            if prop.start_knobs.get(k) != v]
            listed = [tuple(knob_path(d_old, k)) for k in prop.knobs]
            # a knob's own change, or the list / option it lives in when the knob created it (an unset parameter)
            res["moved"] = [{"path": _path_text(p), "old": o, "new": n} for p, o, n in _diff(old, new)
                            if not any(tuple(p)[:len(kp)] == kp or kp[:len(p)] == tuple(p) for kp in listed)]
            res.update(predicted=prop.predicted, objective=float(prop.objective), revision=str(rev),
                       at_bounds=list(prop.at_bounds), notes=list(prop.notes))
            if res["knobs"]:
                res["tunable"] = True
                res["message"] = (f"Predicted distance from the targets after the change: {prop.objective:.2g} "
                                  "tolerances (0 = on target). The prediction is from a surrogate; simulate again to check.")
            else:
                res["message"] = "Already on target to within the surrogate's resolution: no knob needs to change."
            if prop.notes:
                res["message"] += f" {len(prop.notes)} note(s) on what is not tuned (listed below)."
    if out:
        Path(out).write_text(json.dumps(res, indent=2, default=float) + "\n", encoding="utf-8")
    return res


def _path_text(path) -> str:
    parts = list(path)
    if len(parts) >= 4 and parts[0] == "instances" and parts[2] == "params":
        return ".".join(str(p) for p in [parts[1], *parts[3:]])
    if len(parts) >= 3 and parts[0] in ("instances", "routes"):
        return ".".join(str(p) for p in parts[1:])
    return ".".join(str(p) for p in parts)


def apply_knobs(design, proposal: dict, out=None) -> dict:
    """The design with the proposal's knobs set (``codesign.apply``: moves the waypoints that follow a port too), as a
    design.json dict. Raises when a knob no longer has the value the proposal started from."""
    from quantcore_circuits import codesign as cd  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.optimise import get_knob  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    for k in proposal["knobs"]:
        now_value = get_knob(d, k["knob"])
        if k.get("old") is not None and abs(float(now_value) - float(k["old"])) > 1e-6 * max(1.0, abs(float(k["old"]))):
            raise ValueError(f"{k['knob']} is {now_value} now, the proposal started from {k['old']}: the design changed "
                             "since the proposal; propose again")
    new = cd.apply(d, {k["knob"]: k["new"] for k in proposal["knobs"]}).to_json_dict()
    if out:
        Path(out).write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    return new

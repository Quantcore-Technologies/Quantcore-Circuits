"""Helpers for the tutorials in ``examples/tutorials/`` (00 quickstart, 01 chip 12, 02 IBM bowtie, 03 surface-17).

The tutorials walk through the Quantcore design loop one small step at a time. These helpers keep their cells short
and say what each step shows:

* :func:`setup`: the repository root becomes the working directory; ``examples/designs`` (the design helpers
  ``_common``, ``_legacy*``, ``_surface17``) goes on ``sys.path``; pictures go to ``examples/tutorials/img/``.
* :func:`live_mode`: live KLayout (KLive) when ``QCC_LIVE`` is unset or ``1`` and a KLayout exists, otherwise
  headless. Live cells never fail without KLayout. ``live_mode(gui=KLAYOUT_GUI)``: ``True`` opens the KLayout window
  when it is not running and brings it to the front; ``False`` only redraws a KLayout that is already open.
* :func:`pdk_md`, :func:`fab_layers_md`: the PDK facts the tutorials rely on, as Markdown tables.
* :func:`built`, :func:`snap`, :func:`drc`, :func:`drc_md`: build when needed, headless KLayout snapshot, DRC.
* :func:`send`, :func:`solve_or_load`, :func:`cmatrix_md`, :func:`eigen_md`, :func:`fem_vs_lom_md`: the FEM round
  trip. Jobs are exported to ``build/jobs/`` ("send"). With ``RUN_FEM = True`` and AEDT 2024 R1+ installed, a job is
  solved by ``sim_tools.hfss.solve_job`` the ``AEDT_MODE`` way: ``"batch"`` a new non-graphical AEDT, ``"gui"`` a
  new AEDT window (left open: mesh, convergence, fields), ``"attach"`` the AEDT window you have open (else a new
  one; released afterwards, projects left open). A progress line (pass, mesh, ΔF / ΔS / ΔC) is printed every 30 s.
  Never KQC's ``run_pyepr_t1_estimate.py``. Its ``results.json`` + ``job.json`` are kept under
  ``examples/tutorials/fem/<job>/``, so the "bring it back" cells work later without AEDT (``build/`` is not in
  git). :func:`fem_fast` (the notebooks' ``FEM_FAST``): loose convergence and few passes for whole-chip test runs.
* :func:`lom_params`, :func:`before_after_md`: the iterate step (change one property, rebuild, compare).
* :func:`sim_subset`, :func:`subset_md`, :func:`free_ram_gb` (phase C): the notebooks' ``SIM_SUBSET`` switch —
  ``"whole"`` (the built-in ``chip`` group) or pairs such as ``[("Q1", "R1")]`` / ``[("Q3", None), ("Q5", None)]``
  (``Designer.sim_subset``: the chosen qubits with their readout chains, the feedline cut into 50 Ω ports by the
  box, buses to other qubits cut); the read-back fills only those components of the whole-chip netlist
  (:func:`subset_md` shows which branch came from which job). ``solve_or_load`` notes low free RAM
  (``MIN_FREE_GB``) but solves anyway.
* :func:`subset_check` (2026-11-14): the notebooks' two FEM stages are (1) an optional **subset check**, FEM only
  (convergence, raw C-matrix / eigenmodes, FEM-filled C next to the estimates; no LOM, no feedback), then (2) the
  **whole chip**: render + solve, fill the whole netlist, LOM, LOM vs FEM, feedback, revision, DRC, fab.
  ``solve_or_load(..., force=RESOLVE)``: ``force`` may be a set of analyses to re-solve although kept results match.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import shutil
import sys
from pathlib import Path

from IPython.display import Image, Markdown, display

TUT = Path(__file__).resolve().parent
ROOT = TUT.parents[1]
IMG = TUT / "img"
FEM = TUT / "fem"
DESIGNS = TUT / "designs"
PREFIX = "tut"
AEDT_MODE = None  # default for solve_or_load / render_or_load: QCC_AEDT_MODE, else "batch" (notebooks pass theirs)
MIN_FREE_GB = 6.0  # solve_or_load prints a note below this much free RAM, and solves anyway (2026-11-14)

__all__ = [
    "DESIGNS",
    "FEM",
    "IMG",
    "Image",
    "Markdown",
    "ROOT",
    "TUT",
    "before_after_md",
    "built",
    "check_md",
    "cmatrix_md",
    "convergence_md",
    "display",
    "drc",
    "drc_md",
    "driven_md",
    "eigen_md",
    "epr_values",
    "exchange_on",
    "fab_layers_md",
    "fab_report_md",
    "fem_fast",
    "fem_vs_lom_md",
    "free_ram_gb",
    "inst_box",
    "junction_box",
    "kept_matches",
    "kept_results",
    "live_mode",
    "lom_params",
    "md",
    "pad_edges_md",
    "pdk_md",
    "render_or_load",
    "send",
    "setup",
    "sim_subset",
    "snap",
    "solve_or_load",
    "subset_check",
    "subset_md",
]


def md(text: str) -> None:
    """Show Markdown inline."""
    display(Markdown(text))


def setup(prefix: str) -> Path:
    """Repo root as the working directory, the design helpers importable, picture names ``img/<prefix>_<view>.png``."""
    global PREFIX  # noqa: PLW0603
    PREFIX = prefix
    os.chdir(ROOT)
    for p in (ROOT / "examples" / "designs", ROOT / "examples" / "designs" / "legacy",
              ROOT / "examples" / "designs" / "devicelayout", TUT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    IMG.mkdir(exist_ok=True)
    DESIGNS.mkdir(exist_ok=True)
    return ROOT


def live_mode(verbose: bool = True, gui: bool | None = None) -> bool:
    """Whether the Designer should run live (``Designer(..., live=LIVE)``).

    ``QCC_LIVE=0`` → headless. Otherwise live if KLive answers on localhost:8082 (KLayout open with the klive Salt
    package) or a KLayout executable is found (``QCC_KLAYOUT`` or the usual install folders). ``gui`` (the notebooks'
    ``KLAYOUT_GUI``; None keeps ``QCC_KLAYOUT_GUI``, default on): True → the first build starts KLayout if needed
    (with the Quantcore plugin and the layout), and its window is brought to the front; False → only a KLayout that
    is already open is redrawn. No KLayout at all → headless with a note, so the notebook still runs.
    """
    say = print if verbose else (lambda *a, **k: None)
    if os.environ.get("QCC_LIVE", "1") != "1":
        say("Headless (QCC_LIVE=0): each build writes build/<name>.oas; pictures are headless KLayout snapshots.")
        return False
    from quantcore_circuits.live import klive_available  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.live.klayout import find_klayout, use_gui  # pylint: disable=import-outside-toplevel

    window = use_gui(gui)
    if klive_available():
        say("Live: KLayout is running with KLive (localhost:8082); every change below is redrawn there in ~0.1–2 s"
            + (" (its window is brought to the front on the first build)." if window else "."))
        return True
    exe = find_klayout()
    if exe is not None and window:
        say(f"Live: KLayout ({exe}) is not running yet; the first build opens its window (≈ 15–20 s, with the "
            "Quantcore plugin) and brings it to the front.")
        return True
    if exe is not None:
        say("Live, KLAYOUT_GUI = False: KLayout is not open and will not be started; builds are written to "
            "build/<name>.oas (open KLayout with klive to see them, or set KLAYOUT_GUI = True).")
        return True
    say("No KLayout found (install it or set QCC_KLAYOUT): running headless; pictures are headless snapshots.")
    return False


def _aedt(aedt: str | None) -> str:
    from quantcore_circuits.sim_tools.aedt_session import resolve_mode  # pylint: disable=import-outside-toplevel

    return resolve_mode(aedt or AEDT_MODE)


_AEDT_SAYS = {
    "batch": "a new non-graphical AEDT (progress printed every 30 s)",
    "gui": "a new AEDT window (watch the mesh / convergence there; it stays open)",
    "attach": "the AEDT window you have open (else a new one; released afterwards, projects left open)",
}


# ---- PDK ---------------------------------------------------------------------------------------------------------
def pdk_md(pdk=None) -> str:
    """The PDK facts the tutorials use: stack, CPW, die frame, pad rule, junction rule, 3/0 keep-out, cheese,
    rounding."""
    from quantcore_circuits.circuit.bridges import junction_from_fingers  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    p = get_pdk() if pdk is None else (get_pdk(pdk) if isinstance(pdk, str) else pdk)
    s, f, j, k, c, r = p.stack, p.frame, p.junction, p.keepout, p.cheese, p.rounding
    nom = junction_from_fingers(*j.nominal_fingers_um, 1, p)
    rows = [
        ("PDK", f"`{p.name}` (version {p.version})"),
        ("stack", f"{s.substrate_material}, {s.substrate_height:g} µm, εr {s.substrate_permittivity:g}, "
                  f"tan δ {s.substrate_loss_tangent:g}; Nb film {s.metal_thickness_um:g} µm (a sheet in FEM), "
                  f"λ_L {s.london_penetration_depth_um * 1e3:g} nm → L_k {p.kinetic.sheet_pH_sq(s):.3f} pH/□"),
        ("CPW default", f"centre a = {p.cpw_a:g} µm, gap b = {p.cpw_b:g} µm (≈ 50 Ω on sapphire), bends r = "
                        f"{p.turn_radius:g} µm"),
        ("die frame", f"L dicing markers ({f.dicing_leg:g} µm legs, {f.dicing_width:g} µm wide, 1000/0), 3 × 3 "
                      f"alignment grids in the {f.marker_area:g} µm corner squares (1001/0), chip boundary 100/0, "
                      f"optional device ID ({f.device_id[0]:g} × {f.device_id[1]:g} µm), brand `{p.brand}`"),
        ("pad rule", f"outer etch edge of every bond pad / launcher **{f.pad_edge:g} µm** (the design-area margin) "
                     "from the die edge: `d.add(..., edge=\"auto\")`; DRC design warning `pad_edge` otherwise"),
        ("junction rule", f"{j.material}: Δ = {j.gap_meV:g} meV, I_c·R_n = πΔ/2e; **R_n {j.rn_target_kohm[0]:g}–"
                          f"{j.rn_target_kohm[1]:g} kΩ**, qubits {j.f_q_range_GHz[0]:g}–{j.f_q_range_GHz[1]:g} GHz; "
                          f"nominal {j.nominal_fingers_um[0]:g} × {j.nominal_fingers_um[1]:g} µm = "
                          f"{j.rn_nominal_kohm:g} kΩ → L_J {nom.lj_nH:.2f} nH, C_J {nom.cj_fF:.0f} fF; cells "
                          "`Quantcore Junction` / `Quantcore Squid` (the default junction_type)"),
        ("3/0 keep-out", f"filled second-metal etch: routes = CPW footprint + {k.route_margin:g} µm, components = "
                         f"etch bbox + {k.component_margin:g} µm (or the cell's own `qcc_keepout`), other 1/0 + "
                         f"{k.other_margin:g} µm"),
        ("cheese", f"a band of {c.rows} rows of {c.size:g} µm squares with {c.gap:g} µm gaps around 3/0, drawn in the "
                   "build (KQC `ground_grid`); the whole die instead with chip `cheese: \"chip\"`; an original "
                   "design's own cheese is kept; never in FEM exports"),
        ("corner rounding", f"fab export only: r = min({r.fraction:g} × the polygon's shortest dimension, "
                            f"{r.max_radius:g} µm) on {', '.join(r.layers)}; junction fingers stay sharp"),
    ]
    return "| PDK fact | value |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)


def fab_layers_md(pdk=None) -> str:
    """The fab layer map (negative mask: drawn = removed)."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    p = get_pdk() if pdk is None else (get_pdk(pdk) if isinstance(pdk, str) else pdk)
    out = ["| fab layer | name | drawn from | meaning |", "|---|---|---|---|"]
    for name, fl in sorted(p.fab_layers.items(), key=lambda t: (t[1].layer, t[1].datatype)):
        out.append(f"| {fl.layer}/{fl.datatype} | `{name}` | `{fl.source}` | {fl.description} |")
    return "\n".join(out)


# ---- build, snapshot, DRC ------------------------------------------------------------------------------------------
def built(d):
    """The current build of ``d`` (rebuilt when the design changed since the last one; live designers rebuild on
    every change already)."""
    if d.result is None or getattr(d, "_dirty", True) or not Path(d.out).exists():
        d.show()
    return d.result


def snap(d, view: str, box=None, size=(1400, 1400), width: int = 560, source=None, show: bool = True) -> Path:
    """Headless KLayout render (KQC colours, as in the GUI) of ``d``'s layout, or of ``source`` (another OAS, e.g. a
    fab export), to ``img/<prefix>_<view>.png``; ``box`` = (x0, y0, x1, y1) µm zooms in."""
    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    if source is None:
        built(d)
        source = d.out
    png = snapshot(source, IMG / f"{PREFIX}_{view}.png", size=size, box=box)
    if show:
        display(Image(filename=str(png), width=width))
    return png


def inst_box(d, name: str) -> tuple[float, float, float, float]:
    """Bounding box (µm) of instance ``name`` in the current build (from the sidecar)."""
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    return tuple(sidecar_dict(built(d), overlays=False)["instances"][name]["bbox"])


def junction_box(d, name: str, half: float = 8.0, which: int = 0) -> tuple[float, float, float, float]:
    """Zoom box (± ``half`` µm) on a junction of instance ``name``: centred on its finger overlap, marked by the
    trilayer spacer (50/0 ``qcc_spacer``), else on the ``SIS_junction`` leads. ``which`` picks one junction of a
    SQUID (sorted by x, then y)."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    r = built(d)
    x0, y0, x1, y1 = inst_box(d, name)
    region = pya.DBox(x0, y0, x1, y1)
    for key in ("qcc_spacer", "SIS_junction"):
        boxes = []
        for li in r.layout.layer_indexes():
            lname = r.layout.get_info(li).name or ""
            if not (lname == key if key == "qcc_spacer" else key in lname):
                continue
            it = r.top.begin_shapes_rec_overlapping(li, region)
            while not it.at_end():
                boxes.append(it.shape().dbbox().transformed(it.dtrans()))
                it.next()
        if boxes:
            c = sorted((round(b.center().x, 1), round(b.center().y, 1)) for b in boxes)[min(which, len(boxes) - 1)]
            return (c[0] - half, c[1] - half, c[0] + half, c[1] + half)
    raise ValueError(f"{name}: no junction shapes found")


def pad_edges_md(d) -> str:
    """Each bond pad / launcher: the distance of its outer etch edge from the nearest die edge (PDK rule:
    ``frame.pad_edge``, 100 µm)."""
    from quantcore_circuits.assembly.drc import _bond_pad  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    side = sidecar_dict(built(d), overlays=False)["instances"]
    x0, y0, x1, y1 = d.design.chip.box
    out = ["| pad | asked at (x, y) µm | outer etch edge → die edge (µm) |", "|---|---|---|"]
    for name, spec in d.data["instances"].items():
        if not _bond_pad(spec["cell"]) or name not in side:
            continue
        b = side[name]["bbox"]
        gap = min(b[0] - x0, b[1] - y0, x1 - b[2], y1 - b[3])
        at = spec["place"].get("at") or ["–", "–"]
        out.append(f"| `{name}` | ({at[0]:.0f}, {at[1]:.0f}) | {gap:.1f} |")
    return "\n".join(out)


def drc(d):
    """The DRC of the current build (connectivity, overlaps, crossings, frame keep-outs, netlist, PDK warnings)."""
    from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel

    return check(built(d))


def drc_md(rep, examples: int = 2) -> str:
    """DRC issues counted by severity and rule, with an example or two of each."""
    from collections import defaultdict  # pylint: disable=import-outside-toplevel

    groups = defaultdict(list)
    for i in rep.issues:
        groups[(i.severity, i.rule)].append(i.message)
    order = {"error": 0, "warning": 1, "design": 2}
    out = [f"**{'DRC clean' if rep.ok else 'DRC ERRORS'}** — {sum(1 for i in rep.issues if i.severity == 'error')} "
           f"errors, {sum(1 for i in rep.issues if i.severity == 'warning')} warnings, "
           f"{sum(1 for i in rep.issues if i.severity == 'design')} PDK design warnings", "",
           "| severity | rule | count | example |", "|---|---|---|---|"]
    for (sev, rule), msgs in sorted(groups.items(), key=lambda t: (order.get(t[0][0], 9), t[0][1])):
        ex = "<br>".join(m.replace("|", "/") for m in msgs[:examples])
        out.append(f"| {sev} | `{rule}` | {len(msgs)} | {ex} |")
    if not rep.issues:
        out.append("| – | – | 0 | – |")
    return "\n".join(out)


def fab_report_md(report: dict, path) -> str:
    """Summary of an ``export_fab`` report: polygons per fab layer, cheese source and holes, dropped layers."""
    out = [f"`{Path(path).as_posix()}`: cheese **{report.get('cheese_source', 'none')}** "
           f"({report.get('cheese_holes', 0)} holes)", "", "| fab layer | polygons |", "|---|---|"]
    out += [f"| `{k}` | {v} |" for k, v in sorted((report.get("written") or {}).items())]
    if report.get("dropped"):
        out += ["", "Not in the mask (no PDK fab layer): " + ", ".join(f"`{k}` × {v}" for k, v in
                                                                       report["dropped"].items())]
    return "\n".join(out)


# ---- FEM round trip ------------------------------------------------------------------------------------------------
def free_ram_gb() -> float | None:
    """Free physical memory in GB (None if psutil is missing)."""
    try:
        import psutil  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    return psutil.virtual_memory().available / 2**30


def sim_subset(d, subset, name: str = "S", margin_um: float = 300.0, analyses=("q3d_cmatrix",), settings=None,
               split: str = "auto", show: bool = True, readouts: bool = True) -> list[str]:
    """The notebooks' ``SIM_SUBSET`` cell: which part of the chip is rendered and simulated.

    ``subset = "whole"``: the built-in ``chip`` group (every instance and route, nothing cut; with ``FEM_FAST`` a
    quick whole-chip test). Otherwise a list of ``(qubit, resonator)`` pairs (resonator ``None``: the qubit's readout)
    or qubit names: ``Designer.sim_subset`` adds one sim group per box (pairs that share a bus or a declared coupling
    share a box; others get their own, so AEDT solves small boxes one after the other). ``readouts=False``: the
    qubits alone, their readouts cut by the box into 50 Ω lines (an eigenmode box that fits). Returns the group
    names."""
    if subset == "whole" or subset == ["whole"]:
        if show:
            md("**SIM_SUBSET = \"whole\"**: the whole chip (built-in group `chip`: every instance and route, nothing "
               "cut, a 50 Ω port on each pad). Its read-back fills every branch; lines kept whole give only their "
               "mutual capacitances (their own C to ground is the LOM's transmission line).")
        return ["chip"]
    from quantcore_circuits.sim_tools.subset import describe  # pylint: disable=import-outside-toplevel

    pairs = [(x, None) if isinstance(x, str) else tuple(x) for x in subset]
    groups = d.sim_subset(name, pairs=pairs, margin_um=margin_um, analyses=list(analyses), settings=settings,
                          split=split, readouts=readouts)
    if show:
        md(f"**SIM_SUBSET = {list(subset)}** → {len(groups)} box(es); each is rendered and simulated on its own, and "
           "its values fill only these components of the whole-chip netlist:\n\n" + describe(d.subset_plan))
    return groups


def subset_md(filled, rows: int = 40) -> str:
    """Which branch of the (whole-chip) circuit came from which FEM job, and how many kept their estimates."""
    out = ["| branch | nodes | estimate | FEM | from |", "|---|---|---|---|---|"]
    fem = [(k, v) for k, v in filled.values.items() if v.type in ("C", "HANGER") and v.extracted is not None]
    for k, v in fem[:rows]:
        out.append(f"| `{k}` | {' – '.join(v.nodes)} | {_fmt(v.estimate)} | {_fmt(v.extracted)} | "
                   f"`{v.source.split(':', 1)[-1]}` |")
    if len(fem) > rows:
        out.append(f"| … {len(fem) - rows} more | | | | |")
    est = [k for k, v in filled.values.items() if v.type in ("C", "HANGER") and v.extracted is None]
    outside = [k for k in est if filled.values[k].extra.get("subset") == "outside"]
    out += ["", f"**{len(fem)}** branches filled from FEM; **{len(est)}** kept their estimates "
                f"({len(outside)} outside the subset" + (f", e.g. `{'`, `'.join(outside[:6])}`" if outside else "")
            + ")."]
    for j in getattr(filled, "jobs", []):
        out.append(f"- `{j.get('job')}` (group `{j.get('group')}`, {j.get('analysis')}): "
                   f"{len([b for b in j.get('filled', []) if filled.values[b].type in ('C', 'HANGER')])} branches; "
                   f"scope {', '.join(j['scope']) if j.get('scope') else 'whole chip'}")
    return "\n".join(out)


def subset_check(keeps: dict, model=None, design=None, rows: int = 24):
    """Stage 1 of the FEM part (2026-11-14): the subset check, FEM only, before the whole-chip simulation.

    ``keeps``: ``{label: kept folder or None}`` of the subset jobs. Shows their convergence (passes, Δ, mesh, wall
    time), the raw FEM values (C-matrix; eigenmodes f, Q, p_J; driven notches) and, with ``model`` (the whole chip's
    netlist) and ``design``, the FEM-filled capacitances next to the component estimates of the simulated
    components. No LOM is simulated and nothing is fed back from a subset. Returns the filled circuit (or None)."""
    done = {k: v for k, v in keeps.items() if v}
    if not done:
        md("**Subset check:** nothing solved yet (`RUN_FEM = True` solves the boxes above, one AEDT at a time).")
        return None
    md(convergence_md(keeps))
    for keep in done.values():
        res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
        if res.get("cmatrix"):
            md(cmatrix_md(keep))
        if res.get("eigenmodes"):
            md(eigen_md(keep))
        if res.get("sparams"):
            md(driven_md(keep))
    filled = None
    q3d = [v for v in done.values()
           if json.loads((Path(v) / "results" / "results.json").read_text(encoding="utf-8")).get("cmatrix")]
    if model is not None and design is not None and q3d:
        from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel

        filled = fill(model, design, q3d)
        md("**FEM-filled capacitances of the simulated components** (the other branches keep their estimates):\n\n"
           + subset_md(filled, rows=rows))
    md("**Look at these before the whole chip:** if the passes converged (or Δ sits near its target), the "
       "capacitances are positive and near their estimates and the qubit mode has p_J ≈ 1, go on and render and "
       "simulate the whole chip (stage 2). If not, change the mesh / settings here first: a subset solves in minutes.")
    return filled


def send(design_path, groups, analysis: str) -> dict:
    """"Send": export one job per sim group into ``build/jobs/<design>_<group>_<analysis>`` (overwritten)."""
    from _common import export_sims  # pylint: disable=import-outside-toplevel

    return export_sims(design_path, groups, analysis=analysis)


def kept_results(job_dir) -> Path | None:
    """The kept copy ``examples/tutorials/fem/<job>/`` of a solved job, if it has ``results/results.json``."""
    keep = FEM / Path(job_dir).name
    return keep if (keep / "results" / "results.json").exists() else None


def fem_fast(flag: bool = True) -> bool:
    """The notebooks' ``FEM_FAST`` switch: True → every job exported from here on (``send``, ``export_sims``,
    ``hfss.render``, ``pipeline_evaluator``) gets the library's fast whole-chip test settings
    (``sim_tools.export.FAST_SETTINGS``: Q3D 2 % / ≤ 8 passes; eigenmode ΔF 1 % / ≤ 3 passes, memory-bound here;
    driven ΔS 0.05 / ≤ 6 passes; mesh seeds × 3, none given: a 40 / 30 µm gap seed for eigenmode / driven; sweeps
    ≤ 10 001 points). The values are not converged; they move with the design, so the loop can be tested in minutes.
    False → the settings the notebook gives. Returns the flag."""
    from quantcore_circuits.sim_tools.export import FAST_SETTINGS, set_fem_fast  # pylint: disable=C0415

    set_fem_fast(bool(flag))
    if flag:
        print("FEM_FAST: jobs are exported with the fast test settings ("
              + "; ".join(f"{a} " + ", ".join(f"{k} {v:g}" for k, v in s.items() if k != "minimum_converged_passes")
                          for a, s in FAST_SETTINGS.items() if a != "hfss_eigenmode")
              + "); values are not converged")
    return bool(flag)


def kept_matches(job_dir) -> bool:
    """Whether the kept results of ``job_dir`` were solved for the same job: same design hash, group and analysis,
    and the same solver settings or tighter ones (a full solve stands in for a ``FEM_FAST`` re-run; not the other
    way round). Then a ``RUN_FEM = True`` re-run does not solve it again."""
    from quantcore_circuits.sim_tools.export import tighter_or_equal  # pylint: disable=import-outside-toplevel

    keep = kept_results(job_dir)
    if keep is None or not (Path(job_dir) / "job.json").exists():
        return False
    new, old = json.loads((Path(job_dir) / "job.json").read_text(encoding="utf-8")), _job_meta(keep)
    # jobs exported since phase C also carry group_hash (the design with only their own sim group): adding another
    # subset group to the design then does not make this group's kept results look like another revision
    key = "group_hash" if new.get("group_hash") and old.get("group_hash") else "design_hash"
    return (all(new.get(k) == old.get(k) for k in (key, "group", "analysis"))
            and tighter_or_equal(old.get("settings") or {}, new.get("settings") or {}))


def solve_or_load(job_dir, run_fem, timeout: float = 1200.0, force: bool = False, aedt: str | None = None
                  ) -> Path | None:
    """``run_fem``: solve ``job_dir`` with ``hfss.solve_job`` in AEDT the ``aedt`` way (``"batch"``: a new
    non-graphical AEDT; ``"gui"``: a new AEDT window, left open; ``"attach"``: the AEDT window that is open, else a
    new one; default ``AEDT_MODE``), with a progress line every 30 s; after ``timeout`` s qcc stops waiting and kills
    only what it started; keep ``results.json`` + ``job.json`` under ``examples/tutorials/fem/<job>/``. ``run_fem``
    is a bool or a set of analysis names (``{"q3d_cmatrix"}``: solve only the Q3D jobs). Kept results of the same job
    (same design hash, group, analysis and settings: :func:`kept_matches`) are not solved again unless ``force``.
    Either way, return the kept results folder (a valid ``fill(...)`` / ``load_results`` source) or None."""
    job_dir = Path(job_dir)
    if run_fem and not isinstance(run_fem, bool):  # a set of analyses
        analysis = json.loads((job_dir / "job.json").read_text(encoding="utf-8")).get("analysis")
        run_fem = analysis in set(run_fem)
    if force and not isinstance(force, bool):  # the notebooks' RESOLVE: a set of analyses to re-solve (nb-flow)
        force = json.loads((job_dir / "job.json").read_text(encoding="utf-8")).get("analysis") in set(force)
    if run_fem and not force and kept_matches(job_dir):
        print(f"{job_dir.name}: kept results match this job (same design hash; same or tighter settings); not "
              "solved again (force=True re-solves)")
        run_fem = False
    if run_fem and free_ram_gb() is not None and free_ram_gb() < MIN_FREE_GB:  # a note only (2026-11-14)
        print(f"{job_dir.name}: note: only {free_ram_gb():.1f} GB of RAM free (< T.MIN_FREE_GB = {MIN_FREE_GB:g}); "
              "solving anyway (AEDT may swap and run slowly)")
    if run_fem:
        from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=C0415

        exe = find_ansys_executable()
        if exe is None:
            print("RUN_FEM: no AEDT 2024 R1+ found (set QCC_ANSYS_EXECUTABLE); nothing solved")
        else:
            from quantcore_circuits.sim_tools.hfss import solve_job  # pylint: disable=import-outside-toplevel

            mode = _aedt(aedt)
            print(f"solving {job_dir.name} with {exe} in {_AEDT_SAYS[mode]}; timeout {timeout:.0f} s …")
            r = solve_job(job_dir, timeout=timeout, aedt=mode)
            print(f"  {'ok' if r.ok else 'FAILED'} in {r.seconds:.0f} s (AEDT {r.mode} pid {r.pid}); log {r.log}"
                  + (f"; {r.note}" if r.note else ""))
            res = job_dir / "results" / "results.json"
            if r.ok and res.exists():
                keep = FEM / job_dir.name
                (keep / "results").mkdir(parents=True, exist_ok=True)
                shutil.copy2(res, keep / "results" / "results.json")
                shutil.copy2(job_dir / "job.json", keep / "job.json")
    keep = kept_results(job_dir)
    if keep is None:
        print(f"{job_dir.name}: no solved results kept (examples/tutorials/fem/{job_dir.name}/)")
    elif (Path(job_dir) / "job.json").exists() and not kept_matches(job_dir):
        print(f"{job_dir.name}: the kept results were solved for another revision of this job (design hash or "
              "settings differ); they are shown as they are — re-solve with RUN_FEM = True")
    return keep


def render_or_load(design_path, group: str, analysis: str, run, timeout: float = 1800.0, aedt: str | None = None
                   ) -> Path | None:
    """Render (no solve) sim group ``group`` / ``analysis`` of ``design_path`` into an AEDT project with
    ``hfss.render(..., solve=False)`` in AEDT the ``aedt`` way (as :func:`solve_or_load`; ``"gui"`` / ``"attach"``
    leave the rendered project open in a window) — only what qcc started is stopped on a timeout —
    and read the project back with ``hfss.check_project`` (design and solution type, stack, metal sheets, ports /
    terminations, nets, every solver setting). ``run``: bool or a set of analyses (as :func:`solve_or_load`). The
    check is kept as ``examples/tutorials/fem/<job>/check.json`` (+ ``job.json``), so :func:`check_md` works later
    without AEDT. Returns the kept folder or None."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    name = f"{load_design(design_path).name}_{group}_{analysis}"
    keep = FEM / name
    if run and not isinstance(run, bool):
        run = analysis in set(run)
    from quantcore_circuits import track  # pylint: disable=import-outside-toplevel

    if run:
        from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=C0415
        from quantcore_circuits.sim_tools.hfss import check_project, render  # pylint: disable=C0415

        if find_ansys_executable() is None:
            print("no AEDT 2024 R1+ found (set QCC_ANSYS_EXECUTABLE); nothing rendered")
        else:
            job_dir = ROOT / "build" / "jobs" / name
            mode = _aedt(aedt)
            print(f"rendering {name} (no solve) in {_AEDT_SAYS[mode]}; timeout {timeout:.0f} s …")
            with track.stage("render", f"{name} (AEDT project check)") as st:
                r = render(design_path, group, analysis, job_dir=job_dir, solve=False, timeout=timeout, aedt=mode)
                if not r.ok:
                    st.fail("render failed")
                st.note = "rendered and read back"
            print(f"  {'ok' if r.ok else 'FAILED'} in {r.seconds:.0f} s (AEDT {r.mode} pid {r.pid}); log {r.log}"
                  + (f"; {r.note}" if r.note else ""))
            if r.ok:
                chk = check_project(job_dir)
                keep.mkdir(parents=True, exist_ok=True)
                data = {"render_seconds": round(r.seconds, 1), "summary": r.summary, **chk}
                (keep / "check.json").write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
                shutil.copy2(job_dir / "job.json", keep / "job.json")
    if not (keep / "check.json").exists():
        print(f"{name}: not rendered yet (examples/tutorials/fem/{name}/check.json); RUN_FEM = True renders it")
        return None
    track.emit("stage", step="render", phase="done", label=name, detail="kept render check (check.json)")
    return keep


def check_md(keep: Path) -> str:
    """The read-back of a rendered AEDT project (:func:`render_or_load`): one row per check, the settings count."""
    data = json.loads((Path(keep) / "check.json").read_text(encoding="utf-8"))
    s = data.get("summary") or {}
    out = [f"`{Path(keep).name}`: {s.get('design_type', '?')} / {s.get('solution_type', '?')}, rendered in "
           f"{data.get('render_seconds', '?')} s; {len(s.get('boundaries') or [])} boundaries, nets "
           f"{sorted(s.get('nets') or {})} — **{'OK' if data.get('ok') else 'CHECK FAILED'}**", "",
           "| check | ok | detail |", "|---|---|---|"]
    out += [f"| {c['check']} | {'✓' if c['ok'] else '✗'} | {str(c['detail']).replace('|', '/')[:120]} |"
            for c in data.get("checks", [])]
    return "\n".join(out)


def driven_md(keep: Path) -> str:
    """The driven S21 notch fits (f0, κ_ext, Q_c, Q_i, depth, fit residual) of a solved ``hfss_driven`` job, its mesh
    and wall time."""
    res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
    meta, sp = _job_meta(keep), res.get("sparams") or {}
    out = [f"Driven S-parameters of `{meta['simulation_name']}` ({res.get('aedt', {}).get('aedt', 'AEDT')}, "
           f"{meta.get('solve_seconds', '?')} s; ports {sp.get('ports')}, {sp.get('n_points')} points over "
           f"{sp.get('f_GHz')} GHz):", "",
           "| notch | f0 (GHz) | κ_ext/2π (MHz) | Q_c | Q_i | depth | fit residual |", "|---|---|---|---|---|---|---|"]
    for k, v in (sp.get("notch") or {}).items():
        out.append(f"| {k} | {v['f0_GHz']:.5f} | {v['kappa_ext_MHz']:.4f} | {v['Q_coupling']:.4g} | "
                   f"{v['Q_internal']:.3g} | {v['depth']:.3f} | {v['residual_rms']:.2g} |")
    if not sp.get("notch"):
        out.append("| – | no notch found in the sweep | | | | | |")
    return "\n".join(out)


def convergence_md(keeps: dict) -> str:
    """One row per kept job: passes, mesh, the convergence criterion and whether it was met, wall time."""
    out = ["| analysis | passes | tets (last) | criterion | last Δ / target | converged | wall time (s) |",
           "|---|---|---|---|---|---|---|"]
    for name, keep in keeps.items():
        if keep is None:
            out.append(f"| {name} | – | – | – | – | not solved | – |")
            continue
        res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
        c, meta = res.get("convergence") or {}, _job_meta(keep)
        passes, elems, delta = c.get("passes") or [], c.get("elements") or [], c.get("delta") or []
        last = next((x for x in reversed(delta) if x is not None), None)
        out.append(f"| {name} | {passes[-1] if passes else '–'} | {elems[-1] if elems else '–'} | "
                   f"{c.get('criterion', '–')} | {'–' if last is None else f'{last:.3g}'} / {c.get('target', '–')} | "
                   f"{c.get('converged', '–')} | {meta.get('solve_seconds', '?')} |")
    return "\n".join(out)


def _job_meta(keep: Path) -> dict:
    return json.loads((Path(keep) / "job.json").read_text(encoding="utf-8"))


def cmatrix_md(keep: Path) -> str:
    """The solved Maxwell capacitance matrix (fF) with its net names, and the solver's wall time."""
    res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
    cm, meta = res["cmatrix"], _job_meta(keep)
    labels = cm["labels"]
    out = [f"Q3D C-matrix of `{meta['simulation_name']}` ({res.get('aedt', {}).get('aedt', 'AEDT')}, "
           f"{meta.get('solve_seconds', '?')} s; Maxwell form, fF):", "",
           "| net | " + " | ".join(f"`{x}`" for x in labels) + " |", "|---|" + "---|" * len(labels)]
    for name, row in zip(labels, cm["matrix"]):
        out.append(f"| `{name}` | " + " | ".join(f"{v:.3f}" for v in row) + " |")
    return "\n".join(out)


def eigen_md(keep: Path) -> str:
    """Eigenmodes (f, Q) and the pyEPR quantities (p_J, dressed f, χ, α) of a solved eigenmode/EPR job."""
    res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
    meta = _job_meta(keep)
    modes = res.get("eigenmodes") or []
    epr = res.get("epr") or {}
    out = [f"Eigenmodes of `{meta['simulation_name']}` ({res.get('aedt', {}).get('aedt', 'AEDT')}, "
           f"{meta.get('solve_seconds', '?')} s):", "", "| mode | f linear (GHz) | Q | p_J | f dressed, pyEPR (GHz) "
           "| self-Kerr χ_mm (MHz) |", "|---|---|---|---|---|---|"]
    for i, m in enumerate(modes):
        pj = (epr.get("p_mj") or [[None]] * len(modes))[i][0] if epr.get("p_mj") else None
        fd = (epr.get("f_GHz") or [None] * len(modes))[i] if epr.get("f_GHz") else None
        chi = epr["chi_MHz"][i][i] if epr.get("chi_MHz") else None
        out.append(f"| {m['mode']} | {m['f_GHz']:.4f} | {m.get('Q', float('nan')):.4g} | "
                   f"{'–' if pj is None else f'{pj:.4f}'} | {'–' if fd is None else f'{fd:.4f}'} | "
                   f"{'–' if chi is None else f'{chi:.1f}'} |")
    if epr.get("chi_MHz") and len(modes) > 1:
        out.append("")
        out.append(f"Cross-Kerr (dispersive shift) χ₁₂ = {epr['chi_MHz'][0][1]:.3f} MHz (pyEPR, numerical "
                   "diagonalisation).")
    conv = res.get("convergence")
    if conv:
        delta = [x for x in conv.get("delta") or [] if x is not None]
        out.append("")
        out.append(f"Convergence: {len(conv.get('passes') or [])} passes, {(conv.get('elements') or ['?'])[-1]} tets, "
                   f"last {conv.get('criterion', 'Δ')} {delta[-1] if delta else '–'} (target {conv.get('target')}), "
                   f"converged: {conv.get('converged')}.")
        extra = [f"mode {m['mode']} → {m['f_extrapolated']['value']:.4f} GHz" for m in modes if m.get("f_extrapolated")]
        if extra and not conv.get("converged"):
            out.append("Mesh extrapolation of the last passes (power law): " + ", ".join(extra) + ".")
    return "\n".join(out)


def epr_values(keep, readouts: dict[str, str], f_guess: dict[str, float]) -> dict:
    """Target-style values from a kept eigenmode/EPR job with several qubits: ``readouts`` maps qubit → its readout
    resonator (``{"Q1": "R1", "Q2": "R2"}``), ``f_guess`` the expected resonator frequencies (GHz, e.g. the LOM's).

    Each qubit's mode is the one with the largest participation of *its* junction (``epr["junction_names"]``); each
    resonator's mode is the remaining mode (Q > 100: not a cut feedline's own) nearest its guess. Returns
    ``{"Q1.f_q_GHz", "Q1.alpha_MHz", "R1.f_GHz", "R1.chi_MHz", "R1.kappa_MHz", …, "Q1-Q2.zz_MHz"}`` — pyEPR dressed
    frequencies and Kerr terms, κ = f/Q of the 50 Ω-terminated feedline (bulk-dielectric loss removed) — plus
    ``"modes"`` (name → mode index)."""
    res = json.loads((Path(keep) / "results" / "results.json").read_text(encoding="utf-8"))
    epr, modes = res.get("epr") or {}, res.get("eigenmodes") or []
    if not epr.get("p_mj"):
        return {}
    from quantcore_circuits.circuit.adapters import _epr_plausible  # pylint: disable=import-outside-toplevel

    names = [n.split(".", 1)[0] for n in epr.get("junction_names") or []]
    chi, f_nd, q_d = epr["chi_MHz"], epr["f_GHz"], epr.get("Q_dielectric") or [None] * len(modes)
    out, idx = {}, {}
    for q in readouts:
        j = names.index(q)
        idx[q] = max(range(len(modes)), key=lambda i, j=j: epr["p_mj"][i][j])
        if not _epr_plausible(modes[idx[q]]["f_GHz"], f_nd[idx[q]], chi[idx[q]][idx[q]]):
            print(f"epr_values: {q}'s mode {idx[q] + 1} is not a transmon (linear {modes[idx[q]]['f_GHz']:.3f} GHz, "
                  f"pyEPR {f_nd[idx[q]]:.3f} GHz): mesh not converged? Its values are left out.")
            # still give the linear eigenfrequency of the qubit mode: the lowest mode its junction dominates (a coarse
            # mesh can put p_J ≈ 1 on box modes above it too; tutorial 02's 2-pass qubit-only boxes, 2026-11-14)
            low = [i for i in range(len(modes)) if epr["p_mj"][i][j] >= 0.5]
            if low:
                out[f"{q}.f_linear_GHz"] = modes[min(low, key=lambda i: modes[i]["f_GHz"])]["f_GHz"]
            continue
        out[f"{q}.f_q_GHz"], out[f"{q}.alpha_MHz"] = f_nd[idx[q]], chi[idx[q]][idx[q]]
    free = [i for i in range(len(modes)) if i not in idx.values() and (modes[i].get("Q") or 0) > 100]
    # order-preserving: the k-th lowest guess gets the k-th lowest of the chosen modes. A greedy nearest-guess choice
    # swapped R1 / R2 in tutorial 04 (2026-11-13: both FEM readouts ≈ 0.17 GHz below the LOM, so R1's guess 7.08 was
    # nearer R2's mode 7.13 than its own 6.83), and the feedback then pushed the two lengths the wrong way.
    pairs = sorted(((q, r) for q, r in readouts.items() if f"{q}.f_q_GHz" in out), key=lambda t: f_guess.get(t[1], 0))
    free.sort(key=lambda i: modes[i]["f_GHz"])
    n = min(len(pairs), len(free))
    best = min(itertools.combinations(free, n),
               key=lambda c: sum((modes[i]["f_GHz"] - f_guess[r]) ** 2 for i, (_, r) in zip(c, pairs)), default=())
    for i, (q, r) in zip(best, pairs):
        idx[r] = i
        qq, qd = modes[i]["Q"], q_d[i] if i < len(q_d) else None
        q_ext = 1 / (1 / qq - 1 / qd) if qd and 1 / qq > 1 / qd else qq
        out[f"{r}.f_GHz"], out[f"{r}.chi_MHz"] = f_nd[i], chi[idx[q]][i]
        out[f"{r}.kappa_MHz"] = modes[i]["f_GHz"] / q_ext * 1e3
    qs = [q for q in readouts if f"{q}.f_q_GHz" in out]
    for a in range(len(qs)):
        for b in range(a + 1, len(qs)):
            out[f"{qs[a]}-{qs[b]}.zz_MHz"] = chi[idx[qs[a]]][idx[qs[b]]]
    out["modes"] = idx
    return out


def exchange_on(model, design, qa: str, qb: str, job=None, span: float = 0.04, max_modes: int = 3) -> dict:
    """Exchange coupling J (MHz) between qubits ``qa`` and ``qb`` of ``model`` from the avoided crossing, on the
    component estimates or (``job``) on a solved C-matrix: as ``_common.exchange_coupling``, but on a given model and
    job. ``qb``'s L_J is swept through the crossing; the dressed splitting s is fitted with s² = a(L − L0)² + 4J².
    Returns ``{"J_MHz", "f_a_GHz", "f_b_GHz", "lj_cross_nH", "C_ab_fF"}`` (C_ab: the chosen qa–qb capacitance)."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    jb = f"J_{qb}"
    lj0 = float(model.branches[jb].value["Lj_nH"])

    def run(lj=None):
        m = model.model_copy(deep=True)
        if lj is not None:
            m.branches[jb].value["Lj_nH"] = float(lj)
        return simulate(fill(m, design, job), max_modes=max_modes)

    def fq(res, q):
        f = res.params.get(f"{q}.f_q_GHz")
        return f if f is not None else next((x.f_GHz for x in res.modes if x.label == q), None)

    base = run()
    fa, fb = fq(base, qa), fq(base, qb)
    filled = fill(model, design, job)
    c_ab = sum(v.value or 0 for v in filled.values.values() if v.type == "C" and set(v.nodes) == {qa, qb})

    def split(x):
        r = run(x)
        return abs(fq(r, qa) - fq(r, qb)) * 1e3

    def fit(xs):
        ys = [split(x) for x in xs]
        return np.polyfit(np.array(xs), np.array(ys) ** 2, 2), ys

    guess = lj0 * (fb / fa) ** 2
    (a2, a1, _), _ = fit(list(np.linspace(guess * (1 - span), guess * (1 + span), 3)))
    x0 = -a1 / (2 * a2) if a2 > 0 else guess
    h = 10.0 / (math.sqrt(a2) if a2 > 0 else 1.0)
    (a2, a1, a0), ys = fit([x0 - h, x0, x0 + h])
    x0 = -a1 / (2 * a2) if a2 > 0 else x0
    s2 = max(a0 - a1**2 / (4 * a2), 0.0) if a2 > 0 else min(ys) ** 2
    return {"J_MHz": math.sqrt(s2) / 2, "f_a_GHz": fa, "f_b_GHz": fb, "lj_cross_nH": float(x0), "C_ab_fF": c_ab}


def lom_params(res, keys) -> dict:
    """``{key: value}`` from a :class:`LomResult`'s QuTiP-dressed parameters (``Q1.f_q_GHz``, ``R1.chi_MHz``, …)."""
    return {k: res.params.get(k) for k in keys}


def _fmt(v, nd=4):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "–"
    return f"{v:.{nd}g}"


def fem_vs_lom_md(rows: list[tuple]) -> str:
    """Rows ``(quantity, LOM estimate, LOM with FEM values or FEM, note)`` as a Markdown table with Δ %."""
    out = ["| quantity | LOM (component estimates) | FEM / LOM on FEM values | Δ | note |", "|---|---|---|---|---|"]
    for q, a, b, note in rows:
        delta = "–" if a in (None, 0) or b is None else f"{100 * (b - a) / abs(a):+.1f} %"
        out.append(f"| {q} | {_fmt(a)} | {_fmt(b)} | {delta} | {note} |")
    return "\n".join(out)


def before_after_md(before: dict, after: dict, units: dict | None = None) -> str:
    """Before/after table of the iterate step (same keys)."""
    units = units or {}
    changed = [k for k in before if before[k] is not None and after.get(k) is not None and before[k] != after[k]]
    from quantcore_circuits import track  # pylint: disable=import-outside-toplevel

    with track.stage("feedback", "knob update") as st:  # dashboard: an iterate step is a feedback step (04's own loop)
        st.note = "no knob changed"
        if changed:
            st.note = f"{len(changed)} knob(s) changed: " + ", ".join(f"{k} {_fmt(before[k])}→{_fmt(after[k])}"
                                                                       for k in changed[:6])
    out = ["| quantity | before | after | change |", "|---|---|---|---|"]
    for k in before:
        a, b = before[k], after.get(k)
        if a is None or b is None:
            ch = "–"
        else:
            ch = f"{b - a:+.4g}" + (f" ({100 * (b - a) / abs(a):+.1f} %)" if a else "")
        out.append(f"| `{k}`{' (' + units[k] + ')' if k in units else ''} | {_fmt(a, 5)} | {_fmt(b, 5)} | {ch} |")
    return "\n".join(out)

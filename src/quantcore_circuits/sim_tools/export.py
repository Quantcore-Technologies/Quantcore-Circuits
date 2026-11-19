"""Export a :class:`SimSetup` to a self-contained job directory using KQC's exporters.

Job directory = KQC export (``scripts/``, ``<sim>.gds``, ``<sim>.json``) + ``job.json``
(qcc metadata: design hash, group, analysis, solver settings, port → net labels) + ``simulation.oas``. Ansys jobs
also get ``scripts/qcc_render.py`` / ``qcc_solve.py`` (:mod:`.aedt_scripts`) and ``simulation.bat`` / ``simulation.sh``
that run ``qcc_solve.py`` in a new non-graphical AEDT and collect ``results/results.json``.

Analyses:

==================  ==========================================================================================
``q3d_cmatrix``     Ansys Q3D Maxwell capacitance matrix (KQC ``AnsysQ3dSolution``)
``hfss_eigenmode``  Ansys HFSS eigenmode with Lj/Cj lumped RLC on junctions (``AnsysEigenmodeSolution``)
``eigenmode_epr``   as above + KQC ``pyepr`` flag (junction lines); ``qcc_solve.py`` evaluates pyEPR's field
                    integrals in its own AEDT, :mod:`..analysis.epr` turns them into p_mj, χ, α (not KQC's
                    ``run_pyepr_t1_estimate.py``: it attaches to a running AEDT over COM and quits it)
``elmer_cap``       Elmer electrostatics capacitance matrix (``ElmerCapacitanceSolution``)
``palace_cap``      Palace electrostatic C-matrix (KQC gmsh mesh → Palace config, see :mod:`.palace`)
``palace_eig``      Palace eigenmode with junction LumpedPort L=Lj (see :mod:`.palace`)
``hfss_driven``     Ansys HFSS driven modal S-parameters (``AnsysHfssSolution``): wave ports where lines leave
                    the box, junctions as lumped L/C; e.g. a hanger's S21 → κ to calibrate the LOM coupling
==================  ==========================================================================================
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.post_process import PostProcess

from quantcore_circuits.design.io import design_hash, group_hash, tool_versions
from quantcore_circuits.pdk import get_pdk
from quantcore_circuits.sim_tools.builder import SimSetup

JOB_SCHEMA = "qcc-job/0.1"
MAX_SWEEP_POINTS = 25000  # AEDT: "A sweep can not have over 25000 points"

DEFAULT_SETTINGS = {
    "q3d_cmatrix": {"percent_error": 0.5, "maximum_passes": 18, "minimum_passes": 2, "minimum_converged_passes": 2},
    "hfss_eigenmode": {
        "n_modes": 2,
        "min_frequency": 3.0,
        "max_delta_f": 0.1,
        "maximum_passes": 17,
        "minimum_passes": 1,
        "minimum_converged_passes": 2,
        "percent_refinement": 30,
        "integrate_energies": False,
    },
    "elmer_cap": {"p_element_order": 3, "maximum_passes": 1},
    "palace_cap": {"order": 2, "mesh_global_max": 100.0, "mesh_edge": 4.0},
    "palace_eig": {"order": 2, "n_modes": 2, "target_GHz": 3.0, "mesh_global_max": 100.0, "mesh_edge": 4.0},
}
DEFAULT_SETTINGS["eigenmode_epr"] = {**DEFAULT_SETTINGS["hfss_eigenmode"], "n_modes": 2}
DEFAULT_SETTINGS["hfss_driven"] = {
    "frequency": 6.0,  # GHz, adaptive-mesh frequency (put it near the resonance of interest)
    "max_delta_s": 0.02,
    "maximum_passes": 20,
    "minimum_passes": 2,
    "minimum_converged_passes": 2,
    "percent_refinement": 30,
    "sweep_enabled": True,
    "sweep_start": 4.0,
    "sweep_end": 9.0,
    "sweep_count": 1001,
    "sweep_type": "interpolating",
}

# "Fast FEM" (2026-11-13): whole-chip *test* runs that finish in minutes on a workstation. The values are not
# accurate (the mesh is not converged); they move with the design, so the whole loop (render → solve → save → read
# back → fill → feedback → re-solve) can be exercised before anyone fine-tunes the settings. Criteria are loosened to
# at least these values, pass counts capped at them; mesh seeds (``mesh_size``) are coarsened by FAST_MESH_FACTOR and a
# sweep capped at FAST_SWEEP_POINTS. Switch: ``export_job(..., fast=True)``, :func:`set_fem_fast` or
# ``QCC_FEM_FAST=1``.
FAST_SETTINGS = {
    "q3d_cmatrix": {"percent_error": 2.0, "maximum_passes": 8, "minimum_passes": 1, "minimum_converged_passes": 1},
    # eigenmode: memory, not time, is the limit here (31 GB): tutorial 04's two-qubit box needed 20 GB for hf3d at
    # pass 3 (265 k tets) and pass 4 would not have fitted, so 3 passes on a 40 µm gap seed (≈ 15 GB at most)
    "hfss_eigenmode": {"max_delta_f": 1.0, "maximum_passes": 3, "minimum_passes": 1, "minimum_converged_passes": 1},
    "hfss_driven": {"max_delta_s": 0.05, "maximum_passes": 6, "minimum_passes": 1, "minimum_converged_passes": 1},
}
FAST_SETTINGS["eigenmode_epr"] = FAST_SETTINGS["hfss_eigenmode"]
# HFSS starts from a mesh too coarse to resolve the junction gap and the CPW gaps: unseeded, the first ~6 eigenmode
# passes show the qubit and the readout at the wrong frequencies (the 2026-11-03 fixture: 10–14 GHz until pass 7,
# then 3.2 → 5.2 GHz), and a driven S21 stays flat. So a fast run without a seed of its own gets one on the gaps.
# Tutorial 00 with 20 µm: qubit / readout 5.23 / 6.65 GHz at pass 1, 5.32 / 6.96 at pass 3, 5.35 / 7.00 at pass 4;
# tutorial 04 with 30 µm: both qubits and both readouts at pass 1 (158 k tets).
FAST_MESH_SEED = {"hfss_eigenmode": {"1t1_gap": 40.0}, "eigenmode_epr": {"1t1_gap": 40.0},
                  "hfss_driven": {"1t1_gap": 30.0}}
FAST_MESH_FACTOR = 3.0
# … and the junction islands (the nets of the junction ports, KQC layer ``<face>_signal_<n>``) a fine seed of their own:
# with the gap seed alone a qubit-only box (tutorial 01 ``Q1_q``, 0.8 × 1 mm) got 18 k tets and no qubit mode
# (10.3 / 11.6 GHz). The islands are small, so this costs little.
FAST_ISLAND_SEED = 10.0
FAST_SWEEP_POINTS = 10001
_LOOSER = ("percent_error", "max_delta_f", "max_delta_s")  # larger = looser
_FEWER = ("maximum_passes", "minimum_passes", "minimum_converged_passes")  # smaller = faster
_FAST: bool | None = None


def set_fem_fast(flag: bool | None) -> None:
    """Process-wide default for ``export_job(fast=None)`` (None: ``QCC_FEM_FAST``, else off)."""
    global _FAST  # noqa: PLW0603
    _FAST = flag


def fem_fast(fast: bool | None = None) -> bool:
    """Whether jobs are exported with :data:`FAST_SETTINGS`: ``fast`` if given, else :func:`set_fem_fast`'s value,
    else ``QCC_FEM_FAST`` (``1`` / ``true``)."""
    if fast is not None:
        return bool(fast)
    if _FAST is not None:
        return _FAST
    return os.environ.get("QCC_FEM_FAST", "").strip().lower() in ("1", "true", "yes", "on")


def fast_settings(analysis: str, settings: dict, islands: list[int] | tuple = ()) -> dict:
    """``settings`` for a fast whole-chip test run of ``analysis`` (see :data:`FAST_SETTINGS`): each convergence
    criterion at least the fast value, each pass count at most the fast value, ``mesh_size`` seeds × FAST_MESH_FACTOR
    (no seed given: :data:`FAST_MESH_SEED` for eigenmode / driven), ``sweep_count`` ≤ FAST_SWEEP_POINTS. Other keys
    (frequencies, modes, sweep band) are kept. Analyses without fast
    values (Elmer, Palace, plugins) are returned unchanged. ``islands``: KQC excitation numbers of the junction
    islands; eigenmode / driven runs seed each with :data:`FAST_ISLAND_SEED`."""
    fast = FAST_SETTINGS.get(analysis)
    out = dict(settings)
    if not fast:
        return out
    for k, v in fast.items():
        if k in _LOOSER:
            out[k] = max(float(out.get(k, v)), v)
        elif k in _FEWER:
            out[k] = min(int(out.get(k, v)), v)
    if "minimum_passes" in out and "maximum_passes" in out:
        out["minimum_passes"] = min(out["minimum_passes"], out["maximum_passes"])
    if isinstance(out.get("mesh_size"), dict) and out["mesh_size"]:
        out["mesh_size"] = {k: v * FAST_MESH_FACTOR for k, v in out["mesh_size"].items()}
    elif analysis in FAST_MESH_SEED:
        out["mesh_size"] = dict(FAST_MESH_SEED[analysis])
    if analysis in FAST_MESH_SEED:
        for n in islands:
            out["mesh_size"].setdefault(f"*_signal_{int(n)}", FAST_ISLAND_SEED)
    if int(out.get("sweep_count", 0)) > FAST_SWEEP_POINTS:
        out["sweep_count"] = FAST_SWEEP_POINTS
    return out


def tighter_or_equal(old: dict, new: dict) -> bool:
    """Whether solver settings ``old`` are at least as tight as ``new``: the same keys and values except that each
    convergence criterion of ``old`` is ≤ ``new``'s, each pass count ≥ and each mesh seed ≤ (e.g. a full solve vs the
    fast settings of the same job: its results can stand in for a fast re-run)."""
    for k in set(old) | set(new):
        a, b = old.get(k), new.get(k)
        if a == b:
            continue
        if a is None or b is None:  # e.g. an unseeded run vs a seeded one: not comparable (unseeded early passes
            # can miss the qubit entirely), so it does not stand in
            return False
        if k in _LOOSER:
            ok = float(a) <= float(b)
        elif k in _FEWER:
            ok = int(a) >= int(b)
        elif k == "mesh_size" and isinstance(a, dict) and isinstance(b, dict):
            ok = set(a) == set(b) and all(a[x] <= b[x] for x in a)
        elif k == "sweep_count":
            ok = int(a) >= int(b)
        else:
            ok = False
        if not ok:
            return False
    return True


# pyEPR post-process defaults (KQC run_pyepr_t1_estimate.py inputs)
PYEPR_DEFAULTS = {
    "substrate_loss_tangent": 1e-6,
    "dielectric_surfaces": {
        "layerMA": {"tan_delta_surf": 1e-3, "th": 3e-9, "eps_r": 10},
        "layerMS": {"tan_delta_surf": 1e-3, "th": 3e-9, "eps_r": 10},
        "layerSA": {"tan_delta_surf": 1e-3, "th": 3e-9, "eps_r": 10},
    },
}


def solver_of(analysis: str) -> str:
    builtin = {"q3d": "ansys", "hfs": "ansys", "eig": "ansys", "elm": "elmer", "pal": "palace"}
    if analysis in DEFAULT_SETTINGS:
        return builtin[analysis[:3]]
    from quantcore_circuits.plugins import analysis_plugins  # pylint: disable=import-outside-toplevel

    return analysis_plugins()[analysis].solver


def export_job(setup: SimSetup, job_dir: str | Path, overwrite: bool = False, fast: bool | None = None,
               **settings) -> Path:
    """Write the job directory for ``setup`` (:func:`_export_job`); marks the dashboard's Render step running → done /
    failed with the job name (nested inside :func:`hfss.render`, only the outer render marks it)."""
    from quantcore_circuits import track as _track  # pylint: disable=import-outside-toplevel

    with _track.stage("render", f"export {Path(job_dir).name}") as st:
        out = _export_job(setup, job_dir, overwrite, fast, **settings)
        st.note = "job exported"
        return out


def _export_job(setup: SimSetup, job_dir: str | Path, overwrite: bool = False, fast: bool | None = None,
                **settings) -> Path:
    """Write the job directory for ``setup``. ``settings`` override :data:`DEFAULT_SETTINGS` for the analysis.
    ``fast`` (None: :func:`fem_fast`): loosen the result to :func:`fast_settings` (a whole-chip test run; recorded
    as ``"fem_fast": true`` in ``job.json``)."""
    job_dir = Path(job_dir)
    if job_dir.exists():
        if not overwrite:
            raise FileExistsError(f"{job_dir} exists; pass overwrite=True to replace it")
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)
    analysis = setup.analysis
    plugin = None
    if analysis not in DEFAULT_SETTINGS:
        from quantcore_circuits.plugins import analysis_plugins  # pylint: disable=import-outside-toplevel

        plugin = analysis_plugins()[analysis]
    defaults = plugin.defaults if plugin else DEFAULT_SETTINGS[analysis]
    cfg = {**defaults, **group_settings(setup, defaults), **settings}
    is_fast = fem_fast(fast) and analysis in FAST_SETTINGS
    if is_fast:
        cfg = fast_settings(analysis, cfg, _junction_islands(setup))
    # mesh seeds by name (the KLayout Simulate dialog): "gap_seed" µm on the CPW gaps, "island_seed" µm on the
    # junction islands (what a fast run seeds by itself); None / 0 = no seed
    gap_seed, island_seed = cfg.pop("gap_seed", None), cfg.pop("island_seed", None)
    if gap_seed or island_seed:
        seeds = dict(cfg.get("mesh_size") or {})
        if gap_seed:
            seeds[f"{get_pdk(setup.design.pdk).face}_gap"] = float(gap_seed)
        if island_seed:
            for n in _junction_islands(setup):
                seeds[f"*_signal_{int(n)}"] = float(island_seed)
        cfg["mesh_size"] = seeds
    ansys_exe = cfg.pop("ansys_executable", None)
    sim = setup.simulation
    if plugin is None and solver_of(analysis) in ("ansys", "elmer"):
        from quantcore_circuits.kqc_files import ensure_kqc_scripts  # pylint: disable=C0415

        ensure_kqc_scripts()  # a pip-installed kqcircuits ships no scripts/ folder (qcc kqc-files)
    if solver_of(analysis) == "ansys":
        from quantcore_circuits.sim_tools.ansys import configure_kqc_ansys  # pylint: disable=C0415

        configure_kqc_ansys(ansys_exe)

    if plugin is not None:
        plugin.export(setup, job_dir, **cfg)
    elif analysis == "q3d_cmatrix":
        from kqcircuits.simulations.export.ansys.ansys_export import export_ansys  # pylint: disable=C0415

        export_ansys(
            [sim],
            path=job_dir,
            ansys_tool="q3d",
            exit_after_run=True,
            post_process=PostProcess("produce_cmatrix_table.py", command=_python()),
            **cfg,
        )
    elif analysis in ("hfss_eigenmode", "eigenmode_epr"):
        from kqcircuits.simulations.export.ansys.ansys_export import export_ansys  # pylint: disable=C0415

        extra = {}
        if analysis == "eigenmode_epr":
            # "pyepr" makes KQC draw a Junction<n> line over each junction (line voltage → EPR). KQC's own post-process
            # (run_pyepr_t1_estimate.py) is NOT used: it attaches to any running AEDT over COM and quits it at the
            # end. qcc_solve.py evaluates pyEPR's field integrals in its own batch AEDT instead (aedt_scripts).
            epr_options = {**PYEPR_DEFAULTS, **cfg.pop("pyepr", {})}
            extra = {"simulation_flags": ["pyepr"]}
        export_ansys([sim], path=job_dir, ansys_tool="eigenmode", exit_after_run=True, **extra, **cfg)
    elif analysis == "hfss_driven":
        from kqcircuits.simulations.export.ansys.ansys_export import export_ansys  # pylint: disable=C0415

        if int(cfg.get("sweep_count", 0)) > MAX_SWEEP_POINTS:  # AEDT refuses the sweep (seen on 2024 R1)
            raise ValueError(f"sweep_count {cfg['sweep_count']} > {MAX_SWEEP_POINTS}: AEDT allows at most 25000 points")
        export_ansys([sim], path=job_dir, ansys_tool="hfss", exit_after_run=True, **cfg)
    elif analysis == "elmer_cap":
        from kqcircuits.simulations.export.elmer.elmer_export import export_elmer  # pylint: disable=C0415
        from kqcircuits.simulations.export.elmer.mesh_size_helpers import refine_metal_edges  # pylint: disable=C0415

        workflow = {"python_executable": _python(), "n_workers": 1, "elmer_n_processes": -1, "gmsh_n_threads": -1}
        export_elmer(
            [sim],
            path=job_dir,
            tool="capacitance",
            workflow=workflow,
            mesh_size={"global_max": 100.0, **refine_metal_edges(4.0)},
            **cfg,
        )
    elif analysis in ("palace_cap", "palace_eig"):
        from quantcore_circuits.sim_tools.palace import export_palace  # pylint: disable=C0415

        export_palace(setup, job_dir, **cfg)
    else:  # pragma: no cover - guarded by builder
        raise ValueError(analysis)

    if solver_of(analysis) == "ansys":
        _add_tool_key(job_dir, sim.name)
        _ansys_launchers(job_dir, sim.name, ansys_exe)
        if analysis != "q3d_cmatrix":  # Q3D: AutoIdentifyNets makes each overlapping piece its own net (AEDT 2024 R1)
            _split_gds_records(setup, job_dir / f"{sim.name}.gds")
    if not (job_dir / "simulation.oas").exists():
        export_simulation_oas([sim], job_dir)
    if analysis == "eigenmode_epr":
        cfg = {**cfg, "pyepr": epr_options}
    write_job_json(setup, job_dir, cfg)
    if is_fast:
        update_job(job_dir, fem_fast=True)
    return job_dir


def _split_gds_records(setup: SimSetup, gds: Path) -> None:
    """HFSS jobs: GDS polygons above the XY record limit (C8; after the builder's bend simplification only holes are
    left, e.g. flux-trap rows) → overlapping pieces of one conductor (:func:`~.builder.split_large_gds_polygons`);
    recorded in ``geometry.gds_polygons_split`` and a note. HFSS makes every metal sheet PEC, so the pieces act as one
    conductor (rendered in AEDT 2024 R1: imported, PerfE on all pieces). Not for Q3D: its ``AutoIdentifyNets`` keeps
    overlapping pieces as separate nets (same render), so a Q3D job keeps such a polygon whole (checker warning)."""
    from quantcore_circuits.sim_tools.builder import GDS_MAX_POINTS, split_large_gds_polygons  # pylint: disable=C0415

    if not gds.exists():
        return
    n = split_large_gds_polygons(gds)
    if n:
        setup.geometry["gds_polygons_split"] = n
        note = (f"{n} polygon(s) still above {GDS_MAX_POINTS} points (holes, not bends: e.g. flux-trap holes) written "
                "to the GDS as overlapping pieces of the same conductor (outline unchanged)")
        if note not in setup.notes:
            setup.notes.append(note)


def _junction_islands(setup: SimSetup) -> list[int]:
    """KQC excitation numbers of the nets the junction ports connect (the qubit islands)."""
    by_name = {v: k for k, v in setup.nets.items()}
    out = []
    for p in setup.ports:
        if p.kind == "junction" and (p.excitation or "") in by_name:
            out.append(int(by_name[p.excitation]))
    return sorted(set(out))


def group_settings(setup: SimSetup, defaults: dict) -> dict:
    """Solver settings from the sim group's ``settings``: keys of the analysis defaults (plus ``mesh_size``,
    ``pyepr``), and a nested ``{"<analysis>": {...}}`` dict for that analysis only. Builder options (``airbridges``)
    and settings of other analyses are left out."""
    from quantcore_circuits.sim_tools.builder import group_spec  # pylint: disable=import-outside-toplevel

    try:
        raw = dict(group_spec(setup.design, setup.group).settings or {})
    except ValueError:
        return {}
    allowed = set(defaults)
    if solver_of(setup.analysis) == "ansys":
        allowed.add("mesh_size")  # KQC AnsysSolution: {layer pattern: max element length µm}
    if setup.analysis == "eigenmode_epr":
        allowed.add("pyepr")
    out = {k: v for k, v in raw.items() if k in allowed}
    nested = raw.get(setup.analysis)
    if isinstance(nested, dict):
        out.update(nested)
    return out


def _group_select(setup: SimSetup) -> list[str] | None:
    """The group's selection (None for the built-in whole-chip ``chip`` group)."""
    from quantcore_circuits.sim_tools.builder import CHIP_GROUP, group_spec  # pylint: disable=import-outside-toplevel

    if setup.group == CHIP_GROUP and setup.group not in setup.design.sim_groups:
        return None
    return list(group_spec(setup.design, setup.group).select)


def write_job_json(setup: SimSetup, job_dir: Path, settings: dict) -> Path:
    box = setup.box
    data = {
        "schema": JOB_SCHEMA,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "design": setup.design.name,
        "design_hash": design_hash(setup.design),
        "group": setup.group,
        # subset read-back (additive): this group's own hash, what it selected, which routes stayed in the geometry
        "group_hash": group_hash(setup.design, setup.group),
        "select": _group_select(setup),
        "routes_in_sim": list(getattr(setup, "routes", []) or []),
        "analysis": setup.analysis,
        "solver": solver_of(setup.analysis),
        "simulation_name": setup.simulation.name,
        "settings": settings,
        "box_um": [box.left, box.bottom, box.right, box.top] if box else None,
        "ports": [vars(p) for p in setup.ports],
        "nets": {str(k): v for k, v in sorted(setup.nets.items())},
        "waveguide_length_um": setup.waveguide_length,
        "geometry": getattr(setup, "geometry", {}),
        "notes": getattr(setup, "notes", []),
        "versions": tool_versions(setup.design.pdk),
        "status": "exported",
    }
    path = job_dir / "job.json"
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def read_job(job_dir: str | Path) -> dict:
    return json.loads((Path(job_dir) / "job.json").read_text(encoding="utf-8"))


def update_job(job_dir: str | Path, **fields) -> dict:
    data = read_job(job_dir)
    data.update(fields)
    (Path(job_dir) / "job.json").write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return data


def _add_tool_key(job_dir: Path, sim_name: str) -> None:
    """KQC main's ``produce_cmatrix_table.py`` reads ``data["tool"]`` but ``export_ansys`` writes ``ansys_tool``."""
    path = job_dir / f"{sim_name}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if "tool" not in data and "ansys_tool" in data:
            data["tool"] = data["ansys_tool"]
            path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def _ansys_launchers(job_dir: Path, sim_name: str, executable=None) -> None:
    """qcc AEDT scripts + launchers that solve in a *new* non-graphical AEDT (never one that is already open) and
    collect the results: ``simulation.bat`` (replaces KQC's, which ran AEDT with its GUI and, for pyEPR jobs, a
    post-process that quits whatever AEDT it attached to) and ``simulation.sh`` (Linux server)."""
    from quantcore_circuits.sim_tools.aedt_scripts import SOLVE_SCRIPT, write_scripts  # pylint: disable=C0415
    from quantcore_circuits.sim_tools.ansys import default_executable, find_ansys_executable  # pylint: disable=C0415

    write_scripts(job_dir)
    exe = Path(executable) if executable else (find_ansys_executable() or default_executable())
    flag = "SF6694_NON_GRAPHICAL_COMMAND_EXECUTION"
    collect = "from quantcore_circuits.analysis.results import collect_results; collect_results('.')"
    run = f'-ng -features={flag} -RunScriptAndExit "scripts/{SOLVE_SCRIPT}" -ScriptArgs "{sim_name}.json"'
    bat = [
        "@echo off",
        "rem qcc: solve in a separate non-graphical AEDT, then collect results/results.json",
        f"set ANSYSEM_FEATURE_{flag}_ENABLE=1",
        f'"{exe}" {run}',
        f'{_python()} -c "{collect}"',
    ]
    (job_dir / "simulation.bat").write_text("\r\n".join(bat) + "\r\n", encoding="utf-8", newline="")
    linux_exe = exe if os.name != "nt" else default_executable_linux()
    sh = [
        "#!/bin/bash",
        "# qcc: solve in a separate non-graphical AEDT, then collect results/results.json",
        'cd "$(dirname "$0")"',
        f"export ANSYSEM_FEATURE_{flag}_ENABLE=1",
        f'"${{QCC_ANSYS_EXECUTABLE:-{linux_exe}}}" {run}',
        f'"${{QCC_PYTHON:-python3}}" -c "{collect}"',
    ]
    (job_dir / "simulation.sh").write_text("\n".join(sh) + "\n", encoding="utf-8", newline="")


def default_executable_linux(version: int | None = None) -> str:
    from quantcore_circuits.sim_tools.ansys import TARGET_VERSION  # pylint: disable=import-outside-toplevel

    return f"/ansys_inc/v{version or TARGET_VERSION}/AnsysEM/ansysedt"


def _python() -> str:
    """Python used by post-process steps inside the job (this environment, so pyEPR/pandas are available)."""
    return f'"{sys.executable}"'

"""Render a design into an Ansys HFSS / Q3D project (geometry, materials, ports, Lj boundaries), and solve it.

``render`` = ``build_simulation`` → KQC ``export_ansys`` job → one batch AEDT run of ``scripts/qcc_render.py``
(:mod:`.aedt_scripts`: KQC's ``import_simulation_geometry.py`` + qcc port fix-ups + π-model/reports, saved as
``<sim>_project.aedt``, no solve). ``solve`` runs ``scripts/qcc_solve.py`` on a job directory (import, fix-ups,
``AnalyzeAll``, KQC's ``export_solution_data.py``, qcc extras incl. the pyEPR field integrals) and then
:func:`~quantcore_circuits.analysis.results.collect_results`.

Where AEDT runs (``aedt=``, :mod:`.aedt_session`): ``"batch"`` (default, or ``QCC_AEDT_MODE``) a *separate*
non-graphical process (``-ng`` + pyaedt's feature flag); ``"gui"`` a new AEDT window that stays open after the run;
``"attach"`` inside an AEDT window that is already open (else as ``"gui"``), released afterwards with every project
left open. While a job runs, one progress line (step, pass, mesh, ΔF / ΔS / ΔC, mode frequencies) is printed every
``progress`` s (30; :mod:`.aedt_progress`). On a timeout only processes qcc started are killed (never an attached
session).

``group="chip"`` renders the whole chip (nothing cut; bond pads get 50 Ω lumped ports), any other name renders that
``sim_groups`` cut-out. Verified on AEDT 2024 R1 (v241, Windows).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from quantcore_circuits import track as _track
from quantcore_circuits.sim_tools.aedt_progress import echo, format_progress, read_progress
from quantcore_circuits.sim_tools.aedt_project import check_settings, project_info
from quantcore_circuits.sim_tools.aedt_scripts import (
    AEDT_SOURCE,
    COLLECT_SCRIPT,
    RENDER_SCRIPT,
    SCRIPT_MODE,
    SOLVE_SCRIPT,
    STATUS_FILE,
    write_scripts,
)
from quantcore_circuits.sim_tools.aedt_session import (
    AEDT_MODES,
    attach_command,
    find_sessions,
    launch_gui,
    pick_session,
    pid_alive,
    progress_interval,
    resolve_mode,
)
from quantcore_circuits.sim_tools.ansys import find_ansys_executable
from quantcore_circuits.sim_tools.builder import CHIP_GROUP, build_simulation
from quantcore_circuits.sim_tools.export import export_job, read_job, solver_of, update_job

__all__ = [
    "AEDT_MODES",
    "RENDER_SCRIPT",
    "SOLVE_SCRIPT",
    "RenderResult",
    "aedt_env",
    "aedt_summary",
    "check_project",
    "check_settings",
    "project_info",
    "render",
    "render_command",
    "render_status",
    "solve",
]

_RENDER_SOURCE = AEDT_SOURCE  # kept for callers of the old name
NG_FEATURE = "SF6694_NON_GRAPHICAL_COMMAND_EXECUTION"


@dataclass
class RenderResult:
    job_dir: Path
    project: Path | None
    log: Path
    returncode: int
    seconds: float
    summary: dict = field(default_factory=dict)
    status: list[str] = field(default_factory=list)
    results: dict = field(default_factory=dict)  # solve: collect_results output
    pid: int | None = None
    mode: str = "batch"  # where AEDT ran: batch | gui | attach (see aedt_session)
    owned: bool = True  # the AEDT process was started by qcc (False: an attached session)
    note: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.project is not None
            and self.project.exists()
            and not any(s == "error" or s.startswith("error ") for s in self.status)
            and "done" in self.status
        )


def render_command(
    job_dir: Path, executable: Path | None = None, graphical: bool = False, script: str = RENDER_SCRIPT
) -> list[str]:
    """``ansysedt`` command line for a qcc AEDT script (non-graphical by default, as pyaedt launches AEDT)."""
    exe = executable or find_ansys_executable()
    if exe is None:
        raise FileNotFoundError(
            "AEDT 2024 (ansysedt, v241+) not found; install Electronics Desktop or set QCC_ANSYS_EXECUTABLE"
        )
    sim_json = f"{read_job(job_dir)['simulation_name']}.json"
    cmd = [str(exe)]
    if not graphical:
        cmd += ["-ng", f"-features={NG_FEATURE}"]
    return cmd + ["-RunScriptAndExit", f"scripts/{script}", "-ScriptArgs", sim_json]


def aedt_env() -> dict:
    """Environment for batch AEDT runs (enables non-graphical script execution)."""
    return {**os.environ, f"ANSYSEM_FEATURE_{NG_FEATURE}_ENABLE": "1"}


def render_status(job_dir: str | Path, mode: str = "render") -> list[str]:
    path = Path(job_dir) / STATUS_FILE[mode]
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []


def aedt_summary(project: str | Path) -> dict:
    """Design type and name, solution type, variables, boundaries by type, nets and setups of an ``.aedt`` file."""
    info = project_info(project)
    if not info["designs"]:
        return {"models": 0}
    d = info["designs"][0]
    bounds = d["boundaries"]
    by_type: dict[str, int] = {}
    for b in bounds.values():
        by_type[b.get("BoundType", "?")] = by_type.get(b.get("BoundType", "?"), 0) + 1
    return {
        "design_type": d["design_type"],
        "design": d["name"],
        "solution_type": d["solution_type"],
        "variables": d["variables"],
        "boundaries": sorted(bounds),
        "boundary_types": by_type,
        "lumped_rlc": by_type.get("Lumped RLC", 0),
        "lumped_ports": by_type.get("Lumped Port", 0),
        "wave_ports": by_type.get("Wave Port", 0),
        "nets": {k: v["excitations"] for k, v in d["nets"].items() if v["type"] == "SignalNet"},
        "setups": sorted(d["setups"]),
        "materials": info["materials"],
        "models": len(info["designs"]),
    }


def check_project(job_dir: str | Path) -> dict:
    """Read the rendered project back and check it against the job: stack, ports/boundaries, nets, settings.

    Returns ``{"ok": bool, "checks": [{"check", "ok", "detail"}], "settings": [...]}``.
    """
    job_dir = Path(job_dir)
    job = read_job(job_dir)
    project = _project_path(job_dir)
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    if project is None:
        add("project saved", False, "no *_project.aedt")
        return {"ok": False, "checks": checks, "settings": []}
    info = project_info(project)
    d = info["designs"][0]
    analysis = job["analysis"]
    want_type = {"q3d_cmatrix": "Q3D Extractor"}.get(analysis, "HFSS")
    add("design type", d["design_type"] == want_type, f"{d['design_type']} / {d['solution_type']}")
    if want_type == "HFSS":
        want_sol = "Eigenmode" if analysis in ("hfss_eigenmode", "eigenmode_epr") else "HFSS Terminal Network"
        add("solution type", d["solution_type"] == want_sol, str(d["solution_type"]))
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    pdk_name = job.get("versions", {}).get("pdk", "").split("@", 1)[0]
    stack = get_pdk(pdk_name).stack if pdk_name else None
    subs = [p for p in d["parts"] if str(p["name"]).startswith("substrate")]
    for p in subs:
        mat = info["materials"].get(p["material"], {})
        eps = float(mat.get("permittivity", "nan"))
        thick = float(str(p.get("box", {}).get("ZSize", "nan")).replace("um", ""))
        if stack is not None:
            add(
                f"{p['name']} stack",
                abs(eps - stack.substrate_permittivity) < 1e-9 and abs(thick - stack.substrate_height) < 1e-6,
                f"{p['material']} εr {eps:g}, {thick:g} µm (PDK {stack.substrate_permittivity:g}, "
                f"{stack.substrate_height:g} µm)",
            )
    bounds = d["boundaries"]
    metal = {p["name"] for p in d["parts"] if str(p["name"]).startswith(("1t1_signal", "1t1_ground", "2b1_"))}
    sheet_type = "ThinConductor" if want_type == "Q3D Extractor" else "Perfect E"
    covered = {o for b in bounds.values() if b.get("BoundType") == sheet_type for o in b["objects"]}
    add(f"metal sheets {sheet_type}", metal and metal <= covered, f"{len(metal & covered)}/{len(metal)} sheets")
    rlc = {k: v for k, v in bounds.items() if v.get("BoundType") == "Lumped RLC"}
    sim_json = job_dir / f"{job['simulation_name']}.json"
    sim_ports = (
        {p["number"]: p for p in json.loads(sim_json.read_text(encoding="utf-8")).get("ports", [])}
        if sim_json.exists()
        else {}
    )

    def same(var, want):  # "1.2e-08H" / "2e-15farad" vs the exported port value (H, F)
        got = re.match(r"^\s*([-+0-9.eE]+)", str(d["variables"].get(var, "")))
        return want is None or (got is not None and abs(float(got.group(1)) - want) <= 1e-9 * abs(want))

    for port in job.get("ports", []):
        n, kind = port["number"], port["kind"]
        if analysis == "q3d_cmatrix":
            continue
        if kind == "junction":
            b = rlc.get(f"LumpRLC_jj_{n}")
            sp = sim_ports.get(n, {})
            ok = (
                b is not None
                and b.get("UseInduct")
                and b.get("Inductance") == f"Lj_{n}"
                and same(f"Lj_{n}", sp.get("inductance"))
                and same(f"Cj_{n}", sp.get("capacitance"))
            )
            add(
                f"port {n} {port['name']}: junction RLC",
                ok,
                f"L={d['variables'].get(f'Lj_{n}')} C={d['variables'].get(f'Cj_{n}')}" if ok else "missing",
            )
        elif analysis in ("hfss_eigenmode", "eigenmode_epr"):
            b = rlc.get(f"LumpRLC_term_{n}")
            ok = b is not None and b.get("UseResist") and str(b.get("Resistance", "")).startswith("50")
            add(f"port {n} {port['name']}: 50 Ω termination", ok, str(b.get("Resistance")) if b else "missing")
        else:  # driven: a terminal port (lumped on pads, wave port at the box edge)
            b = bounds.get(str(n))
            want = "Wave Port" if kind == "edge" else "Lumped Port"
            add(
                f"port {n} {port['name']}: {want}",
                b is not None and b.get("BoundType") == want,
                b.get("BoundType") if b else "missing",
            )
    if analysis == "q3d_cmatrix":
        signal = {k: v for k, v in d["nets"].items() if v["type"] == "SignalNet"}
        for exc, label in sorted(((int(k), v) for k, v in job.get("nets", {}).items())):
            net = f"Net{exc}"
            ok = net in signal and signal[net]["excitations"] == [exc]
            add(f"net {net} = {label}", ok, f"objects {signal.get(net, {}).get('objects')}")
        extra = sorted(set(signal) - {f"Net{k}" for k in job.get("nets", {})})
        add("no unlabelled signal nets", not extra, ", ".join(extra))
    settings = check_settings(info, analysis, job.get("settings", {}))
    bad = [r["key"] for r in settings if r["ok"] is False]
    add("settings read back", not bad, ", ".join(bad) or f"{sum(r['ok'] is True for r in settings)} keys")
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "settings": settings}


def _kill_tree(pid: int) -> None:
    """Kill the process tree qcc started (never anything else)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        import signal  # pylint: disable=import-outside-toplevel

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass


@dataclass
class AedtRun:
    code: int
    seconds: float
    pid: int | None  # the AEDT process (batch / gui) or the attached session
    mode: str = "batch"
    owned: bool = True
    note: str = ""


def _finished(status_file: Path, grace: float = 3.0) -> bool:
    """The qcc script has ended (``end`` line; or ``done`` / ``error`` and no write for ``grace`` s)."""
    if not status_file.exists():
        return False
    lines = status_file.read_text(encoding="utf-8", errors="replace").splitlines()
    if "end" in lines:
        return True
    return ("done" in lines or "error" in lines) and time.time() - status_file.stat().st_mtime > grace


def run_aedt_mode(
    job_dir: Path,
    script: str,
    executable: str | Path | None = None,
    aedt: str | None = None,
    timeout: float | None = None,
    log_name: str = "render.log",
    progress: float | None = None,
    aedt_pid: int | None = None,
    graphical: bool = False,
) -> AedtRun:
    """Run ``scripts/<script>`` on ``job_dir`` in AEDT the ``aedt`` way (see the module docstring), printing a
    progress line every ``progress`` s; returns when the script has ended (a ``gui`` / ``attach`` window stays open)."""
    job_dir = Path(job_dir)
    mode = resolve_mode(aedt, graphical)
    every = progress_interval(progress)
    status_mode = SCRIPT_MODE.get(script, "render")
    status_file = job_dir / STATUS_FILE[status_mode]
    status_file.unlink(missing_ok=True)  # a stale file would read as "finished"
    job = read_job(job_dir)
    sim_json = f"{job['simulation_name']}.json"
    log_path = job_dir / log_name
    session = None
    note = ""

    def say(msg):
        if every:
            echo(f"[aedt] {msg}")

    if mode == "attach":
        session = pick_session(find_sessions(), aedt_pid)
        if session is None:
            note = "no AEDT window open: opened a new one (as aedt='gui')"
            say(note)
            mode = "gui"
    t0 = time.time()
    proc, pid, owned = None, None, True
    with log_path.open("w", encoding="utf-8") as log:
        try:
            if mode == "batch":
                cmd = render_command(job_dir, Path(executable) if executable else None, script=script)
                proc = subprocess.Popen(  # noqa: S603
                    cmd,
                    cwd=job_dir,
                    env=aedt_env(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                )
                pid = proc.pid
                say(f"{status_mode} {job_dir.name}: new non-graphical AEDT pid {pid} (log {log_path.name})")
            elif mode == "gui":
                exe = Path(executable) if executable else find_ansys_executable()
                if exe is None:
                    raise FileNotFoundError("AEDT 2024 (ansysedt, v241+) not found; set QCC_ANSYS_EXECUTABLE")
                pid = launch_gui(exe, job_dir, script, sim_json)
                if pid is None:
                    raise OSError("the new AEDT window did not start (no ansysedt process with this job's script)")
                say(f"{status_mode} {job_dir.name}: new AEDT window pid {pid}; watch it there (it stays open)")
            else:
                owned = False
                pid = session.pid
                project = f"{job['simulation_name']}_project"
                cmd = attach_command(session, job_dir / "scripts" / script, str(job_dir / sim_json), project)
                proc = subprocess.Popen(cmd, cwd=job_dir, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603
                say(f"{status_mode} {job_dir.name}: attached to {session.describe()}; watch the project {project} "
                    "there (released afterwards, left open)")
        except OSError as e:
            log.write(f"\n[qcc aedt] {type(e).__name__}: {e}\n")
            say(f"could not start ({mode}): {e}")
            return AedtRun(-1, time.time() - t0, pid, mode, owned, str(e))
        # the pid of what qcc started (never the pid of an attached session: nobody should kill that one)
        (job_dir / f"{log_name}.pid").write_text(str(proc.pid if mode == "attach" else pid), encoding="utf-8")
        label = f"{mode} pid {pid}"
        next_line = t0 + every if every else None
        code = None
        while code is None:
            time.sleep(0.5)
            now = time.time()
            if proc is not None and proc.poll() is not None:
                code = proc.returncode
            elif mode == "gui" and _finished(status_file):
                code = 0
            elif mode == "gui" and not pid_alive(pid):
                code, note = 1, "the AEDT window was closed before the script ended"
            elif mode == "attach" and _finished(status_file, 30.0):
                proc.kill()  # the helper only; the script has ended inside the session
                code = 0
            elif timeout and now - t0 > timeout:
                if mode == "attach":
                    proc.kill()
                    note = (f"timeout after {timeout:.0f} s: stopped waiting (helper killed); the run goes on in "
                            f"the attached AEDT pid {pid}: stop it there if needed")
                else:
                    _kill_tree(pid)
                    if proc is not None:
                        proc.wait()
                    note = f"timeout after {timeout:.0f} s: killed own process tree {pid}"
                log.write(f"\n[qcc aedt] {note}\n")
                code = -1
            if next_line is not None and (code is not None or now >= next_line):
                echo(format_progress(read_progress(job_dir, status_mode), now - t0, label))
                next_line = now + every
    if mode != "batch" and code == 0 and "done" not in render_status(job_dir, status_mode):
        code = 1
    if note:
        say(note)
    return AedtRun(code, time.time() - t0, pid, mode, owned, note)


def run_aedt(
    job_dir: Path,
    script: str,
    executable: str | Path | None = None,
    graphical: bool = False,
    timeout: float | None = None,
    log_name: str = "render.log",
    aedt: str | None = None,
    progress: float | None = None,
) -> tuple[int, float, int | None]:
    """:func:`run_aedt_mode` as (return code, seconds, pid) (``graphical=True`` = ``aedt="gui"``)."""
    r = run_aedt_mode(job_dir, script, executable, aedt, timeout, log_name, progress, graphical=graphical)
    return r.code, r.seconds, r.pid


def render(
    source,
    group: str = CHIP_GROUP,
    analysis: str = "eigenmode_epr",  # decision #31: eigenmode/EPR is the default
    job_dir: str | Path | None = None,
    jobs_root: str | Path = "build/jobs",
    overwrite: bool = True,
    solve: bool = False,
    open_gui: bool = False,
    graphical: bool = False,
    timeout: float | None = None,
    executable: str | Path | None = None,
    airbridges: bool | None = None,
    aedt: str | None = None,
    progress: float | None = None,
    aedt_pid: int | None = None,
    **settings,
) -> RenderResult:
    """Build ``group`` of ``source`` and render it into an AEDT project (see module docstring); ``solve=True`` also
    solves it and collects the results. ``timeout`` (s) defaults to 30 min for a render and 6 h for a solve; on a
    timeout only the AEDT process tree started here is killed. ``airbridges`` keeps (True) or drops (default, or the
    group's ``settings["airbridges"]``) airbridge geometry; ``settings`` override the solver defaults. ``aedt``:
    ``"batch"`` | ``"gui"`` | ``"attach"`` (module docstring); ``progress``: seconds between progress lines."""
    if timeout is None:
        timeout = 6 * 3600 if solve else 1800
    if solver_of(analysis) != "ansys":
        raise ValueError(f"{analysis} is not an Ansys analysis")
    with _track.stage("render", Path(job_dir).name if job_dir else f"{group}_{analysis}") as st:
        setup = build_simulation(source, group, analysis, airbridges=airbridges)
        job_dir = Path(job_dir or Path(jobs_root) / setup.simulation.name).resolve()
        export_job(
            setup, job_dir, overwrite=overwrite, **({"ansys_executable": executable} if executable else {}), **settings
        )
        if solve:
            res = solve_job(
                job_dir,
                executable=executable,
                graphical=graphical,
                timeout=timeout,
                open_gui=open_gui,
                aedt=aedt,
                progress=progress,
                aedt_pid=aedt_pid,
            )
            if not res.ok:
                st.fail(f"solve failed (see {res.log})")
            return res
        write_scripts(job_dir)
        run = run_aedt_mode(job_dir, RENDER_SCRIPT, executable, aedt, timeout, "render.log", progress, aedt_pid, graphical)
        project = _project_path(job_dir)
        result = RenderResult(
            job_dir,
            project,
            job_dir / "render.log",
            run.code,
            run.seconds,
            _summary(project),
            render_status(job_dir),
            pid=run.pid,
            mode=run.mode,
            owned=run.owned,
            note=run.note,
        )
        if not result.ok:
            st.fail(f"render failed (see {result.log})")
        st.note = f"rendered in {run.seconds:.0f} s"
        update_job(
            job_dir,
            status="rendered" if result.ok else "render_failed",
            render_seconds=round(run.seconds, 1),
            aedt_mode=run.mode,
        )
        if open_gui and result.ok and run.mode == "batch":  # gui / attach: the project is open in a window already
            open_project(project, executable)
        return result


def solve_job(
    job_dir: str | Path,
    executable: str | Path | None = None,
    graphical: bool = False,
    timeout: float | None = None,
    open_gui: bool = False,
    aedt: str | None = None,
    progress: float | None = None,
    aedt_pid: int | None = None,
) -> RenderResult:
    """Solve an exported Ansys job directory, then collect its results (``results.json``). ``aedt``: ``"batch"``
    (default: a new non-graphical AEDT) | ``"gui"`` (a new AEDT window, left open) | ``"attach"`` (the open AEDT
    window, else a new one); a progress line every ``progress`` s (default 30, 0 = quiet)."""
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel

    job_dir = Path(job_dir).resolve()
    write_scripts(job_dir)
    update_job(job_dir, status="solving", started=time.time())
    run = run_aedt_mode(job_dir, SOLVE_SCRIPT, executable, aedt, timeout, "solve.log", progress, aedt_pid, graphical)
    code, seconds = run.code, run.seconds
    status = render_status(job_dir, "solve")
    project = _project_path(job_dir)
    results = collect_results(job_dir)
    result = RenderResult(
        job_dir,
        project,
        job_dir / "solve.log",
        code,
        seconds,
        _summary(project),
        status,
        results,
        run.pid,
        run.mode,
        run.owned,
        run.note,
    )
    have = any(k in results for k in ("cmatrix", "eigenmodes", "sparams"))
    update_job(
        job_dir,
        status="done" if result.ok and have else "failed",
        returncode=code,
        solve_seconds=round(seconds, 1),
        finished=time.time(),
        aedt_mode=run.mode,
    )
    if open_gui and result.ok and run.mode == "batch":
        open_project(project, executable)
    return result


solve = solve_job


def collect_job(
    job_dir: str | Path,
    executable: str | Path | None = None,
    aedt: str | None = "batch",
    timeout: float | None = 1800.0,
    progress: float | None = None,
) -> RenderResult:
    """Re-export a solved job from its saved project as it is now (no import, no solve; e.g. after the setup was
    changed and solved again in AEDT), then collect the results. ``aedt="batch"`` opens the saved project in a new
    non-graphical AEDT (close it in your own AEDT first, or run ``scripts/qcc_collect.py`` there instead)."""
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel

    job_dir = Path(job_dir).resolve()
    project = _project_path(job_dir)
    if not project.exists():
        raise FileNotFoundError(f"{job_dir}: no saved project {project.name} (render or solve the job first)")
    write_scripts(job_dir)
    run = run_aedt_mode(job_dir, COLLECT_SCRIPT, executable, aedt, timeout, "collect.log", progress)
    results = collect_results(job_dir)
    return RenderResult(job_dir, project, job_dir / "collect.log", run.code, run.seconds, _summary(project),
                        render_status(job_dir, "collect"), results, run.pid, run.mode, run.owned, run.note)


def open_project(project: str | Path, executable: str | Path | None = None) -> subprocess.Popen:
    """Open ``project`` in a new AEDT GUI window (detached)."""
    exe = Path(executable) if executable else find_ansys_executable()
    if exe is None:
        raise FileNotFoundError("ansysedt not found")
    flags = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    return subprocess.Popen([str(exe), str(project)], cwd=Path(project).parent, creationflags=flags)  # noqa: S603


def _project_path(job_dir: Path) -> Path | None:
    hits = sorted(Path(job_dir).glob("*_project.aedt"))
    return hits[0] if hits else None


def _summary(project: Path | None) -> dict:
    return aedt_summary(project) if project is not None and project.exists() else {}

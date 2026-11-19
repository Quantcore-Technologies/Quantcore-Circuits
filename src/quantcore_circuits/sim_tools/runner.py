"""Run simulation jobs locally or through a filesystem queue (lab server).

Local run: executes the job's launcher — Ansys: ``ansysedt -ng … -RunScriptAndExit scripts/qcc_solve.py`` in a new
batch AEDT (:mod:`.aedt_scripts`; never attaches to an open AEDT); Elmer: KQC ``simulation.bat``/``.sh``; Palace:
``run_palace.sh`` — then collects results into ``results/results.json``. On a timeout only the process tree the
runner started is killed.

Queue (``qcc runner serve QUEUE``): ``QUEUE/pending/<job>`` → ``running/`` → ``done/`` | ``failed/``. Submitting
copies the job directory into ``pending/``. SLURM can replace :func:`run_job` later without changing the layout.

Ansys (verified with AEDT 2024 R1 on Windows, 2026-11-03): ``ansysedt -ng
-features=SF6694_NON_GRAPHICAL_COMMAND_EXECUTION -RunScriptAndExit scripts/qcc_solve.py -ScriptArgs <sim>.json`` with
``ANSYSEM_FEATURE_SF6694_NON_GRAPHICAL_COMMAND_EXECUTION_ENABLE=1`` (the way pyaedt launches non-graphical AEDT).
TODO(verify on the Linux server): the same under AEDT 2024 R2.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from quantcore_circuits.sim_tools.export import read_job, update_job

QUEUE_DIRS = ("pending", "running", "done", "failed")


def launcher_command(job_dir: Path) -> list[str]:
    job = read_job(job_dir)
    if job["solver"] == "palace":
        return ["bash", "run_palace.sh"]
    if job["solver"] != "ansys":
        return ["cmd", "/c", "simulation.bat"] if os.name == "nt" else ["bash", "simulation.sh"]
    from quantcore_circuits.sim_tools.aedt_scripts import SOLVE_SCRIPT, write_scripts  # pylint: disable=C0415
    from quantcore_circuits.sim_tools.ansys import find_ansys_executable  # pylint: disable=import-outside-toplevel

    if not (Path(job_dir) / "scripts" / SOLVE_SCRIPT).exists():
        write_scripts(job_dir)  # a job exported before the qcc AEDT scripts existed
    exe = find_ansys_executable() or Path("ansysedt")
    sim_json = f"{job['simulation_name']}.json"
    return [
        str(exe),
        "-ng",
        "-features=SF6694_NON_GRAPHICAL_COMMAND_EXECUTION",
        "-RunScriptAndExit",
        f"scripts/{SOLVE_SCRIPT}",
        "-ScriptArgs",
        sim_json,
    ]


def run_job(
    job_dir: str | Path,
    timeout: float | None = None,
    dry_run: bool = False,
    aedt: str | None = None,
    progress: float | None = None,
) -> dict:
    """Run the job synchronously; returns the updated job.json. Raises nothing for solver failures (see status).

    Ansys jobs with ``aedt="gui"`` / ``"attach"`` (or ``QCC_AEDT_MODE``) run through
    :func:`quantcore_circuits.sim_tools.hfss.solve_job` (a new AEDT window / the open one); batch Ansys jobs print
    a progress line every ``progress`` s (30; :mod:`.aedt_progress`)."""
    job_dir = Path(job_dir).resolve()
    cmd = launcher_command(job_dir)
    if dry_run:
        return {**read_job(job_dir), "command": cmd}
    ansys = read_job(job_dir)["solver"] == "ansys"
    if ansys:
        from quantcore_circuits.sim_tools.aedt_session import progress_interval, resolve_mode  # pylint: disable=C0415

        if resolve_mode(aedt) != "batch":
            from quantcore_circuits.sim_tools.hfss import solve_job  # pylint: disable=import-outside-toplevel

            solve_job(job_dir, timeout=timeout, aedt=aedt, progress=progress)
            return read_job(job_dir)
        every = progress_interval(progress)
    else:
        every = None
    update_job(job_dir, status="running", started=time.time(), command=cmd)
    log = (job_dir / "run.log").open("w", encoding="utf-8")
    try:
        env = {**os.environ, "ANSYSEM_FEATURE_SF6694_NON_GRAPHICAL_COMMAND_EXECUTION_ENABLE": "1"}
        proc = subprocess.Popen(  # noqa: S603
            cmd, cwd=job_dir, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt"
        )
        update_job(job_dir, pid=proc.pid)
        try:
            code = _wait(proc, job_dir, timeout, every)
        except subprocess.TimeoutExpired as e:
            from quantcore_circuits.sim_tools.hfss import _kill_tree  # pylint: disable=import-outside-toplevel

            _kill_tree(proc.pid)  # only the process tree this runner started
            proc.wait()
            log.write(f"\n[qcc runner] {type(e).__name__}: {e}; killed process tree {proc.pid}\n")
            code = -1
    except OSError as e:
        log.write(f"\n[qcc runner] {type(e).__name__}: {e}\n")
        code = -1
    finally:
        log.close()
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel

    results = collect_results(job_dir)
    ok = code == 0 and any(k in results for k in ("cmatrix", "eigenmodes", "epr", "sparams"))
    return update_job(job_dir, status="done" if ok else "failed", returncode=code, finished=time.time())


def _wait(proc: subprocess.Popen, job_dir: Path, timeout: float | None, every: float | None) -> int:
    """``proc.wait(timeout)``, printing an AEDT progress line every ``every`` s (None: just wait)."""
    if not every:
        return proc.wait(timeout=timeout)
    from quantcore_circuits.sim_tools.aedt_progress import echo, format_progress, read_progress  # pylint: disable=C0415

    t0 = time.time()
    while True:
        left = None if timeout is None else timeout - (time.time() - t0)
        if left is not None and left <= 0:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        try:
            code = proc.wait(timeout=every if left is None else min(every, left))
        except subprocess.TimeoutExpired:
            echo(format_progress(read_progress(job_dir), time.time() - t0, f"batch pid {proc.pid}"))
            continue
        echo(format_progress(read_progress(job_dir), time.time() - t0, f"batch pid {proc.pid}"))
        return code


def submit(job_dir: str | Path, queue: str | Path) -> Path:
    queue = Path(queue)
    for d in QUEUE_DIRS:
        (queue / d).mkdir(parents=True, exist_ok=True)
    target = queue / "pending" / Path(job_dir).name
    if target.exists():
        raise FileExistsError(f"{target} already queued")
    shutil.copytree(job_dir, target)
    update_job(target, status="queued", queued=time.time())
    return target


def serve(queue: str | Path, poll: float = 5.0, once: bool = False, log=print) -> None:
    """Process queued jobs one at a time (oldest first)."""
    queue = Path(queue)
    for d in QUEUE_DIRS:
        (queue / d).mkdir(parents=True, exist_ok=True)
    log(f"[qcc runner] serving {queue}")
    while True:
        pending = sorted((queue / "pending").iterdir(), key=lambda p: p.stat().st_mtime)
        if not pending:
            if once:
                return
            time.sleep(poll)
            continue
        job = pending[0]
        running = queue / "running" / job.name
        shutil.move(str(job), str(running))
        log(f"[qcc runner] running {job.name}")
        result = run_job(running)
        final = queue / ("done" if result["status"] == "done" else "failed") / job.name
        shutil.move(str(running), str(final))
        log(f"[qcc runner] {job.name}: {result['status']} -> {final}")
        if once:
            return


def queue_status(queue: str | Path) -> dict[str, list[str]]:
    queue = Path(queue)
    return {d: sorted(p.name for p in (queue / d).iterdir()) if (queue / d).exists() else [] for d in QUEUE_DIRS}


def job_summary(job_dir: str | Path) -> str:
    job = read_job(job_dir)
    res_path = Path(job_dir) / "results" / "results.json"
    res = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    have = [k for k in ("cmatrix", "eigenmodes", "epr", "sparams") if k in res]
    return f"{job['simulation_name']}: {job['status']} ({job['analysis']}, results: {', '.join(have) or 'none'})"

"""Automatic run tracking for the dashboard: hooks, FEM job progress, follow-mode server (fast, no browser)."""

import json
import os
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "q1_r1_feedline.json"


@pytest.fixture
def tracking(tmp_path):
    """A tracking session writing under ``tmp_path`` (no snapshots, no watcher thread work)."""
    from quantcore_circuits import track

    track.stop()
    s = track.start("unit", root=tmp_path, snapshots=False)
    yield s
    track.stop()


def _state(tmp_path, name="unit"):
    return json.loads((tmp_path / name / "state.json").read_text(encoding="utf-8"))


def test_run_is_one_object_per_directory(tmp_path):
    from quantcore_circuits.track import Run

    a = Run(EXAMPLE, tmp_path / "r", reset=True)
    b = Run(EXAMPLE, tmp_path / "r")  # a notebook's Run(...) and the tracking hooks share it
    assert a is b
    a.log("x")
    assert Run(EXAMPLE, tmp_path / "r", reset=True) is a and a.state["log"] == []


def test_model_only_run(tmp_path):
    from quantcore_circuits.track import Run

    run = Run(None, tmp_path / "m", name="lom_only")
    assert run.state["design"]["name"] == "lom_only" and run.state["schema"] == "qcc-state/0.1"


def test_tracking_is_a_noop_when_off():
    from quantcore_circuits import track

    track.stop()
    assert track.emit("layout", result=None, path=None) is None
    assert track.run_for(None) is None


def test_env_switch_starts_a_session(monkeypatch, tmp_path):
    from quantcore_circuits import track

    track.stop()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QCC_TRACK", "envrun")
    monkeypatch.setattr(track, "_ENV_CHECKED", False)
    try:
        s = track.session()
        assert s is not None and s.name == "envrun"
    finally:
        track.stop()


def test_layout_and_drc_hooks(tracking, tmp_path):
    from quantcore_circuits.assembly import build, write_layout
    from quantcore_circuits.assembly.drc import check

    result = build(EXAMPLE)
    write_layout(result, tmp_path / "chip.oas")
    check(result)
    st = _state(tmp_path)
    layout = next(s for s in st["steps"] if s["id"] == "layout")
    assert layout["status"] == "done" and "R1" in layout["summary"] and "DRC" in layout["summary"]
    assert st["design"]["name"] == "q1_r1_feedline" and st["currentStep"] == "layout"
    assert json.loads((tmp_path / "_live.json").read_text())["run"] == "unit"  # the pointer `qcc dashboard` follows


def test_fill_and_lom_hooks_record_values_targets_history(tracking, tmp_path):
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom import lom_from_design
    from quantcore_circuits.lom.simulate import simulate

    simulate(fill(lom_from_design(EXAMPLE).model, EXAMPLE))
    st = _state(tmp_path)
    assert st["circuit"] and st["circuit"]["branches"]
    assert st["targets"] and all(t["value"] is not None for t in st["targets"])
    assert st["goal"]["total"] == len(st["targets"])
    assert [s["status"] for s in st["steps"] if s["id"] in ("extract", "hamiltonian", "compare")] == ["done"] * 3
    assert len(st["history"]) == 1 and st["history"][0]["kind"] == "lom" and st["history"][0]["residuals"]
    assert st["cards"] and st["elements"]  # the Parameters tab
    assert any(p["id"] == "levels" for p in st["plots"])


def test_compare_hook_old_api(tracking, tmp_path):
    from quantcore_circuits.analysis.extract import compare

    compare({"Q1": {"f_q_GHz": 5.1}}, {"Q1": {"f_q_GHz": 5.12}})
    st = _state(tmp_path)
    assert st["targets"][0]["key"] == "Q1.f_q_GHz" and st["targets"][0]["value"] == 5.12


def test_quiet_suspends_the_automatic_hooks(tracking, tmp_path):
    from quantcore_circuits import track
    from quantcore_circuits.analysis.extract import compare

    with track.quiet():
        compare({"Q1": {"f_q_GHz": 5.1}}, {"Q1": {"f_q_GHz": 5.12}})
    assert not (tmp_path / "unit" / "state.json").exists() or _state(tmp_path)["targets"] == []


def test_hook_failures_never_raise(tracking):
    tracking.handle("lom", {"result": None, "filled": None})  # wrong payload: logged, not raised


def _job(root: Path, name: str, **fields):
    d = root / name
    d.mkdir(parents=True)
    job = {
        "design": "dsg",
        "group": "G",
        "analysis": "eigenmode_epr",
        "solver": "ansys",
        "status": "exported",
        "settings": {"maximum_passes": 14},
        **fields,
    }
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return d


CONV = """Setup : Setup1

==================
Number of Passes
Completed : 3
Maximum   : 14
Criterion : Max Delta Freq. %
Target    : 0.2
Current   : 9.1571
Converged : No
==================
Pass Number|Solved Elements|Max Delta Freq. %|
          1|           8419|              N/A|
          2|           9883|           49.839|
          3|          12828|           9.1571|
"""


def test_job_progress_states(tmp_path):
    from quantcore_circuits.track import scan_jobs

    jobs = tmp_path / "jobs"
    _job(jobs, "dsg_exported")
    live = _job(jobs, "dsg_live", status="solving", started=time.time() - 30)
    (live / "solve.log").write_text("SYS_ERROR noise\nAdaptive pass 3\n", encoding="utf-8")
    (live / "solve.log.pid").write_text(str(os.getpid()), encoding="utf-8")  # a live process
    (live / "dsg_live_project_convergence.txt").write_text(CONV, encoding="utf-8")
    dead = _job(jobs, "dsg_dead", status="solving", started=time.time() - 5000)
    (dead / "solve.log.pid").write_text("999999", encoding="utf-8")
    done = _job(jobs, "dsg_done", status="done", solve_seconds=120.5, finished=1.0e9)
    (done / "results").mkdir()
    (done / "results" / "results.json").write_text("{}", encoding="utf-8")
    _job(jobs, "other_design_job", design="other")

    by = {j["name"]: j for j in scan_jobs({"dsg"}, jobs, None)}
    assert set(by) == {"dsg_exported", "dsg_live", "dsg_dead", "dsg_done"}  # other designs' jobs are not shown
    assert by["dsg_exported"]["progress"] is None and by["dsg_exported"]["hasResults"] is False
    p = by["dsg_live"]["progress"]
    assert by["dsg_live"]["status"] == "solving"
    assert (p["pass"], p["maxPasses"], p["converged"], p["target"]) == (3, 14, False, 0.2)
    assert p["elements"][-1] == 12828 and p["delta"][-1] == pytest.approx(9.1571) and p["logTail"] == "Adaptive pass 3"
    assert 25 < p["elapsedS"] < 120
    assert by["dsg_dead"]["status"] == "interrupted" and by["dsg_dead"]["progress"]["stale"] is True
    assert by["dsg_done"]["hasResults"] is True and by["dsg_done"]["progress"]["elapsedS"] == 120.5


def test_kept_results_count_for_an_exported_job(tmp_path):
    from quantcore_circuits.track import scan_jobs

    jobs, keep = tmp_path / "jobs", tmp_path / "keep"
    _job(jobs, "dsg_q3d")
    kept = _job(keep, "dsg_q3d", status="done")
    (kept / "results").mkdir()
    (kept / "results" / "results.json").write_text("{}", encoding="utf-8")
    (job,) = scan_jobs({"dsg"}, jobs, keep)
    assert job["hasResults"] and job["source"] == "kept" and job["status"] == "done"


def test_watcher_marks_simulate_running_then_done(tmp_path):
    from quantcore_circuits import track
    from quantcore_circuits.track import Run

    track.stop()
    jobs_root = tmp_path / "build" / "jobs"  # next to the run directories
    s = track.start("w", root=tmp_path / "build", snapshots=False, watch=False)
    try:
        run = s.run_for(None, "dsg")  # a model-only run; the jobs of design "dsg" belong to it
        run.design_names.add("dsg")
        d = _job(jobs_root, "dsg_ALL_eigenmode_epr", status="solving", started=time.time())
        (d / "solve.log.pid").write_text(str(os.getpid()), encoding="utf-8")
        s._watch_jobs()  # noqa: SLF001  one watcher tick
        step = next(x for x in run.state["steps"] if x["id"] == "simulate")
        assert step["status"] == "running" and "solving" in step["summary"]
        job = json.loads((d / "job.json").read_text())
        (d / "job.json").write_text(json.dumps({**job, "status": "done", "solve_seconds": 3}), encoding="utf-8")
        (d / "results").mkdir()
        (d / "results" / "results.json").write_text("{}", encoding="utf-8")
        s._watch_jobs()  # noqa: SLF001
        assert next(x for x in run.state["steps"] if x["id"] == "simulate")["status"] == "done"
        assert Run(None, run.dir).state["jobs"][0]["hasResults"] is True
    finally:
        track.stop()


def test_follow_mode_server(tmp_path):
    from quantcore_circuits.review.server import live_run_dir, serve_live
    from quantcore_circuits.track import Run

    root = tmp_path / "build"
    root.mkdir()
    assert live_run_dir(root) is None
    server = serve_live(root, port=0, open_browser=False, background=True)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        waiting = json.loads(urllib.request.urlopen(f"{base}/api/state", timeout=5).read())
        assert waiting["design"]["name"] == "waiting for a run" and "track.start" in waiting["log"][0]["msg"]
        run = Run(EXAMPLE, root / "q1")
        run.log("hello")
        st = json.loads(urllib.request.urlopen(f"{base}/api/state", timeout=5).read())
        assert st["design"]["name"] == "q1_r1_feedline"  # the newest state.json
        (root / "q1" / "shots").mkdir()
        (root / "q1" / "shots" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        assert urllib.request.urlopen(f"{base}/files/shots/a.png", timeout=5).headers["Content-Type"] == "image/png"
        other = Run(EXAMPLE, root / "q2", name="q2")
        (root / "_live.json").write_text(json.dumps({"run": "q1"}), encoding="utf-8")
        assert live_run_dir(root).name == "q1"  # the pointer wins over mtimes
        (root / "_live.json").write_text(json.dumps({"run": other.dir.name}), encoding="utf-8")
        assert live_run_dir(root).name == "q2"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.aedt_fixture
def test_job_progress_reads_a_running_aedt_job_with_the_gui_live_reader(tmp_path):
    """While AEDT runs, the Progress column comes from ``aedt_progress.read_progress`` (EMConvData, per-pass .sd),
    not only from the convergence file AEDT writes at the end."""
    import shutil

    from quantcore_circuits.track import scan_jobs

    src = ROOT / "tests" / "data" / "aedt_2024r1" / "progress" / "eigenmode_epr"
    d = tmp_path / "jobs" / "dsg_eig"
    shutil.copytree(src, d)
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    job.update(design="dsg", status="solving", started=time.time() - 30)
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (d / "solve.log.pid").write_text(str(os.getpid()), encoding="utf-8")
    (j,) = scan_jobs({"dsg"}, tmp_path / "jobs", None)
    p = j["progress"]
    assert j["status"] == "solving" and (p["pass"], p["maxPasses"], p["criterion"]) == (17, 17, "ΔF")
    assert p["delta"][-1] == pytest.approx(0.448, abs=1e-3) and p["elements"][-1] == 170738
    assert p["modesGHz"][:2] == pytest.approx([5.2393, 6.6234], abs=1e-4)


def test_a_job_collecting_its_results_is_not_interrupted(tmp_path):
    """AEDT has exited (its pid is gone) and the status file ends with "end", but job.json still says "solving" while
    qcc collects the results: the dashboard shows it solving, not interrupted (seen on tutorial 00's eigenmode job)."""
    from quantcore_circuits.track import scan_jobs

    d = _job(tmp_path / "jobs", "dsg_fin", status="solving", started=time.time() - 200)
    (d / "solve.log.pid").write_text("999999", encoding="utf-8")
    (d / "qcc_solve_status.txt").write_text("step epr\ndone\nend\n", encoding="utf-8")
    (j,) = scan_jobs({"dsg"}, tmp_path / "jobs", None)
    assert j["status"] == "solving" and not (j["progress"] or {}).get("stale")
    (d / "qcc_solve_status.txt").write_text("step solve\n", encoding="utf-8")  # died mid-solve
    (j,) = scan_jobs({"dsg"}, tmp_path / "jobs", None)
    assert j["status"] == "interrupted"


def test_stopping_the_session_records_the_last_job_state(tmp_path):
    """q1_r1_loop (2026-11-14): its last optimiser solve finished within the watcher's last second and the dashboard
    kept showing it "running" after the script ended. ``track.stop()`` takes a last look at the jobs."""
    from quantcore_circuits import track

    track.stop()
    jobs = tmp_path / "build" / "jobs"
    d = _job(jobs, "unit_job", design="unit", status="running", started=time.time())
    s = track.start("unit", root=tmp_path / "build", snapshots=False, watch=False)
    run = s.run_for(None, "unit")
    run.state["design"] = {**(run.state.get("design") or {}), "name": "unit"}
    run.refresh_jobs(jobs, None)
    data = json.loads((d / "job.json").read_text(encoding="utf-8"))
    (d / "job.json").write_text(json.dumps({**data, "status": "done"}), encoding="utf-8")
    track.stop()
    by = {j["name"]: j["status"] for j in run.state.get("jobs") or []}
    assert by.get("unit_job") == "done", by


# ---- 2026-11-14 gaps: Feedback / Render step marks --------------------------------------------------------------
def _step(tmp_path, step_id, name="unit"):
    return next(s for s in _state(tmp_path, name)["steps"] if s["id"] == step_id)


def _simple_design():
    from quantcore_circuits.design import load_design

    return load_design(EXAMPLE)


def test_old_api_optimise_marks_feedback_done(tracking, tmp_path):
    import numpy as np  # noqa: F401

    from quantcore_circuits.optimise import get_knob, optimise

    d = _simple_design()
    knob = next(
        f"{n}.{k}" for n, inst in d.instances.items() for k in inst.params if isinstance(inst.params[k], (int, float))
    )
    x0 = float(get_knob(d, knob))
    target = {f"{knob.split('.')[0]}.val": x0 * 1.02}
    qty = next(iter(target)).split(".")[1]

    def evaluate(design):
        return {knob.split(".")[0]: {qty: float(get_knob(design, knob))}}

    res = optimise(d, {knob: (x0 * 0.5, x0 * 2)}, target, evaluate, max_iter=4, log=lambda *_: None)
    assert res.converged
    st = _step(tmp_path, "feedback")
    assert st["status"] == "done" and "converged" in st["summary"]


def test_old_api_optimise_failure_marks_feedback_failed(tracking, tmp_path):
    from quantcore_circuits.optimise import optimise

    d = _simple_design()
    name, inst = next((n, i) for n, i in d.instances.items() if i.params)
    key = next(iter(inst.params))

    def boom(_design):
        raise RuntimeError("solver died")

    with pytest.raises(RuntimeError):
        optimise(d, {f"{name}.{key}": (0.0, 1e6)}, {f"{name}.x": 1.0}, boom, log=lambda *_: None)
    # the run exists only once an event arrived: the end event creates it through the named session
    st = _step(tmp_path, "feedback")
    assert st["status"] == "failed" and "solver died" in st["summary"]


def test_stage_marks_render_running_done_and_failed(tracking, tmp_path):
    from quantcore_circuits import track

    with track.stage("render", "jobA, jobB") as h:
        assert _step(tmp_path, "render")["status"] == "running"
        h.note = "2 job(s) exported"
    st = _step(tmp_path, "render")
    assert st["status"] == "done" and "jobA, jobB" in st["summary"] and "2 job" in st["summary"]
    with track.stage("render", "jobC") as h:
        h.fail("render failed")
    st = _step(tmp_path, "render")
    assert st["status"] == "failed" and "jobC" in st["summary"]
    with pytest.raises(ValueError):
        with track.stage("render", "jobD"):
            raise ValueError("bad")
    assert _step(tmp_path, "render")["status"] == "failed"


def test_nested_stage_marks_only_the_outermost(tracking, tmp_path):
    from quantcore_circuits import track

    with track.stage("render", "outer"):
        with track.stage("render", "inner export"):
            pass
        assert _step(tmp_path, "render")["status"] == "running"  # the inner end did not finish the render
    assert _step(tmp_path, "render")["status"] == "done"


def test_stage_is_a_noop_when_tracking_is_off():
    from quantcore_circuits import track

    track.stop()
    with track.stage("render", "x") as h:
        h.fail("ignored")


def test_export_job_marks_render(tracking, tmp_path):
    from quantcore_circuits.sim_tools import build_simulation, export_job

    setup = build_simulation(EXAMPLE, next(iter(_simple_design().sim_groups)), "q3d_cmatrix")
    export_job(setup, tmp_path / "jobs" / "unit_export", overwrite=True)
    st = _step(tmp_path, "render")
    assert st["status"] == "done" and "unit_export" in st["summary"]


def test_hfss_render_marks_render_failed_without_aedt(tracking, tmp_path, monkeypatch):
    """hfss.render marks Render running → failed (not stuck) when AEDT's batch run fails; no AEDT is started."""
    from quantcore_circuits.sim_tools import hfss

    class _Run:
        code, seconds, pid, mode, owned, note = 1, 0.1, None, "batch", True, ""

    monkeypatch.setattr(hfss, "run_aedt_mode", lambda *a, **k: _Run())
    monkeypatch.setattr(hfss, "write_scripts", lambda *a, **k: None)
    monkeypatch.setattr(hfss, "_summary", lambda *a, **k: {})
    monkeypatch.setattr(hfss, "render_status", lambda *a, **k: [])
    group = next(iter(_simple_design().sim_groups))
    r = hfss.render(EXAMPLE, group, "q3d_cmatrix", job_dir=tmp_path / "jobs" / "unit_render")
    assert not r.ok
    st = _step(tmp_path, "render")
    assert st["status"] == "failed" and "unit_render" in st["summary"]


def test_tutorial_before_after_helper_marks_feedback_done(tracking, tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "examples" / "tutorials"))
    try:
        import _tut as T
    finally:
        sys.path.pop(0)
    T.before_after_md({"len1": 4000.0, "cross1": 200.0}, {"len1": 3900.0, "cross1": 200.0})
    st = _step(tmp_path, "feedback")
    assert st["status"] == "done" and "len1" in st["summary"] and "1 knob" in st["summary"]


def test_loading_kept_results_marks_simulate_done(tracking, tmp_path):
    """RUN_FEM = False notebooks read earlier results: Simulate (never run here) must not stay pending."""
    from quantcore_circuits.analysis.extract import compare

    compare({"Q1": {"f_q_GHz": 5.1}}, {"Q1": {"f_q_GHz": 5.12}})
    st = _step(tmp_path, "simulate")
    assert st["status"] == "done" and "not re-run" in st["summary"]


def test_a_running_simulate_is_not_overwritten_by_loading_results(tracking, tmp_path):
    from quantcore_circuits.analysis.extract import compare

    s = tracking
    s._step(s.run_for(None, "unit"), "simulate", "running", "solving")  # noqa: SLF001
    compare({"Q1": {"f_q_GHz": 5.1}}, {"Q1": {"f_q_GHz": 5.12}})
    assert _step(tmp_path, "simulate")["status"] == "running"


def test_drawn_design_marks_synthesis_skipped(tracking, tmp_path):
    from quantcore_circuits.assembly import build, write_layout

    write_layout(build(EXAMPLE), tmp_path / "chip.oas")
    assert _step(tmp_path, "synthesis")["status"] == "skipped"

"""KLayout plugin: the cache and background loading of ``qcc components`` (qcache), a simulation run that outlives
KLayout (simrun) and the LOM / job Stop (jobs.cancel), without a KLayout window. The panel and menu are exercised by
the GUI probes."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kplugin" / "python"))

from qcc_kplugin import qcache, simrun  # noqa: E402


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(qcache, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(qcache, "LAYOUTS", tmp_path / "layouts")
    (tmp_path / "layouts").mkdir()
    (tmp_path / "layouts" / "a.py").write_text("x = 1", encoding="utf-8")
    monkeypatch.setattr(qcache, "_qcc", lambda: sys.executable)
    monkeypatch.setattr(qcache, "_env", lambda: dict(os.environ))
    qcache._MEM.clear()  # noqa: SLF001
    qcache._STATE.update({"key": None, "key_at": 0.0, "loaded": False})  # noqa: SLF001
    qcache.PENDING.clear()
    return tmp_path


def test_fetch_runs_once_then_comes_from_the_cache(cache):
    got = []
    qcache.fetch("list:x", ["-c", "import time; time.sleep(0.3); print('[1, 2]')"], got.append)
    assert got == [] and "list:x" in qcache.PENDING  # returned at once, the query runs in the background
    qcache.fetch("list:x", ["-c", "print('[9]')"], got.append)  # the same query: joins, does not start another
    qcache.wait(30)
    assert got == [[1, 2], [1, 2]]
    qcache.fetch("list:x", ["-c", "raise SystemExit(3)"], got.append)  # cached: answered at once, nothing started
    assert got[-1] == [1, 2] and not qcache.PENDING


def test_failed_query_is_not_cached(cache):
    got = []
    qcache.fetch("schema:Bad", ["-c", "raise SystemExit(3)"], got.append)
    qcache.wait(30)
    assert got == [None] and qcache.get("schema:Bad") is None


def test_cache_survives_a_restart_and_a_library_change_refreshes_it(cache):
    qcache.put("list:x", [1])
    qcache._MEM.clear()  # noqa: SLF001  (a new KLayout session: memory empty, the file is there)
    qcache._STATE.update({"key": None, "loaded": False})  # noqa: SLF001
    assert qcache.get("list:x") == [1]
    time.sleep(0.05)
    lib = cache / "layouts" / "a.py"
    lib.write_text("x = 2", encoding="utf-8")
    os.utime(lib, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))  # the library changed
    qcache._STATE.update({"key": None, "key_at": 0.0})  # noqa: SLF001
    assert qcache.get("list:x") is None


def test_bulk_schemas_fill_the_single_cell_entries(cache):
    code = "import json; print(json.dumps({'Xmon': {'schema': [{'name': 'a'}]}, 'Pad': {'schema': []}}))"
    qcache.fetch("schemas:quantcore", ["-c", code], bulk=True)
    qcache.wait(30)
    assert qcache.get("schema:Xmon") == [{"name": "a"}]
    assert qcache.get("schemas:quantcore") is True


# ---- a run that outlives its parent ---------------------------------------------------------------------------------
def test_detached_run_survives_its_parent(tmp_path):
    marker, log = tmp_path / "marker.txt", tmp_path / "run.log"
    child = f"import time; print('started', flush=True); time.sleep(1.5); open(r'{marker}', 'w').write('ok'); print('done in 2 s')"
    parent = (f"import sys; sys.path.insert(0, r'{ROOT / 'kplugin' / 'python'}'); import os; "
              f"from qcc_kplugin import simrun; "
              f"p = simrun.launch([sys.executable, '-c', {child!r}], r'{tmp_path}', dict(os.environ), r'{log}'); "
              f"print(p.pid)")
    out = subprocess.run([sys.executable, "-c", parent], capture_output=True, text=True, check=True)  # noqa: S603
    pid = int(out.stdout.strip())  # the parent has exited by now
    assert not marker.exists()
    end = time.time() + 20
    while not marker.exists() and time.time() < end:
        time.sleep(0.1)
    assert marker.read_text() == "ok" and "done in" in log.read_text()
    end = time.time() + 5
    while simrun.pid_alive(pid) and time.time() < end:
        time.sleep(0.1)
    assert not simrun.pid_alive(pid)


def test_outcome_from_status_file_and_log(tmp_path):
    log, status = tmp_path / "l.log", tmp_path / "s.json"
    rec = {"pid": 0, "log": str(log), "status": str(status)}
    log.write_text("simulating\n", encoding="utf-8")
    assert simrun.outcome(rec) == "failed"  # vanished without finishing
    log.write_text("simulating\ndone in 12 s: ok\n", encoding="utf-8")
    assert simrun.outcome(rec) == "done"
    status.write_text(json.dumps({"state": "failed"}), encoding="utf-8")
    assert simrun.outcome(rec) == "failed"
    status.write_text(json.dumps({"state": "cancelled"}), encoding="utf-8")
    assert simrun.outcome(rec) == "cancelled"
    assert simrun.PidProc({**rec}).poll() == 1
    assert simrun.pid_alive(os.getpid()) and not simrun.pid_alive(0)


def test_record_round_trip(tmp_path):
    assert simrun.read_record(tmp_path) is None
    simrun.write_record(tmp_path, {"pid": 5, "state": "running"})
    assert simrun.read_record(tmp_path)["pid"] == 5


def test_auto_run_saves_results_under_design_and_group_name(tmp_path):
    from quantcore_circuits import guiflow  # noqa: PLC0415

    design = tmp_path / "chip.json"
    design.write_text(json.dumps({"name": "chip", "instances": {}}), encoding="utf-8")
    job = tmp_path / "jobs" / "gui_sim_q1"
    (job / "results").mkdir(parents=True)
    (job / "results" / "results.json").write_text('{"group": "gui_sim_q1", "x": 1}', encoding="utf-8")
    (job / "job.json").write_text('{"group": "gui_sim_q1"}', encoding="utf-8")
    out = guiflow.save_results_copies(design, [job], say=lambda *_a: None)
    assert [p.name for p in out] == ["chip_gui_sim_q1_results.json"]
    assert out[0].parent == tmp_path / "build" / "chip" and json.loads(out[0].read_text())["x"] == 1


def test_lom_panel_shows_the_failed_route_warning():
    """A route that failed to build is replaced by its last good one in the LOM; the panel must say so."""
    from qcc_kplugin import dock

    note = ("WARNING: route R2 failed to build (segment 3 is 14.1 um but its bends need 112.8 um); "
            "using its last good route (1274.5 µm)")
    out = (f"  C  Cc_Q1  Q1.claw_n - gnd\n  note: {note}\nsrc/derive.py:26: RuntimeWarning: {note}\n"
           f"  plan = plan_for_lom(design, source)\nsrc/builder.py:87: RuntimeWarning: {note}\nwrote c.json\n")
    assert dock.lom_warnings(out) == [note]  # once, without the note: / file prefixes
    assert dock.lom_warnings("wrote c.json\nnote: Port_PAD_F: both ends on gnd (dropped)\n") == []

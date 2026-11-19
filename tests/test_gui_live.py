"""AEDT modes (batch / gui / attach), the live progress reader, and the KLayout window launcher.

No AEDT and no KLayout is started here: process starts, the attach helper and the window calls are replaced by fakes.
The progress reader runs on real AEDT 2024 R1 result files kept in ``tests/data/aedt_2024r1/progress/`` (the same
q1_r1_feedline runs as the other ``aedt_2024r1`` fixtures: Q3D 14 passes, eigenmode 17 passes, seeded driven 4 passes).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from quantcore_circuits.sim_tools import aedt_session as S
from quantcore_circuits.sim_tools import hfss
from quantcore_circuits.sim_tools.aedt_progress import format_progress, parse_em_conv, read_progress

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "tests" / "data" / "aedt_2024r1" / "progress"
EXE = Path(r"C:\Program Files\AnsysEM\v241\Win64\ansysedt.exe")


# ---- mode selection ------------------------------------------------------------------------------------------------
def test_mode_default_env_aliases_and_errors(monkeypatch):
    monkeypatch.delenv(S.ENV_MODE, raising=False)
    assert S.resolve_mode() == "batch"
    assert S.resolve_mode(graphical=True) == "gui"  # the old graphical flag
    monkeypatch.setenv(S.ENV_MODE, "attach")
    assert S.resolve_mode() == "attach"
    assert S.resolve_mode("batch") == "batch"  # an explicit choice wins over the environment
    assert S.resolve_mode("GUI") == "gui" and S.resolve_mode("ng") == "batch" and S.resolve_mode("connect") == "attach"
    with pytest.raises(ValueError, match="batch"):
        S.resolve_mode("server")


def test_progress_interval(monkeypatch):
    monkeypatch.delenv(S.ENV_PROGRESS, raising=False)
    assert S.progress_interval() == 30.0
    assert S.progress_interval(0) is None and S.progress_interval(5) == 5.0
    monkeypatch.setenv(S.ENV_PROGRESS, "0")
    assert S.progress_interval() is None


# ---- session discovery ---------------------------------------------------------------------------------------------
NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:2001           0.0.0.0:0              LISTENING       10140
  TCP    0.0.0.0:5531           0.0.0.0:0              LISTENING       28388
  TCP    127.0.0.1:8082         0.0.0.0:0              LISTENING       19956
  TCP    [::]:50051             [::]:0                 LISTENING       10140
  TCP    127.0.0.1:50051        127.0.0.1:61000        ESTABLISHED     10140
"""


def test_netstat_and_session_properties():
    ports = S.parse_netstat(NETSTAT)
    assert ports == {10140: [2001, 50051], 28388: [5531], 19956: [8082]}
    gui = S.AedtSession(10140, EXE, [str(EXE)], ports[10140], created=2.0)
    batch = S.AedtSession(28388, EXE, [str(EXE), "-ng", "-features=X", "-RunScriptAndExit", "scripts/qcc_solve.py"],
                          ports[28388], created=3.0)
    grpc = S.AedtSession(5, EXE, [str(EXE), "-grpcsrv", "127.0.0.1:50077"], [], created=1.0)
    assert gui.graphical and gui.port == 50051 and gui.version == 241 and "2024 R1" in gui.describe()
    assert not batch.graphical and batch.port is None
    assert grpc.port == 50077
    assert gui.plugin_dir == EXE.parent / "PythonFiles" / "DesktopPlugin"


def test_pick_session_never_picks_a_batch_job(monkeypatch):
    monkeypatch.delenv(S.ENV_PID, raising=False)
    old = S.AedtSession(1, EXE, [str(EXE)], [50051], created=1.0)
    new = S.AedtSession(2, EXE, [str(EXE)], [50052], created=5.0)
    batch = S.AedtSession(3, EXE, [str(EXE), "-ng"], [50053], created=9.0)
    assert S.pick_session([batch, new, old]) is new  # newest graphical one (find_sessions sorts newest first)
    assert S.pick_session([batch]) is None
    assert S.pick_session([batch, new, old], pid=1) is old
    with pytest.raises(LookupError, match="batch"):
        S.pick_session([batch, new], pid=3)
    with pytest.raises(LookupError, match="no AEDT process"):
        S.pick_session([new], pid=99)
    monkeypatch.setenv(S.ENV_PID, "1")
    assert S.pick_session([new, old]) is old


def test_gui_command_keeps_the_window_open():
    cmd = S.gui_command(EXE, "qcc_solve.py", "x.json")
    assert "-ng" not in cmd and "-RunScript" in cmd and "-RunScriptAndExit" not in cmd
    assert cmd[-2:] == ["-ScriptArgs", "x.json"]


def test_attach_helper_releases_and_never_quits():
    """The helper only connects, runs the script and releases; nothing in it (or in the AEDT script) quits AEDT."""
    import ast

    src = S.ATTACH_HELPER.read_text(encoding="utf-8")
    calls = {n.func.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and
             isinstance(n.func, ast.Attribute)}
    assert not calls & {"QuitApplication", "Shutdown", "CloseAllWindows"}
    assert {"Release", "RunScriptWithArguments", "CreateAedtApplication"} <= calls
    assert 'CreateAedtApplication("", a.port, False, False)' in src  # connect, never a new session
    from quantcore_circuits.sim_tools.aedt_scripts import AEDT_SOURCE

    assert "QuitApplication" not in AEDT_SOURCE and 'log("end")' in AEDT_SOURCE
    session = S.AedtSession(4242, EXE, [str(EXE)], [50051])
    cmd = S.attach_command(session, Path("C:/job/scripts/qcc_solve.py"), "C:/job/x.json", "x_project")
    assert cmd[:3] == [sys.executable, "-I", str(S.ATTACH_HELPER)]
    assert cmd[cmd.index("--port") + 1] == "50051" and cmd[cmd.index("--pid") + 1] == "4242"


# ---- progress reader -----------------------------------------------------------------------------------------------
@pytest.mark.aedt_fixture
def test_progress_eigenmode():
    p = read_progress(PROGRESS / "eigenmode_epr")
    assert (p["step"], p["finished"], p["failed"]) == ("epr", True, False)
    assert p["criterion"] == "ΔF" and p["pass"] == 17 and p["elements"] == 170738
    assert p["delta"] == pytest.approx(0.44804, abs=1e-5) and p["target"] == 0.1 and not p["converged"]
    assert [round(f, 3) for f in p["modes_GHz"]] == [5.239, 6.623]
    line = format_progress(p, 75.0, "batch pid 1")
    assert line.startswith("[aedt 1:15 batch pid 1] epr · pass 17/17 · 170 738 tets · ΔF 0.448 % (target 0.1 %)")


@pytest.mark.aedt_fixture
def test_progress_driven_and_q3d():
    d = read_progress(PROGRESS / "hfss_driven")
    assert (d["criterion"], d["pass"], d["max_passes"], d["elements"]) == ("ΔS", 4, 10, 359210)
    assert d["delta"] == pytest.approx(0.002614, rel=1e-3) and d["converged"] and d["modes_GHz"] == []
    q = read_progress(PROGRESS / "q3d_cmatrix")
    assert (q["criterion"], q["pass"], q["max_passes"], q["target"]) == ("ΔC", 14, 18, 0.5)
    assert q["element_unit"] == "triangles" and 0 < q["delta"] < 0.5
    assert "ΔC 0.378 % (target 0.5 %)" in format_progress(q)


@pytest.mark.aedt_fixture
def test_progress_mid_run_and_stuck_hint(tmp_path):
    """A Q3D job half way: passes 1–5 on disk, the status file at "step solve" → running, pass 5/18."""
    job = tmp_path / "q3d"
    shutil.copytree(PROGRESS / "q3d_cmatrix", job)
    for f in job.rglob("*_MCAP*_V0.sd"):
        n = int(f.name.split("_MCAP")[1].split("_")[0])
        if n == 0 or n > 5:
            f.unlink()
    (job / "qcc_solve_status.txt").write_text("python 2.7.4 | aedt 2024.1.0 | mode solve\nstep import\nok import 9 s\n"
                                               "saved x_project.aedt\nstep solve\n", encoding="utf-8")
    p = read_progress(job)
    assert (p["step"], p["finished"], p["pass"]) == ("solve", False, 5)
    line = format_progress(p, 40.0, now=p["last_write"] + 10)
    assert "solve · pass 5/18" in line and "finished" not in line and "no solver output" not in line
    assert "no solver output for" in format_progress(p, 900.0, now=p["last_write"] + 600)
    empty = read_progress(tmp_path / "nothing")
    assert empty["step"] is None and format_progress(empty, 3.0) == "[aedt 0:03] starting"


@pytest.mark.aedt_fixture
def test_parse_em_conv_merges_frequency_rows():
    text = next((PROGRESS / "hfss_driven").glob("*.aedtresults/*/*.EMConvData")).read_text(encoding="utf-8")
    c = parse_em_conv(text)
    assert [x["pass"] for x in c["passes"]] == [1, 2, 3, 4] and c["passes"][0]["delta"] is None


# ---- run_aedt_mode with fake processes -----------------------------------------------------------------------------
def _job(tmp_path) -> Path:
    job = tmp_path / "job"
    (job / "scripts").mkdir(parents=True)
    meta = {"simulation_name": "x", "analysis": "q3d_cmatrix", "solver": "ansys", "design_hash": "0", "group": "G",
            "settings": {}}
    (job / "job.json").write_text(json.dumps(meta), encoding="utf-8")
    return job


class FakeProc:
    """A Popen stand-in: 'runs' for ``seconds``, writing the qcc status file as the AEDT script would."""

    def __init__(self, job, seconds=0.2, lines=("step solve", "done", "end"), pid=5555):
        self.job, self.t_end, self.lines, self.pid, self.returncode, self.killed = job, time.time() + seconds, lines, \
            pid, None, False
        self.args = ["fake"]

    def poll(self):
        if self.returncode is None and time.time() >= self.t_end:
            (self.job / "qcc_solve_status.txt").write_text("\n".join(self.lines) + "\n", encoding="utf-8")
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else -9

    def kill(self):
        self.killed, self.returncode = True, -9


def test_attach_runs_the_helper_and_leaves_the_session(tmp_path, monkeypatch, capsys):
    job = _job(tmp_path)
    session = S.AedtSession(4242, EXE, [str(EXE)], [50051], created=1.0)
    monkeypatch.setattr(hfss, "find_sessions", lambda *a, **k: [session])
    monkeypatch.setattr(hfss, "_kill_tree", lambda pid: pytest.fail(f"must not kill {pid}"))
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        seen["proc"] = FakeProc(job, 0.3)
        return seen["proc"]

    monkeypatch.setattr(hfss.subprocess, "Popen", popen)
    r = hfss.run_aedt_mode(job, hfss.SOLVE_SCRIPT, aedt="attach", log_name="solve.log", progress=0.1)
    assert (r.code, r.mode, r.owned, r.pid) == (0, "attach", False, 4242)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--script") + 1] == str(job / "scripts" / "qcc_solve.py")
    assert cmd[cmd.index("--arg") + 1] == str(job / "x.json") and cmd[cmd.index("--project") + 1] == "x_project"
    assert (job / "solve.log.pid").read_text() == "5555"  # the helper's pid, never the attached session's
    out = capsys.readouterr().out
    assert "attached to AEDT 2024 R1 pid 4242" in out and "[aedt 0:0" in out


def test_attach_timeout_stops_waiting_but_never_kills_the_session(tmp_path, monkeypatch):
    job = _job(tmp_path)
    session = S.AedtSession(4242, EXE, [str(EXE)], [50051])
    monkeypatch.setattr(hfss, "find_sessions", lambda *a, **k: [session])
    monkeypatch.setattr(hfss, "_kill_tree", lambda pid: pytest.fail(f"must not kill {pid}"))
    proc = FakeProc(job, seconds=60)
    monkeypatch.setattr(hfss.subprocess, "Popen", lambda cmd, **kw: proc)
    r = hfss.run_aedt_mode(job, hfss.SOLVE_SCRIPT, aedt="attach", timeout=0.8, log_name="solve.log", progress=0)
    assert r.code == -1 and proc.killed and "goes on in the attached AEDT pid 4242" in r.note


def test_attach_without_a_window_opens_a_gui(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(hfss, "find_sessions", lambda *a, **k: [])
    monkeypatch.setattr(hfss, "find_ansys_executable", lambda *a, **k: EXE)
    calls = []

    def launch(exe, job_dir, script, sim_json, *a, **k):
        calls.append((exe, script, sim_json))
        (job_dir / "qcc_solve_status.txt").write_text("step solve\ndone\nend\n", encoding="utf-8")
        return 777

    monkeypatch.setattr(hfss, "launch_gui", launch)
    monkeypatch.setattr(hfss, "pid_alive", lambda pid: True)
    r = hfss.run_aedt_mode(job, hfss.SOLVE_SCRIPT, aedt="attach", log_name="solve.log", progress=0)
    assert (r.code, r.mode, r.owned, r.pid) == (0, "gui", True, 777) and "no AEDT window open" in r.note
    assert calls == [(EXE, "qcc_solve.py", "x.json")]


def test_gui_timeout_kills_only_its_own_window(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(hfss, "find_ansys_executable", lambda *a, **k: EXE)
    monkeypatch.setattr(hfss, "launch_gui", lambda *a, **k: 888)
    monkeypatch.setattr(hfss, "pid_alive", lambda pid: True)
    killed = []
    monkeypatch.setattr(hfss, "_kill_tree", killed.append)
    r = hfss.run_aedt_mode(job, hfss.SOLVE_SCRIPT, aedt="gui", timeout=0.8, log_name="solve.log", progress=0)
    assert r.code == -1 and killed == [888] and r.owned


def test_gui_window_closed_early_is_reported(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(hfss, "find_ansys_executable", lambda *a, **k: EXE)
    monkeypatch.setattr(hfss, "launch_gui", lambda *a, **k: 888)
    monkeypatch.setattr(hfss, "pid_alive", lambda pid: False)
    r = hfss.run_aedt_mode(job, hfss.SOLVE_SCRIPT, aedt="gui", log_name="solve.log", progress=0)
    assert r.code == 1 and "closed before the script ended" in r.note


def test_batch_prints_progress_and_clears_a_stale_status(tmp_path, monkeypatch, capsys):
    job = _job(tmp_path)
    (job / "qcc_solve_status.txt").write_text("done\nend\n", encoding="utf-8")  # from an earlier run
    monkeypatch.setattr(hfss, "render_command", lambda *a, **k: ["ansysedt", "-ng"])
    proc = FakeProc(job, 1.2)
    monkeypatch.setattr(hfss.subprocess, "Popen", lambda cmd, **kw: proc)
    r = hfss.run_aedt_mode(job, hfss.SOLVE_SCRIPT, aedt="batch", log_name="solve.log", progress=0.4)
    out = capsys.readouterr().out
    assert r.code == 0 and r.mode == "batch" and r.owned
    assert out.count("[aedt 0:0") >= 2 and "starting" in out  # the stale status file was removed first
    assert "finished" in out.strip().splitlines()[-1]


def test_solve_job_records_the_mode(tmp_path, monkeypatch):
    job = _job(tmp_path)
    monkeypatch.setattr(hfss, "run_aedt_mode", lambda *a, **k: hfss.AedtRun(0, 1.0, 9, "gui", True, ""))
    r = hfss.solve_job(job, aedt="gui")
    assert r.mode == "gui" and json.loads((job / "job.json").read_text())["aedt_mode"] == "gui"


# ---- the tutorials' switch -----------------------------------------------------------------------------------------
@pytest.fixture()
def tut(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.syspath_prepend(str(ROOT / "examples" / "tutorials"))
    cwd = os.getcwd()
    import _tut  # pylint: disable=import-outside-toplevel

    yield _tut
    os.chdir(cwd)


def test_solve_or_load_passes_the_aedt_mode(tut, tmp_path, monkeypatch):
    import quantcore_circuits.sim_tools.ansys as ansys

    job = _job(tmp_path)
    monkeypatch.setattr(tut, "FEM", tmp_path / "fem")
    monkeypatch.setattr(ansys, "find_ansys_executable", lambda *a, **k: EXE)
    seen = {}

    def fake_solve(job_dir, **kw):
        seen.update(kw)
        return hfss.RenderResult(job_dir, None, job_dir / "solve.log", 1, 1.0, mode=kw["aedt"])

    monkeypatch.setattr(hfss, "solve_job", fake_solve)
    assert tut.solve_or_load(job, True, timeout=5, aedt="attach") is None
    assert seen == {"timeout": 5, "aedt": "attach"}
    monkeypatch.setenv(S.ENV_MODE, "gui")
    tut.solve_or_load(job, True)
    assert seen["aedt"] == "gui"  # no AEDT_MODE given: QCC_AEDT_MODE


@pytest.mark.parametrize("path", sorted((ROOT / "examples" / "tutorials").glob("[0-9][0-9]_*.ipynb")) + [
    ROOT / "examples" / p for p in ("q1_r1_first_run.ipynb", "q1_r1_loop.ipynb", "lom_from_layout.ipynb",
                                    "fem_loop/fem_loop.ipynb")], ids=lambda p: p.stem)
def test_notebooks_have_the_switches(path):
    """Each tutorial / example notebook that solves or goes live has ``AEDT_MODE`` and ``KLAYOUT_GUI``, explained."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    md = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
    if "LIVE = " in code:  # goes live (fem_loop is headless: no KLayout switch)
        assert "KLAYOUT_GUI = " in code and "KLAYOUT_GUI" in md, path.name
    if "RUN_FEM" in code or "run_job(" in code or "hfss.render(" in code:
        assert "AEDT_MODE = " in code and "AEDT_MODE" in md, path.name
        assert 'AEDT_MODE = "batch"' in code, f"{path.name}: the default stays batch"


# ---- KLayout window ------------------------------------------------------------------------------------------------
@pytest.fixture()
def kl(monkeypatch, tmp_path):
    from quantcore_circuits.live import klayout

    monkeypatch.setenv(klayout.GUI_ENV, "1")
    monkeypatch.setattr(klayout, "find_klayout", lambda: tmp_path / "klayout_app.exe")
    monkeypatch.setattr(klayout, "plugin_installed", lambda: False)
    state = {"klive": [False], "pids": [[]], "spawned": [], "front": []}

    def klive():
        return state["klive"].pop(0) if len(state["klive"]) > 1 else state["klive"][0]

    def pids():
        return state["pids"].pop(0) if len(state["pids"]) > 1 else state["pids"][0]

    monkeypatch.setattr(klayout, "klive_available", klive)
    monkeypatch.setattr(klayout, "klayout_pids", pids)
    monkeypatch.setattr(klayout, "_spawn_detached", lambda args, env: state["spawned"].append(args) or FakeProc(
        tmp_path, 0))
    monkeypatch.setattr(klayout, "bring_to_front", lambda pid=None, layout=None: state["front"].append(pid) or True)
    state["mod"] = klayout
    return state


def test_open_klayout_starts_the_window_with_the_layout(kl, tmp_path):
    kl["klive"] = [False, False, True]
    kl["pids"] = [[11], [11], [11, 77]]  # the user's KLayout without klive (11), then ours (77)
    info = kl["mod"].open_klayout(tmp_path / "chip.oas", timeout=5)
    args = kl["spawned"][0]
    assert args[:2] == [str(tmp_path / "klayout_app.exe"), "-e"] and args[2] == "-rm"
    assert args[3].endswith("load_dev.py") and args[-1] == str((tmp_path / "chip.oas").resolve())
    assert info["started"] and info["klive"] and info["pid"] == 77 and kl["front"] == [77]
    assert "klive is not listening" in info["note"]


def test_open_klayout_running_or_switched_off(kl, tmp_path, monkeypatch):
    kl["klive"] = [True]
    assert kl["mod"].open_klayout(tmp_path / "chip.oas") == {"started": False, "klive": True, "front": True}
    assert kl["spawned"] == [] and kl["front"] == [None]
    kl["klive"] = [False]
    kl["mod"].use_gui(False)
    assert kl["mod"].gui_enabled() is False
    info = kl["mod"].open_klayout(tmp_path / "chip.oas")
    assert not info["started"] and kl["spawned"] == [] and "QCC_KLAYOUT_GUI=0" in info["hint"]


def _tiny(**kw):
    from quantcore_circuits.designer import Designer

    d = Designer("t_gui_live", box=(0, 0, 4000, 4000), verbose=False, **kw)
    with d.batch():
        d.add("PAD_W", "BondPad", at=(500, 2000), rot=270)
        d.add("PAD_E", "BondPad", at=(3500, 2000), rot=90)
    return d


def test_designer_opens_raises_and_reopens_klayout(kl, monkeypatch, tmp_path):
    import quantcore_circuits.live as live

    sent, opened = [], []
    klive_up = {"v": False}
    monkeypatch.setattr(live, "klive_available", lambda: klive_up["v"])
    monkeypatch.setattr(live, "send_to_klive", lambda path, **k: sent.append(path) or {})

    def fake_open(layout, front=True, **k):
        opened.append(layout)
        klive_up["v"] = True
        return {"started": True, "klive": True, "pid": 77}

    monkeypatch.setattr(kl["mod"], "open_klayout", fake_open)
    kl["pids"] = [[77]]
    d = _tiny(live=False, out=tmp_path / "t.oas")
    d.live = True
    d.show()  # KLayout not running: started, layout sent, its window raised
    assert len(opened) == 1 and len(sent) == 1 and kl["front"] == [77]
    d.show()  # running: only redrawn, no second raise
    assert len(opened) == 1 and len(sent) == 2 and kl["front"] == [77]
    klive_up["v"] = False  # the user closed the window
    kl["pids"] = [[]]
    d.show()
    assert len(opened) == 2 and kl["front"] == [77, 77]
    klive_up["v"], kl["pids"] = False, [[77]]  # ours is open but klive never answers: no third window
    monkeypatch.setattr(kl["mod"], "open_klayout", lambda *a, **k: pytest.fail("must not start another KLayout"))
    d.show()


def test_designer_switch_off_never_starts_klayout(kl, monkeypatch, tmp_path):
    import quantcore_circuits.live as live

    monkeypatch.setattr(live, "klive_available", lambda: False)
    monkeypatch.setattr(kl["mod"], "open_klayout", lambda *a, **k: pytest.fail("must not start KLayout"))
    d = _tiny(live=False, out=tmp_path / "t.oas", open_klayout=False)
    d.live = True
    d.show()
    kl["mod"].use_gui(False)
    d2 = _tiny(live=False, out=tmp_path / "t2.oas")
    d2.live = True
    d2.show()
    assert kl["front"] == []


def test_live_mode_sets_the_window_switch(tut, monkeypatch, capsys):
    from quantcore_circuits.live import klayout

    monkeypatch.setenv("QCC_LIVE", "1")
    monkeypatch.setenv(klayout.GUI_ENV, "1")
    monkeypatch.setattr("quantcore_circuits.live.klive_available", lambda: False)
    monkeypatch.setattr(klayout, "find_klayout", lambda: Path("klayout_app.exe"))
    assert tut.live_mode(gui=True) is True and klayout.gui_enabled()
    assert "brings it to the front" in capsys.readouterr().out
    assert tut.live_mode(gui=False) is True and not klayout.gui_enabled()
    assert "will not be started" in capsys.readouterr().out

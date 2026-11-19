"""KLayout plugin, Simulate / Results / Fab (``qcc_kplugin.flow``): the parts that need no KLayout window.

The window behaviour (selection → subset, status-bar progress, non-modal result windows, undo of an applied revision) is
covered by ``kplugin/gui_smoke_flow.py`` in a real KLayout; here the contract with the menu and the commands the
buttons start are checked with a fake job runner.
"""

import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kplugin" / "python"))

from qcc_kplugin import flow  # noqa: E402
from qcc_kplugin.session import SESSION  # noqa: E402


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """flow with a design on disk, no questions asked and every background job recorded instead of started."""
    design = tmp_path / "chip.json"
    design.write_text('{"name": "chip"}', encoding="utf-8")
    monkeypatch.setattr(SESSION, "design_path", design)
    monkeypatch.setattr(SESSION, "layout_path", tmp_path / "build" / "chip.oas")
    monkeypatch.setattr(SESSION, "data", {"instances": {"Q1": {}, "PAD": {}}, "routes": {"R1": {}}, "drc": []})
    monkeypatch.setattr(flow, "_design_ready", lambda: True)
    monkeypatch.setattr(flow, "selected_names", lambda: [])
    monkeypatch.setattr(flow, "_running", lambda prefix="": None)
    monkeypatch.setattr(flow, "message", lambda *a, **k: None)
    runs = []

    class Job:
        finished = True

        def wait(self, *_a):
            return True

    def run(steps, label, done, status_file=None, cwd=None):
        runs.append({"steps": [[str(x) for x in s] for s in steps], "label": label, "done": done,
                     "status": status_file, "cwd": cwd})
        return Job()

    monkeypatch.setattr(flow, "_run", run)
    asked = []
    monkeypatch.setattr(flow, "choose", lambda title, text, choices, checkbox=None: asked.append((title, choices))
                        or (0, False))
    monkeypatch.setattr(flow, "config", lambda key, default="": default)
    monkeypatch.setattr(flow, "set_config", lambda key, value: None)
    picks = []  # what the Simulate dialog returns, in order (default: the selection, eigenmode, fast, no window)

    def dialog(names):
        asked.append(("Simulate dialog", list(names)))
        return picks.pop(0) if picks else {"scope": "selection" if names else "default", "analysis": "hfss_eigenmode",
                                           "window": False, "action": "run"}
    monkeypatch.setattr(flow, "simulate_dialog", dialog)
    monkeypatch.setattr(flow, "ask_dir", lambda title, start: str(tmp_path / "out"))
    monkeypatch.setattr(flow, "ask_file", lambda title, start, pattern="": str(tmp_path / "r.json"))
    return type("Fake", (), {"runs": runs, "asked": asked, "design": design, "tmp": tmp_path, "picks": picks})


# ---- the contract with the menu (the other agent's menu.py builds the submenus from ACTIONS) -----------------------
def test_actions_contract():
    assert 3 <= len(flow.ACTIONS) <= 8  # a short menu for newcomers
    names = [a[1] for a in flow.ACTIONS]
    titles = [a[2] for a in flow.ACTIONS]
    assert len(set(names)) == len(names) and len(set(titles)) == len(titles)  # no duplicates
    assert {a[0] for a in flow.ACTIONS} == {"design", "simulate", "results", "fab"}
    for submenu, name, title, func, shortcut in flow.ACTIONS:
        assert submenu in ("design", "simulate", "results", "fab") and name.startswith("qcc_") and title
        assert callable(func)
        assert isinstance(shortcut, str)
    for fn in (flow.simulate, flow.results, flow.fab):  # what the Flow-strip buttons call, with no arguments
        assert callable(fn)


def test_menu_has_only_what_the_audit_kept():
    """Menu audit 2026-11-16: items the panel, a dialog or KLayout already covers are not in the menu; every entry
    that is the only way to reach a shortcut stays."""
    text = (ROOT / "kplugin" / "python" / "qcc_kplugin" / "menu.py").read_text(encoding="utf-8")
    chunks = re.split(r"\n        \((?:D|E|C), ", text)[1:]  # one entry each (some run over two lines)
    items = {}
    for c in chunks:
        entry = c.split("\n        (")[0].split("\n    ]")[0]
        items[re.match(r'"(qcc_\w+)"', entry).group(1)] = re.findall(r'"([^"]*)"\)', entry)[-1]
    for gone in ("qcc_place", "qcc_path_route", "qcc_live", "qcc_sync", "qcc_shot", "qcc_junction", "qcc_delete",
                 "qcc_stop_lom"):
        assert gone not in items, gone
    for name, shortcut in {"qcc_rebuild": "Ctrl+Shift+B", "qcc_undo": "Ctrl+Shift+Z", "qcc_redo": "Ctrl+Shift+Y",
                           "qcc_edit": "Ctrl+Shift+Q", "qcc_rot_ccw": "[", "qcc_rot_cw": "]",
                           "qcc_duplicate": "Ctrl+Shift+U", "qcc_mirror": "Ctrl+Shift+F",
                           "qcc_node_delete": "Ctrl+Shift+X", "qcc_node_props": "Ctrl+Shift+N",
                           "qcc_meander_here": "Ctrl+Shift+M", "qcc_join_mode": "Ctrl+Shift+J",
                           "qcc_drc": "Ctrl+Shift+D", "qcc_run_lom": "Ctrl+Shift+O"}.items():
        assert items.get(name) == shortcut, name
    kept = {a[1] for a in flow.ACTIONS}
    assert not kept & {"qcc_export_job", "qcc_open_results"}


def test_shortcuts_do_not_clash_with_the_plugin():
    """The plugin's own shortcuts live in the .lym and menu.py; every flow shortcut must be new."""
    taken = set(re.findall(r'"(Ctrl\+[A-Za-z+]+|\[|\])"', (ROOT / "kplugin" / "pymacros" / "qcc_kplugin.lym").read_text(
        encoding="utf-8") + (ROOT / "kplugin" / "python" / "qcc_kplugin" / "menu.py").read_text(encoding="utf-8")))
    for _s, _n, _t, _f, shortcut in flow.ACTIONS:
        assert shortcut not in taken or shortcut == ""


# ---- what the buttons start --------------------------------------------------------------------------------------
def test_simulate_selection_is_the_subset(fake, monkeypatch):
    monkeypatch.setattr(flow, "selected_names", lambda: ["Q1", "R1"])
    flow.simulate()
    (run,) = fake.runs
    assert run["steps"][0][:3] == ["sim", "auto", str(fake.design)]
    assert run["steps"][0][run["steps"][0].index("--instances") + 1] == "Q1,R1"
    assert "--aedt" in run["steps"][0] and run["steps"][0][run["steps"][0].index("--aedt") + 1] == "batch"  # no AEDT window
    assert run["label"] == "Simulate" and run["status"].name == "sim_status.json" and run["cwd"] == fake.design.parent
    assert fake.asked[0] == ("Simulate dialog", ["Q1", "R1"])  # the dialog shows what will be rendered
    args = run["steps"][0]
    assert args[args.index("-a") + 1] == "hfss_eigenmode" and "--fast" in args
    fake.picks.append({"scope": "selection", "analysis": "q3d_cmatrix", "window": False, "action": "run"})
    flow.simulate()
    args = fake.runs[-1]["steps"][0]
    assert args[args.index("-a") + 1] == "q3d_cmatrix" and "--fast" in args and "--set" not in args  # fast always


def test_simulate_without_selection_asks_default_or_whole(fake, monkeypatch):
    flow.simulate()  # the dialog's first scope: the default subset
    assert "--default" in fake.runs[-1]["steps"][0] and fake.asked[-1] == ("Simulate dialog", [])
    fake.picks.append({"scope": "whole", "analysis": "hfss_eigenmode", "window": True, "action": "run"})
    flow.simulate()
    args = fake.runs[-1]["steps"][0]
    assert "--whole" in args and args[args.index("--aedt") + 1] == "gui"  # the checkbox: a visible AEDT window
    monkeypatch.setattr(flow, "simulate_dialog", lambda names: None)  # cancelled
    n = len(fake.runs)
    flow.simulate()
    assert len(fake.runs) == n
    fake.picks.clear()
    monkeypatch.setattr(flow, "simulate_dialog", lambda names: {"scope": "default", "analysis": "q3d_cmatrix",
                                                                "window": False, "action": "export"})
    flow.simulate()  # "Export the job only": the manual export instead of a run
    assert fake.runs[-1]["steps"][0][:2] == ["sim", "subset"]


def test_simulate_never_attaches_to_the_users_aedt(fake, monkeypatch):
    monkeypatch.setattr(flow, "selected_names", lambda: ["Q1"])
    for window in (True, False):
        fake.runs.clear()
        flow.simulate(window=window)
        args = fake.runs[0]["steps"][0]
        assert args[args.index("--aedt") + 1] in ("batch", "gui")  # "attach" is not an option of qcc sim auto


def test_running_simulation_is_offered_to_stop(fake, monkeypatch):
    class Running:
        label = "Simulate"
        stopped = False

        def status(self):
            return {"message": "solve"}

        def elapsed(self):
            return 12.0

        def cancel(self):
            Running.stopped = True

    monkeypatch.setattr(flow, "_running", lambda prefix="": Running())
    flow.simulate()
    assert Running.stopped and not fake.runs  # a second run is not started on top of the first


def test_export_job_command(fake, monkeypatch):
    monkeypatch.setattr(flow, "selected_names", lambda: ["Q1"])
    flow.export_job()
    args = fake.runs[0]["steps"][0]
    assert args[:3] == ["sim", "subset", str(fake.design)] and "--instances" in args and "Q1" in args
    assert Path(args[args.index("-o") + 1]) == fake.tmp / "out" / "chip_sim"
    flow.export_job(names=[], subset="whole", folder=str(fake.tmp / "x"))
    assert "--whole" in fake.runs[-1]["steps"][0]


def test_export_job_offers_a_short_folder_when_too_deep_for_aedt(fake, monkeypatch):
    """The manual export gets the automatic run's guard: a job path AEDT cannot solve on Windows goes to
    %TEMP%/qcc_jobs (first choice) or stays where asked (second choice)."""
    import tempfile

    from quantcore_circuits import guiflow

    assert flow.AEDT_PATH_LIMIT == guiflow.AEDT_PATH_LIMIT  # the plugin's copy of the rule

    class _WindowsOs:  # "nt" for the plugin only: a patched os.name makes pathlib build WindowsPath on Linux
        name = "nt"

        def __getattr__(self, attr):
            return getattr(os, attr)

    monkeypatch.setattr(flow, "os", _WindowsOs())
    deep = fake.tmp / ("x" * 150)
    flow.export_job(names=["Q1"], subset="selection", folder=str(deep))
    args = fake.runs[-1]["steps"][0]
    assert Path(args[args.index("-o") + 1]) == Path(tempfile.gettempdir()) / "qcc_jobs" / "chip_sim"
    assert len(fake.asked[-1][1]) == 2
    monkeypatch.setattr(flow, "choose", lambda *a, **k: (1, False))
    flow.export_job(names=["Q1"], subset="selection", folder=str(deep))
    args = fake.runs[-1]["steps"][0]
    assert Path(args[args.index("-o") + 1]) == deep / "chip_sim"


def test_import_results_command(fake):
    flow.import_results()  # first choice: a results.json file
    assert fake.runs[0]["steps"][0] == ["results", "import", str(fake.design), str(fake.tmp / "r.json")]
    flow.import_results(source=str(fake.tmp / "job"))
    assert fake.runs[-1]["steps"][0][-1] == str(fake.tmp / "job")


def test_fab_writes_mask_netlist_and_python(fake, monkeypatch):
    flow.fab()
    (run,) = fake.runs
    kinds = [s[:2] if s[0] != "mask" else s[:1] for s in run["steps"]]
    assert kinds == [["mask"], ["circuit", "export"], ["design", "to-python"]]
    assert run["steps"][0][-1].endswith("chip_fab.oas") and run["steps"][2][-1].endswith("chip.py")
    # DRC errors: the user is asked before exporting (and can say no)
    fake.runs.clear()
    monkeypatch.setattr(SESSION, "data", {"drc": [{"severity": "error", "message": "pad overlaps the frame"}]})
    monkeypatch.setattr(flow, "choose", lambda *a, **k: None)
    flow.fab()
    assert not fake.runs
    monkeypatch.setattr(flow, "choose", lambda *a, **k: (0, False))
    flow.fab()
    assert len(fake.runs) == 1


def test_propose_then_apply_goes_through_the_session(fake, monkeypatch):
    flow.propose()
    run = fake.runs[0]
    assert run["steps"][0][:3] == ["results", "propose", str(fake.design)] and "-o" in run["steps"][0]
    proposal_path = Path(run["steps"][0][-1])
    proposal = {"tunable": True, "knobs": [{"knob": "Q1.cross_length", "old": 300.0, "new": 312.5}], "moved": [],
                "message": "x", "basis": "the layout's own estimates"}
    # Apply asks `qcc results apply` for the new design, then commits it with SESSION.commit (so undo works)
    commits = []
    monkeypatch.setattr(SESSION, "commit", lambda design, what="": commits.append((design, what)))
    flow.apply_proposal(proposal, proposal_path)
    apply_run = fake.runs[-1]
    assert apply_run["steps"][0][:3] == ["results", "apply", str(fake.design)] and str(proposal_path) in apply_run["steps"][0]
    new_file = Path(apply_run["steps"][0][-1])
    new_file.write_text(json.dumps({"name": "chip", "instances": {"Q1": {"params": {"cross_length": 312.5}}}}),
                        encoding="utf-8")
    apply_run["done"](True, "")
    (design, what), = commits
    assert design["instances"]["Q1"]["params"]["cross_length"] == 312.5 and "Q1.cross_length 300 → 312.5" in what
    apply_run["done"](False, "error: the design changed since the proposal")  # a refused apply commits nothing
    assert len(commits) == 1


def test_nothing_tunable_is_said_in_the_window(fake, monkeypatch):
    """The proposal's message reaches the user as it is (the library says which designs the feedback can tune)."""
    shown = []
    monkeypatch.setattr(flow, "ProposalWindow", lambda proposal, path: shown.append(proposal))
    flow.propose()
    p = fake.runs[0]
    path = Path(p["steps"][0][-1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tunable": False, "knobs": [], "moved": [], "basis": "x",
                                "message": "Nothing can be tuned automatically yet: the feedback handles an Xmon qubit."}),
                    encoding="utf-8")
    p["done"](True, "")
    assert shown and "Nothing can be tuned" in shown[0]["message"]


def test_simulate_passes_the_dialogs_solver_settings(fake, monkeypatch):
    monkeypatch.setattr(flow, "selected_names", lambda: ["Q1"])
    fake.picks.append({"scope": "selection", "analysis": "q3d_cmatrix", "window": False, "action": "run",
                       "settings": {"percent_error": 1.0, "maximum_passes": 12, "minimum_converged_passes": 2}})
    flow.simulate()
    args = fake.runs[-1]["steps"][0]
    assert "--full" in args and "maximum_passes=12" in args and "percent_error=1.0" in args and "--fast" not in args

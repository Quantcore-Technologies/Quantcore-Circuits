"""KLayout plugin, junction values: the merge into design.json, the values a placed qubit gets, the Simulate dialog's
pre-check (selection and default subset) and the simulation-layout export. The dialog rows and the menu item are
checked in a real KLayout by a GUI probe."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kplugin" / "python"))

from qcc_kplugin import design_ops, flow, jfetch, simsetup  # noqa: E402
from qcc_kplugin.session import SESSION  # noqa: E402

EXAMPLE = ROOT / "examples" / "q1_r1_feedline.json"
KEEP = design_ops.KEEP


@pytest.fixture
def qcc_cli(monkeypatch):
    """The plugin's ``qcc`` calls go to this Python's ``quantcore_circuits.cli`` (the same code, no installed script)."""
    monkeypatch.setattr(jfetch, "_qcc_cmd", lambda args: [sys.executable, "-m", "quantcore_circuits.cli",
                                                          *[str(a) for a in args]])
    monkeypatch.setattr(jfetch, "_env", lambda: {**os.environ, "PYTHONIOENCODING": "utf-8",
                                                 "QCC_LIVE": "0"})
    jfetch._CACHE.clear()  # noqa: SLF001
    jfetch._DEFAULT.clear()  # noqa: SLF001
    return sys.executable


def sample() -> dict:
    return {"instances": {"Q1": {"cell": "Xmon", "place": {"at": [0, 0]}}}}


# ---- set_junction merges ---------------------------------------------------------------------------------------------
def test_set_junction_merges_flux_and_asymmetry():
    d = sample()
    d["instances"]["Q1"]["junction"] = {"Lj_nH": 12.0, "Cj_fF": 2.0, "flux_phi0": 0.25, "asym": 0.1, "note": "x"}
    # the dialog of a SQUID gives all four, the other rows only L_J and C_J: those keep what is stored
    assert design_ops.set_junction(d, "Q1", 11.0, 2.0) is True
    assert d["instances"]["Q1"]["junction"] == {"Lj_nH": 11.0, "Cj_fF": 2.0, "flux_phi0": 0.25, "asym": 0.1, "note": "x"}
    assert design_ops.set_junction(d, "Q1", 11.0, 2.0, 0.3, 0.1) is True
    assert d["instances"]["Q1"]["junction"]["flux_phi0"] == 0.3
    # zero is the default: the key is left out, like the library does
    assert design_ops.set_junction(d, "Q1", 11.0, 2.0, 0.0, 0.0) is True
    assert d["instances"]["Q1"]["junction"] == {"Lj_nH": 11.0, "Cj_fF": 2.0, "note": "x"}
    assert design_ops.set_junction(d, "Q1", 11.0, 2.0, 0.0, 0.0) is False
    # emptying L_J and C_J leaves flux / asym; the entry goes only when nothing is left
    assert design_ops.set_junction(d, "Q1", None, None, 0.2, KEEP) is True
    assert d["instances"]["Q1"]["junction"] == {"flux_phi0": 0.2, "note": "x"}
    d["instances"]["Q1"]["junction"] = {"flux_phi0": 0.2}
    assert design_ops.set_junction(d, "Q1", None, None, 0.0, KEEP) is True and "junction" not in d["instances"]["Q1"]
    with pytest.raises(ValueError):
        design_ops.set_junction(d, "Q1", -1.0, None)
    d["instances"]["Q1"]["junction"] = [{"Lj_nH": 1.0}, {"Lj_nH": 2.0}]
    with pytest.raises(ValueError):
        design_ops.set_junction(d, "Q1", 3.0, None)


def test_set_junction_undo_through_the_session(tmp_path, monkeypatch):
    """The dialog's edit is one commit: Undo restores the junction as it was (flux and asymmetry included)."""
    from qcc_kplugin import design_io

    path = tmp_path / "chip.json"
    d = sample()
    d["instances"]["Q1"]["junction"] = {"Lj_nH": 12.0, "flux_phi0": 0.25}
    path.write_text(json.dumps(d), encoding="utf-8")
    before = json.loads(path.read_text(encoding="utf-8"))
    after = json.loads(json.dumps(before))
    design_ops.set_junction(after, "Q1", 9.0, 1.5)
    assert before["instances"]["Q1"]["junction"] == {"Lj_nH": 12.0, "flux_phi0": 0.25}  # history keeps the old dict
    assert after["instances"]["Q1"]["junction"] == {"Lj_nH": 9.0, "Cj_fF": 1.5, "flux_phi0": 0.25}
    assert design_io.read_design(path)["instances"]["Q1"]["junction"]["flux_phi0"] == 0.25


# ---- the values a placed qubit gets ---------------------------------------------------------------------------------
def test_fix_junction_at_placement_note_and_duplicates():
    d = sample()
    note = design_ops.fix_junction_at_placement(d, "Q1", {"Lj_nH": 6.7344, "Cj_fF": 15.0, "source": "PDK nominal SQUID"})
    assert d["instances"]["Q1"]["junction"] == {"Lj_nH": 6.7344, "Cj_fF": 15.0}
    assert note == ("Q1: junction L_J 6.73 nH (PDK nominal SQUID; simulation value, edit in the component dialog)")
    # an instance that has a junction (a duplicate keeps its source's) is left alone; no value: nothing written
    d["instances"]["Q1"]["junction"] = {"Lj_nH": 12.0, "Cj_fF": 2.0}
    assert design_ops.fix_junction_at_placement(d, "Q1", {"Lj_nH": 6.7, "Cj_fF": 15.0}) is None
    assert d["instances"]["Q1"]["junction"] == {"Lj_nH": 12.0, "Cj_fF": 2.0}
    d2 = sample()
    assert design_ops.fix_junction_at_placement(d2, "Q1", None) is None and "junction" not in d2["instances"]["Q1"]


def test_placement_values_come_from_the_library(qcc_cli):
    nominal = jfetch.placement_junction("Xmon", {"junction_type": "Manhattan"})  # KQC type: no PDK value
    assert nominal["source"] == "PDK nominal SQUID" and nominal["Lj_nH"] == pytest.approx(6.7344)
    assert nominal["Cj_fF"] == pytest.approx(15.0) and nominal["drawn"] is None
    drawn = jfetch.placement_junction("TrilayerConcentricTransmon", {})  # a drawn trilayer junction: its PDK value
    assert drawn["source"].startswith("drawn trilayer") and drawn["drawn"]["Lj_nH"] == drawn["Lj_nH"]
    assert jfetch.placement_junction("Launcher", {}) is None  # no junction
    assert jfetch.placement_junction("Xmon", {"junction_type": "Manhattan"}) is nominal  # cached: no new call
    assert jfetch.key("Xmon", {"junction_type": "Manhattan"}) in jfetch._CACHE  # noqa: SLF001


def test_placement_junction_matches_the_library_helper():
    from quantcore_circuits import guiflow

    assert guiflow.placement_junction("Xmon", {"junction_type": "Manhattan"})["Lj_nH"] == pytest.approx(6.7344)
    assert guiflow.placement_junction("Launcher") is None


def test_trilayer_name_rule_equals_the_library():
    from quantcore_circuits.layouts.junctions.trilayer import trilayer_classes

    for name in trilayer_classes():
        assert jfetch.is_trilayer_type(name), name
    for name in ("Manhattan", "Sim", "Single Xmon", "Sim Squid", "No Squid", "Manhattan Single Junction"):
        assert not jfetch.is_trilayer_type(name), name


def test_pdk_junction_copy_matches_the_library():
    """The plugin's copy of the build's PDK junction default (an unset KQC / Metal junction_type → the trilayer)."""
    from quantcore_circuits.assembly import plan

    assert jfetch.PDK_JUNCTION == plan._PDK_JUNCTION  # noqa: SLF001
    assert jfetch.drawn_type(None, "Manhattan") == "Quantcore Squid"
    assert jfetch.drawn_type("Manhattan", "Manhattan") == "Manhattan"  # chosen: drawn as it is
    assert jfetch.drawn_type(None, "Trilayer Junction") == "Trilayer Junction"
    assert jfetch.drawn_type(None, "Manhattan", junction_cell=True) == "Manhattan"


# ---- the Simulate dialog's pre-check --------------------------------------------------------------------------------
def test_missing_junctions_uses_the_sidecar_rule():
    cats = {"Xmon": "qubit", "BondPad": "launcher"}
    data = {"instances": {
        "Q1": {"cell": "Xmon", "junction": {"kind": "SQUID", "Lj0_nH": None, "Lj_eff_nH": None, "source": None}},
        "Q2": {"cell": "Xmon", "junction": {"kind": "SQUID", "Lj0_nH": 6.7, "Lj_eff_nH": 6.7, "source": "drawn Quantcore Squid"}},
        "Q3": {"cell": "Xmon", "junction": {"kind": "SQUID", "Lj0_nH": 12.0, "Lj_eff_nH": None, "error": "no finite L"}},
        "Q4": {"cell": "Xmon"},  # an older sidecar: the design's own value decides
        "PAD": {"cell": "BondPad"}}}
    design = {"instances": {"Q4": {"cell": "Xmon", "junction": {"Lj_nH": 5.0}}}}
    assert simsetup.missing_junctions(["Q1", "Q2", "Q3", "Q4", "PAD"], data, cats, design) == ["Q1", "Q3"]
    design["instances"]["Q4"].pop("junction")
    assert simsetup.missing_junctions(["Q4"], data, cats, design) == ["Q4"]
    text = simsetup.missing_text(["Q3"], data, {"Q1": "Q1: x"})
    assert "no finite L" in text and "component" in text and "Junction" in text
    assert simsetup.missing_text([], data) == ""
    assert simsetup.missing_text(["Q1"], data, {"Q1": "Q1: its Manhattan junction has no PDK value"}).startswith(
        "Q1: its Manhattan junction")


def _design_without_lj(tmp_path, with_lj: bool):
    d = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    d["instances"]["Q1"]["params"]["junction_type"] = "Manhattan"  # no PDK value
    if not with_lj:
        d["instances"]["Q1"].pop("junction")
    path = tmp_path / ("with.json" if with_lj else "without.json")
    path.write_text(json.dumps(d), encoding="utf-8")
    return path


def test_default_subset_is_checked_when_nothing_is_selected(tmp_path, qcc_cli):
    bad = _design_without_lj(tmp_path, False)
    miss = jfetch.missing_default(bad)
    assert list(miss) == ["Q1"] and "no junction L_J" in miss["Q1"] and "Manhattan" in miss["Q1"]
    assert jfetch.missing_default(bad) is miss  # cached while design.json is unchanged
    assert jfetch.missing_default(_design_without_lj(tmp_path, True)) == {}
    assert jfetch.missing_default(tmp_path / "nope.json") == {}


def test_cli_junctions_default(tmp_path, qcc_cli):
    bad = _design_without_lj(tmp_path, False)
    run = subprocess.run([qcc_cli, "-m", "quantcore_circuits.cli", "design", "junctions", str(bad), "--default", "--json"],
                         capture_output=True, text=True, check=False, env={**os.environ,
                                                                           "PYTHONIOENCODING": "utf-8"})
    assert run.returncode == 1
    data = json.loads(run.stdout.strip().splitlines()[-1])
    assert list(data["junctions"]) == ["Q1"] and list(data["missing"]) == ["Q1"]


def test_precheck_scope_rule_is_in_the_dialog_source():
    """Selected: the sidecar rule; nothing selected and the default subset: ``jfetch.missing_default``; the run and the
    export are blocked for eigenmode only."""
    text = (ROOT / "kplugin" / "python" / "qcc_kplugin" / "flow.py").read_text(encoding="utf-8")
    assert "simsetup.missing_junctions(names, data, tools.CATEGORY, SESSION.design())" in text
    assert "jfetch.missing_default(SESSION.design_path)" in text
    assert "run_btn.enabled = not miss" in text and "exp_btn.enabled = not miss" in text
    assert "analysis == simsetup.EIGEN" in text.split("miss, why = [], {}")[1][:200]


# ---- the simulation layout (job geometry, no AEDT) ------------------------------------------------------------------
@pytest.fixture
def fake_flow(tmp_path, monkeypatch):
    design = tmp_path / "chip.json"
    shutil.copy(EXAMPLE, design)
    monkeypatch.setattr(SESSION, "design_path", design)
    monkeypatch.setattr(SESSION, "layout_path", tmp_path / "build" / "chip.oas")
    monkeypatch.setattr(SESSION, "data", {"instances": {"Q1": {"cell": "Xmon"}}, "routes": {"R1": {}}})
    monkeypatch.setattr(flow, "_design_ready", lambda: True)
    monkeypatch.setattr(flow, "selected_names", lambda: [])
    monkeypatch.setattr(flow, "message", lambda *a, **k: None)
    monkeypatch.setattr(flow, "simlayout_root", lambda: tmp_path / "simlayout")
    runs, asked = [], []

    class Job:
        finished = True

        def wait(self, *_a):
            return True

    monkeypatch.setattr(flow, "_run", lambda steps, label, done, status=None, cwd=None: runs.append(
        {"steps": [[str(x) for x in s] for s in steps], "label": label, "done": done}) or Job())
    monkeypatch.setattr(flow, "choose", lambda title, text, choices, checkbox=None: asked.append(choices) or (0, False))
    missing, windows = {}, []  # the default subset's pre-check (qcc design junctions --default), set by a test
    monkeypatch.setattr(jfetch, "missing_default", lambda path: dict(missing))
    monkeypatch.setattr(flow, "info_window", lambda title, text, buttons=None: windows.append(
        {"title": title, "text": text, "buttons": buttons or {}}))
    return type("F", (), {"runs": runs, "asked": asked, "design": design, "tmp": tmp_path, "missing": missing,
                          "windows": windows})


def test_sim_layout_args_never_write_the_design(fake_flow):
    f = fake_flow
    flow.open_sim_layout(names=["Q1", "R1"])
    args = f.runs[-1]["steps"][0]
    assert args[:3] == ["sim", "subset", str(f.design)] and "--no-write-group" in args and "-o" in args
    assert args[args.index("--instances") + 1] == "Q1,R1" and f.runs[-1]["label"] == "Open simulation layout"
    assert args[args.index("-a") + 1] == "q3d_cmatrix" or args[args.index("-a") + 1] == "hfss_eigenmode"
    flow.open_sim_layout()  # nothing selected: asks; the first choices are the default subset, per analysis
    args = f.runs[-1]["steps"][0]
    assert "--default" in args and f.asked[-1][0].startswith("The default subset for HFSS eigenmode")
    assert args[args.index("-a") + 1] == "hfss_eigenmode"  # the first choice: with the resonator and the feedline
    assert f.asked[-1][1].startswith("The default subset for Q3D")
    assert f.asked[-1][2:] == ["The saved sim group Q1R1"]  # the example's saved group is offered too
    d = json.loads(f.design.read_text(encoding="utf-8"))
    d["sim_groups"] = {"G1": {"select": ["Q1"], "analyses": ["hfss_eigenmode"]}}
    f.design.write_text(json.dumps(d), encoding="utf-8")
    flow.open_sim_layout(group="G1")
    args = f.runs[-1]["steps"][0]
    assert args[args.index("--group") + 1] == "G1" and args[args.index("-a") + 1] == "hfss_eigenmode"
    assert json.loads(f.design.read_text(encoding="utf-8")) == d  # the design file was not touched by the plugin


def test_sim_layout_menu_checks_lj_before_the_export(fake_flow, monkeypatch):
    """Open simulation layout (menu, or the dialog's button) runs the Simulate dialog's pre-check: an eigenmode layout
    with a qubit without L_J is not exported; the window names it and offers the Q3D layout, which needs none."""
    from qcc_kplugin import tools

    f = fake_flow
    f.missing["Q1"] = "Q1: no junction L_J (its Manhattan junction has no PDK value)"
    flow.open_sim_layout()  # nothing selected, first choice: the default subset for eigenmode
    assert f.runs == [] and "Q1: no junction L_J" in f.windows[-1]["text"]
    assert "Edit selected component" in f.windows[-1]["text"] and "Q3D" in f.windows[-1]["text"]
    label, again = f.windows[-1]["buttons"]["q3d"]
    assert label == "Open the Q3D layout instead"
    again()  # the Q3D render of the same default subset: no L_J needed, exported
    args = f.runs[-1]["steps"][0]
    assert "--default" in args and args[args.index("-a") + 1] == "q3d_cmatrix"
    # a selection or a saved group: the sidecar rule (simsetup.missing_junctions) on its qubits
    monkeypatch.setattr(tools, "CATEGORY", {"Xmon": "qubit"})
    d = json.loads(f.design.read_text(encoding="utf-8"))
    d["instances"]["Q1"].pop("junction")
    d["instances"]["Q1"]["params"]["junction_type"] = "Manhattan"
    d["sim_groups"] = {"G1": {"select": ["Q1"], "analyses": ["eigenmode_epr"]}}
    f.design.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(SESSION, "data", {"instances": {"Q1": {"cell": "Xmon", "junction": {
        "kind": "SQUID", "Lj_eff_nH": None, "error": "Q1: no junction L_J (Manhattan)"}}}})
    n = len(f.runs)
    flow.open_sim_layout(names=["Q1"], analysis=simsetup.EIGEN)
    flow.open_sim_layout(group="G1")
    assert len(f.runs) == n and len(f.windows) == 3 and "Q1: no junction L_J (Manhattan)" in f.windows[-1]["text"]
    flow.open_sim_layout(names=["Q1"], analysis=simsetup.Q3D)  # capacitances only: exported
    flow.open_sim_layout(group="G1", analysis="q3d_cmatrix")
    assert len(f.runs) == n + 2 and len(f.windows) == 3


def test_capacitance_analyses_copy_matches_the_library():
    from quantcore_circuits.sim_tools import builder

    assert simsetup.CAPACITANCE_ANALYSES == builder.CAPACITANCE_ANALYSES
    assert simsetup.Q3D in simsetup.CAPACITANCE_ANALYSES and simsetup.EIGEN not in simsetup.CAPACITANCE_ANALYSES


def test_sim_layout_export_with_the_library(tmp_path, qcc_cli):
    """The command the menu item starts: the default subset and a saved group, written to a folder, no design change."""
    design = tmp_path / "chip.json"
    shutil.copy(EXAMPLE, design)
    d = json.loads(design.read_text(encoding="utf-8"))
    d["sim_groups"] = {"G1": {"select": ["Q1", "R1"], "analyses": ["hfss_eigenmode"]}}
    design.write_text(json.dumps(d), encoding="utf-8")
    before = design.read_bytes()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "QCC_LIVE": "0"}
    for tag in ("default", "group"):
        out = tmp_path / f"job_{tag}"
        args = flow.sim_layout_args(design, out, "group" if tag == "group" else "default", [], "hfss_eigenmode",
                                    "G1" if tag == "group" else None)
        run = subprocess.run([qcc_cli, "-m", "quantcore_circuits.cli", *map(str, args)], capture_output=True, text=True,
                             check=False, env=env)
        assert run.returncode == 0, run.stdout + run.stderr
        meta = json.loads((out / "job.json").read_text(encoding="utf-8"))
        assert (out / f"{meta['simulation_name']}.gds").exists() and (out / f"{meta['simulation_name']}.json").exists()
    assert design.read_bytes() == before  # neither the default subset nor the group wrote the design
    assert flow.sim_layer_name("1t1_gap").startswith("gap") and flow.sim_layer_name("1t1_signal_2").startswith("signal 2")
    assert flow.sim_layer_name("1t1_ground").startswith("ground")


def test_menu_item_and_dialog_button_are_wired():
    assert any(a[:2] == ("simulate", "qcc_sim_layout") and a[3] is flow.open_sim_layout for a in flow.ACTIONS)
    text = (ROOT / "kplugin" / "python" / "qcc_kplugin" / "flow.py").read_text(encoding="utf-8")
    assert 'go("layout")' in text and 'picked["action"] == "layout"' in text

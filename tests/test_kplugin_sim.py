"""Simulate: what is rendered for a selection (Q3D or eigenmode), the solver settings, the convergence feedback, and
the hanger coupler with narrowed facing gaps. No AEDT is started: exports and plain logic only."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kplugin" / "python"))

from qcc_kplugin import design_io, simsetup  # noqa: E402

EXAMPLE = ROOT / "examples" / "q1_r1_feedline.json"


def test_recommend_eigenmode_for_lines_and_q3d_for_qubits_alone():
    data = {"instances": {"Q1": {"cell": "Xmon"}, "PAD_W": {"cell": "BondPad"}, "C1": {"cell": "CpweFingerCapacitor"}},
            "routes": {"R1": {}, "FL": {}}}
    cats = {"Xmon": "qubit", "BondPad": "launcher", "CpweFingerCapacitor": "capacitor"}
    assert simsetup.recommend(["Q1"], data, cats)[0] == simsetup.Q3D
    assert simsetup.recommend(["Q1", "C1"], data, cats)[0] == simsetup.Q3D
    assert simsetup.recommend(["Q1", "R1", "FL"], data, cats)[0] == simsetup.EIGEN
    assert simsetup.recommend(["PAD_W"], data, cats)[0] == simsetup.EIGEN
    design = {"instances": {"Q1": {"cell": "Xmon"}}}
    assert simsetup.missing_junctions(["Q1", "R1"], data, cats, design) == ["Q1"]
    design["instances"]["Q1"]["junction"] = {"Lj_nH": 12}
    assert simsetup.missing_junctions(["Q1"], data, cats, design) == []


def test_selection_group_renders_the_selection_plus_joins_and_end_pads(tmp_path):
    from quantcore_circuits import guiflow

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    spec, notes = guiflow.selection_group(design, ["Q1", "FL"], "hfss_eigenmode")
    assert spec["select"][:2] == ["Q1", "FL"] and "R1" in spec["select"]  # R1 joins Q1 and FL (hanger)
    assert {"PAD_W", "PAD_E"} <= set(spec["select"]) and "FLUX" not in spec["select"]
    assert spec["analyses"] == ["hfss_eigenmode"] and any("R1" in n for n in notes)
    with pytest.raises(ValueError, match="nothing to simulate"):
        guiflow.selection_group(design, ["nope"])


def test_eigenmode_export_of_a_selection_renders_every_part(tmp_path):
    from quantcore_circuits import guiflow

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    jobs = guiflow.export_manual(design, ["Q1", "R1", "FL"], analysis="hfss_eigenmode", out=tmp_path / "job",
                                 fast=False, settings={"maximum_passes": 12}, say=lambda *_: None)
    job = json.loads((jobs[0] / "job.json").read_text(encoding="utf-8"))
    assert job["select"] == ["Q1", "R1", "FL", "PAD_W", "PAD_E"]
    assert {"R1", "FL"} <= set(job["routes_in_sim"])
    kinds = {p["name"]: p["kind"] for p in job["ports"]}
    assert kinds["Q1.junction"] == "junction" and kinds["PAD_W.pad"] == "lumped" and kinds["PAD_E.pad"] == "lumped"
    assert job["settings"]["maximum_passes"] == 12
    # Q3D of the qubit alone: the resonator is cut to a stub port, the box is the qubit's
    jobs = guiflow.export_manual(design, ["Q1"], analysis="q3d_cmatrix", out=tmp_path / "q3d", say=lambda *_: None)
    job = json.loads((jobs[0] / "job.json").read_text(encoding="utf-8"))
    assert {p["kind"] for p in job["ports"]} == {"junction", "waveguide"} and "R1" not in job["routes_in_sim"]


@pytest.mark.parametrize("names, analysis", [(["Q1", "R1", "FL"], "hfss_eigenmode"), (["Q1"], "q3d_cmatrix"),
                                              (["Q1", "R1"], "q3d_cmatrix")])
def test_sim_preview_is_what_the_export_renders(tmp_path, names, analysis):
    """The overlay the plugin draws (``qcc sim preview``) = the box, ports and routes of the exported job folder."""
    from quantcore_circuits import guiflow

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    before = design.read_text(encoding="utf-8")
    prev = guiflow.preview_groups(design, names, analysis=analysis)
    assert design.read_text(encoding="utf-8") == before  # nothing is written
    (group,) = prev["groups"]
    jobs = guiflow.export_manual(design, names, analysis=analysis, out=tmp_path / "job", say=lambda *_: None,
                                 write_group=False)
    job = json.loads((jobs[0] / "job.json").read_text(encoding="utf-8"))
    sim = json.loads((jobs[0] / f"{job['simulation_name']}.json").read_text(encoding="utf-8"))
    assert group["box"] == job["box_um"] and group["select"] == job["select"] and group["routes"] == job["routes_in_sim"]
    assert [(p["number"], p["kind"], p["name"]) for p in group["ports"]] == [(p["number"], p["kind"], p["name"])
                                                                              for p in job["ports"]]
    for mine, exported in zip(group["ports"], sim["ports"]):  # the same port positions as the KQC json
        assert mine["at"] == pytest.approx(exported["signal_location"][:2], abs=1e-3)
        assert mine["junction"] == bool(exported["junction"])
    assert {p["kind"] for p in group["ports"]} >= {"junction"}


def test_sim_preview_of_a_saved_group_and_the_cli(tmp_path):
    import subprocess

    from quantcore_circuits import guiflow

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    prev = guiflow.preview_groups(design, group="Q1R1")  # analysis: the group's first
    assert prev["groups"][0]["name"] == "Q1R1" and prev["analysis"] == "q3d_cmatrix" and prev["groups"][0]["select"] == ["Q1", "R1"]
    with pytest.raises(ValueError, match="no sim group"):
        guiflow.preview_groups(design, group="nope")
    whole = guiflow.preview_groups(design, whole=True)["groups"][0]
    assert whole["whole"] and whole["ports"] == [] and len(whole["box"]) == 4
    out = subprocess.run([sys.executable, "-m", "quantcore_circuits.cli", "sim", "preview", str(design), "-g", "Q1R1"],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr[-400:]
    assert json.loads(out.stdout.strip().splitlines()[-1])["groups"][0]["box"] == prev["groups"][0]["box"]


CONV = """Setup : Setup1
==================
Number of Passes
Completed : {n}
Maximum   : {n}
==================
Criterion : Delta %
Target    : 2
Current   : {last}
==================
Pass|# Triangle|Delta %|
{rows}
"""


def _job(tmp_path, deltas):
    job = tmp_path / "j"
    job.mkdir()
    (job / "job.json").write_text(json.dumps({"analysis": "q3d_cmatrix", "settings": {
        "percent_error": 2.0, "maximum_passes": len(deltas)}}), encoding="utf-8")
    rows = "\n".join(f"{i + 1:4d}|{1000 * (i + 1):10d}|{('N/A' if d is None else f'{d:.4f}'):>7}|"
                     for i, d in enumerate(deltas))
    (job / "x_project_convergence.txt").write_text(CONV.format(n=len(deltas), last=deltas[-1], rows=rows),
                                                   encoding="utf-8")
    return job


def test_import_reads_a_job_folder_again_when_its_aedt_outputs_are_newer(tmp_path):
    import os
    import time

    from quantcore_circuits import guiflow

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    jobs = guiflow.export_manual(design, ["Q1"], analysis="q3d_cmatrix", out=tmp_path / "job", say=lambda *_: None)
    job = jobs[0]
    assert (job / "scripts" / "qcc_collect.py").exists() and "qcc_collect.py" in (job / "README.md").read_text(
        encoding="utf-8")
    (job / "results").mkdir(exist_ok=True)
    res = job / "results" / "results.json"
    res.write_text(json.dumps({"analysis": "q3d_cmatrix", "cmatrix": {"labels": ["x"], "matrix": [[1.0]]}}),
                   encoding="utf-8")
    old = time.time() - 100
    os.utime(res, (old, old))
    rows = "   1|  1000|    N/A|\n   2|  2000| 1.2000|"
    (job / "x_project_convergence.txt").write_text(CONV.format(n=2, last=1.2, rows=rows), encoding="utf-8")
    called = []
    import quantcore_circuits.analysis.results as R
    real = R.collect_results
    R.collect_results = lambda d: called.append(d) or {}
    try:
        _job, _errors, warns = guiflow.stage_import(design, job)
    finally:
        R.collect_results = real
    assert called and any("read again" in w for w in warns)


def test_collect_script_mode_in_the_aedt_source():
    from quantcore_circuits.sim_tools.aedt_scripts import AEDT_SOURCE, COLLECT_SCRIPT, SCRIPT_MODE

    compile(AEDT_SOURCE, COLLECT_SCRIPT, "exec")
    assert SCRIPT_MODE[COLLECT_SCRIPT] == "collect" and 'MODE == "collect"' in AEDT_SOURCE
    assert "AnalyzeAll" in AEDT_SOURCE.split('if MODE == "solve":', 1)[1].split("oProject.Save()", 1)[0]


def test_convergence_feedback_proposes_more_passes_only_when_needed(tmp_path):
    from quantcore_circuits import guiflow

    fb = guiflow.convergence_feedback(_job(tmp_path, [None, 5.0, 3.1]))
    assert fb["converged"] is False and fb["next"] == {"maximum_passes": 7, "percent_error": 2.0}
    (tmp_path / "b").mkdir()
    fb = guiflow.convergence_feedback(_job(tmp_path / "b", [None, 1.2]))
    assert fb["converged"] is True and fb["next"] == {}


def test_hanger_with_narrowed_facing_gaps(tmp_path):
    from quantcore_circuits.assembly.plan import plan_design
    from quantcore_circuits.design import load_design

    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    plain = plan_design(load_design(data))
    assert plain.metal == [] and "metal" not in json.loads(plain.to_json())  # unchanged designs: no extra metal
    data["routes"]["R1"]["to"].update(coupler_gap=3.0, line_gap=3.0, ground_gap=4.0)
    plan = plan_design(load_design(data))
    (poly,) = plan.metal
    ys = sorted({round(q[1], 3) for q in poly})
    assert ys == [3738.0, 3742.0]  # the 4 µm ground strip between the narrowed gaps (line at y 3750, right side)
    nodes = plan.routes["R1"].polyline()
    assert abs(nodes[-1].y - 3730.0) < 1e-6  # centre lines 20 µm apart (28 µm with the full 6 µm gaps)
    data["routes"]["R1"]["to"]["coupler_gap"] = 7.0
    from quantcore_circuits.route.router import RoutingError

    with pytest.raises(RoutingError, match="at most the CPW gaps"):
        plan_design(load_design(data))


def test_junction_triplet_and_lom_rows():
    t = design_io.junction_triplet(1.4, lj_nh=12.0)
    assert abs(t["Ic_nA"] - 27.43) < 0.01 and abs(t["Rn_kohm"] - 80.18) < 0.05
    assert abs(design_io.junction_triplet(1.4, rn_kohm=t["Rn_kohm"])["Lj_nH"] - 12.0) < 1e-9
    side = {"lom": {"branches": {
        "C_Q1": {"type": "C", "nodes": ["Q1", "gnd"], "value": {"estimate": 64.05, "estimate_source": "calibration"}},
        "J_Q1": {"type": "SQUID", "nodes": ["Q1", "gnd"], "value": {"Lj_nH": 12.0, "Cj_fF": 2.0}},
        "R1": {"type": "TLres", "nodes": ["Q1.claw_n", "gnd"], "value": {"kind": "lambda/4", "length_um": 4200,
                                                                         "f_GHz": 7.5, "Z0_ohm": 55.1}},
        "K_R1": {"type": "HANGER", "nodes": ["Q1.claw_n", "FL"], "value": {"coupling_length_um": 300,
                                                                           "ground_gap_um": 6, "kappa_MHz": 0.26}}}}}
    q1 = {b: text for b, _, text in design_io.lom_rows(side, "Q1")}
    assert q1["C_Q1"].startswith("64.05 fF") and q1["J_Q1"].startswith("L_J 12 nH")
    r1 = {b: text for b, _, text in design_io.lom_rows(side, "R1")}
    assert set(r1) == {"R1", "K_R1"} and "7.5 GHz" in r1["R1"] and "κ 0.26 MHz" in r1["K_R1"]


def test_auto_run_checks_the_export_before_aedt_and_stops_on_errors(tmp_path, monkeypatch):
    from quantcore_circuits import guiflow
    from quantcore_circuits.sim_tools import geometry_check, hfss

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    monkeypatch.setattr("quantcore_circuits.sim_tools.ansys.find_ansys_executable", lambda: "ansysedt.exe")
    solved = []
    monkeypatch.setattr(hfss, "solve_job", lambda *a, **k: solved.append(a) or None)
    monkeypatch.setattr(geometry_check, "check_job", lambda job: {"errors": ["nets 1 and 2 touch"], "warnings": []})
    with pytest.raises(RuntimeError, match="nothing was solved: nets 1 and 2 touch"):
        guiflow.run_auto(design, ["Q1"], analysis="q3d_cmatrix", say=lambda *_: None)
    assert not solved  # AEDT never started


def test_dialog_settings_start_at_the_librarys_fast_values():
    from quantcore_circuits.sim_tools.export import (
        DEFAULT_SETTINGS, FAST_ISLAND_SEED, FAST_MESH_SEED, FAST_SETTINGS)

    for analysis in simsetup.ANALYSES:
        fast = {**DEFAULT_SETTINGS[analysis], **FAST_SETTINGS[analysis]}
        for k, v in simsetup.FAST[analysis].items():
            if k == "gap_seed":
                assert FAST_MESH_SEED[analysis]["1t1_gap"] == v
            elif k == "island_seed":
                assert FAST_ISLAND_SEED == v
            else:
                assert fast[k] == v, (analysis, k)
    args = simsetup.cli_args(simsetup.EIGEN, {"maximum_passes": 6, "gap_seed": None})
    assert args[:3] == ["--full", "--set", "minimum_passes=1"] and "maximum_passes=6" in args
    assert not any(a.startswith("gap_seed") for a in args) and "island_seed=10.0" in args
    assert simsetup.parse_settings(simsetup.Q3D, {"percent_error": "1", "maximum_passes": "12",
                                                  "minimum_converged_passes": "2"}) == {
        "percent_error": 1.0, "maximum_passes": 12, "minimum_converged_passes": 2}
    with pytest.raises(ValueError, match="not a number"):
        simsetup.parse_settings(simsetup.Q3D, {"percent_error": "x"})


def test_dialog_settings_export_like_the_fast_run(tmp_path):
    """The dialog's fast values passed explicitly give the same solver settings as a fast export."""
    from quantcore_circuits import guiflow

    design = tmp_path / "q.json"
    shutil.copy(EXAMPLE, design)
    say = lambda *_: None  # noqa: E731
    fast = guiflow.export_manual(design, ["Q1", "R1", "FL"], analysis="hfss_eigenmode", out=tmp_path / "a",
                                 say=say)[0]
    args = simsetup.cli_args(simsetup.EIGEN, {})
    sets = dict(a.split("=", 1) for a in args[args.index("--set"):] if a != "--set")
    settings = {k: (json.loads(v) if v[0].isdigit() else v) for k, v in sets.items()}
    expl = guiflow.export_manual(design, ["Q1", "R1", "FL"], analysis="hfss_eigenmode", out=tmp_path / "b",
                                 fast=False, settings=settings, say=say)[0]
    a = json.loads((fast / "job.json").read_text(encoding="utf-8"))["settings"]
    b = json.loads((expl / "job.json").read_text(encoding="utf-8"))["settings"]
    assert a == b, (a, b)

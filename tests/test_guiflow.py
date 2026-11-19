"""The GUI flow's library half (``quantcore_circuits.guiflow``, ``qcc sim subset|auto``, ``qcc results import|propose|
apply|template``): subset choice, manual job export, results import, tune. No AEDT is started here: the solved Q1 + R1
job in ``tests/data/gui_flow_q1r1_job`` is a real fast Q3D run (AEDT 2024 R1) kept as the fixture."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantcore_circuits import guiflow
from quantcore_circuits.cli import app
from tests.conftest import have

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "gui_flow_q1r1_job"
needs_analysis = pytest.mark.skipif(
    not have("qiskit_metal", "scqubits", "qutip"), reason="analysis stack (quantum-metal, scqubits, qutip) not installed"
)


@pytest.fixture
def work(tmp_path, example_path):
    """A scratch copy of the example design (the flow writes its sim group and run files next to it)."""
    path = tmp_path / "q1.json"
    shutil.copy(example_path, path)
    return path


def test_selection_names_qubits_and_readouts(work):
    assert guiflow.resolve_selection(work, ["Q1"])[0] == ["Q1"]
    assert guiflow.resolve_selection(work, ["R1"])[0] == ["Q1"]  # a readout route stands for its qubit
    assert guiflow.resolve_selection(work, ["Q1", "R1", "Q1"])[0] == ["Q1"]
    qubits, notes = guiflow.resolve_selection(work, ["PAD_W", "FL", "nope"])
    assert qubits == [] and len(notes) == 3  # pads, the feedline and unknown names are not qubits
    assert guiflow.resolve_selection(work, [], default=True)[0] == ["Q1"]
    assert guiflow.resolve_selection(work, [])[0] == []  # nothing selected, no default: the caller asks


def test_groups_are_written_once_and_replaced(work):
    out = guiflow.pick_groups(work, ["Q1"], margin_um=250)
    assert out["groups"] == ["gui_sim"] and out["qubits"] == ["Q1"] and "FL" in out["describe"]
    data = json.loads(work.read_text(encoding="utf-8"))
    g = data["sim_groups"]["gui_sim"]
    assert g["select"][:2] == ["Q1", "R1"] and g["margin_um"] == 250 and g["analyses"] == ["q3d_cmatrix"]
    assert "Q1R1" in data["sim_groups"]  # the user's own group stays
    before = work.read_text(encoding="utf-8")
    guiflow.pick_groups(work, ["Q1"], margin_um=250)
    assert work.read_text(encoding="utf-8") == before  # the same subset does not touch the file again
    guiflow.pick_groups(work, ["Q1"], margin_um=400)
    assert json.loads(work.read_text(encoding="utf-8"))["sim_groups"]["gui_sim"]["margin_um"] == 400
    with pytest.raises(ValueError, match="no qubit"):
        guiflow.pick_groups(work, ["FL"])
    assert guiflow.pick_groups(work, whole=True)["groups"] == ["chip"]  # the built-in whole-chip group


def test_manual_export_writes_job_readme_and_template(work, tmp_path):
    res = CliRunner().invoke(app, ["sim", "subset", str(work), "-i", "Q1,R1", "-o", str(tmp_path / "job")])
    assert res.exit_code == 0, res.output
    job = tmp_path / "job"
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    assert meta["group"] == "gui_sim" and meta["analysis"] == "q3d_cmatrix" and meta["fem_fast"] is True
    assert meta["select"] == ["Q1", "R1"] and meta["settings"]["percent_error"] == 2.0  # the fast settings
    assert (job / "scripts" / "qcc_solve.py").exists() and (job / "simulation.bat").exists()
    readme = (job / "README.md").read_text(encoding="utf-8")
    for must in ("simulation.bat", "qcc_solve.py", "Bring back", "results/results.json", "Import results",
                 "qcc results import", '"cmatrix"', "labels"):
        assert must in readme
    tpl = json.loads((job / "results_template.json").read_text(encoding="utf-8"))
    assert tpl["cmatrix"]["labels"] == ["Q1.island", "Q1.claw_n"] and tpl["group"] == "gui_sim"


def test_manual_export_needs_a_qubit(work, tmp_path):
    res = CliRunner().invoke(app, ["sim", "subset", str(work), "-i", "FL", "-o", str(tmp_path / "job")])
    assert res.exit_code == 1 and "no qubit" in res.output


def test_results_format_and_template_are_documented():
    res = CliRunner().invoke(app, ["results", "template", "--format", "x.json"])
    assert res.exit_code == 0 and '"cmatrix"' in res.output and "MAXWELL" in res.output and "eigenmodes" in res.output


def test_validate_results_catches_wrong_files(work):
    good = json.loads((FIXTURE / "results" / "results.json").read_text(encoding="utf-8"))
    assert guiflow.validate_results(work, good, "chip")[0] == []
    assert "analysis" in guiflow.validate_results(work, {"cmatrix": good["cmatrix"]})[0][0]
    wrong = {"analysis": "q3d_cmatrix", "cmatrix": {"labels": ["A", "B"], "matrix": [[1, -0.1], [-0.1, 1]]}}
    errors, _ = guiflow.validate_results(work, wrong, "chip")
    assert errors and "none of the cmatrix labels" in errors[0]
    shape = {"analysis": "q3d_cmatrix", "cmatrix": {"labels": ["Q1.island"], "matrix": [[1, 2], [3, 4]]}}
    assert "labels" in guiflow.validate_results(work, shape, "chip")[0][0]
    empty = {"analysis": "q3d_cmatrix"}
    assert "nothing to read" in guiflow.validate_results(work, empty, "chip")[0][0]
    half = json.loads(json.dumps(good))
    half["cmatrix"]["labels"][1] = "mystery"
    errors, warns = guiflow.validate_results(work, half, "chip")
    assert not errors and any("mystery" in w for w in warns)


def test_stage_import_folder_and_loose_file(work, tmp_path):
    job = tmp_path / "solved"
    shutil.copytree(FIXTURE, job)
    d, errors, warns = guiflow.stage_import(work, job)
    assert d == job and not errors
    assert any("design has changed" in w for w in warns)  # the fixture was solved for another revision of the file
    loose = tmp_path / "mine.json"
    loose.write_text((FIXTURE / "results" / "results.json").read_text(encoding="utf-8"), encoding="utf-8")
    d2, errors, warns = guiflow.stage_import(work, loose)
    assert not errors and d2.name == "q1_r1_feedline_imported_mine"
    staged = json.loads((d2 / "job.json").read_text(encoding="utf-8"))
    assert staged["status"] == "imported" and staged["design"] == "q1_r1_feedline"
    d3, errors, _ = guiflow.stage_import(work, job / "results" / "results.json")  # the results file of a job folder
    assert d3 == job and not errors
    assert guiflow.stage_import(work, tmp_path / "missing.json")[1]


@needs_analysis
def test_import_then_propose_and_apply(work, tmp_path):
    """Manual round trip without AEDT: import the solved job, see it against the targets, propose, apply."""
    job = tmp_path / "solved"
    shutil.copytree(FIXTURE, job)
    out = guiflow.import_results(work, [job], say=lambda *_a: None)
    assert any(r["param"] == "Q1.f_q_GHz" and 5.0 < r["value"] < 5.5 for r in out["rows"])
    rec = guiflow.flow_record(work)
    assert rec["source"] == "import" and rec["jobs"] == [str(job)]
    state = json.loads((work.parent / "build" / "q1_r1_feedline" / "state.json").read_text(encoding="utf-8"))
    assert state["design"]["hash"] and state["elements"]

    # the sidecar's results (what KLayout's Results tab shows) are found beside the layout, not only under cwd/build
    from quantcore_circuits.assembly import build, write_layout

    layout = work.parent / "build" / "q1.oas"
    write_layout(build(work), layout)
    side = json.loads(layout.with_name("q1.qcc.json").read_text(encoding="utf-8"))
    assert side["results"]["Q1"]["params"] and not side["results"]["Q1"]["stale"]

    prop_file = tmp_path / "proposal.json"
    res = CliRunner().invoke(app, ["results", "propose", str(work), "-o", str(prop_file)])
    assert res.exit_code == 0, res.output
    prop = json.loads(prop_file.read_text(encoding="utf-8"))
    assert prop["tunable"] and prop["knobs"] and prop["basis"].startswith("the FEM results of")
    assert all({"knob", "old", "new"} <= set(k) for k in prop["knobs"]) and prop["objective"] is not None
    new_file = tmp_path / "new.json"
    res = CliRunner().invoke(app, ["results", "apply", str(work), str(prop_file), "-o", str(new_file)])
    assert res.exit_code == 0, res.output
    new = json.loads(new_file.read_text(encoding="utf-8"))
    knob = prop["knobs"][0]
    inst, name = knob["knob"].split(".")
    assert new["instances"][inst]["params"][name] == pytest.approx(knob["new"])
    # the design moved on (another edit of the same knob): the proposal is refused, not applied blindly
    data = json.loads(work.read_text(encoding="utf-8"))
    data["instances"][inst]["params"][name] = knob["old"] * 1.5
    work.write_text(json.dumps(data), encoding="utf-8")
    res = CliRunner().invoke(app, ["results", "apply", str(work), str(prop_file), "-o", str(new_file)])
    assert res.exit_code == 1 and "propose again" in res.output


def test_propose_says_when_nothing_can_be_tuned(work, tmp_path, monkeypatch):
    """A design without targets (or without an Xmon + λ/4 pair) gets a plain explanation, not a traceback."""
    data = json.loads(work.read_text(encoding="utf-8"))
    data["targets"] = {}
    work.write_text(json.dumps(data), encoding="utf-8")
    if not have("qiskit_metal", "scqubits", "qutip"):
        pytest.skip("analysis stack not installed")
    res = guiflow.propose(work, None, tmp_path / "p.json", say=lambda *_a: None)
    assert not res["tunable"] and "no targets" in res["message"].lower() and res["knobs"] == []


def test_long_job_paths_move_to_a_short_folder(work, monkeypatch):
    """AEDT fails on Windows paths over 260 characters (its *.aedtresults folders repeat the job name)."""
    real = guiflow.aedt_path_too_long
    monkeypatch.setattr(guiflow, "aedt_path_too_long", lambda job, analysis="": False)
    assert guiflow.short_job_dir(work, "gui_sim", "q3d_cmatrix").parent == work.parent / "build" / "jobs"
    monkeypatch.setattr(guiflow, "aedt_path_too_long", lambda job, analysis="": "qcc_jobs" not in str(job))
    job = guiflow.short_job_dir(work, "gui_sim", "q3d_cmatrix")
    assert job.parent.name == "qcc_jobs" and job.name == "q1_r1_feedline_gui_sim_q3d_cmatrix"
    # the real check: the job folder name is repeated in AEDT's own folders, ~85 characters deeper
    import os

    if os.name == "nt":
        assert real(Path("C:/") / ("x" * 150) / ("y" * 40)) and not real(Path("C:/qcc_jobs/q1_sim"))
        # the failing path of 2026-11-15 was exactly 260 characters long: it must count as too long
        failing = Path("C:/Users/abcde/AppData/Local/Temp/claude/2d488478c1110aaf/bc57212e-332b-4b72-a649-9a7d016579c9"
                       "/scratchpad/auto/build/jobs/q1_r1_feedline_gui_sim_q3d_cmatrix")
        assert real(failing)


def test_auto_refuses_without_aedt(work, monkeypatch):
    monkeypatch.setattr("quantcore_circuits.sim_tools.ansys.find_ansys_executable", lambda *a, **k: None)
    status = work.parent / "status.json"
    res = CliRunner().invoke(app, ["sim", "auto", str(work), "-i", "Q1", "--status", str(status)])
    assert res.exit_code == 1 and "AEDT" in res.output
    st = json.loads(status.read_text(encoding="utf-8"))
    assert st["state"] == "failed" and "AEDT" in st["message"]
    bad = CliRunner().invoke(app, ["sim", "auto", str(work), "-i", "Q1", "--aedt", "attach"])
    assert bad.exit_code != 0  # never attaches to the user's open AEDT

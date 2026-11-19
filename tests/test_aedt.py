"""AEDT 2024 R1 render / solve / read-back.

Fast tests run on real result files from AEDT 2024 R1 (v241, Windows, 2026-11-03) stored in ``tests/data/aedt_2024r1``
(trimmed ``.aedt`` text, KQC/qcc exports): parsers, settings read-back, C-matrix → fill, EPR → pyEPR estimator,
Touchstone → notch fit. ``solver`` tests render and solve a small job in a new batch AEDT (``-m solver``; also marked
``slow`` so the fast suite never launches AEDT) and are skipped where AEDT 2024 is not installed.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from quantcore_circuits.sim_tools.aedt_scripts import AEDT_SOURCE, RENDER_SCRIPT, SOLVE_SCRIPT, write_scripts
from quantcore_circuits.sim_tools.ansys import find_ansys_executable

DATA = Path(__file__).parent / "data" / "aedt_2024r1"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "q1_r1_feedline.json"
needs_aedt = pytest.mark.skipif(find_ansys_executable() is None, reason="AEDT 2024 (ansysedt v241+) not installed")


def _job(tmp_path: Path, name: str) -> Path:
    job = tmp_path / name
    shutil.copytree(DATA / name, job)
    return job


# --------------------------------------------------------------------------------------------- scripts (no AEDT)


def test_aedt_script_runs_under_ironpython():
    """AEDT 2024 R1 runs batch scripts in IronPython 2.7.4: no f-strings, annotations or walrus in the qcc script."""
    tree = ast.parse(AEDT_SOURCE)
    banned = (ast.JoinedStr, ast.NamedExpr, ast.AnnAssign, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await)
    assert not [type(n).__name__ for n in ast.walk(tree) if isinstance(n, banned)]
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        assert fn.returns is None and all(a.annotation is None for a in fn.args.args), fn.name
        assert not fn.args.kwonlyargs, fn.name
    assert "QuitApplication" not in AEDT_SOURCE  # never closes an AEDT it did not start


def test_job_launchers_never_attach_to_a_running_aedt(example_path, tmp_path):
    from quantcore_circuits.sim_tools import build_simulation, export_job

    job = export_job(build_simulation(example_path, "Q1R1", "eigenmode_epr"), tmp_path / "j")
    bat = (job / "simulation.bat").read_text()
    assert "-ng" in bat and f"scripts/{SOLVE_SCRIPT}" in bat and "run_pyepr_t1_estimate" not in bat
    assert "collect_results" in bat and "import_and_simulate" not in bat
    assert (job / "scripts" / RENDER_SCRIPT).read_text() == AEDT_SOURCE
    assert "-ng" in (job / "simulation.sh").read_text()
    sim = json.loads((job / f"{json.loads((job / 'job.json').read_text())['simulation_name']}.json").read_text())
    assert sim["simulation_flags"] == ["pyepr"]  # KQC still draws the junction lines used for the line voltage
    assert json.loads((job / "job.json").read_text())["settings"]["pyepr"]["substrate_loss_tangent"] == 1e-6


def test_runner_uses_the_qcc_solve_script(example_path, tmp_path):
    from quantcore_circuits.sim_tools import build_simulation, export_job
    from quantcore_circuits.sim_tools.runner import launcher_command

    job = export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"), tmp_path / "j")
    shutil.rmtree(job / "scripts")
    (job / "scripts").mkdir()
    cmd = launcher_command(job)
    assert cmd[1:3] == ["-ng", "-features=SF6694_NON_GRAPHICAL_COMMAND_EXECUTION"]
    assert cmd[-3:] == [f"scripts/{SOLVE_SCRIPT}", "-ScriptArgs", "q1_r1_feedline_Q1R1_q3d_cmatrix.json"]
    assert (job / "scripts" / SOLVE_SCRIPT).exists()  # written for jobs exported before the qcc scripts
    assert write_scripts(job) == job / "scripts"


# --------------------------------------------------------------------------------------------- Q3D (AEDT 2024 R1)


@pytest.mark.aedt_fixture
def test_q3d_project_reads_back():
    from quantcore_circuits.sim_tools.aedt_project import check_settings, project_info

    info = project_info(DATA / "q3d_cmatrix" / "q1_r1_feedline_Q1R1_q3d_cmatrix_project.aedt")
    d = info["designs"][0]
    assert d["design_type"] == "Q3D Extractor"
    assert info["materials"]["sapphire"]["permittivity"] == 10.25
    sub = next(p for p in d["parts"] if p["name"] == "substrate_1")
    assert sub["material"] == "sapphire" and sub["box"]["ZSize"] == "650um" and sub["box"]["ZPosition"] == "-650um"
    assert {k: v["excitations"] for k, v in d["nets"].items() if v["type"] == "SignalNet"} == {"Net1": [1], "Net2": [2]}
    assert d["boundaries"]["ThinCond1"]["BoundType"] == "ThinConductor"  # metal sheets are PEC thin conductors
    job = json.loads((DATA / "q3d_cmatrix" / "job.json").read_text())
    rows = check_settings(info, "q3d_cmatrix", job["settings"])
    assert [r["key"] for r in rows if r["ok"]] == list(job["settings"])
    assert check_settings(info, "q3d_cmatrix", {"percent_error": 1.0})[0]["ok"] is False


@pytest.mark.aedt_fixture
def test_check_project_on_the_q3d_render(tmp_path):
    from quantcore_circuits.sim_tools.hfss import check_project

    report = check_project(_job(tmp_path, "q3d_cmatrix"))
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]
    names = [c["check"] for c in report["checks"]]
    assert "net Net1 = Q1.island" in names and "net Net2 = Q1.claw_n" in names


def test_q3d_results_fill_the_circuit(tmp_path):
    """Real Q3D (sapphire, 0.5 %): Maxwell matrix with named nets → fill → LOM calibration within 3 %."""
    from quantcore_circuits.analysis.results import collect_results
    from quantcore_circuits.circuit.derive import circuit_from_design
    from quantcore_circuits.circuit.fill import fill

    job = _job(tmp_path, "q3d_cmatrix")
    res = collect_results(job)
    cm = res["cmatrix"]
    assert cm["labels"] == ["Q1.island", "Q1.claw_n"] and cm["aedt_nets"] == ["Net1", "Net2"]
    assert cm["source_convention"] == "mutual"
    c = np.asarray(cm["matrix"])
    assert c[0, 0] == pytest.approx(67.25, abs=0.01) and c[1, 1] == pytest.approx(94.02, abs=0.01)
    assert c[0, 1] == c[1, 0] == pytest.approx(-3.177, abs=0.001)
    assert res["aedt"]["aedt"] == "2024.1.0" and res["aedt"]["solve_seconds"] > 0
    # the 2021 R1 silicon run (74.4 / 104.0 / 3.51 fF) rescaled by (εr + 1)/2 agrees within 0.5 %
    si = np.array([74.4, 104.0, 3.51]) * (10.25 + 1) / (11.45 + 1)
    assert np.allclose([c[0, 0], c[1, 1], -c[0, 1]], si, rtol=5e-3)
    filled = fill(circuit_from_design(EXAMPLE, "Q1R1"), EXAMPLE, job)
    v = filled.values
    assert v["C_Q1"].origin == "fem" and v["C_Q1"].extracted == pytest.approx(64.07, abs=0.01)
    for name in ("C_Q1", "Cg_Q1_claw_n", "Cc_Q1_claw_n"):  # Xmon calibration (lom/calibration.py) vs this run
        assert v[name].estimate == pytest.approx(v[name].extracted, rel=0.03), name


def test_q3d_rows_follow_the_aedt_net_order(tmp_path):
    """C-matrix rows are labelled by the AEDT net names recorded in the qcc extras, not by position."""
    from quantcore_circuits.analysis.results import collect_results

    job = _job(tmp_path, "q3d_cmatrix")
    extras_path = next(job.glob("*_project_qcc.json"))
    extras = json.loads(extras_path.read_text())
    exc = extras["excitations"]
    pairs = list(zip(exc[::2], exc[1::2]))
    pairs = [p for p in pairs if p[1] != "SignalNet"] + [("Net2", "SignalNet"), ("Net1", "SignalNet")]
    extras["excitations"] = [x for p in pairs for x in p]
    extras_path.write_text(json.dumps(extras))
    assert collect_results(job)["cmatrix"]["labels"] == ["Q1.claw_n", "Q1.island"]


@pytest.mark.aedt_fixture
def test_cli_check_and_set(tmp_path, monkeypatch):
    """``qcc hfss check JOB`` reads the project back; ``--set k=v`` (JSON values) reaches job.json and KQC's json."""
    from typer.testing import CliRunner

    from quantcore_circuits.cli import app

    res = CliRunner().invoke(app, ["hfss", "check", str(_job(tmp_path, "q3d_cmatrix"))])
    assert res.exit_code == 0 and "ok  net Net1 = Q1.island" in res.output and res.output.strip().endswith("OK")
    monkeypatch.setattr("quantcore_circuits.sim_tools.ansys.find_ansys_executable", lambda *a, **k: None)
    out = tmp_path / "dry"
    args = ["hfss", "render", str(EXAMPLE), "-g", "Q1R1", "-a", "q3d_cmatrix", "-o", str(out), "--dry-run"]
    res = CliRunner().invoke(app, [*args, "--set", "percent_error=1.5", "--set", 'mesh_size={"1t1_gap": 20}'])
    assert res.exit_code == 0, res.output
    job = json.loads((out / "job.json").read_text())
    assert job["settings"]["percent_error"] == 1.5 and job["settings"]["mesh_size"] == {"1t1_gap": 20}
    sim = json.loads((out / f"{job['simulation_name']}.json").read_text())
    assert sim["analysis_setup"]["percent_error"] == 1.5 and sim["mesh_size"] == {"1t1_gap": 20}
    assert job["geometry"]["airbridges"] == "dropped"


# --------------------------------------------------------------------------------------------- eigenmode + EPR
# (defaults, 18 passes / 222k tets: ΔF 0.52 % at the last pass — not converged to 0.1 %)


@pytest.mark.aedt_fixture
def test_eigenmode_project_reads_back(tmp_path):
    from quantcore_circuits.sim_tools.hfss import check_project

    report = check_project(_job(tmp_path, "eigenmode_epr"))
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]
    checks = {c["check"]: c["detail"] for c in report["checks"]}
    assert checks["port 1 Q1.junction: junction RLC"] == "L=1.2e-08H C=2e-15farad"
    assert checks["port 2 FL: 50 Ω termination"] == checks["port 3 FL: 50 Ω termination"] == "50ohm"
    assert sum(r["ok"] is True for r in report["settings"]) == 7


def test_epr_results_from_aedt(tmp_path):
    """.eig (AEDT 2024 rows) + qcc EPR integrals → pyEPR participations and Hamiltonian."""
    from quantcore_circuits.analysis.results import collect_results

    res = collect_results(_job(tmp_path, "eigenmode_epr"))
    modes = res["eigenmodes"]
    assert [round(m["f_GHz"], 4) for m in modes] == [5.2665, 6.6312]
    assert modes[0]["Q"] == pytest.approx(1.09211e6) and modes[1]["Q"] == pytest.approx(29785.1)
    e = res["epr"]
    assert e["junction_names"] == ["Q1.junction"] and e["Lj_nH"] == [pytest.approx(12.0)]
    assert e["p_mj"][0][0] == pytest.approx(0.98895, abs=1e-4) and e["p_mj"][1][0] == pytest.approx(0.0015754, rel=1e-3)
    assert all(abs(u) < 1e-3 for u in e["U_diff"])  # capacitive and inductive energies balance (pyEPR check)
    chi = np.asarray(e["chi_MHz"])
    assert chi[0, 0] == pytest.approx(-282.73, abs=0.05) and chi[0, 1] == pytest.approx(-0.6768, abs=1e-3)
    assert e["f_GHz"][0] == pytest.approx(5.00357, abs=1e-4)  # dressed qubit
    assert e["Q_dielectric"][1] == pytest.approx(1.102e6, rel=1e-3)  # p_substrate 0.907 × tan δ 1e-6
    assert res["aedt"]["solve_seconds"] == pytest.approx(620.4) and res["aedt"]["python"] == "2.7.4"
    conv = res["convergence"]  # pass table + per-pass mode frequencies (KQC "Solution Convergence" report)
    assert not conv["converged"] and conv["passes"][-1] == 18 and conv["elements"][-1] == 221962
    assert conv["delta"][-1] == pytest.approx(0.51901) and len(conv["mode_GHz"]["1"]) == 18
    assert conv["mode_GHz"]["1"][-1] == pytest.approx(5.26653, abs=1e-5)  # Hz in the CSV (unit "[]") → GHz
    ext = modes[0]["f_extrapolated"]  # f(N) = f∞ − C N^−p over the last 5 passes
    assert 5.29 < ext["value"] < 5.36 and ext["change"] > 0


def test_independent_qutip_matches_pyepr(tmp_path):
    """M10: χ and α from a QuTiP diagonalisation of the EPR Hamiltonian (exact cosine, own code) vs pyEPR."""
    from quantcore_circuits.analysis.epr import epr_qutip
    from quantcore_circuits.analysis.results import collect_results

    e = collect_results(_job(tmp_path, "eigenmode_epr"))["epr"]
    q = epr_qutip(e["f_linear_GHz"], e["p_mj"], e["Lj_nH"], e["s_mj"], fock=12)
    chi_q, chi_e = np.asarray(q["chi_MHz"]), np.asarray(e["chi_MHz"])
    assert chi_q[0, 1] == pytest.approx(chi_e[0, 1], rel=0.05)  # dispersive shift within 5 %
    assert chi_q[0, 0] == pytest.approx(chi_e[0, 0], rel=0.01)  # anharmonicity within 1 %
    assert q["f_GHz"] == pytest.approx(e["f_GHz"], abs=1e-3)


def test_pyepr_estimator_joins_the_consensus(tmp_path):
    """Q3D C-matrix (LOM estimators) + eigenmode EPR (pyEPR) in one loop.analyse; FEM κ reaches the pair."""
    from quantcore_circuits.analysis.results import collect_results, combine_jobs
    from quantcore_circuits.loop import analyse

    q3d, epr = _job(tmp_path, "q3d_cmatrix"), _job(tmp_path, "eigenmode_epr")
    collect_results(q3d)
    collect_results(epr)
    job = combine_jobs(q3d, [epr], tmp_path / "combined")
    an = analyse(EXAMPLE, job, readout=False)
    rows = {r.param: r for r in an.rows}
    for param in ("Q1.f_q_GHz", "Q1.alpha_MHz", "R1.chi_MHz", "R1.f_GHz", "R1.kappa_MHz"):
        assert rows[param].chosen_by == "pyepr", param
    assert rows["Q1.alpha_MHz"].chosen == pytest.approx(-282.73, abs=0.05)
    assert {"metal_lom", "qucat", "sqcircuit", "scqubits", "qutip"} <= set(rows["Q1.f_q_GHz"].values)
    assert an.filled.cmatrix is not None and an.filled.values["C_Q1"].origin == "fem"
    k = an.filled.values["K_R1"]
    assert k.origin == "fem" and k.extracted == pytest.approx(0.21662, rel=1e-3)  # eigenmode Q, dielectric removed
    assert an.filled.pairs[0].kappa_MHz == k.extracted


# --------------------------------------------------------------------------------------------- driven S21 (hanger κ)
# group Q1 + R1 (wave ports where FL leaves the box), 10 µm gap seed, 4 passes / 359k tets, fast sweep 6.0–7.2 GHz
# (fixture: the rows within ±5 MHz of the resonance)


@pytest.mark.aedt_fixture
def test_driven_project_reads_back(tmp_path):
    from quantcore_circuits.sim_tools.hfss import check_project

    report = check_project(_job(tmp_path, "hfss_driven"))
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]
    checks = {c["check"]: c["detail"] for c in report["checks"]}
    assert checks["port 1 Q1.junction: junction RLC"] == "L=1.2e-08H C=2e-15farad"  # not a 50 Ω terminal port
    assert checks["port 2 FL: Wave Port"] == checks["port 3 FL: Wave Port"] == "Wave Port"
    rows = {r["key"]: r for r in report["settings"]}
    assert rows["sweep_type"]["found"] == "Fast" and rows["sweep_count"]["found"] == 20001
    assert rows["mesh_size.1t1_gap"]["ok"] and rows["frequency"]["found"] == "6.63GHz"


def test_driven_s21_notch_from_aedt(tmp_path):
    from quantcore_circuits.analysis.results import collect_results

    sp = collect_results(_job(tmp_path, "hfss_driven"))["sparams"]
    assert sp["ports"] == ["FL", "FL"] and sp["port_numbers"] == [2, 3] and sp["z0_ohm"] == 50.0
    fit = sp["notch"]["S21"]
    assert fit["f0_GHz"] == pytest.approx(6.60083, abs=1e-5)
    assert fit["kappa_ext_MHz"] == pytest.approx(0.2673, rel=3e-3)
    assert fit["Q_coupling"] == pytest.approx(24700, rel=3e-3)
    assert fit["Q_internal"] == pytest.approx(1.10e6, rel=0.02)  # = 1/(p_substrate tan δ) from the EPR job
    assert fit["residual_rms"] < 1e-3


def test_hanger_k_is_calibrated_on_the_driven_run(tmp_path):
    """HANGER_K[6 µm] reproduces the HFSS κ_ext of R1; driven κ wins over the eigenmode Q in the combined job."""
    from quantcore_circuits.analysis.results import collect_results, combine_jobs
    from quantcore_circuits.circuit.derive import circuit_from_design
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.calibration import HANGER_K

    assert HANGER_K[6.0] == pytest.approx(0.0663)
    est = fill(circuit_from_design(EXAMPLE, "Q1R1"), EXAMPLE).values["K_R1"]  # layout → LOM only
    assert est.origin == "estimate" and est.extra["k"] == pytest.approx(0.0663)
    # kinetic inductance (decision #45): 0.2673 -> 0.2632 (v_p and Z0 of the line include L_k)
    assert est.estimate == pytest.approx(0.2632, rel=0.01)
    jobs = {n: _job(tmp_path, n) for n in ("q3d_cmatrix", "eigenmode_epr", "hfss_driven")}
    for job in jobs.values():
        collect_results(job)
    combined = combine_jobs(
        jobs["q3d_cmatrix"], [jobs["eigenmode_epr"], jobs["hfss_driven"]], tmp_path / "all", same_design=False
    )  # the driven group lives in a copy of the design
    k = fill(circuit_from_design(EXAMPLE, "Q1R1"), EXAMPLE, combined).values["K_R1"]
    assert k.origin == "fem" and k.source.startswith("driven S21") and k.extracted == pytest.approx(0.2673, rel=3e-3)


# --------------------------------------------------------------------------------------------- solver (AEDT)


@pytest.mark.solver
@pytest.mark.slow
@needs_aedt
def test_render_eigenmode_epr_reads_back(tmp_path):
    """Render only (≈ 30 s): junction RLC with Lj/Cj, both 50 Ω feedline terminations, settings in Setup1."""
    from quantcore_circuits.sim_tools.hfss import check_project, render

    r = render(EXAMPLE, "Q1R1", "eigenmode_epr", job_dir=tmp_path / "epr", timeout=900)
    assert r.ok, r.status
    report = check_project(r.job_dir)
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]
    assert r.summary["lumped_rlc"] == 3


@pytest.mark.solver
@pytest.mark.slow
@needs_aedt
def test_solve_small_q3d_job(tmp_path):
    """Render + solve Q1R1 Q3D at 2 % (≈ 80 s) and read the named Maxwell matrix back."""
    from quantcore_circuits.sim_tools.hfss import render

    r = render(
        EXAMPLE,
        "Q1R1",
        "q3d_cmatrix",
        job_dir=tmp_path / "q3d",
        solve=True,
        timeout=1200,
        percent_error=2.0,
        maximum_passes=10,
    )
    assert r.ok, r.status
    cm = r.results["cmatrix"]
    assert cm["labels"] == ["Q1.island", "Q1.claw_n"]
    ref = (
        np.asarray(
            json.loads((DATA / "q3d_cmatrix" / "q1_r1_feedline_Q1R1_q3d_cmatrix_project_results.json").read_text())[
                "CMatrix"
            ]
        )
        * 1e15
    )
    c = np.abs(np.asarray(cm["matrix"]))
    # 2 % target, 10 passes: island and C_g settle fast; the claw net (with its 100 µm stub) came out 88.8 and
    # 91.9 fF in two runs vs 94.0 at 0.5 %
    assert c[0, 0] == pytest.approx(abs(ref[0, 0]), rel=0.02) and c[0, 1] == pytest.approx(abs(ref[0, 1]), rel=0.05)
    assert c[1, 1] == pytest.approx(abs(ref[1, 1]), rel=0.10)
    assert json.loads((r.job_dir / "job.json").read_text())["status"] == "done"


def test_pyepr_drops_an_unphysical_mode(tmp_path):
    """chain-verify (2026-11-13): an unconverged fast eigenmode left tutorial 00's junction resonating on its own
    (p_J ≈ 1 at 15.4 GHz, pyEPR dressed f 136 GHz, α −125 GHz) and pyEPR's values won the consensus, so the feedback
    proposed a 810 µm cross. Such a mode is dropped; the LOM estimators decide."""
    from quantcore_circuits.analysis.results import collect_results, combine_jobs
    from quantcore_circuits.circuit.adapters import pyepr
    from quantcore_circuits.loop import analyse

    q3d, epr = _job(tmp_path, "q3d_cmatrix"), _job(tmp_path, "eigenmode_epr")
    collect_results(q3d)
    res = collect_results(epr)
    path = epr / "results" / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["epr"]["f_GHz"] = [124.29, 135.90]
    data["epr"]["chi_MHz"] = [[-118001.0, -118001.2], [-118001.2, -125124.8]]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert res["epr"]["p_mj"]
    job = combine_jobs(q3d, [epr], tmp_path / "combined")
    with pytest.warns(UserWarning, match="not a transmon"):
        an = analyse(EXAMPLE, job, readout=False)
    rows = {r.param: r for r in an.rows}
    assert rows["Q1.f_q_GHz"].chosen_by != "pyepr" and 4.0 < rows["Q1.f_q_GHz"].chosen < 7.0
    assert "Q1.f_q_GHz" not in pyepr(an.filled)


def test_epr_leaves_out_a_junction_self_resonance():
    """chain-verify (2026-11-13): tutorial 00's fast eigenmode (4 passes) found the qubit (5.345 GHz, p_J 0.985), R1
    (7.003 GHz) and a 15.65 GHz mode with p_J 0.9999 = 1/2π√(L_J C_J) (L_J 6.872 nH, C_J 14.7 fF): the lumped RLC on
    its own. With it in the Hamiltonian every dressed f came out at 45–54 GHz; it is now left out."""
    from quantcore_circuits.analysis.epr import epr_hamiltonian, junction_self_modes

    p = {"f_GHz": [5.3453, 7.0035, 15.6496], "p_mj": [[0.98506], [0.00064], [0.99990]], "Lj_nH": [6.8719],
         "Cj_fF": [14.7], "s_mj": [[1], [1], [1]]}
    assert junction_self_modes(p) == [2]
    assert junction_self_modes({**p, "Cj_fF": [2.0]}) == []  # C_J 2 fF: f_LC 43 GHz, nothing near it
    h = epr_hamiltonian(p["f_GHz"][:2], p["p_mj"][:2], p["Lj_nH"], p["s_mj"][:2])
    assert 5.0 < h["f_GHz"][0] < 5.35 and -200 < h["chi_MHz"][0][0] < -100 and -1 < h["chi_MHz"][0][1] < 0


def test_fill_keeps_the_estimate_for_a_non_physical_fem_capacitance(tmp_path):
    """chain-verify (2026-11-14): tutorial 02's fast Q3D (2 %, 7 passes) of the pocket transmon gave a Maxwell row that
    is not diagonally dominant (island → ground −35 fF) and QuCat refused the circuit. Such a branch keeps its
    estimate, with a note, so the chain goes on."""
    from quantcore_circuits.analysis.results import collect_results
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom import lom_from_design
    from quantcore_circuits.lom.simulate import simulate

    job = _job(tmp_path, "q3d_cmatrix")
    collect_results(job)
    path = job / "results" / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cmatrix"]["matrix"] = [[67.25, -80.0], [-80.0, 94.02]]  # island → ground 67.25 − 80 < 0
    path.write_text(json.dumps(data), encoding="utf-8")
    filled = fill(lom_from_design(EXAMPLE).model, EXAMPLE, job)
    c = filled.values["C_Q1"]
    assert c.extracted is None and c.origin == "estimate" and c.value > 0
    assert filled.values["Cg_Q1_claw_n"].extracted == pytest.approx(80.0)
    assert any("not physical" in n for n in filled.notes)
    assert simulate(filled, max_modes=2).params["Q1.f_q_GHz"] > 0

import json
import warnings

import numpy as np
import pytest

pytestmark = pytest.mark.analysis
warnings.filterwarnings("ignore")


def test_unit_conversions_match_metal_tutorial():
    from quantcore_circuits.analysis.transmon import c_from_ec, ec_from_c, ej_from_lj, lj_from_ej

    # Metal LOM tutorial 4.05: Lj = 12 nH -> EJ = 13621.79 MHz; Lj = 10 nH -> 16346.15 MHz
    assert ej_from_lj(12.0) * 1e3 == pytest.approx(13621.79, rel=1e-5)
    assert ej_from_lj(10.0) * 1e3 == pytest.approx(16346.15, rel=1e-5)
    assert lj_from_ej(ej_from_lj(9.3)) == pytest.approx(9.3)
    assert c_from_ec(ec_from_c(80.0)) == pytest.approx(80.0)


def test_synthesis_inverts_targets():
    from quantcore_circuits.analysis.synthesis import synthesize_transmon_readout
    from quantcore_circuits.analysis.transmon import transmon_spectrum

    s = synthesize_transmon_readout(5.1, -220, 7.2, 90)
    f, a = transmon_spectrum(s["EJ_GHz"], s["EC_GHz"])
    assert f == pytest.approx(5.1, abs=1e-6) and a == pytest.approx(-220, abs=1e-3)
    assert 3800 < s["resonator_length_um"] < 4600  # λ/4 at 7.2 GHz on Si
    assert 2 < s["Cg_fF"] < 10


def test_sqcircuit_agrees_with_scqubits():
    from quantcore_circuits.analysis.circuits import sqcircuit_transmon
    from quantcore_circuits.analysis.transmon import transmon_from_circuit

    ref = transmon_from_circuit(90.0, 10.0)
    sq = sqcircuit_transmon(90.0, 10.0)
    assert sq["f_q_GHz"] == pytest.approx(ref.f_q_GHz, abs=2e-3)
    assert sq["alpha_MHz"] == pytest.approx(ref.alpha_MHz, abs=1.0)


def test_qutip_chi_matches_koch_estimate():
    from quantcore_circuits.analysis.circuits import qutip_transmon_resonator
    from quantcore_circuits.analysis.transmon import koch_chi_MHz

    q = qutip_transmon_resonator(5.1, -220, 7.2, 90)
    assert q["chi_MHz"] == pytest.approx(koch_chi_MHz(5.1, -220, 7.2, 90), rel=0.1)
    assert q["chi_MHz"] < 0


def test_scqubits_dressed_with_compat():
    from quantcore_circuits.analysis.transmon import dressed_transmon_resonator, transmon_from_targets

    ej, ec = transmon_from_targets(5.1, -220)
    d = dressed_transmon_resonator(ej, ec, 7.2, 90)
    assert d["f_q_GHz"] < 5.1 and d["f_r_GHz"] > 7.2  # level repulsion
    assert -3 < d["chi_MHz"] < 0


def test_lom_grounded_transmon():
    from quantcore_circuits.analysis.lom import lom_transmon_resonator, maxwell_with_ground
    from quantcore_circuits.analysis.transmon import ej_from_lj

    cmat = np.array([[85.0, -5.0], [-5.0, 40.0]])
    full = maxwell_with_ground(cmat, ["island", "claw"])
    assert np.allclose(full.values.sum(axis=1)[:2], 0)  # Maxwell rows incl. ground sum to zero
    r = lom_transmon_resonator(cmat, ["island", "claw"], "island", "claw", lj_nH=12.0, f_r_GHz=7.2, cj_fF=2.0)
    assert r["EJ_GHz"] == pytest.approx(ej_from_lj(12.0), rel=1e-4)
    assert 4 < r["f_q_GHz"] < 6 and -320 < r["alpha_MHz"] < -180
    assert 20 < r["g_MHz"] < 200 and r["chi_MHz"] < 0
    assert r["f_r_GHz"] == pytest.approx(7.2, abs=0.05)


def test_pyepr_hamiltonian_signs():
    from quantcore_circuits.analysis.epr import epr_hamiltonian

    e = epr_hamiltonian([5.2, 7.25], [[0.97], [0.012]], [9.26])
    chi = np.asarray(e["chi_MHz"])
    assert chi[0, 0] < -100  # qubit anharmonicity negative
    assert chi[0, 1] < 0 and chi[0, 1] == pytest.approx(chi[1, 0])
    assert e["f_GHz"][0] < 5.2


def test_qucat_lumped_network():
    from quantcore_circuits.analysis.circuits import qucat_from_cmatrix

    cmat = np.array([[97.0, -5.3], [-5.3, 30.0]])
    q = qucat_from_cmatrix(
        cmat, ["island", "claw"], "island", 9.26, resonators={"claw": (7.2, 50.0)}, loads={"claw": 1e6}
    )
    assert len(q["modes_GHz"]) == 2
    assert 4 < q["f_q_GHz"] < 6.5 and q["alpha_MHz"] < -100
    assert q["kappa_MHz"][1 - q["qubit_mode"]] > 0  # loaded resonator


def test_results_pipeline_from_q3d_output(example_path, tmp_path):
    """Fake Q3D output in a real job dir → collect → extract (LOM) → store."""
    from quantcore_circuits.analysis.extract import compare, extract
    from quantcore_circuits.analysis.results import collect_results
    from quantcore_circuits.analysis.store import ResultsStore
    from quantcore_circuits.sim_tools import build_simulation, export_job

    setup = build_simulation(example_path, "Q1R1", "q3d_cmatrix")
    job = export_job(setup, tmp_path / "job")
    cm_F = (np.array([[90.0, -5.5], [-5.5, 35.0]]) * 1e-15).tolist()
    (job / f"{setup.simulation.name}_project_results.json").write_text(json.dumps({"CMatrix": cm_F}))
    res = collect_results(job)
    assert res["cmatrix"]["labels"] == ["Q1.island", "Q1.claw_n"]
    params = extract(example_path, res)
    assert set(params) == {"Q1", "R1"}
    assert 4 < params["Q1"]["f_q_GHz"] < 6.5 and 6.5 < params["R1"]["f_GHz"] < 7.8
    rows = {(r["instance"], r["quantity"]): r for r in compare(setup.design.targets, params)}
    assert rows[("Q1", "f_q_GHz")]["value"] == params["Q1"]["f_q_GHz"]
    store = ResultsStore(tmp_path / "r.sqlite")
    rid = store.put(res["design_hash"], "Q1R1", "q3d_cmatrix", params, design="q1_r1_feedline", job_dir=job)
    assert store.latest(res["design_hash"], "Q1R1")["id"] == rid


def test_parse_eig_formats(tmp_path):
    from quantcore_circuits.analysis.results import parse_eig

    p = tmp_path / "x.eig"
    p.write_text("Eigenmode  Frequency  Q\n1  5.1234e9  2.5e6\n2 (7.25, 0.0001)\n")
    modes = parse_eig(p)
    assert modes[0]["f_GHz"] == pytest.approx(5.1234) and modes[0]["Q"] == pytest.approx(2.5e6)
    assert modes[1]["f_GHz"] == pytest.approx(7.25) and modes[1]["Q"] == pytest.approx(7.25 / 0.0002)


def test_parse_eig_aedt_2024_rows(tmp_path):
    """AEDT 2024 R1 ``ExportEigenmodes``: ``mode  f_re + f_im j  Q`` (the imaginary part is not Q)."""
    from quantcore_circuits.analysis.results import parse_eig

    p = tmp_path / "y.eig"
    p.write_text(
        "# Ansys eigenmode data file.  Version 2.0\n#   Mode   Frequency (GHz)   Q\n"
        "       1    4.74627524389 + 2.07422288999E-06 j      1.14411e+06\n"
        "       2    6.21166180946 + 8.31330553575E-06 j\n"
    )
    m = parse_eig(p)
    assert [x["mode"] for x in m] == [1, 2]
    assert m[0]["f_GHz"] == pytest.approx(4.74627524389) and m[0]["Q"] == pytest.approx(1.14411e6)
    assert m[1]["Q"] == pytest.approx(6.21166180946 / (2 * 8.31330553575e-6))


def test_epr_participations_follow_pyepr():
    """pyEPR line-voltage method: I = V/(ωLj), p = ½LjI²/(U_E + ½CjV²), renormalised to |Ū − U_H|/Ū per mode."""
    from quantcore_circuits.analysis.epr import epr_analysis, participations

    f, lj, cj = 5.0, 10e-9, 0.0
    w = 2 * np.pi * f * 1e9
    u_peak = 1e-24  # total peak energy of the mode
    u_j = 0.9 * u_peak  # 90 % inductive energy in the junction, 10 % in the field
    v = np.sqrt(2 * u_j / lj) * w * lj  # V = ω Lj I with ½ Lj I² = U_J
    mode = {"mode": 1, "freq_Hz": f * 1e9, "U_E": 2 * u_peak, "U_H": 2 * 0.1 * u_peak, "U_E_volumes": {"sub": u_peak}}
    mode["junctions"] = {"1": {"V_re": -v * 0.6, "V_im": -v * 0.8, "Lj_H": lj, "Cj_F": cj}}  # |V| = v, negative sign
    p = participations({"modes": [mode]})
    assert p["p_mj_raw"][0][0] == pytest.approx(0.9) and p["p_mj"][0][0] == pytest.approx(0.9)
    assert p["s_mj"] == [[-1]] and p["U_diff"][0] == pytest.approx(0.0, abs=1e-12)
    assert p["p_volume"][0]["sub"] == pytest.approx(0.5)
    res = epr_analysis({"modes": [mode]}, tan_delta=1e-6)
    assert res["chi_MHz"][0][0] < -100 and res["f_GHz"][0] < f  # transmon-like: α < 0, dressed below linear
    assert res["Q_dielectric"][0] == pytest.approx(2e6)


def test_fem_kappa_prefers_driven_fits_then_eigenmode_q():
    from quantcore_circuits.analysis.results import fem_kappa

    eig = [{"mode": 1, "f_GHz": 5.5, "Q": 1e6}, {"mode": 2, "f_GHz": 6.8, "Q": 2.0e4}]
    epr = {"p_mj": [[0.99], [0.001]], "Q_dielectric": [1.2e6, 1.0e6]}
    k = fem_kappa({"eigenmodes": eig, "epr": epr}, {"R1": 7.6})
    q_ext = 1 / (1 / 2.0e4 - 1 / 1.0e6)  # dielectric loss removed
    assert k["R1"]["kappa_MHz"] == pytest.approx(6.8 / q_ext * 1e3) and "eigenmode 2" in k["R1"]["source"]
    fit = {"f0_GHz": 6.79, "Q_coupling": 3.0e4, "kappa_ext_MHz": 6.79 / 3.0e4 * 1e3, "residual_rms": 1e-3}
    k = fem_kappa({"eigenmodes": eig, "epr": epr, "sparams": {"file": "x.s2p", "notch": {"S21": fit}}}, {"R1": 7.6})
    assert k["R1"]["kappa_MHz"] == pytest.approx(0.22633, rel=1e-4) and k["R1"]["source"].startswith("driven S21")
    assert fem_kappa({"sparams": {"notch": {"S21": {**fit, "residual_rms": 0.5}}}}, {"R1": 7.6}) == {}  # bad fit


def test_combine_jobs_guards_the_design_hash(tmp_path):
    from quantcore_circuits.analysis.results import combine_jobs

    def job(name, h, res):
        d = tmp_path / name
        (d / "results").mkdir(parents=True)
        (d / "job.json").write_text(json.dumps({"design_hash": h, "analysis": name, "ports": []}))
        (d / "results" / "results.json").write_text(json.dumps({"group": "G", **res}))
        return d

    a = job("q3d", "h1", {"cmatrix": {"labels": ["x"], "matrix": [[1.0]]}})
    b = job("eig", "h1", {"eigenmodes": [{"mode": 1, "f_GHz": 5.0, "Q": 1e6}], "cmatrix": {"labels": [], "matrix": []}})
    c = job("drv", "h2", {"sparams": {"file": "s.s2p"}})
    out = combine_jobs(a, [b], tmp_path / "ab")
    res = json.loads((out / "results" / "results.json").read_text())
    assert res["cmatrix"]["labels"] == ["x"] and res["eigenmodes"][0]["f_GHz"] == 5.0  # primary C-matrix kept
    assert json.loads((out / "job.json").read_text())["analysis"] == "q3d"
    with pytest.raises(ValueError, match="design hash"):
        combine_jobs(a, [c], tmp_path / "ac")
    out = combine_jobs(a, [c], tmp_path / "ac", same_design=False)
    res = json.loads((out / "results" / "results.json").read_text())
    assert res["sparams"]["file"] == "s.s2p" and res["combined_hash_mismatch"]


def test_smatrix_ports_follow_the_aedt_excitations():
    from quantcore_circuits.analysis.results import smatrix_ports

    job = {"ports": [{"number": 1, "kind": "junction"}, {"number": 2, "kind": "edge"}, {"number": 3, "kind": "edge"}]}
    assert smatrix_ports(job, {}, 2) == [2, 3]  # junction ports are lumped L/C in a driven design
    assert smatrix_ports(job, {"excitations": ["3", "2"]}, 2) == [3, 2]
    assert smatrix_ports(job, {"excitations": ["Port2_T1", "Port3_T1"]}, 2) == [2, 3]


def test_fit_notches_fits_each_resonator_on_one_feedline():
    """Two hangers on one feedline (examples/fem_loop): one fit per notch; the half-width is the contiguous dip."""
    import numpy as np

    from quantcore_circuits.analysis.results import fit_notch, fit_notches

    f = np.linspace(6.5, 8.4, 24001)

    def notch(f0, ql, qc):
        return 1 - (ql / qc) / (1 + 2j * ql * (f / f0 - 1))

    s21 = notch(6.92, 30000, 31000) * notch(7.53, 25000, 60000)
    fits = fit_notches(f, s21)
    assert [round(x["f0_GHz"], 3) for x in fits] == [6.92, 7.53]
    assert fits[0]["kappa_ext_MHz"] == pytest.approx(6920 / 31000, rel=0.05)
    assert fits[1]["kappa_ext_MHz"] == pytest.approx(7530 / 60000, rel=0.05)
    single = fit_notch(f, s21)  # the deepest one alone, no longer widened by the second notch
    assert single["f0_GHz"] == pytest.approx(6.92, abs=1e-3)

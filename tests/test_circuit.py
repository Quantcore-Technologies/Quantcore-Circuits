"""M8–M10: circuit.json, extraction bridges, estimator adapters, consensus and the QuTiP Hamiltonian."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from quantcore_circuits.circuit import bridges
from quantcore_circuits.circuit.schema import CircuitModel, load_circuit, save_circuit

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "tests" / "data" / "q1_r1_feedline_Q1R1_q3d_cmatrix"  # solved Q3D job, small files (build/ is untracked)
needs_job = pytest.mark.skipif(not (JOB / "job.json").exists(), reason="Q3D job from the AEDT run not present")


def _ring(**extra):
    return {
        "nodes": {"gnd": {"ground": True}, "a": {"layout": {"island": "A"}}},
        "branches": {"C": {"type": "C", "nodes": ["a", "gnd"]}},
        **extra,
    }


def test_schema_validates_topology(tmp_path):
    m = CircuitModel.model_validate(_ring())
    assert m.ground == "gnd" and m.islands() == {"A": "a"}
    assert [(frozenset(e[:2]), e[2]) for e in m.to_networkx().edges(keys=True)] == [(frozenset({"a", "gnd"}), "C")]
    assert load_circuit(save_circuit(m, tmp_path / "c.json")).to_json_dict() == m.to_json_dict()
    bad = _ring()
    bad["nodes"]["b"] = {}
    with pytest.raises(ValueError, match="floating"):
        CircuitModel.model_validate(bad)
    bad = _ring()
    bad["nodes"]["gnd"]["ground"] = False
    with pytest.raises(ValueError, match="no ground"):
        CircuitModel.model_validate(bad)
    bad = _ring()
    bad["nodes"]["b"] = {"layout": {"island": "A"}}
    bad["branches"]["Cb"] = {"type": "C", "nodes": ["b", "gnd"]}
    with pytest.raises(ValueError, match="mapped to two nodes"):
        CircuitModel.model_validate(bad)


def test_cmatrix_bridge_round_trip():
    branches = {("A", "ground"): 70.0, ("B", "ground"): 90.0, ("A", "B"): 3.5}
    maxwell = bridges.maxwell_from_branches(branches, ["A", "B"])
    assert maxwell[0, 0] == pytest.approx(73.5) and maxwell[0, 1] == pytest.approx(-3.5)
    assert bridges.branch_capacitances(maxwell, ["A", "B"]) == pytest.approx(branches)


def test_q3d_mutual_convention_is_normalised():
    from quantcore_circuits.analysis.results import to_maxwell

    c, conv = to_maxwell(np.array([[74.4e-15, 3.51e-15], [3.51e-15, 104e-15]]))
    assert conv == "mutual" and c[0, 1] == pytest.approx(-3.51e-15)
    c2, conv2 = to_maxwell(c)
    assert conv2 == "maxwell" and np.allclose(c2, c)


def test_lc_and_junction_bridges():
    c, ind = bridges.quarter_wave_lc(7.0, 50.0)
    assert 1 / (2 * math.pi * math.sqrt(c * 1e-15 * ind * 1e-9)) / 1e9 == pytest.approx(7.0)
    ic = bridges.ic_from_rn(1000.0, 1.4)
    assert ic == pytest.approx(math.pi * 1.4e-3 / 2000)  # Ambegaokar–Baratoff
    assert bridges.lj_from_ic(bridges.ic_from_lj(12.0)) == pytest.approx(12.0)
    assert bridges.squid_ej(20.0, 0.0, 0.25) == pytest.approx(20.0 * math.cos(math.pi / 4))
    assert bridges.squid_ej(20.0, 0.2, 0.5) == pytest.approx(20.0 * 0.2, rel=1e-6)  # asymmetric floor


def test_tl_resonator_matches_quarter_wave_length():
    from quantcore_circuits.analysis.synthesis import quarter_wave_length_um

    length = quarter_wave_length_um(7.2, 10, 6)
    assert bridges.tl_resonator(length, 10, 6)["f_GHz"] == pytest.approx(7.2, rel=1e-3)


def test_derived_circuit_for_example(example_path):
    from quantcore_circuits.circuit.derive import circuit_from_design

    m = circuit_from_design(example_path, "Q1R1")
    assert {"C_Q1", "J_Q1", "Cg_Q1_claw_n", "Cc_Q1_claw_n", "R1", "K_R1", "Port_FL"} <= set(m.branches)
    assert m.branches["K_R1"].type == "HANGER" and m.branches["K_R1"].value["kappa_MHz"] > 0
    assert m.branches["J_Q1"].type == "SQUID" and m.branches["R1"].type == "TLres"
    assert m.targets["Q1.f_q_GHz"].value == 5.1 and "R1.length" in m.knobs


@pytest.mark.analysis
def test_transmon_limits_analytic():
    """α ≈ −E_C and f01 ≈ √(8 E_J E_C) − E_C deep in the transmon regime; χ from the Koch formula."""
    from quantcore_circuits.circuit.hamiltonian import TransmonResonator, dressed

    ej, ec = 20.0, 0.2
    d = dressed(TransmonResonator(ej, ec, 7.0, 1.0, nq=6, nr=4))  # ~decoupled
    assert d["alpha_MHz"] == pytest.approx(-ec * 1e3, rel=0.12)
    assert d["f_q_GHz"] == pytest.approx(math.sqrt(8 * ej * ec) - ec, rel=0.01)
    # χ: exact diagonalisation vs second-order perturbation theory summed over transmon levels (incl.
    # counter-rotating terms), E_qn shift = Σ_j |g_n n_qj|² [(n+1)/(E_q − E_j − f_r) + n/(E_q − E_j + f_r)]
    model = TransmonResonator(ej, ec, 7.0, 40.0, nq=8, nr=6)
    d = dressed(model)
    e, nmat = model.transmon()
    gn, fr = model.g_n_MHz / 1e3, model.f_r_GHz

    def shift(q, n):
        return sum(
            abs(gn * nmat[q, j]) ** 2 * ((n + 1) / (e[q] - e[j] - fr) + n / (e[q] - e[j] + fr))
            for j in range(len(e))
            if j != q
        )

    chi_pt = ((shift(1, 1) - shift(1, 0)) - (shift(0, 1) - shift(0, 0))) * 1e3
    assert d["chi_MHz"] == pytest.approx(chi_pt, rel=0.05)


@pytest.fixture(scope="module")
def filled():
    from quantcore_circuits.circuit.derive import circuit_from_design
    from quantcore_circuits.circuit.fill import fill

    example = ROOT / "examples" / "q1_r1_feedline.json"
    return fill(circuit_from_design(example, "Q1R1"), example, JOB)


@needs_job
@pytest.mark.analysis
def test_fill_keeps_design_and_extracted_side_by_side(filled):
    rows = {r["branch"]: r for r in filled.branch_table()}
    assert rows["Cg_Q1_claw_n"]["extracted"] > 0  # Maxwell off-diagonal → positive branch capacitance
    assert rows["C_Q1"]["design"] == pytest.approx(97.1 - 5.13 - 2.0, abs=0.5)  # island→ground part of C_Σ
    assert any(n.startswith("stack correction") for n in filled.notes)  # Si job, sapphire PDK
    assert any("port stub" in n for n in filled.notes)


@needs_job
@pytest.mark.analysis
def test_four_adapters_agree(filled):
    """M9 acceptance: on one C-matrix the 4 adapters agree on f_q within 1 % and α within 5 %."""
    from quantcore_circuits.circuit.adapters import solve_all

    est = solve_all(filled, ["metal_lom", "qucat", "sqcircuit", "scqubits"])
    assert all("error" not in v for v in est.values()), est
    fq = [v["Q1.f_q_GHz"] for v in est.values()]
    al = [v["Q1.alpha_MHz"] for v in est.values()]
    assert (max(fq) - min(fq)) / np.mean(fq) < 0.01
    assert (max(al) - min(al)) / abs(np.mean(al)) < 0.05
    fr = [v["R1.f_GHz"] for v in est.values()]
    assert (max(fr) - min(fr)) / np.mean(fr) < 0.002


@needs_job
@pytest.mark.analysis
def test_qutip_readout_chi_matches_estimator(filled):
    """M10 acceptance: χ from simulated resonator transmission vs qubit state matches the estimator χ within 5 %."""
    from quantcore_circuits.circuit import hamiltonian as H
    from quantcore_circuits.circuit.adapters import qucat

    model = H.from_pair(filled.pairs[0])
    r = H.readout(model, kappa_MHz=1.0, n_points=61)
    assert r["P_e_at_peak_e"] > 0.9 and r["P_e_at_peak_g"] < 0.01
    chi_est = qucat(filled)["R1.chi_MHz"]
    assert r["chi_readout_MHz"] == pytest.approx(chi_est, rel=0.05)


def test_consensus_policy_spread_and_goal():
    from quantcore_circuits.circuit.consensus import consensus, goal, report_markdown

    est = {
        "sqcircuit": {"Q1.f_q_GHz": 5.10, "R1.chi_MHz": -1.0},
        "qucat": {"Q1.f_q_GHz": 5.11, "R1.chi_MHz": -1.5},
        "broken": {"error": "boom"},
    }
    rows = {r.param: r for r in consensus(est, {"Q1.f_q_GHz": {"value": 5.1, "tol": 0.02}})}
    assert rows["Q1.f_q_GHz"].chosen_by == "sqcircuit" and rows["Q1.f_q_GHz"].status == "pass"
    assert rows["R1.chi_MHz"].chosen_by == "qucat" and rows["R1.chi_MHz"].flagged
    assert goal(list(rows.values())) == {
        "reached": True,
        "passed": 1,
        "total": 1,
        "summary": "1 of 1 targets within tolerance",
    }
    assert "sqcircuit" in report_markdown(list(rows.values()))


def test_flux_curve_and_purcell():
    from quantcore_circuits.circuit.hamiltonian import flux_curve, purcell_t1_us

    fc = flux_curve(15.0, 0.25, 0.0, [0.0, 0.25, 0.4])
    assert fc["f01_GHz"][0] > fc["f01_GHz"][1] > fc["f01_GHz"][2]
    assert purcell_t1_us(5.0, 7.0, 50.0, 1.0) == pytest.approx(1 / (2 * math.pi * (50 / 2000) ** 2), rel=1e-9)


def test_job_json_records_stub_length(example_path, tmp_path):
    from quantcore_circuits.sim_tools import build_simulation, export_job

    job = export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"), tmp_path / "j")
    assert json.loads((job / "job.json").read_text())["waveguide_length_um"] == 100.0


def test_near_resonance_pairs_are_flagged():
    """|f_q − f_r| < 5 g: hybridised modes, so the rows are flagged with a note (d14 Q_B3: Δ 140 MHz, g 42 MHz)."""
    from types import SimpleNamespace

    from quantcore_circuits.circuit.consensus import consensus, flag_near_resonance

    est = {
        "sqcircuit": {
            "Q1.f_q_GHz": 4.29,
            "R1.f_GHz": 4.43,
            "R1.g_MHz": 42.0,
            "Q2.f_q_GHz": 5.1,
            "R2.f_GHz": 7.2,
            "R2.g_MHz": 80.0,
        },
    }
    rows = consensus(est)
    notes = flag_near_resonance(
        rows, [SimpleNamespace(qubit="Q1", resonator="R1"), SimpleNamespace(qubit="Q2", resonator="R2")]
    )
    by = {r.param: r for r in rows}
    assert len(notes) == 1 and "Q1–R1" in notes[0] and "140 MHz" in notes[0]
    assert by["Q1.f_q_GHz"].flagged and by["R1.g_MHz"].flagged and by["Q1.f_q_GHz"].notes == notes
    assert not by["Q2.f_q_GHz"].flagged and not by["Q2.f_q_GHz"].notes  # 2.1 GHz ≫ 5 × 80 MHz

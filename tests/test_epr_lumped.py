"""Lumped-junction EPR (analysis/epr_lumped.py): analytic LC cases, transmon-resonator against epr.py / QuTiP, the
dL route on a coupled network, the LOM route on the Q1/R1 example, the kept eigenmode job. No solver runs."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from quantcore_circuits.analysis import epr as E
from quantcore_circuits.analysis import epr_lumped as L

REPO = Path(__file__).resolve().parents[1]
KEPT = REPO / "examples" / "tutorials" / "fem" / "t04_two_qubit_ALL_eigenmode_epr" / "results" / "results.json"


def _modes(lj, ls, cq, cr, cg, lr):
    """Normal modes (GHz, ascending) and each mode's fraction of inductive energy in the junction, for a transmon
    (L_J plus a series inductor ``ls`` in parallel with ``cq``) capacitively coupled (``cg``; fF, nH) to a resonator
    (``lr`` parallel ``cr``)."""
    from scipy.linalg import eigh

    k = np.diag([1 / (lj + ls), 1 / lr]) * 1e9  # 1/H
    c = np.array([[cq + cg, -cg], [-cg, cr + cg]]) * 1e-15
    w2, x = eigh(k, c)
    f = np.sqrt(w2) / (2 * math.pi) / 1e9
    e_q, e_r = x[0] ** 2 / (lj + ls), x[1] ** 2 / lr  # flux energies (same units for the ratio)
    return f, e_q / (e_q + e_r) * lj / (lj + ls)


def test_single_lc_p_is_lj_over_total():
    cap, lj, ls = 80.0, 8.0, 2.0
    f = lambda lt: 1 / (2 * math.pi * math.sqrt(lt * 1e-9 * cap * 1e-15)) / 1e9  # noqa: E731
    res = L.eigenmode_dL([f(lj + ls)], [lj], {0: [(lj * 0.99, [f(lj * 0.99 + ls)]), (lj * 1.01, [f(lj * 1.01 + ls)])]})
    assert res["p"][0][0] == pytest.approx(lj / (lj + ls), rel=2e-4)
    assert res["method"] == "eigenmode-dL"
    # one-sided two-point step: the slope is at the mid-point, error of the order of the step
    one = L.eigenmode_dL([f(lj + ls)], [lj], {0: [(lj * 1.02, [f(lj * 1.02 + ls)])]})
    assert one["p"][0][0] == pytest.approx(lj / (lj + ls), rel=0.02)


def test_p_is_one_without_series_inductance_and_negative_slope_sign():
    f = lambda lj: 1 / (2 * math.pi * math.sqrt(lj * 1e-9 * 70e-15)) / 1e9  # noqa: E731
    p = L.dL_participation(10.0, [(9.0, f(9.0)), (10.0, f(10.0)), (11.0, f(11.0))])
    assert p == pytest.approx(1.0, abs=1e-3)  # f falls when L_J rises: p > 0


def test_normalisation_two_junctions_one_mode():
    """Two junctions in series in one LC: p_a + p_b = L_JJ / L_total, p_a / p_b = L_a / L_b."""
    la, lb, ls, cap = 6.0, 9.0, 5.0, 90.0
    f = lambda a, b: 1 / (2 * math.pi * math.sqrt((a + b + ls) * 1e-9 * cap * 1e-15)) / 1e9  # noqa: E731
    pert = {
        "A": [(la * 0.98, [f(la * 0.98, lb)]), (la * 1.02, [f(la * 1.02, lb)])],
        "B": [(lb * 0.98, [f(la, lb * 0.98)]), (lb * 1.02, [f(la, lb * 1.02)])],
    }
    res = L.eigenmode_dL([f(la, lb)], [la, lb], pert, junctions=["A", "B"])
    pa, pb = res["p"][0]
    assert pa + pb == pytest.approx((la + lb) / (la + lb + ls), rel=5e-4)
    assert pa / pb == pytest.approx(la / lb, rel=5e-3)
    assert not res["notes"]


def test_transmon_resonator_dL_matches_exact_and_epr_formulas():
    lj, ls, cq, cr, cg, lr = 9.0, 0.0, 85.0, 400.0, 4.0, 11.0
    f0, p0 = _modes(lj, ls, cq, cr, cg, lr)
    pert = {0: [(lj * (1 + d), _modes(lj * (1 + d), ls, cq, cr, cg, lr)[0]) for d in (-0.02, 0.02)]}
    res = L.eigenmode_dL(f0, [lj], pert, labels=["Q", "R"], junctions=["J"])
    assert np.allclose(np.array(res["p"])[:, 0], p0, rtol=2e-3, atol=1e-5)
    # the same p through epr.py's Hamiltonian gives identical dressed values and chi
    h = E.epr_hamiltonian(f0, np.array(res["p"]), [lj])
    assert np.allclose(res["chi_MHz"], h["chi_MHz"], atol=1e-9)
    assert np.allclose(res["f_GHz"], h["f_GHz"])
    qi = int(np.argmax(p0))  # the transmon is the mode that holds the junction (here the upper one)
    assert res["modes"][qi]["kind"] == "qubit" and res["modes"][1 - qi]["kind"] == "other"
    # against the independent QuTiP Hamiltonian
    q = E.epr_qutip(f0, np.array(res["p"]), [lj], fock=10)
    assert res["alpha_MHz"][qi] == pytest.approx(q["chi_MHz"][qi][qi], rel=0.03)
    assert res["chi_MHz"][0][1] == pytest.approx(q["chi_MHz"][0][1], rel=0.05, abs=0.01)
    # signs: self-Kerr negative, Lamb shift negative for a transmon, matrix symmetric
    assert res["alpha_MHz"][qi] < 0 and res["lamb_MHz"][qi] < 0
    assert np.allclose(res["chi_MHz"], np.array(res["chi_MHz"]).T)
    assert res["alpha_MHz"] == [res["chi_MHz"][i][i] for i in range(2)]
    # E_C = alpha: the transmon's alpha is about -p^2 hf / (8 EJ) ... check by size: -(e^2 / 2 C_sigma) h^-1
    assert -400 < res["alpha_MHz"][qi] < -100


def test_contract_keys():
    res = L.epr_result("energy", [5.0, 7.0], [[0.97], [0.002]], [10.0], ["Q1", "R1"], None, ["Q1"])
    for k in ("method", "modes", "junctions", "p", "alpha_MHz", "chi_MHz", "lamb_MHz", "notes"):
        assert k in res
    assert res["modes"][0] == {"label": "Q1", "f_GHz": 5.0, "kind": "qubit"}
    assert len(res["chi_MHz"]) == 2 and len(res["chi_MHz"][0]) == 2
    json.dumps(res)  # plain data


def test_energy_route():
    lj, f = 10.0, 5.0
    i, u = 1e-7, 0.5 * lj * 1e-9 * 1e-14 / 0.9
    res = L.epr_from_energy([f], [lj], [[math.sqrt(1e-14)]], [u], labels=["Q"], junctions=["J"])
    assert res["p"][0][0] == pytest.approx(0.9)
    assert res["method"] == "energy"
    del i


def test_negative_p_noise_is_clipped_with_a_note():
    res = L.epr_result("eigenmode-dL", [5.0, 6.0], [[0.9], [-0.01]], [10.0])
    assert any("negative" in n for n in res["notes"])
    assert res["alpha_MHz"][1] == 0.0 and math.isfinite(res["alpha_MHz"][0])


def test_kept_eigenmode_job_reproduces_pyepr():
    """The kept two-qubit job: lumped finaliser on its p_mj reproduces the solver's dressed values."""
    kept = json.loads(KEPT.read_text(encoding="utf-8"))
    res = L.epr_from_job(kept)
    e = kept["epr"]
    assert res["junctions"] == ["Q1", "Q2"]
    for i in (0, 1):
        assert res["f_GHz"][i] == pytest.approx(e["f_GHz"][i], abs=2e-3)
        assert res["alpha_MHz"][i] == pytest.approx(e["chi_MHz"][i][i], rel=0.05)
    assert res["chi_MHz"][0][1] == pytest.approx(e["chi_MHz"][0][1], abs=0.05)
    rows = L.compare_epr(res, res)
    assert all(r["dp"] == 0 for r in rows)
    assert "alpha" in L.compare_md(res, res) and "Cross-Kerr" in L.epr_md(res)


@pytest.mark.analysis
def test_lom_route_and_comparison():
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom import lom_from_design
    from quantcore_circuits.lom.simulate import simulate

    example = REPO / "examples" / "q1_r1_feedline.json"
    if not example.exists():
        pytest.skip("example design missing")
    lom = simulate(fill(lom_from_design(example).model, example))
    res = L.epr_from_lom(lom)
    q = next(m for m in res["modes"] if m["kind"] == "qubit")
    i = res["modes"].index(q)
    assert res["p"][i][0] > 0.9  # the qubit mode holds its junction's energy
    assert res["alpha_MHz"][i] == pytest.approx(lom.params[f"{q['label']}.alpha_MHz"], rel=0.05)
    assert abs(res["chi_MHz"][i][1 - i]) > 0  # a dispersive shift to the resonator
    rows = L.compare_epr(res, res)
    assert rows[0]["d_alpha_pct"] == 0

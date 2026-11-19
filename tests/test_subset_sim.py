"""Subset simulation (phase C): plan a subset, cut and port choice, a fill that touches only the subset, the netlist
unchanged. No AEDT: the read-back tests use the kept tutorial-02 Q3D results (``examples/tutorials/fem/``)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from quantcore_circuits.circuit.fill import branch_owners, fill
from quantcore_circuits.design import Design
from quantcore_circuits.lom import lom_from_design
from quantcore_circuits.sim_tools.subset import _Graph, plan_subset, readout_of

ROOT = Path(__file__).resolve().parents[1]
DESIGNS = ROOT / "examples" / "tutorials" / "designs"
FEM = ROOT / "examples" / "tutorials" / "fem"
Q2_READ = FEM / "t02_ibm_bowtie_5q_Q2_read_q3d_cmatrix"
CHIP02 = FEM / "t02_ibm_bowtie_5q_chip_q3d_cmatrix"
# the sim group the kept Q2_read job was solved for (tutorial 02 before phase C)
Q2_READ_GROUP = {"select": ["Q2", "R_Q2", "C_Q2"], "margin_um": 100.0, "analyses": ["q3d_cmatrix", "eigenmode_epr"]}


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")


def _design(name: str, groups: dict | None = None) -> Design:
    data = json.loads((DESIGNS / f"{name}.json").read_text(encoding="utf-8"))
    if groups is not None:
        data["sim_groups"] = copy.deepcopy(groups)
    return Design.model_validate(data)


def test_subset_of_one_pair_keeps_the_existing_group_spec():
    """Tutorial 00 / 04: the subset of their pairs is exactly the group they already had (same design hash, so the
    kept results stay valid); the hanger feedline is found, nothing is cut."""
    t00 = plan_subset(_design("t00_quickstart"), "Q1R1", pairs=[("Q1", "R1")])
    assert [(g.name, g.select, g.ports, g.feedlines) for g in t00] == [("Q1R1", ["Q1", "R1"], {}, ["FL"])]
    t04 = plan_subset(_design("t04_two_qubit"), "PAIR", pairs=[("Q1", "R1"), ("Q2", "R2")])
    assert [(g.name, g.select, g.ports) for g in t04] == [("PAIR", ["Q1", "Q2", "R1", "R2"], {})]
    one = plan_subset(_design("t04_two_qubit"), "S", qubits=["Q1"])  # readout found on its own
    assert one[0].select == ["Q1", "R1"]


def test_subset_cuts_buses_to_unchosen_qubits_and_keeps_the_feedline_out_of_the_selection():
    d = _design("t02_ibm_bowtie_5q")
    assert readout_of(d, "Q2") == "R_Q2"
    (g,) = plan_subset(d, "S", qubits=["Q2"])
    assert g.select == ["Q2", "R_Q2", "C_Q2"]  # the readout chain: λ/2 + finger capacitor
    assert g.ports == {"BusA": "cut", "BusB": "cut"}  # both buses reach qubits outside the subset
    assert g.feedlines == ["L_Q2"]  # the 50 Ω line to the pad: cut by the box, never selected
    assert "L_Q2" not in g.select


def test_disjoint_pairs_get_one_box_each_and_a_shared_bus_joins_them():
    d = _design("t02_ibm_bowtie_5q")
    two = plan_subset(d, "S", pairs=[("Q1", None), ("Q3", None)])
    assert [g.name for g in two] == ["S_Q1", "S_Q3"]
    assert two[0].ports == {"BusA_Q1": "cut"} and two[1].ports == {"BusB_Q3": "cut"}
    (one,) = plan_subset(d, "S", qubits=["Q2", "Q3"])  # bus B reaches both: one box with it
    assert {"BusB", "TB", "BusB_Q3"} <= set(one.select)
    assert one.ports == {"BusA": "cut", "BusB_Q4": "cut"}  # the stub to Q4 (outside) is cut at the tee
    forced = plan_subset(d, "S", pairs=[("Q1", None), ("Q3", None)], split="one")
    assert [g.name for g in forced] == ["S"]
    with pytest.raises(ValueError, match="readouts found"):
        plan_subset(d, "S", pairs=[("Q3", "R3")])  # 02 names its readouts R_Qn


def test_surface17_readout_chain_walks_through_the_purcell_filter_to_the_feedline():
    d = _design("t03_demoqpu17")
    (g,) = plan_subset(d, "S", qubits=["Q23"])
    assert g.select == ["Q23", "RO_Q23", "PF_Q23", "T_Q23"]  # readout, (declared) tap, Purcell filter, its tee
    assert g.feedlines == ["FL2_2", "FL2_3"]  # the feedline backbone through the tees (pad to pad)
    assert g.ports["CPL_Q23_Q33"] == "cut"
    assert {"FL1_0", "FL2_2", "FL4_4"} <= _Graph(d).feedlines


def test_cut_bus_gets_a_q3d_stub_at_the_qubit_and_is_open_in_eigenmode(tmp_path):
    from quantcore_circuits.sim_tools import build_simulation  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.builder import simulation_design  # pylint: disable=import-outside-toplevel

    d = _design("t02_ibm_bowtie_5q", {})
    (g,) = plan_subset(d, "S", qubits=["Q1"])
    data = d.to_json_dict()
    data["sim_groups"] = {"S": g.spec(100.0, ["q3d_cmatrix", "eigenmode_epr"], None)}
    path = tmp_path / "t02.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    sim, cuts = simulation_design(Design.model_validate(data), "S", "eigenmode_epr")
    assert "BusA_Q1" not in sim.routes and cuts == []  # removed, no stub in eigenmode (open pad)
    q3d = build_simulation(path, "S", "q3d_cmatrix")
    kinds = {(p.kind, p.name) for p in q3d.ports}
    assert ("waveguide", "Q1.bus") in kinds  # the cut bus pad is its own net
    assert ("edge", "L_Q1") in kinds  # the feedline (readout line to the pad) cut by the box
    eig = build_simulation(path, "S", "eigenmode_epr")
    assert ("edge_lumped", "L_Q1") in {(p.kind, p.name) for p in eig.ports}  # 50 Ω at the box edge
    assert all(p.name != "Q1.bus" for p in eig.ports)


def test_branch_owners_follow_the_component_that_made_them():
    d = _design("t02_ibm_bowtie_5q")
    own = branch_owners(lom_from_design(d).model, d)
    assert own["C_C_Q0_a"] == {"C_Q0"} and own["Cc_Q3_bus"] == {"Q3"} and own["Port_P_Q2"] == {"P_Q2"}
    assert own["R_Q2"] == {"R_Q2"} and own["Cg_Q2_be"] == {"Q2"}
    t04 = _design("t04_two_qubit")
    own4 = branch_owners(lom_from_design(t04).model, t04)
    assert own4["C_C_Q1Q2"] == {"Q1", "Q2"} and own4["K_R1"] == {"R1"}


def test_subset_fill_touches_only_the_subset_and_leaves_the_netlist_whole():
    d = _design("t02_ibm_bowtie_5q", {"Q2_read": Q2_READ_GROUP})
    model = lom_from_design(d).model
    before = model.model_dump()
    filled = fill(model, d, Q2_READ)
    assert model.model_dump() == before  # the netlist is not touched
    assert set(filled.values) == set(model.branches)  # every branch of the whole chip is there
    own = branch_owners(model, d)
    fem = {k for k, v in filled.values.items() if v.extracted is not None}
    assert fem and all(own[k] & {"Q2", "C_Q2", "R_Q2"} for k in fem)
    assert {"Cg_Q2_ro", "C_C_Q2"} <= fem  # the readout coupling and the coupling to the feedline (L_Q2's net)
    for k, v in filled.values.items():
        if v.type == "C" and not own[k] & {"Q2", "C_Q2", "R_Q2"}:
            assert v.extracted is None and v.value == v.estimate
            assert "outside subset Q2_read" in v.source and v.extra.get("subset") == "outside"
    assert filled.values["Cg_Q3_bus"].value == model.branches["Cg_Q3_bus"].value["estimate"]
    assert filled.jobs[0]["scope"] == ["C_Q2", "Q2", "R_Q2"]


def test_line_nets_keep_their_ground_estimate_and_shared_branches_split_the_fem_value():
    d = _design("t02_ibm_bowtie_5q", {"Q2_read": Q2_READ_GROUP})
    filled = fill(lom_from_design(d).model, d, Q2_READ)
    v = filled.values
    # L_Q2 (cut by the box) carries a piece of line: its ground C is not a lumped pad capacitance
    assert v["C_C_Q2_a"].extracted is None and any("line net" in n and "C_C_Q2_a" in n for n in filled.notes)
    # C_Q2.b–ground: one FEM value shared by the capacitor's pad and the qubit's readout pad
    a, b = v["C_C_Q2_b"], v["Cc_Q2_ro"]
    assert a.extra["fem_total"] == pytest.approx(a.extracted + b.extracted)
    assert a.extracted / b.extracted == pytest.approx(a.estimate / b.estimate)


def test_whole_chip_readouts_no_longer_carry_the_line_capacitance():
    """Phase B's open item: on the uncut whole chip a λ/2 readout is one net with ≈ 1060 fF to ground; it used to land
    on a lumped branch (f_r −49 %). Now that branch keeps its estimate and f_r moves by < 3 %."""
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    d = _design("t02_ibm_bowtie_5q", {})
    sel = ["Q2", "R_Q2", "C_Q2", "L_Q2", "P_Q2"]
    model = lom_from_design(d, sel).model
    est = simulate(fill(model, d), max_modes=2).params["R_Q2.f_GHz"]
    filled = fill(model, d, CHIP02)
    fem = simulate(filled, max_modes=2).params["R_Q2.f_GHz"]
    assert abs(fem - est) / est < 0.03
    assert filled.values["Cc_Q2_ro"].extracted is None  # the line's ground C stays the LOM's
    assert filled.values["Cg_Q2_ro"].extracted is not None  # its mutual C to the qubit comes from the FEM


def _fake_job(tmp_path, name, group, select, labels, matrix, design_name="t02_ibm_bowtie_5q"):
    job = tmp_path / name
    (job / "results").mkdir(parents=True)
    (job / "results" / "results.json").write_text(json.dumps(
        {"analysis": "q3d_cmatrix", "group": group, "cmatrix": {"labels": labels, "matrix": matrix}}), encoding="utf-8")
    (job / "job.json").write_text(json.dumps(
        {"design": design_name, "group": group, "analysis": "q3d_cmatrix", "simulation_name": name, "select": select,
         "routes_in_sim": [], "ports": [], "waveguide_length_um": 0.0}), encoding="utf-8")
    return job


def test_two_subset_jobs_fill_one_whole_chip_circuit_each_with_its_own_branches(tmp_path):
    d = _design("t02_ibm_bowtie_5q", {})
    model = lom_from_design(d).model
    labels = ["Q1.island1", "Q1.island2", "Q1.ro"]
    m1 = (np.array([[160.0, -70.0, -2.0], [-70.0, 165.0, -15.0], [-2.0, -15.0, 50.0]])).tolist()
    m3 = (np.array([[150.0, -60.0, -16.0], [-60.0, 155.0, -1.5], [-16.0, -1.5, 48.0]])).tolist()
    j1 = _fake_job(tmp_path, "S_Q1", "S_Q1", ["Q1", "R_Q1", "C_Q1"], labels, m1)
    j3 = _fake_job(tmp_path, "S_Q3", "S_Q3", ["Q3", "R_Q3", "C_Q3"], [x.replace("Q1", "Q3") for x in labels], m3)
    filled = fill(model, d, [j1, j3])
    v = filled.values
    assert v["C_Q1_12"].extracted == pytest.approx(70.0) and v["C_Q1_12"].source == "cmatrix:S_Q1"
    assert v["C_Q3_12"].extracted == pytest.approx(60.0) and v["C_Q3_12"].source == "cmatrix:S_Q3"
    for q in ("Q0", "Q2", "Q4"):  # not simulated: estimates, marked
        assert v[f"C_{q}_12"].extracted is None and "outside subset S_Q1, S_Q3" in v[f"C_{q}_12"].source
    assert [j["job"] for j in filled.jobs] == ["S_Q1", "S_Q3"]
    assert len(filled.pairs) == 5  # every readout pair of the whole chip, two of them on FEM values


def test_kept_results_survive_a_new_subset_group(tmp_path):
    """``job.json`` carries ``group_hash`` (the design with only its own group): adding another subset group does not
    make a kept job look like another revision."""
    from quantcore_circuits.design.io import design_hash, group_hash  # pylint: disable=import-outside-toplevel

    d = _design("t02_ibm_bowtie_5q", {"A": Q2_READ_GROUP})
    d2 = _design("t02_ibm_bowtie_5q", {"A": Q2_READ_GROUP, "B": {**Q2_READ_GROUP, "select": ["Q1"]}})
    assert design_hash(d) != design_hash(d2)
    assert group_hash(d, "A") == group_hash(d2, "A")
    assert group_hash(d, "A") != group_hash(d2, "B")


def test_designer_sim_subset_adds_the_groups(tmp_path):
    from quantcore_circuits.designer import Designer  # pylint: disable=import-outside-toplevel

    src = tmp_path / "t02.json"
    shutil.copy(DESIGNS / "t02_ibm_bowtie_5q.json", src)
    d = Designer.load(src, live=False, out=str(tmp_path / "t02.oas"))
    names = d.sim_subset("P", qubits=["Q1", "Q3"], margin_um=100, analyses=["q3d_cmatrix"])
    assert names == ["P_Q1", "P_Q3"]
    assert d.data["sim_groups"]["P_Q1"]["ports"] == {"BusA_Q1": "cut"}
    assert [g.qubits for g in d.subset_plan] == [["Q1"], ["Q3"]]


def test_qubit_only_subset_cuts_the_readout_with_the_box():
    """``readouts=False`` (an eigenmode box that fits): only the qubit is selected; a grounded λ/4 readout gets
    ``"edge"`` so the box terminates it in 50 Ω (tutorial 01's ``Q1_q`` recipe)."""
    (g,) = plan_subset(_design("t01_chip12"), "Q", qubits=["Q1"], readouts=False)
    assert g.select == ["Q1"] and g.ports == {"R1": "edge"}
    (g2,) = plan_subset(_design("t02_ibm_bowtie_5q"), "Q", qubits=["Q2"], readouts=False)
    assert g2.select == ["Q2"] and g2.ports == {"BusA": "cut", "BusB": "cut"}  # the λ/2 floats: no "edge" needed


def test_dashboard_keeps_the_fem_filled_whole_chip_when_a_sub_circuit_is_filled():
    from quantcore_circuits.autotrack import _keep_shown  # pylint: disable=import-outside-toplevel

    whole = {"branches": [{"id": "a", "source": "fem: cmatrix:S"}, {"id": "b", "source": "estimate: x"}]}
    assert _keep_shown(whole, {"branches": [{"id": "a", "source": "estimate: x"}]})  # a sub-circuit
    assert not _keep_shown(whole, {"branches": [{"id": "a", "source": "estimate"}, {"id": "b", "source": "e"}]})
    assert not _keep_shown({"branches": [{"id": "a", "source": "estimate"}]}, {"branches": []})


def test_a_chosen_component_with_missing_nets_keeps_its_ground_estimates(tmp_path):
    """Surface-17's StarQubit (2026-11-14): its pin stubs got no excitation, so its pads were ground in the Q3D and the
    island's ground C included them. A chosen component with some nodes missing from the C-matrix keeps the ground
    estimates of the others."""
    d = _design("t02_ibm_bowtie_5q", {})
    job = _fake_job(tmp_path, "S_Q1", "S_Q1", ["Q1", "R_Q1", "C_Q1"], ["Q1.island1", "Q1.ro"],
                    [[160.0, -15.0], [-15.0, 50.0]])
    filled = fill(lom_from_design(d).model, d, job)
    assert filled.values["C_Q1_1"].extracted is None  # island1 → ground: island2 is missing, so it is in "ground"
    assert filled.values["Cf_Q1_ro"].extracted == pytest.approx(15.0)  # mutual C: still from the FEM
    assert any("no C-matrix net" in n for n in filled.notes)

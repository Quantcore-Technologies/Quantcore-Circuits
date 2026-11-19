"""Layout ↔ LOM: Designer (code-first), component LOM models, netlist builder, LOM simulation, DRC, synthesis."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "q1_r1_feedline.json"


def _code_design(live=False):
    from quantcore_circuits.designer import Designer

    d = Designer("q1_r1_code", box=(0, 0, 7500, 7500), chip={"name_chip": "Q1R1"}, live=live)
    pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270)
    pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90)
    fl = d.route("FL", pw.a, pe.a, airbridges="none")
    q1 = d.add(
        "Q1",
        "Xmon",
        at=(2975, 2200),
        cross_length=300,
        arm_width=25,
        gap=25,
        claws=["n"],
        flux_port=True,
        junction_type="Trilayer Squid",
        junction={"Lj_nH": 12.0, "Cj_fF": 2.0},
    )
    d.route("R1", q1.claw_n, fl.hanger(s=2000, length=300, side="right", ground_gap=6), meander=4200)
    pf = d.add(
        "PAD_F", "BondPad", at=(2964.5, 750), a=4, b=6, pad_width=300, pad_height=300, pad_gap=150, taper_length=300
    )
    d.route("FLUX", pf.a, q1.flux, a=4, b=6, nodes=[d.waypoint((2964.5, 1967.0), a=1, b=7.5)])
    d.targets(Q1={"f_q_GHz": 5.1, "alpha_MHz": -220}, R1={"f_GHz": 7.2, "g_MHz": 90})
    d.sim_group("Q1R1", ["Q1", "R1"], margin_um=300, analyses=["q3d_cmatrix", "eigenmode_epr"])
    return d


def test_designer_reproduces_the_example():
    d = _code_design()
    ref = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    a, b = d.design.to_json_dict(), ref
    from quantcore_circuits.design import load_design

    b = load_design(ref).to_json_dict()
    for key in ("instances", "routes", "targets", "sim_groups"):
        assert json.dumps(a[key], sort_keys=True) == json.dumps(b[key], sort_keys=True), key
    r = d.show()
    assert r.route_lengths()["R1"] == pytest.approx(4200.0, abs=0.01)


def test_designer_validates_immediately():
    from quantcore_circuits.designer import Designer

    d = Designer("t")
    with pytest.raises(ValueError, match="unknown parameter"):
        d.add("Q", "Xmon", cros_length=300)
    q = d.add("Q", "Xmon")
    with pytest.raises(AttributeError, match="has no port 'claw_s'"):
        q.claw_s  # noqa: B018
    with pytest.raises(ValueError, match="no instance"):
        d.route("R", "Q.claw_n", "P.a")
    assert "R" not in d.data["routes"] and set(d.data["instances"]) == {"Q"}  # failed changes leave no trace


def test_layout_to_lom_mapping():
    from quantcore_circuits.lom import lom_from_design

    b = lom_from_design(EXAMPLE)
    m = b.model
    assert set(m.nodes) == {"gnd", "FL", "Q1", "Q1.claw_n"}
    assert m.nodes["FL"].nets == ["FL", "PAD_W.pad", "PAD_E.pad"]  # the feedline joins both pads
    types = {n: x.type for n, x in m.branches.items()}
    assert types == {
        "Port_PAD_W": "R",
        "Port_PAD_E": "R",
        "C_Q1": "C",
        "J_Q1": "SQUID",
        "Cg_Q1_claw_n": "C",
        "Cc_Q1_claw_n": "C",
        "R1": "TLres",
        "K_R1": "HANGER",
    }
    assert m.branches["K_R1"].nodes == ("Q1.claw_n", "FL") and m.branches["R1"].value["kind"] == "lambda/4"
    assert m.controls["FLUX"]["target"] == "J_Q1"  # flux line = control, its pad conductor is grounded
    assert b.port_map["PAD_F.a"] == "gnd" and b.unconnected == []
    sub = lom_from_design(EXAMPLE, ["Q1", "R1"]).model
    assert sub.branches["Port_FL"].value["R_ohm"] == 25.0  # feedline outside the selection: two 50 Ω in parallel


def test_generic_cell_without_lom_keeps_connectivity(monkeypatch):
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.lom import fragment, lom_from_design

    d = Designer("g")
    a = d.add("A", "BondPad", at=(1500, 5000), rot=270)
    c = d.add("C", "FingerCapacitorSquare", at=(5000, 5000))
    d.route("W", a.a, c.a)
    assert {"C_C", "C_C_a", "C_C_b"} <= set(lom_from_design(d.design).model.branches)  # registered π network
    fragment.registered()
    monkeypatch.delitem(fragment._REGISTRY, "FingerCapacitorSquare")  # pretend it has no model
    b = lom_from_design(d.design)
    assert any("no LOM model" in n for n in b.notes)
    assert b.port_map["A.a"] == b.port_map["C.a"]  # the wire joined the pad and the capacitor port


def test_standalone_circuit_json_round_trip(tmp_path):
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.circuit.schema import load_circuit, save_circuit
    from quantcore_circuits.lom import lom_from_design

    m = lom_from_design(EXAMPLE).model
    f1 = fill(m, EXAMPLE)
    f2 = fill(load_circuit(save_circuit(m, tmp_path / "c.json")), None)
    assert [p.qubit for p in f2.pairs] == ["Q1"]
    assert f2.pairs[0].cg_fF == pytest.approx(f1.pairs[0].cg_fF)
    assert f2.pairs[0].f_r_GHz == pytest.approx(f1.pairs[0].f_r_GHz, rel=1e-6)
    assert f2.pairs[0].kappa_MHz == pytest.approx(f1.pairs[0].kappa_MHz)


@pytest.mark.analysis
def test_lom_simulation_matches_estimators():
    from quantcore_circuits.circuit.adapters import sqcircuit
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom import lom_from_design
    from quantcore_circuits.lom.simulate import simulate

    f = fill(lom_from_design(EXAMPLE).model, EXAMPLE)
    res = simulate(f)
    kinds = {m.label: m.kind for m in res.modes}
    assert kinds == {"Q1": "qubit", "R1": "resonator"}
    sq = sqcircuit(f)
    assert res.params["Q1.f_q_GHz"] == pytest.approx(sq["Q1.f_q_GHz"], rel=1e-3)
    assert res.params["Q1.alpha_MHz"] == pytest.approx(sq["Q1.alpha_MHz"], rel=0.01)
    assert res.params["R1.kappa_MHz"] > 0.01  # the hanger loads the resonator through the 50 Ω pads
    assert res.params["R1.chi_MHz"] == pytest.approx(sq["R1.chi_MHz"], rel=0.05)


def test_drc_rules(tmp_path):
    from quantcore_circuits.assembly.drc import check
    from quantcore_circuits.designer import Designer

    report = check(EXAMPLE)
    assert report.ok and not [i for i in report.issues if i.severity != "design"]
    # the example keeps its legacy pads and its 12 nH SQUID: PDK design warnings, flagged but never enforced
    assert {i.rule for i in report.design} == {"pad_edge", "pdk_rn"} and "DRC clean" in str(report)
    d = Designer.load(EXAMPLE)
    d.data["instances"]["Q1"]["params"]["claws"] = ["n", "w"]
    d.data["routes"]["X"] = {"from": "PAD_F.a", "to": "Q1.flux"}
    del d.data["routes"]["FLUX"]
    d.data["instances"]["PAD_E"]["place"]["at"] = [7400, 3750]
    rules = {(i.rule, tuple(i.objects)) for i in check(d.design, netlist=False).issues}
    assert ("dangling_port", ("Q1.claw_w",)) in rules
    assert ("outside_chip", ("PAD_E",)) in rules


def test_sidecar_carries_drc_and_lom(tmp_path):
    import quantcore_circuits as qcc

    out = tmp_path / "c.oas"
    qcc.write_layout(qcc.build(EXAMPLE), out)
    side = json.loads(out.with_name("c.qcc.json").read_text(encoding="utf-8"))
    assert [i for i in side["drc"] if i["severity"] != "design"] == []
    assert side["lom"]["port_nodes"]["PAD_W.a"] == "FL"


@pytest.mark.analysis
def test_lom_to_layout_two_qubits():
    from quantcore_circuits.lom.synthesize import PairTarget, layout_from_targets

    d = layout_from_targets(
        "two_q", [PairTarget("Q1", 5.1, -220, "R1", 7.2, 90), PairTarget("Q2", 5.4, -210, "R2", 7.5, 80)]
    )
    assert all(max(abs(r) for r in s["residuals"].values()) < 0.1 for s in d.synthesis)
    q1, q2 = (s["knobs"] for s in d.synthesis)
    assert q2["Q2.junction.Lj_nH"] < q1["Q1.junction.Lj_nH"]  # higher f_q → smaller Lj
    assert d.drc().ok
    from quantcore_circuits.lom import lom_from_design

    m = lom_from_design(d.design).model
    assert {"J_Q1", "J_Q2", "R1", "R2", "K_R1", "K_R2"} <= set(m.branches)


def test_cli_circuit_commands(tmp_path):
    from typer.testing import CliRunner

    from quantcore_circuits.cli import app

    runner = CliRunner()
    out = tmp_path / "c.json"
    res = runner.invoke(app, ["circuit", "export", str(EXAMPLE), "-o", str(out)])
    assert res.exit_code == 0 and "HANGER" in res.output and out.exists()
    res = runner.invoke(app, ["design", "drc", str(EXAMPLE), "--no-netlist"])
    assert res.exit_code == 0 and "DRC clean" in res.output


@pytest.mark.analysis
def test_registered_lom_for_stock_kqc_cell():
    """A KQC Swissmon gets its LOM from lom.kqc_models (register_lom), and its unused ports are flagged."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.lom.simulate import simulate

    d = Designer("swiss")
    pw = d.add("PAD_W", "BondPad", at=(1125, 5000), rot=270)
    pe = d.add("PAD_E", "BondPad", at=(8875, 5000), rot=90)
    fl = d.route("FL", pw.a, pe.a)
    q = d.add("QS", "Swissmon", at=(4000, 3000), junction={"Lj_nH": 11, "Cj_fF": 2})
    d.route("RS", q.cplr1, fl.hanger(s=4000 - 1125 + 150, length=300, side="right"), meander=4300)
    m = d.lom().model
    assert {"C_QS", "J_QS", "Cg_QS_cplr1", "RS", "K_RS"} <= set(m.branches)
    dangling = {i.objects[0] for i in d.drc().issues if i.rule == "dangling_port"}
    assert dangling == {"QS.cplr0", "QS.cplr2", "QS.drive", "QS.flux"}  # drive has no direction: still reported
    res = simulate(fill(m, d.design))
    assert {mo.label for mo in res.modes} >= {"QS", "RS"} and 3 < res.params["QS.f_q_GHz"] < 8

"""Junction values for the LOM and the simulations: ``junction.flux_phi0`` / ``asym`` (schema, hash), the one resolver
(:func:`~quantcore_circuits.lom.fragment.effective_junction`, L_eff of a SQUID), the LOM at a flux bias and the
eigenmode / driven export (L at the design flux on the lumped sheet, the drawn trilayer junction's PDK value, the
message for a KQC junction without one)."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from quantcore_circuits.design import Design, design_hash, load_design
from quantcore_circuits.design.io import canonical_json
from quantcore_circuits.design.schema import Instance, Junction
from quantcore_circuits.lom.fragment import effective_junction, instance_junction, squid_l_eff
from quantcore_circuits.pdk import get_pdk

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.setenv("QCC_TRACK", "0")


def _inst(cell: str, params: dict | None = None, junction: dict | None = None) -> Instance:
    data = {"cell": cell, "params": params or {}, "place": {"at": [0.0, 0.0]}}
    if junction is not None:
        data["junction"] = junction
    return Instance.model_validate(data)


# ---- schema -------------------------------------------------------------------------------------------------------
def test_schema_defaults_and_lists():
    j = Junction()
    assert (j.Lj_nH, j.Cj_fF, j.flux_phi0, j.asym) == (None, 0.0, 0.0, 0.0)  # a symmetric SQUID at its sweet spot
    j = Junction.model_validate({"Lj_nH": [6.0, 7.0], "flux_phi0": [0.1, 0.2], "asym": [0.05, 0.0]})
    assert j.flux_phi0 == [0.1, 0.2] and j.asym == [0.05, 0.0]
    with pytest.raises(ValueError, match="asym"):
        Junction.model_validate({"asym": 1.5})
    with pytest.raises(ValueError):
        Junction.model_validate({"flux": 0.1})  # unknown keys are still refused


def _example_designs():
    out = []
    for p in sorted(EXAMPLES.rglob("*.json")):
        if {"build", "jobs", "runs", "results"} & set(p.relative_to(EXAMPLES).parts[:-1]):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema") in ("qcc/0.1", "qcd/0.1"):
            out.append(p)
    return out


def test_old_designs_keep_their_json_and_hash():
    """Additive: a design without the new fields dumps no ``flux_phi0`` / ``asym``, and adding them at their defaults
    leaves the JSON and the hash as they were; a non-default value changes the hash."""
    paths = [p for p in _example_designs() if '"junction"' in p.read_text(encoding="utf-8")]
    assert paths
    for path in paths[:12]:
        d = load_design(path)
        data = d.to_json_dict()
        assert all(not ({"flux_phi0", "asym"} & set(i.get("junction") or {})) for i in data["instances"].values())
        raw = json.loads(path.read_text(encoding="utf-8"))
        for inst in raw["instances"].values():
            if inst.get("junction"):
                inst["junction"] |= {"flux_phi0": 0.0, "asym": 0}
        same = Design.model_validate(raw | {"name": d.name})
        assert canonical_json(same.to_json_dict()) == canonical_json(data)
        assert design_hash(same) == design_hash(d)
    raw = json.loads(paths[0].read_text(encoding="utf-8"))
    name = next(n for n, i in raw["instances"].items() if i.get("junction"))
    raw["instances"][name]["junction"]["flux_phi0"] = 0.1
    moved = Design.model_validate(raw | {"name": load_design(paths[0]).name})
    assert moved.to_json_dict()["instances"][name]["junction"]["flux_phi0"] == 0.1
    assert design_hash(moved) != design_hash(load_design(paths[0]))


# ---- the resolver ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("asym", [0.0, 0.3])
@pytest.mark.parametrize("phi", [0.0, 0.25, 0.45])
def test_squid_l_eff(phi, asym):
    x = math.pi * phi
    expect = 10.0 / (abs(math.cos(x)) * math.sqrt(1 + asym**2 * math.tan(x) ** 2))
    assert squid_l_eff(10.0, phi, asym) == pytest.approx(expect, rel=1e-12)
    same = 10.0 / math.sqrt(math.cos(x) ** 2 + asym**2 * math.sin(x) ** 2)  # the two forms agree
    assert squid_l_eff(10.0, phi, asym) == pytest.approx(same)
    ej = effective_junction(_inst("Xmon", {"junction_type": "Quantcore Squid"},
                                  {"Lj_nH": 10.0, "flux_phi0": phi, "asym": asym}))
    assert ej.kind == "SQUID" and ej.lj0_nH == 10.0 and ej.lj_eff_nH == pytest.approx(expect)
    if phi:
        assert ej.lj_eff_nH > 10.0
        if asym:  # the asymmetric SQUID tunes less
            assert ej.lj_eff_nH < squid_l_eff(10.0, phi, 0.0)


def test_symmetric_squid_at_half_flux_has_no_finite_l():
    with pytest.raises(ValueError, match="no finite L_J"):
        squid_l_eff(10.0, 0.5, 0.0)
    assert squid_l_eff(10.0, 0.5, 0.2) == pytest.approx(50.0)  # L_J0 / d
    ej = effective_junction(_inst("Xmon", {"junction_type": "Quantcore Squid"}, {"Lj_nH": 10.0, "flux_phi0": 0.5}))
    assert "error" in ej.as_dict() and ej.as_dict()["Lj_eff_nH"] is None


def test_single_junction_ignores_flux_and_sources():
    ej = effective_junction(_inst("Xmon", {"junction_type": "Quantcore Junction"}, {"Lj_nH": 9.0, "flux_phi0": 0.3}))
    assert ej.kind == "JJ" and ej.lj_eff_nH == 9.0 and ej.source == "design"
    drawn = effective_junction(_inst("Xmon", {"junction_type": "Quantcore Squid"}, {"flux_phi0": 0.25}))
    assert drawn.lj0_nH == pytest.approx(6.7344, abs=1e-4) and drawn.cj_fF == 15.0
    assert drawn.source == "drawn Quantcore Squid (PDK junction rule)" and drawn.flux_phi0 == 0.25  # Φ: design
    assert drawn.lj_eff_nH == pytest.approx(6.7344 * math.sqrt(2), rel=1e-4)
    unset = effective_junction(_inst("ConcentricTransmon"))  # KQC default Manhattan, unset: drawn as the PDK SQUID
    assert unset.kind == "SQUID" and unset.lj0_nH == pytest.approx(6.7344, abs=1e-4)
    assert unset.source == "drawn Quantcore Squid (PDK junction rule)"
    kqc = effective_junction(_inst("ConcentricTransmon", {"junction_type": "Manhattan"}))  # chosen: no PDK value
    assert kqc.kind == "SQUID" and kqc.lj0_nH is None and kqc.source is None
    assert effective_junction(_inst("Xmon", {"junction_type": "No Squid"})).kind is None


def test_lom_element_carries_design_flux():
    """The J element keeps ``Lj_nH`` = L_J0 and takes ``asym`` / ``flux_phi0`` from the design (no fixed 0)."""
    from quantcore_circuits.lom.fragment import lom_model

    for cell, params in (("Xmon", {"junction_type": "Quantcore Squid"}), ("Swissmon", {}),
                         ("metal:TransmonCrossFL", {"junction_type": "Quantcore Squid"})):
        inst = _inst(cell, params, {"Lj_nH": 8.0, "flux_phi0": 0.2, "asym": 0.1})
        frag = lom_model(cell)("Q", inst, get_pdk())
        j = next(e for e in frag.elements if e.type == "SQUID")
        assert (j.value["Lj_nH"], j.value["flux_phi0"], j.value["asym"]) == (8.0, 0.2, 0.1), cell
        assert instance_junction("Q", inst, get_pdk()).lj_eff_nH == pytest.approx(squid_l_eff(8.0, 0.2, 0.1))


# ---- the LOM at a flux bias -----------------------------------------------------------------------------------------
def _example_dict() -> dict:
    return copy.deepcopy(json.loads((EXAMPLES / "q1_r1_feedline.json").read_text(encoding="utf-8")))


def _filled(data: dict):
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom import lom_from_design

    d = Design.model_validate(data)
    return fill(lom_from_design(d).model, d)


def test_fill_uses_l_at_the_design_flux():
    data = _example_dict()  # Q1: Xmon with a Trilayer Squid, junction 12 nH
    base = _filled(data)
    data["instances"]["Q1"]["junction"] |= {"flux_phi0": 0.25, "asym": 0.2}
    biased = _filled(data)
    assert base.values["J_Q1"].value == 12.0 and "Lj0_nH" not in base.values["J_Q1"].extra
    v = biased.values["J_Q1"]
    assert v.value == pytest.approx(squid_l_eff(12.0, 0.25, 0.2)) and v.extra["Lj0_nH"] == 12.0
    p = biased.pairs[0]
    assert (p.flux_phi0, p.asym, p.lj0_nH) == (0.25, 0.2, 12.0) and p.ej_sum_ratio == pytest.approx(v.value / 12.0)


def test_lom_f_q_drops_with_flux():
    from quantcore_circuits.circuit.fill import two_node_model
    from quantcore_circuits.circuit.hamiltonian import flux_curve

    data = _example_dict()
    f_q = []
    for phi in (0.0, 0.25, 0.45):
        data["instances"]["Q1"]["junction"]["flux_phi0"] = phi
        pair = _filled(data).pairs[0]
        tn = two_node_model(pair)
        f_q.append(math.sqrt(8 * tn["EJ_GHz"] * tn["EC_GHz"]) - tn["EC_GHz"])
        # the flux curve still starts from the zero-flux E_J (the pair is at the bias)
        curve = flux_curve(tn["EJ_GHz"] * pair.ej_sum_ratio, tn["EC_GHz"], pair.asym, [0.0, phi])
        assert curve["f01_GHz"][0] >= curve["f01_GHz"][1]
    assert f_q[0] > f_q[1] > f_q[2]
    assert f_q[1] == pytest.approx(f_q[0] * 2 ** -0.25, rel=0.05)  # f ≈ √(8 E_J E_C), E_J ∝ |cos πΦ|


@pytest.mark.analysis
def test_lom_simulation_f_q_drops_with_flux():
    from quantcore_circuits.lom.simulate import simulate

    data = _example_dict()
    f_q = []
    for phi in (0.0, 0.3):
        data["instances"]["Q1"]["junction"]["flux_phi0"] = phi
        f_q.append(simulate(_filled(data), max_modes=2).params["Q1.f_q_GHz"])
    assert f_q[1] < f_q[0] - 0.3


# ---- the eigenmode / driven export ---------------------------------------------------------------------------------
def _write(tmp_path, data: dict) -> Path:
    path = tmp_path / f"{data['name']}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _junction_port(setup):
    return next(p for p in setup.simulation.ports if getattr(p, "junction", False))


def test_eigenmode_export_takes_the_drawn_trilayer_junction(tmp_path):
    """No ``junction.Lj_nH`` but a drawn Quantcore Squid: the export takes its PDK value (it used to raise)."""
    from quantcore_circuits.sim_tools import build_simulation

    data = _example_dict()
    data["name"] = "drawn_only"
    del data["instances"]["Q1"]["junction"]
    data["instances"]["Q1"]["params"]["junction_type"] = "Quantcore Squid"
    setup = build_simulation(_write(tmp_path, data), "Q1R1", "eigenmode_epr")
    port = _junction_port(setup)
    assert port.inductance == pytest.approx(6.7344e-9, rel=1e-4) and port.capacitance == pytest.approx(15e-15)
    assert any(n.startswith("Q1: junction L 6.734 nH") and "drawn Quantcore Squid, PDK junction rule" in n
               for n in setup.notes), setup.notes


def test_unset_kqc_junction_is_the_drawn_pdk_squid(tmp_path):
    """A KQC qubit placed with its default junction (ConcentricTransmon: Manhattan) and no ``junction`` value: the
    build draws the PDK Quantcore Squid, so the LOM, the eigenmode export and the Simulate pre-check take its PDK
    value (they used to say "its KQC Manhattan junction has no PDK value")."""
    from quantcore_circuits.assembly.plan import element_params, pdk_junction_type
    from quantcore_circuits.guiflow import missing_junctions
    from quantcore_circuits.layouts.registry import resolve_cell
    from quantcore_circuits.lom.fragment import cell_params
    from quantcore_circuits.sim_tools import build_simulation

    for cell, drawn in (("ConcentricTransmon", "Quantcore Squid"), ("Swissmon", "Quantcore Squid"),
                        ("Xmon", None), ("TrilayerConcentricTransmon", None)):
        cls = resolve_cell(cell)
        assert pdk_junction_type(cls, {}) == drawn, cell
        built = element_params(cls, {}, {}).get("junction_type", cls.get_schema()["junction_type"].default)
        assert cell_params(_inst(cell))["junction_type"] == built == (drawn or built), cell
    assert pdk_junction_type(resolve_cell("ConcentricTransmon"), {"junction_type": "Manhattan"}) is None
    data = {"schema": "qcc/0.1", "name": "ct_unset", "pdk": "quantcore_nb_sapphire_v1",
            "chip": {"box": [0.0, 0.0, 10000.0, 10000.0], "params": {"name_chip": "CT"}},
            "instances": {"CT1": {"cell": "ConcentricTransmon", "place": {"at": [5000.0, 5000.0]}}}, "routes": {},
            "sim_groups": {"cell": {"select": ["CT1"], "margin_um": 100.0, "analyses": ["hfss_eigenmode"]}}}
    path = _write(tmp_path, data)
    ej = instance_junction("CT1", load_design(path).instances["CT1"], get_pdk())
    assert ej.lj0_nH == pytest.approx(6.7344, abs=1e-4) and ej.cj_fF == 15.0
    assert ej.source == "drawn Quantcore Squid (PDK junction rule)"
    port = _junction_port(build_simulation(path, "cell", "hfss_eigenmode"))
    assert port.inductance == pytest.approx(6.7344e-9, rel=1e-4) and port.capacitance == pytest.approx(15e-15)
    assert missing_junctions(path) == {}


def test_kqc_manhattan_without_a_value_raises_where_to_set_it(tmp_path):
    """A chosen KQC Manhattan junction (drawn as Manhattan) has no PDK value: the eigenmode export says where to
    set L_J. Left unset, the build draws the PDK SQUID instead (test_unset_kqc_junction_is_the_drawn_pdk_squid)."""
    from quantcore_circuits.sim_tools import build_simulation

    data = {"schema": "qcc/0.1", "name": "ct_manhattan", "pdk": "quantcore_nb_sapphire_v1",
            "chip": {"box": [0.0, 0.0, 10000.0, 10000.0], "params": {"name_chip": "CT"}},
            "instances": {"CT1": {"cell": "ConcentricTransmon", "place": {"at": [5000.0, 5000.0]},
                                  "params": {"junction_type": "Manhattan"}}}, "routes": {},
            "sim_groups": {"cell": {"select": ["CT1"], "margin_um": 100.0, "analyses": ["hfss_eigenmode"]}}}
    path = _write(tmp_path, data)
    with pytest.raises(ValueError) as err:
        build_simulation(path, "cell", "hfss_eigenmode")
    msg = str(err.value)
    assert msg.startswith("CT1: no junction L_J (its KQC Manhattan junction has no PDK value)")
    assert "component dialog ▸ Junction" in msg and "instances.CT1.junction.Lj_nH" in msg
    build_simulation(path, "cell", "q3d_cmatrix")  # capacitance: the gap stays open, no L needed
    from quantcore_circuits.guiflow import missing_junctions

    assert list(missing_junctions(path)) == ["CT1"]
    data["instances"]["CT1"]["junction"] = {"Lj_nH": 9.0}
    assert missing_junctions(_write(tmp_path, data)) == {}


def test_driven_export_uses_l_at_the_design_flux(tmp_path):
    from quantcore_circuits.sim_tools import build_simulation

    data = _example_dict()
    data["name"] = "biased"
    data["instances"]["Q1"]["junction"] |= {"flux_phi0": 0.25, "asym": 0.1}
    setup = build_simulation(_write(tmp_path, data), "Q1R1", "hfss_driven")
    lj = squid_l_eff(12.0, 0.25, 0.1)
    assert _junction_port(setup).inductance == pytest.approx(lj * 1e-9, rel=1e-9)
    assert _junction_port(setup).capacitance == pytest.approx(2e-15)
    assert any(f"junction L {lj:.4g} nH (L_J0 12 nH)" in n and "Φ = 0.25, d = 0.1" in n for n in setup.notes)


def test_sidecar_junction_entry():
    from quantcore_circuits.assembly.sidecar import instance_junction_entry

    d = load_design(EXAMPLES / "q1_r1_feedline.json")
    entry = instance_junction_entry("Q1", d.instances["Q1"], get_pdk(d.pdk))
    assert entry == {"kind": "SQUID", "Lj0_nH": 12.0, "Cj_fF": 2.0, "flux_phi0": 0.0, "asym": 0.0, "Lj_eff_nH": 12.0,
                     "source": "design"}
    assert instance_junction_entry("PAD_W", d.instances["PAD_W"], get_pdk(d.pdk)) is None  # no junction: no entry
    assert instance_junction("R", _inst("metal:Rectangle"), get_pdk()) is None  # a Metal wrapper's junction_type alone


def test_knobs_and_designer_take_the_new_fields(tmp_path):
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.optimise import get_knob, set_knob

    d = load_design(EXAMPLES / "q1_r1_feedline.json")
    assert get_knob(d, "Q1.junction.flux_phi0") == 0.0 and get_knob(d, "Q1.junction.asym") == 0.0
    moved = set_knob(d, "Q1.junction.flux_phi0", 0.2)
    assert moved.instances["Q1"].junction.flux_phi0 == 0.2 and moved.instances["Q1"].junction.Lj_nH == 12.0
    des = Designer("jj")
    q = des.add("Q1", "Xmon", at=(2000, 2000), junction={"Lj_nH": 7.0, "flux_phi0": 0.1, "asym": 0.05})
    assert des.design.instances["Q1"].junction.asym == 0.05
    q.set(junction={"Lj_nH": 7.0, "flux_phi0": 0.3})
    assert des.design.instances["Q1"].junction.flux_phi0 == 0.3
    with pytest.raises(ValueError):
        des.add("Q2", "Xmon", at=(5000, 2000), junction={"Lj_nH": 7.0, "asym": 2.0})

import pytest
from pydantic import ValidationError

from quantcore_circuits.design import Design, design_hash, load_design


def test_example_loads(example_path):
    d = load_design(example_path)
    assert d.name == "q1_r1_feedline"
    assert set(d.instances) == {"PAD_W", "PAD_E", "PAD_F", "Q1"}
    assert d.routes["R1"].type == "meander" and d.routes["R1"].length == 4200


def test_legacy_schema_name_accepted(example_dict):
    example_dict["schema"] = "qcd/0.1"
    assert Design.model_validate(example_dict).schema_ == "qcc/0.1"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["instances"]["Q1"]["place"].update({"snap": "Q1.claw_n"}), "snap placement needs both"),
        (lambda d: d["instances"].update({"chip": d["instances"]["Q1"]}), "reserved"),
        (lambda d: d["routes"]["FL"].update({"to": "NOPE.a"}), "unknown instance"),
        (lambda d: d["routes"]["R1"]["to"].update({"hanger": "XX"}), "not a route"),
        (lambda d: d["routes"]["R1"].pop("length"), "meander routes need a 'length'"),
        (lambda d: d["sim_groups"]["Q1R1"].update({"select": ["Q9"]}), "unknown instance/route"),
    ],
)
def test_validation_errors(example_dict, mutate, message):
    mutate(example_dict)
    with pytest.raises(ValidationError, match=message):
        Design.model_validate(example_dict)


def test_hash_is_canonical_and_ignores_targets(example_dict):
    a = Design.model_validate(example_dict)
    example_dict["targets"]["Q1"]["f_q_GHz"] = 6.0  # targets don't change geometry/results
    reordered = dict(reversed(list(example_dict.items())))
    b = Design.model_validate(reordered)
    assert design_hash(a) == design_hash(b)
    example_dict["instances"]["Q1"]["params"]["gap"] = 24.0
    assert design_hash(Design.model_validate(example_dict)) != design_hash(a)


def test_python_design_file(tmp_path, example_path):
    py = tmp_path / "design.py"
    py.write_text(
        "import json, pathlib\n"
        f"_d = json.loads(pathlib.Path(r'{example_path}').read_text())\n"
        "def design():\n    _d['name'] = 'from_py'\n    return _d\n",
        encoding="utf-8",
    )
    assert load_design(py).name == "from_py"


def test_wire_coupling_is_a_declared_galvanic_join(example_path, tmp_path):
    """``type: "wire"``: port-to-port only, no value; the netlist check counts it as a declared connection."""
    import shutil

    from quantcore_circuits.assembly.netlist import declared_connections
    from quantcore_circuits.designer import Designer

    d = Designer.load(shutil.copy(example_path, tmp_path / "design.json"), verbose=False)  # never touch the example
    d.couple("W1", "PAD_F.a", "Q1.flux", wire=True)
    assert d.data["couplings"]["W1"] == {"between": ["PAD_F.a", "Q1.flux"], "type": "wire", "value": None, "note": ""}
    assert frozenset({"PAD_F.a", "Q1.flux"}) in declared_connections(d.design)
    with pytest.raises(ValueError, match="no value"):
        d.couple("W2", "PAD_F.a", "Q1.flux", C_fF=1.0, wire=True)
    with pytest.raises(ValueError, match="has ports"):
        d.couple("W3", "PAD_F.a", "Q1.nope", wire=True)
    data = d.design.to_json_dict()
    data["couplings"]["W4"] = {"between": ["Q1", "PAD_F.a"], "type": "wire"}
    with pytest.raises(ValidationError, match="must be '<instance>.<port>'"):
        Design.model_validate(data)

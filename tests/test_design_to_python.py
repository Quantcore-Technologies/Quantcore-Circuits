"""``qcc design to-python``: the script rebuilds the same design (same ``qcc design hash``)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantcore_circuits.cli import app
from quantcore_circuits.design import canonical_json, design_hash, load_design
from quantcore_circuits.design.pyscript import RoundTripError, design_to_python, lit

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [
    "examples/q1_r1_feedline.json",  # hanger route, free-form targets, sim group, taper waypoint
    "examples/five_qubit_synth.json",
    "examples/tutorials/designs/t01_chip12.json",
    "examples/designs/legacy/chip_05_flux_tlqubits.json",  # port snaps (ConnectorPad ... snap="PL.a")
    "examples/designs/metal/a2_two_coupled_transmons.json",
    "examples/designs/kqc/test_chips/shaping.json",
    "examples/designs/qpdk/gatemon_test_chip.json",
    "examples/designs/metal/m54_wallraff_cell.json",
]


def _rebuilt(script_path: Path, tmp_path: Path) -> Path:
    """Run the script as a user would (``python design.py``): it writes ``<name>.json`` next to itself."""
    r = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert r.returncode == 0, r.stderr[-1500:]
    out = list(script_path.parent.glob("*.json"))
    assert len(out) == 1, out
    return out[0]


@pytest.mark.parametrize("rel", EXAMPLES)
def test_script_rebuilds_the_same_design(rel, tmp_path):
    src = ROOT / rel
    script = tmp_path / "design.py"
    res = CliRunner().invoke(app, ["design", "to-python", str(src), "-o", str(script)])
    assert res.exit_code == 0, res.output
    again = _rebuilt(script, tmp_path)
    a, b = load_design(src), load_design(again)
    assert design_hash(a) == design_hash(b)
    assert canonical_json(a.to_json_dict()) == canonical_json(b.to_json_dict())


def test_script_is_readable_designer_code():
    text = design_to_python(ROOT / "examples" / "q1_r1_feedline.json")
    assert "from quantcore_circuits.designer import Designer" in text
    flat = " ".join(text.split()).replace("( ", "(")
    assert 'd.add("Q1", "Xmon",' in flat and 'd.route("R1", "Q1.claw_n"' in flat
    assert 'd["FL"].hanger(s=2000.0, length=300.0, side="right")' in flat
    assert "d.targets(" in text and "d.sim_group(" in text
    assert "d.data[" not in text  # everything is said with Designer calls
    compile(text, "design.py", "exec")


def test_what_the_designer_cannot_say_is_written_as_data():
    """A static cell's ports, explicit nets, a waypoint's corner radius, a coupling's fem flag: written as plain data for
    that entry, so the round trip still holds."""
    data = json.loads((ROOT / "examples" / "q1_r1_feedline.json").read_text(encoding="utf-8"))
    data["routes"]["FLUX"]["nodes"] = [{"at": [2964.5, 1967.0], "a": 1, "b": 7.5, "r": 40}]
    data["couplings"] = {"C_x": {"between": ["Q1", "PAD_F"], "type": "C", "value": 1.5, "fem": False}}
    text = design_to_python(data)
    assert 'd.data["couplings"]["C_x"]' in text
    assert "r" in text
    ns: dict = {}
    exec(compile(text.split('\nif __name__')[0], "design.py", "exec"), ns)  # noqa: S102
    assert design_hash(ns["d"].design) == design_hash(load_design(data))


def test_a_broken_script_is_refused(monkeypatch):
    from quantcore_circuits.design import pyscript

    monkeypatch.setattr(pyscript, "_instance_stmt", lambda name, spec: "raise RuntimeError('boom')")
    # the instance falls back to plain data, so the round trip still holds; a broken fallback would raise
    assert "d.data[\"instances\"][\"Q1\"]" in design_to_python(ROOT / "examples" / "q1_r1_feedline.json")
    monkeypatch.setattr(pyscript, "_raw_stmt", lambda section, name, spec: "raise RuntimeError('boom')")
    with pytest.raises(RoundTripError):
        design_to_python(ROOT / "examples" / "q1_r1_feedline.json")


def test_literal_formatting():
    assert lit({"a": 1.0, "b": [1, 2.5], "c": "x"}) == '{"a": 1.0, "b": [1, 2.5], "c": "x"}'
    long = lit({"k" + str(i): [i, i + 0.5] for i in range(30)})
    assert long.startswith("{\n") and long.endswith("\n}")

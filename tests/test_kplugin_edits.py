"""Plugin edits that the GUI tutorials needed: rename, chip settings, junction values, couplings, pad-edge fix, hanger
direction. Pure design.json logic (no KLayout)."""

import copy
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kplugin" / "python"))

from qcc_kplugin import design_io, design_ops  # noqa: E402


def sample():
    d = design_io.new_design("s")
    design_io.add_instance(d, "BP1", "BondPad", (1125, 3750), 270)
    design_io.add_instance(d, "BP2", "BondPad", (6375, 3750), 90)
    design_io.add_instance(d, "X1", "Xmon", (3000, 2200))
    design_io.add_route(d, "FL", "BP1.a", "BP2.a")
    design_io.add_route(d, "R1", "X1.claw_n", design_io.hanger_end("FL", (3000, 3750), 300, "left"), "meander", 4200)
    d["targets"] = {"X1": {"f_q_GHz": 5.2}, "R1": {"f_GHz": 7.0}}
    d["couplings"] = {"C": {"between": ["X1", "R1"], "type": "C", "value": 1.0}}
    d["sim_groups"] = {"G": {"select": ["X1", "R1"], "ports": {"R1": "edge"}}}
    d["instances"]["BP2"]["place"] = {"snap": "a", "to": "X1.claw_n"}  # only for the reference rewrite
    return d


def test_rename_instance_follows_every_reference():
    d = sample()
    design_ops.rename_instance(d, "X1", "Q1")
    assert list(d["instances"]) == ["BP1", "BP2", "Q1"]
    assert d["routes"]["R1"]["from"] == "Q1.claw_n"
    assert d["instances"]["BP2"]["place"]["to"] == "Q1.claw_n"
    assert "Q1" in d["targets"] and "X1" not in d["targets"]
    assert d["couplings"]["C"]["between"] == ["Q1", "R1"]
    assert d["sim_groups"]["G"]["select"] == ["Q1", "R1"]


def test_rename_refuses_taken_and_bad_names():
    d = sample()
    for bad in ("BP1", "FL", "chip", "", "a.b", "a b"):
        with pytest.raises(ValueError):
            design_ops.rename_instance(d, "X1", bad)
    with pytest.raises(ValueError):
        design_ops.rename_instance(d, "nope", "Q9")
    before = copy.deepcopy(d)
    design_ops.rename_instance(d, "X1", "X1")
    assert d == before


def test_rename_route_moves_hangers_targets_and_groups():
    d = sample()
    design_io.add_route(d, "R2", "X1.claw_n", design_io.hanger_end("FL", (3500, 3750), 300), "meander", 4000)
    design_ops.rename_route(d, "FL", "FEED")
    assert list(d["routes"])[0] == "FEED"
    assert d["routes"]["R1"]["to"]["hanger"] == "FEED" and d["routes"]["R2"]["to"]["hanger"] == "FEED"
    design_ops.rename_route(d, "R1", "RO1")
    assert "RO1" in d["targets"] and d["couplings"]["C"]["between"] == ["X1", "RO1"]
    assert d["sim_groups"]["G"]["select"] == ["X1", "RO1"] and "RO1" in d["sim_groups"]["G"]["ports"]


def test_chip_settings_label_size_grid():
    d = design_io.new_design("hello")
    assert design_ops.set_chip(d, "QS2", False, (9000, 8000)) == ["label 'QS2'", "die 9000 x 8000 µm"]
    assert d["chip"]["box"] == [0.0, 0.0, 9000.0, 8000.0] and d["chip"]["params"]["name_chip"] == "QS2"
    assert "with_grid" not in d["chip"]["params"]
    assert design_ops.set_chip(d, "QS2", True, (9000, 8000)) == ["with_grid True"]
    assert design_ops.set_chip(d, "QS2", False, (9000, 8000)) == ["with_grid False"]
    assert "with_grid" not in d["chip"]["params"]
    with pytest.raises(ValueError):
        design_ops.set_chip(d, None, None, (500, 9000))


def test_junction_values():
    d = sample()
    assert design_ops.set_junction(d, "X1", 7.32, 13.8) is True
    assert d["instances"]["X1"]["junction"] == {"Lj_nH": 7.32, "Cj_fF": 13.8}
    assert design_ops.set_junction(d, "X1", 7.32, 13.8) is False
    assert design_ops.set_junction(d, "X1", None, 2.0) is True and d["instances"]["X1"]["junction"] == {"Cj_fF": 2.0}
    assert design_ops.set_junction(d, "X1", None, None) is True and "junction" not in d["instances"]["X1"]
    with pytest.raises(ValueError):
        design_ops.set_junction(d, "X1", -1.0, None)


def test_coupling():
    d = sample()
    design_ops.set_coupling(d, "C_Q", "X1", "BP1", "C", 0.4, "arms")
    assert d["couplings"]["C_Q"] == {"between": ["X1", "BP1"], "type": "C", "value": 0.4, "note": "arms"}
    with pytest.raises(ValueError):
        design_ops.set_coupling(d, "x", "X1", "X1")
    with pytest.raises(ValueError):
        design_ops.set_coupling(d, "x", "X1", "ZZ")
    with pytest.raises(ValueError):
        design_ops.set_coupling(d, "x", "X1", "BP1", "wire")
    design_ops.set_coupling(d, "w", "X1.claw_n", "BP1.a", "wire")
    assert "value" not in d["couplings"]["w"]


def test_pad_edge_fix():
    d = sample()
    d["instances"]["BP2"]["place"] = {"at": [6375, 3750], "rot": 90.0}
    drc = [{"rule": "pad_edge", "objects": ["BP1", "BP2"], "message": "BP1: outer edge"},
           {"rule": "dangling_port", "objects": ["X1"], "message": "X1.a"}]
    names = design_ops.pad_edge_instances(drc)
    assert names == ["BP1", "BP2"]
    assert design_ops.apply_pad_edge(d, names) == ["BP1", "BP2"]
    assert d["instances"]["BP1"]["place"]["edge"] == "auto"
    assert design_ops.apply_pad_edge(d, names) == []  # nothing left to change
    assert design_ops.pad_edge_instances([{"rule": "pad_edge", "message": "BP3: outer edge 0 µm"}]) == ["BP3"]


def test_hanger_end_direction_only_written_when_backward():
    fw = design_io.hanger_end("FL", (1, 2), 300)
    bw = design_io.hanger_end("FL", (1, 2), 300, direction="backward")
    assert "direction" not in fw and bw["direction"] == "backward"
    with pytest.raises(ValueError):
        design_io.hanger_end("FL", (1, 2), 300, direction="sideways")


def test_add_route_with_own_width_and_gap_and_removal():
    d = design_io.new_design("w")
    design_io.add_instance(d, "A", "BondPad", (1000, 3000), 270)
    design_io.add_instance(d, "B", "BondPad", (6000, 3000), 90)
    design_io.add_route(d, "R", "A.a", "B.a", "cpw", None, None, None, 20, 12)
    assert d["routes"]["R"]["a"] == 20.0 and d["routes"]["R"]["b"] == 12.0 and "r" not in d["routes"]["R"]
    design_io.set_route_options(d, "R", a=None, b=None)  # the dialog left both empty
    assert "a" not in d["routes"]["R"] and "b" not in d["routes"]["R"]


def test_metal_options_and_junction_params_text_become_dicts():
    assert design_io.parse_value('{"a": 1}', "{}", "options") == {"a": 1}
    assert design_io.parse_value('{"lj_nH": 7.3}', "{}", "junction_params") == {"lj_nH": 7.3}
    assert design_io.parse_value("{}", "{}", "options") == "{}"  # nothing set: stays the default
    assert design_io.parse_value("{not json", "{}", "options") == "{not json"
    assert design_io.parse_value('{"a": 1}', "{}", "other") == '{"a": 1}'  # other text parameters stay strings
    assert design_io.parse_value("Quantcore Squid", "x") == "Quantcore Squid"


def test_build_error_line_skips_trailing_warnings():
    from qcc_kplugin.session import build_error

    out = ("Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\n"
           "quantcore_circuits.route.router.RoutingError: route R2: could not auto-route Manhattan path; add 'nodes'\n"
           "FutureWarning: As part of our ongoing efforts to align with the Python Scientific Community\n")
    assert build_error(out) == "route R2: could not auto-route Manhattan path; add 'nodes'"  # short for the status bar
    assert build_error("x\nkqcircuits.foo.ValueError: bad b\n") == "ValueError: bad b"
    assert build_error("some failure\nFutureWarning: later\n") == "some failure"
    assert build_error("") == ""


def test_free_end_dir_follows_the_last_node():
    d = design_io.new_design("f")
    design_io.add_instance(d, "A", "BondPad", (1000, 3000), 270)
    free = design_io.free_end((2000, 3000), 180.0, "short")
    design_io.add_route(d, "R", "A.a", free, "cpw", None, [(1500, 3000), (1500, 3400)])
    r = d["routes"]["R"]
    design_io.move_route_node(d, "R", 1, (1900, 3300))  # the last node: the free end looks back at it
    assert r["to"]["dir"] == pytest.approx(math.degrees(math.atan2(300, -100)) % 360)
    design_io.set_node(d, "R", 1, at=(2000, 3500))
    assert r["to"]["dir"] == pytest.approx(90.0)
    design_io.insert_route_node(d, "R", 2, (2000, 3200))  # a new last node
    assert r["to"]["dir"] == pytest.approx(90.0) and len(r["nodes"]) == 3
    design_io.move_route_node(d, "R", 0, (1400, 3000))  # not next to the end: untouched
    assert r["to"]["dir"] == pytest.approx(90.0)
    design_io.delete_route_node(d, "R", 2)  # back to the previous last node
    assert r["to"]["dir"] == pytest.approx(90.0)
    # a free end without a dir, and a port end, are left alone
    design_io.add_route(d, "S", "A.a", free_end := design_io.free_end((2000, 3100)), "cpw", None, [(1500, 3000)])
    design_io.move_route_node(d, "S", 0, (1600, 3000))
    assert "dir" not in d["routes"]["S"]["to"] and free_end["at"] == [2000.0, 3100.0]


def test_lom_progress_stage_from_the_step_and_its_output():
    from qcc_kplugin import dock  # pylint: disable=import-outside-toplevel

    assert dock.lom_stage(0, "") == 1  # the circuit export
    assert dock.lom_stage(1, "") == 2
    assert dock.lom_stage(1, "[lom] reading the circuit x.json\n") == 2
    assert dock.lom_stage(1, "[lom] reading\n[lom] solving 12 branches\n") == 3
    assert dock.lom_stage(1, "[lom] reading\n[lom] solving\n[lom] writing\n[lom] drawing the circuit\n") == 5
    assert len(dock.LOM_STAGES) == 5


def test_circuit_simulate_prints_its_stages_on_stderr(tmp_path):
    """The Run LOM progress bar reads these "[lom]" lines; stdout (the mode table) is unchanged."""
    import subprocess  # pylint: disable=import-outside-toplevel

    root = Path(__file__).resolve().parents[1]
    circuit = tmp_path / "q1.circuit.json"
    exe = Path(sys.executable).parent / "Scripts" / "qcc.exe"
    qcc = [str(exe)] if exe.exists() else [sys.executable, "-m", "quantcore_circuits.cli"]
    r = subprocess.run([*qcc, "circuit", "export", str(root / "examples" / "q1_r1_feedline.json"), "-o", str(circuit)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr[-500:]
    r = subprocess.run([*qcc, "circuit", "simulate", str(circuit)], capture_output=True, text=True, check=False,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr[-500:]
    stages = [ln.split()[1] for ln in r.stderr.splitlines() if ln.startswith("[lom] ")]
    assert stages == ["reading", "solving", "writing"]
    assert "[lom]" not in r.stdout and "mode 0" in r.stdout


def test_build_error_names_the_invalid_design_field():
    from qcc_kplugin.session import build_error

    out = ("Traceback ...\npydantic_core._pydantic_core.ValidationError: 1 validation error for Design\n"
           "  Value error, sim group gui_sim: unknown instance/route 'F1' [type=value_error, input_value={...}]\n"
           "    For further information visit https://errors.pydantic.dev/2.14/v/value_error\n")
    assert build_error(out) == "design.json is not valid: Value error, sim group gui_sim: unknown instance/route 'F1'"


def test_scrub_references_after_a_delete():
    d = sample()
    d["instances"]["BP2"]["place"] = {"snap": "a", "to": "X1.claw_n"}
    design_io.add_route(d, "R2", "BP1.a", design_io.hanger_end("R1", (3000, 3000), 200, "left"), "meander", 3000)
    d["sim_groups"]["gui_sim"] = {"select": ["X1", "R1"]}
    design_io.delete_instance(d, "X1")  # removes R1 (it starts on X1)
    notes = design_io.scrub_references(d, {"BP2": {"trans": {"at": [6375, 3750], "rot": 90, "mirror": False}}})
    assert "R2" not in d["routes"]  # it hung from R1
    assert d["instances"]["BP2"]["place"] == {"at": [6375.0, 3750.0], "rot": 90.0}
    assert "gui_sim" not in d.get("sim_groups", {}) and "G" not in d.get("sim_groups", {})
    assert "X1" not in d.get("targets", {}) and "R1" not in d.get("targets", {}) and "C" not in d.get("couplings", {})
    assert notes and design_io.scrub_references(d) == []  # nothing left to remove
    from quantcore_circuits.design import load_design

    load_design(d)  # valid again

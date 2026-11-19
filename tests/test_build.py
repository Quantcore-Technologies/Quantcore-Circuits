import math

import klayout.db as db
import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits.assembly import PlacementError, build, plan_design, snap_trans, write_layout
from quantcore_circuits.design import Design
from quantcore_circuits.layouts.ports import CellBuildError, Port
from quantcore_circuits.route.router import RoutingError


def test_example_builds_with_exact_meander_length(example_path, tmp_path):
    r = build(example_path)
    lengths = r.route_lengths()
    assert lengths["R1"] == pytest.approx(4200.0, abs=0.01)
    assert lengths["FL"] == pytest.approx(5250.0, abs=0.01)
    out = write_layout(r, tmp_path / "chip.oas")
    ly = db.Layout()
    ly.read(str(out))
    assert [c.name for c in ly.top_cells()] == ["q1_r1_feedline"]  # chip wrapped in a static top cell
    chip = ly.cell(next(ly.top_cell().each_inst()).cell_index)
    ids = {i.property("id") for i in chip.each_inst()} - {None}
    assert ids == {"PAD_W", "PAD_E", "PAD_F", "Q1", "FL", "R1", "FLUX"}


def test_routes_connect_declared_ports(example_path):
    r = build(example_path)
    refp, ports = r.refpoints, r.plan.all_ports()
    for name, route in r.design.routes.items():
        start = ports[route.from_]
        assert refp[f"{name}_port_a"].distance(start.pos) < 1e-3, name
        if isinstance(route.to, str):
            assert refp[f"{name}_port_b"].distance(ports[route.to].pos) < 1e-3, name


def test_snap_trans_faces_ports():
    own = Port("a", pya.DPoint(0, 0), pya.DVector(0, 1))
    target = Port("claw", pya.DPoint(100, 50), pya.DVector(1, 0))
    t = snap_trans(own, target)
    assert (t * own.pos).distance(target.pos) < 1e-9
    d = t * own.dir
    assert d.x == pytest.approx(-1) and abs(d.y) < 1e-12  # anti-parallel
    assert t.angle % 90 == pytest.approx(0)


def snap_design(example_dict, q1_at):
    d = example_dict
    d["instances"]["Q1"]["params"]["claws"] = ["n", "w"]
    d["instances"]["Q1"]["place"]["at"] = q1_at
    d["instances"]["PAD_X"] = {"cell": "BondPad", "place": {"snap": "PAD_X.a", "to": "Q1.claw_w", "gap": 200}}
    del d["routes"]["FLUX"]  # has absolute waypoints tied to the original Q1 position
    return Design.model_validate(d)


def test_snapped_instance_follows_target(example_dict):
    import copy

    p1 = plan_design(snap_design(copy.deepcopy(example_dict), [2975, 2200]))
    p2 = plan_design(snap_design(copy.deepcopy(example_dict), [3175, 2300]))
    for p in (p1, p2):
        pad, claw = p.port("PAD_X.a"), p.port("Q1.claw_w")
        assert pad.pos.distance(claw.pos + claw.dir * 200) < 1e-6
        assert pad.dir.sprod(claw.dir) == pytest.approx(-1)
    moved = p2.instances["PAD_X"].trans.disp - p1.instances["PAD_X"].trans.disp
    assert (moved.x, moved.y) == pytest.approx((200, 100))
    # the meander re-routes but keeps its length
    assert p2.routes["R1"].length == pytest.approx(4200, abs=0.01)


def test_snap_cycle_is_an_error(example_dict):
    d = example_dict
    d["instances"]["A"] = {"cell": "BondPad", "place": {"snap": "A.a", "to": "B.a"}}
    d["instances"]["B"] = {"cell": "BondPad", "place": {"snap": "B.a", "to": "A.a"}}
    with pytest.raises(PlacementError, match="snap cycle"):
        plan_design(Design.model_validate(d))


def test_bad_parameter_is_reported(example_dict):
    example_dict["instances"]["Q1"]["params"]["claws"] = ["x"]
    with pytest.raises(CellBuildError, match="Unknown claw"):
        plan_design(Design.model_validate(example_dict))
    example_dict["instances"]["Q1"]["params"] = {"no_such_param": 1}
    with pytest.raises(ValueError, match="unknown parameter"):
        plan_design(Design.model_validate(example_dict))


def test_too_short_meander_is_reported(example_dict):
    example_dict["routes"]["R1"]["length"] = 500
    with pytest.raises(RoutingError, match="shorter than the shortest path"):
        plan_design(Design.model_validate(example_dict))


def test_hanger_coupler_geometry(example_path):
    p = plan_design(build(example_path).design)
    nodes = p.routes["R1"].polyline()
    fl_y = p.routes["FL"].polyline()[0].y
    coupler_start, coupler_end = nodes[-2], nodes[-1]
    # coupler runs parallel to the feedline, centred at s=2000 µm, 300 µm long, on the right (below)
    assert coupler_start.y == coupler_end.y
    assert coupler_end.x - coupler_start.x == pytest.approx(300)
    assert (coupler_start.x + coupler_end.x) / 2 == pytest.approx(1125 + 2000)
    assert fl_y - coupler_start.y == pytest.approx(10 / 2 + 6 + 6 + 6 + 10 / 2)
    assert p.routes["R1"].params["term2"] == 0  # shorted end


def test_launcher_chip_ports(example_dict):
    example_dict["chip"] = {"box": [0, 0, 10000, 10000], "launchers": "SMA8", "params": {}}
    example_dict["instances"] = {"Q1": example_dict["instances"]["Q1"]}
    example_dict["instances"]["Q1"]["params"]["flux_port"] = False
    example_dict["routes"] = {
        "RO": {"from": "chip.WN", "to": "Q1.claw_n", "type": "cpw", "nodes": [[2975, 8800], [2975, 8800]]}
    }
    example_dict["sim_groups"] = {}
    p = plan_design(Design.model_validate(example_dict))
    assert {"NW", "NE", "WN", "WS"} <= set(p.chip_ports)
    assert math.isclose(p.chip_ports["WN"].dir.length(), 1.0)

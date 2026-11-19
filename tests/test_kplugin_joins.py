"""Connect on a line: hang beside it (hanger coupler) or merge into it (T-junction), and converting between the two.
Pure design.json logic (no KLayout)."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kplugin" / "python"))

from qcc_kplugin import design_io, joins  # noqa: E402

FL = [(1125.0, 3750.0), (1225.0, 3750.0), (6275.0, 3750.0), (6375.0, 3750.0)]  # a built feedline's polyline


def feedline_design():
    d = design_io.new_design("j")
    design_io.add_instance(d, "PAD_W", "BondPad", (1125, 3750), 270)
    design_io.add_instance(d, "PAD_E", "BondPad", (6375, 3750), 90)
    design_io.add_instance(d, "C1", "CpweFingerCapacitor", (3000, 3300), 90)
    design_io.add_route(d, "FL", "PAD_W.a", "PAD_E.a")
    d["routes"]["FL"]["airbridges"] = "none"
    design_io.add_route(d, "R9", "C1.a", design_io.hanger_end("FL", (5000, 3750), 300, "right"), "meander", 4000)
    d["sim_groups"] = {"G": {"select": ["FL", "C1"]}}
    return d


def test_merge_splits_the_line_with_a_tee_facing_the_side():
    d = feedline_design()
    out = joins.merge(d, "FL", FL, (3000, 3752), "right", 100.0)
    assert out["tee"] == "T1" and out["stem"] == "T1.c" and out["second"] == "FL_1"
    tee = d["instances"]["T1"]
    assert tee["cell"] == joins.TEE_CELL and tee["place"] == {"at": [3000.0, 3750.0], "rot": 0.0}  # stem down
    assert out["stem_dir"] == (0.0, -1.0) and out["stem_pos"] == (3000.0, 3750.0 - joins.TEE_ARM)
    fl, fl1 = d["routes"]["FL"], d["routes"]["FL_1"]
    assert (fl["from"], fl["to"]) == ("PAD_W.a", "T1.b")  # the splitter's b faces west at rot 0
    assert (fl1["from"], fl1["to"]) == ("T1.a", "PAD_E.a") and fl1["airbridges"] == "none"
    assert list(d["routes"]).index("FL_1") == list(d["routes"]).index("FL") + 1
    assert d["routes"]["R9"]["to"]["hanger"] == "FL_1"  # the hanger at x 5000 is on the second half now
    assert d["sim_groups"]["G"]["select"] == ["FL", "C1", "FL_1"]


def test_merge_on_the_left_points_the_stem_up_and_keeps_nodes_on_their_half():
    d = feedline_design()
    d["routes"]["FL"]["nodes"] = [[2000, 3750], [5000, 3750]]
    out = joins.merge(d, "FL", FL, (3000, 3700), "left", 100.0)
    assert d["instances"][out["tee"]]["place"]["rot"] == 180.0 and out["stem_dir"] == pytest.approx((0.0, 1.0))
    assert d["routes"]["FL"]["to"] == "T1.a"  # at rot 180 the splitter's a faces west
    assert d["routes"]["FL"]["nodes"] == [[2000, 3750]] and d["routes"]["FL_1"]["nodes"] == [[5000, 3750]]


def test_merge_refuses_a_meander_and_a_point_too_close_to_the_end():
    d = feedline_design()
    with pytest.raises(ValueError, match="needs"):
        joins.merge(d, "FL", FL, (1300, 3750), "right", 100.0)
    with pytest.raises(ValueError, match="meander"):
        joins.merge(d, "R9", FL, (3000, 3750), "right", 100.0)


def test_unmerge_restores_the_line_and_merge_to_hanger_hangs_the_stem_route():
    d = feedline_design()
    before = copy.deepcopy(d)
    out = joins.merge(d, "FL", FL, (3000, 3752), "right", 100.0)
    design_io.add_route(d, "R1", "C1.b", out["stem"], "cpw", None, [[3000, 3500]])
    assert joins.tee_of(d, "R1") == "T1"
    line = joins.merge_to_hanger(d, "R1", lambda name: FL)
    assert line == "FL" and "T1" not in d["instances"] and "FL_1" not in d["routes"]
    assert d["routes"]["FL"]["to"] == "PAD_E.a" and d["routes"]["R9"]["to"]["hanger"] == "FL"
    assert d["routes"]["R1"]["to"] == {"hanger": "FL", "near": [3000.0, 3750.0], "length": 300.0, "side": "right",
                                       "end": "short", "ground_gap": 6.0}
    assert d["sim_groups"] == before["sim_groups"]
    d["routes"].pop("R1")
    assert d == before


def test_hanger_to_merge_converts_a_hanger_end():
    d = feedline_design()
    tee = joins.hanger_to_merge(d, "R9", lambda name: FL, 100.0)
    assert d["routes"]["R9"]["to"] == f"{tee}.c"
    assert d["instances"][tee]["place"]["at"] == [5000.0, 3750.0] and d["instances"][tee]["place"]["rot"] == 0.0


def test_targets_follow_the_component_class():
    assert set(design_io.target_keys("instance", "DoublePads", None, "qubit")) == {"f_q_GHz", "alpha_MHz"}
    assert design_io.target_keys("instance", "TrilayerSquid", None, "junction") == {}  # a squid cell is no qubit
    assert set(design_io.target_keys("instance", "CpwResonator", None, "resonator")) == {"f_GHz", "kappa_MHz"}
    assert set(design_io.target_keys("instance", "Xmon")) == {"f_q_GHz", "alpha_MHz"}  # no class known: the name


def test_materialize_nodes_keeps_the_router_corners_and_existing_nodes():
    d = feedline_design()
    built = {"polyline": [[3010, 2200], [3110, 2200], [3275, 2200], [3275, 2400], [2975, 2400], [2975, 3622],
                          [2975, 3722], [3275, 3722]], "fixed_segments": [1, 6, 7], "waypoint_index": []}
    design_io.add_route(d, "R1", "Q.right", design_io.hanger_end("FL", (3125, 3750), 300, "right"), "meander", 4200)
    assert design_io.materialize_nodes(d, "R1", built) == [2, 3, 4]
    assert d["routes"]["R1"]["nodes"] == [[3275.0, 2200.0], [3275.0, 2400.0], [2975.0, 2400.0]]
    # an existing node (with its extras) stays itself
    d["routes"]["R1"]["nodes"] = [{"at": [3275.0, 2400.0], "r": 50}]
    built["waypoint_index"], built["waypoints"], built["waypoint_r"] = [3], [[3275, 2400]], [50]
    ed = design_io.editable_route(built)  # what Route handles shows: every corner a node, the own r kept
    assert ed["waypoint_index"] == [2, 3, 4] and ed["waypoint_r"] == [None, 50, None]
    assert design_io.materialize_nodes(d, "R1", ed) == [2, 3, 4]
    assert d["routes"]["R1"]["nodes"][1] == {"at": [3275.0, 2400.0], "r": 50}
    # design.json changed since the build (a node count that does not match): left alone
    d["routes"]["R1"]["nodes"] = [[1, 1], [2, 2], [3, 3], [4, 4]]
    assert design_io.materialize_nodes(d, "R1", ed) is None and len(d["routes"]["R1"]["nodes"]) == 4


def test_set_substrate_writes_only_what_differs_from_the_pdk():
    from qcc_kplugin import design_ops

    base = {"h": 650.0, "eps_r": 10.25, "tan_d": 1e-6}
    d = design_io.new_design("s")
    assert design_ops.set_substrate(d, base, 500, 11.45, 1e-6)
    assert d["pdk"] == "quantcore_nb_sapphire_v1+substrate(h=500,eps_r=11.45)"
    assert design_ops.set_substrate(d, base, 500, 11.45, 1e-6) is None  # unchanged
    assert design_ops.set_substrate(d, base, 650, 10.25, 1e-6).endswith("(the PDK's)")
    assert d["pdk"] == "quantcore_nb_sapphire_v1"
    with pytest.raises(ValueError):
        design_ops.set_substrate(d, base, 0, 10.25, 1e-6)


def test_the_pdk_name_with_a_substrate_is_that_pdk_with_its_substrate_replaced():
    from quantcore_circuits.pdk import get_pdk, substrate_name

    name = substrate_name("quantcore_nb_sapphire_v1", h=500, eps_r=11.45, tan_d=2e-6)
    assert name == "quantcore_nb_sapphire_v1+substrate(h=500,eps_r=11.45,tan_d=2e-06)"
    p, base = get_pdk(name), get_pdk("quantcore_nb_sapphire_v1")
    assert (p.stack.substrate_height, p.stack.substrate_permittivity, p.stack.substrate_loss_tangent) == (
        500.0, 11.45, 2e-6)
    assert p.fab_layers == base.fab_layers and p.cpw_a == base.cpw_a
    assert substrate_name("quantcore_nb_sapphire_v1", 650, 10.25, 1e-6) == "quantcore_nb_sapphire_v1"
    with pytest.raises(ValueError, match="unknown substrate key"):
        get_pdk("quantcore_nb_sapphire_v1+substrate(t=3)")

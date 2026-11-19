"""The custom-component examples A (``examples/custom_component/``): the fork transmon, the spiralmon and the freeform
helper they use. Geometry builds, pins and directions, the trilayer junction on its layers, the LOM fragments."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya

os.environ.setdefault("QCC_LIVE", "0")
EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "custom_component"
sys.path.insert(0, str(EXAMPLES))

import custom_qubit  # noqa: E402
import freeform  # noqa: E402
import spiralmon  # noqa: E402

from quantcore_circuits.layouts.registry import create_cell, element_cell_ports, trilayer_junction  # noqa: E402
from quantcore_circuits.pdk import get_pdk  # noqa: E402

GAP, STRAIGHT, BENT = "1t1_base_metal_gap_wo_grid", "1t1_SIS_junction", "1t1_SIS_junction_2"


_LAYOUTS = []  # a cell is destroyed with its layout: keep them alive for the test session


def region(cell: pya.Cell, layer: str) -> pya.Region:
    layout = cell.layout()
    return pya.Region(cell.begin_shapes_rec(layout.layer(default_layers[layer])))


def build(cls, **params):
    layout = pya.Layout()
    _LAYOUTS.append(layout)
    cell = create_cell(layout, cls, **params)
    return cell, element_cell_ports(cls, cell, params)


def fake_inst(cell_ref: str, params: dict, junction: dict | None):
    j = SimpleNamespace(Lj_nH=junction["Lj_nH"], Cj_fF=junction["Cj_fF"], flux_phi0=0.0, asym=0.0) if junction else None
    return SimpleNamespace(cell=cell_ref, params=params, junction=j)


# ---- the fork transmon -------------------------------------------------------------------------------------------
def test_fork_builds_with_pins_and_junction():
    cell, ports = build(custom_qubit.ForkTransmon)
    assert {"claw", "drive"} <= set(ports)
    assert ports["claw"].angle == pytest.approx(0.0) and ports["drive"].angle == pytest.approx(180.0)
    assert ports["claw"].pos.x > 0 > ports["drive"].pos.x
    assert not region(cell, GAP).is_empty()
    # the trilayer junction: both fingers on their layers, centred on the gap between the islands
    for layer in (STRAIGHT, BENT):
        reg = region(cell, layer)
        assert not reg.is_empty(), layer
        assert abs(reg.bbox().center().x) < 20_000 and abs(reg.bbox().center().y) < 20_000  # dbu (20 µm)


def test_fork_without_junction_draws_none():
    for jtype in ("No Squid", "Sim"):
        cell, _ = build(custom_qubit.ForkTransmon, junction_type=jtype)
        assert region(cell, STRAIGHT).is_empty() and region(cell, BENT).is_empty()


def test_fork_islands_are_forked_and_rounded():
    sharp, _ = build(custom_qubit.ForkTransmon, corner_r=0, slot_w=0)
    forked, _ = build(custom_qubit.ForkTransmon, corner_r=15, slot_w=50)
    # a slot and rounded corners etch more away from the island than the plain rectangle does
    assert region(forked, GAP).area() != region(sharp, GAP).area()


def test_fork_rejects_unknown_parameter():
    with pytest.raises(ValueError):
        custom_qubit.ForkTransmon.qcc_params({"nonsense": 1})


def test_fork_lom_fragment():
    pdk = get_pdk()
    params, junction = trilayer_junction("custom_qubit.ForkTransmon")
    frag = custom_qubit.ForkTransmon.qcc_lom("Q1", fake_inst("custom_qubit.ForkTransmon", dict(params), junction), pdk)
    names = {e.name: e for e in frag.elements}
    assert set(names) == {"C_Q1_1", "C_Q1_2", "C_Q1_12", "Cg_Q1_claw", "Cc_Q1_claw", "J_Q1"}
    for key in ("C_Q1_1", "C_Q1_2"):
        assert 20 < names[key].value["estimate"] < 500  # fF
    assert 1 < names["C_Q1_12"].value["estimate"] < 50
    assert 0.5 < names["Cg_Q1_claw"].value["estimate"] < 50
    assert names["J_Q1"].type == "JJ" and names["J_Q1"].nodes == ("island1", "island2")
    assert names["J_Q1"].value["Lj_nH"] == pytest.approx(junction["Lj_nH"])  # the PDK junction rule's value
    assert frag.port_nodes["claw"] == "claw" and frag.port_nodes["drive"].startswith("control:")


def test_fork_bigger_island_has_more_capacitance():
    pdk = get_pdk()
    params, junction = trilayer_junction("custom_qubit.ForkTransmon")
    small = custom_qubit.ForkTransmon.qcc_lom(
        "Q1", fake_inst("custom_qubit.ForkTransmon", {**params, "body_w": 200}, junction), pdk
    )
    big = custom_qubit.ForkTransmon.qcc_lom(
        "Q1", fake_inst("custom_qubit.ForkTransmon", {**params, "body_w": 320}, junction), pdk
    )
    c = lambda f: next(e for e in f.elements if e.name == "C_Q1_1").value["estimate"]  # noqa: E731
    assert c(big) > c(small)


def test_fork_on_a_chip_with_lom():
    from quantcore_circuits.designer import Designer

    d = Designer("test_custom_fork", box=(0, 0, 7500, 7500), live=False)
    params, junction = trilayer_junction("custom_qubit.ForkTransmon", lj_nH=7.0)
    d.add("Q1", "custom_qubit.ForkTransmon", at=(3750, 3000), junction=junction, **params)
    model = d.lom().model
    assert {"J_Q1", "C_Q1_1", "C_Q1_2", "C_Q1_12"} <= set(model.branches)


# ---- the freeform helper ------------------------------------------------------------------------------------------
def test_read_polygons_round_trip(tmp_path):
    poly = pya.DPolygon([pya.DPoint(0, 0), pya.DPoint(40, 0), pya.DPoint(40, 20), pya.DPoint(0, 30)])
    path = freeform.polygons_to_oas({(10, 0): [poly]}, tmp_path / "x.oas")
    back = freeform.read_polygons(path, (10, 0))
    assert len(back) == 1 and back[0].area() == pytest.approx(poly.area())
    with pytest.raises(ValueError):
        freeform.read_polygons(path, (99, 0))


def test_pin_tail_keeps_ground_beside_the_gap():
    """A pin with a tail: the etch beside the tail is the CPW gap b, not the wide clearance."""
    body = pya.DPolygon(pya.DBox(-100, -100, 100, 100))
    tail = pya.DPolygon(pya.DBox(100, -5, 200, 5))  # a = 10 µm, leaves along +x
    cls = freeform.component_from_polygons(
        "TestShape",
        [body, tail],
        [freeform.Pin("p", 200, 0, 0, 10, 6, tail=60)],
        module="test_custom_components_a",
        clearance=40,
    )
    cell, ports = build(cls)
    gap = region(cell, GAP)
    assert ports["p"].angle == pytest.approx(0.0)
    inside_gap = pya.Region(pya.DBox(150, 6, 190, 10).to_itype(0.001))  # 1 µm into b = 6 µm... rows 5..11 are the gap
    ground_beside = pya.Region(pya.DBox(150, 12, 190, 30).to_itype(0.001))  # beyond a/2 + b = 11 µm: ground again
    assert (gap & inside_gap).area() > 0
    assert (gap & ground_beside).is_empty()
    # nothing etched in front of the pin (the route draws its own gaps)
    assert (gap & pya.Region(pya.DBox(201, -40, 240, 40).to_itype(0.001))).is_empty()


def test_component_from_polygons_rejects_unknown_default():
    with pytest.raises(ValueError):
        freeform.component_from_polygons("Bad", [pya.DPolygon(pya.DBox(0, 0, 10, 10))], bogus=1)


# ---- the spiralmon -----------------------------------------------------------------------------------------------
def test_spiral_shape_geometry():
    s = spiralmon.spiral_shapes()
    assert len(s["island"]) == 3 and len(s["claw"]) == 2 and len(s["pins"]) == 1
    pin = s["pins"][0]
    assert pin.name == "claw" and pin.tail > 0
    # the junction line starts at the island's tip and leaves along the tail by exactly the clearance
    (xa, ya), (xb, yb) = s["junction"]
    assert math.dist((xa, ya), (xb, yb)) == pytest.approx(s["params"]["clearance"])
    assert s["geometry"]["wire_length_um"] > 500
    with pytest.raises(ValueError):
        spiralmon.spiral_params(nonsense=1)


def test_spiralmon_builds_with_pin_and_junction():
    cell, ports = build(spiralmon.Spiralmon)
    s = spiralmon.spiral_shapes()
    pin = s["pins"][0]
    assert "claw" in ports
    assert ports["claw"].pos.x == pytest.approx(pin.x, abs=1e-3) and ports["claw"].pos.y == pytest.approx(
        pin.y, abs=1e-3
    )
    assert abs((ports["claw"].angle - pin.angle + 180) % 360 - 180) < 0.01  # degrees
    assert not region(cell, STRAIGHT).is_empty() and not region(cell, BENT).is_empty()
    # the junction sits at the end of the tail, not at the origin
    jc = region(cell, STRAIGHT).bbox().center()
    tip = s["junction"][0]
    assert math.dist((jc.x * 0.001, jc.y * 0.001), tip) < 30


def test_drawn_spiralmon_equals_the_parametric_one():
    layout = pya.Layout()
    _LAYOUTS.append(layout)
    a = create_cell(layout, spiralmon.Spiralmon)
    b = create_cell(layout, spiralmon.DrawnSpiralmon)
    for layer in (GAP, STRAIGHT, BENT):
        diff = (region(a, layer).merged() ^ region(b, layer).merged()).sized(-2)  # ignore slivers up to 2 dbu
        assert diff.is_empty(), layer


def test_spiralmon_lom_fragment():
    pdk = get_pdk()
    params, junction = trilayer_junction("spiralmon.Spiralmon")
    frag = spiralmon.Spiralmon.qcc_lom("S1", fake_inst("spiralmon.Spiralmon", dict(params), junction), pdk)
    names = {e.name: e for e in frag.elements}
    assert set(names) == {"C_S1", "Cg_S1_claw", "Cc_S1_claw", "J_S1"}
    assert 10 < names["C_S1"].value["estimate"] < 300  # fF
    assert 0.5 < names["Cg_S1_claw"].value["estimate"] < 60
    assert names["J_S1"].nodes == ("island", "gnd") and names["J_S1"].value["Lj_nH"] == pytest.approx(junction["Lj_nH"])
    assert frag.port_nodes["claw"] == "claw"
    # more turns: a larger spiral outline, more capacitance to ground
    more = spiralmon.Spiralmon.qcc_lom("S1", fake_inst("spiralmon.Spiralmon", {**params, "turns": 3.0}, junction), pdk)
    assert next(e for e in more.elements if e.name == "C_S1").value["estimate"] > names["C_S1"].value["estimate"]


def test_spiralmon_routes_from_its_oblique_pin_and_lom_runs():
    from quantcore_circuits.designer import Designer

    d = Designer("test_custom_spiralmon", box=(0, 0, 7500, 7500), live=False)
    pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270, edge="auto")
    pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90, edge="auto")
    fl = d.route("FL", pw.a, pe.a)
    params, junction = trilayer_junction("spiralmon.Spiralmon", lj_nH=7.0)
    q = d.add("S1", "spiralmon.Spiralmon", at=(3300, 2200), junction=junction, **params)
    d.route("R1", q.claw, fl.hanger(near=(4400, 3750), length=300, side="right"), meander=4500, r=50)
    model = d.lom().model
    assert {"J_S1", "C_S1", "Cg_S1_claw", "R1", "K_R1"} <= set(model.branches)

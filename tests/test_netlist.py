"""M3 netlist check: declared design connectivity vs. KQC geometric netlist."""

import pytest

from quantcore_circuits.assembly.netlist import check_netlist, extracted_connections


def test_example_netlist_diff_is_empty(example_path):
    import quantcore_circuits as qcc

    report = check_netlist(qcc.build(example_path))
    assert report.ok, [str(i) for i in report.issues]
    assert frozenset({"PAD_W.a", "PAD_E.a"}) in report.extracted
    assert frozenset({"Q1.claw_n"}) in report.extracted  # hanger end: capacitive, galvanically open


def _net(*pins):
    return [{"subcircuit_id": s, "pin": p} for s, p in pins]


def test_wires_join_named_pins_and_detect_short():
    subs = {"1": {"instance_name": "A"}, "2": {"instance_name": "B"}, "3": {"instance_name": "C"}, "9": {}}
    nets = {
        "n1": _net((1, "a"), (9, "a")),  # A.a - wire
        "n2": _net((9, "b"), (2, "a")),  # wire - B.a
        "n3": _net((2, "a"), (3, "x")),  # B.a touches C.x  -> short if undeclared
    }
    groups = extracted_connections({"nets": nets, "subcircuits": subs}, {"A", "B", "C"})
    assert groups == {frozenset({"A.a", "B.a", "C.x"})}


def test_report_lists_open_and_short(example_path, monkeypatch):
    import quantcore_circuits as qcc
    from quantcore_circuits.assembly import netlist

    result = qcc.build(example_path)
    fake = {frozenset({"PAD_W.a"}), frozenset({"PAD_E.a", "Q1.flux", "PAD_F.a"}), frozenset({"Q1.claw_n"})}
    monkeypatch.setattr(netlist, "extract_netlist", lambda cell: {})
    monkeypatch.setattr(netlist, "extracted_connections", lambda nl, names: fake)
    report = netlist.check_netlist(result)
    kinds = {(i.kind, i.ports) for i in report.issues}
    assert ("open", ("PAD_E.a", "PAD_W.a")) in kinds
    assert ("short", ("PAD_E.a", "PAD_F.a", "Q1.flux")) in kinds
    assert all(len(i.where) == len(i.ports) for i in report.issues)


def test_design_without_routes_has_an_empty_netlist():
    """KQC writes no netlist file when nothing connects; the DRC must not fail on it (lom request, 2026-11-03)."""
    from quantcore_circuits.designer import Designer

    d = Designer("no_routes", box=(0, 0, 7500, 7500), verbose=False)
    d.add("X", "BondPad", at=(3000, 3000))
    d.show()
    report = d.drc()
    assert not report.errors
    assert any(i.rule == "dangling_port" for i in report.warnings)


def test_wire_coupling_satisfies_netlist_and_dangling_checks(example_path, tmp_path):
    """A ``wire`` joins overlapping metal whose port texts do not coincide: no ``open``, no ``dangling_port``."""
    import shutil

    from quantcore_circuits.assembly.netlist import check_netlist
    from quantcore_circuits.designer import Designer

    copy = shutil.copy(example_path, tmp_path / "design.json")  # Designer.load + show() saves back to its source
    d = Designer.load(copy, verbose=False)
    d.add("P2", "BondPad", at=(6000, 6000))  # a pad far from anything: its port is dangling...
    d.show()
    assert any(i.rule == "dangling_port" and "P2.a" in i.message for i in d.drc().warnings)
    d.couple("W", "P2.a", "PAD_E.a", wire=True)  # ...until a wire claims it overlaps PAD_E (the check trusts it)
    result = d.show()
    report = check_netlist(result)
    assert not [i for i in report.issues if set(i.ports) & {"P2.a", "PAD_E.a"} and i.kind == "open"], report.issues
    assert not any(i.rule == "dangling_port" and "P2.a" in i.message for i in d.drc().warnings)


def test_open_conductor_rule_sees_etch_between_route_and_port(example_path):
    """``open_conductor``: port texts touch, but etch across the centre conductor at the port opens the route."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly import build
    from quantcore_circuits.assembly.drc import _conductor_opens, check

    result = build(example_path)
    assert _conductor_opens(result) == []
    assert not [i for i in check(result, netlist=False).issues if i.rule == "open_conductor"]
    p = result.plan.all_ports()["PAD_W.a"]  # feedline FL starts here
    across = pya.DVector(-p.dir.y, p.dir.x) * 20
    cut = pya.DPath([p.pos - across, p.pos + across], 1.0).polygon()  # a 1 µm etch line across the port
    result.cell.shapes(result.layout.layer(pya.LayerInfo(130, 1))).insert(cut)
    issues = _conductor_opens(result)
    assert [(i.rule, i.severity, i.objects) for i in issues] == [("open_conductor", "error", ["PAD_W.a", "FL"])]


def test_crossing_rule_respects_chip_faces():
    """Flip chip (kqc/demo_twoface): probe lines switch to face 2b1 at a waypoint and pass over the buses on 1t1."""
    import copy
    import json
    from pathlib import Path

    from quantcore_circuits.assembly.drc import check
    from quantcore_circuits.design import Design

    path = Path(__file__).resolve().parents[1] / "examples" / "designs" / "kqc" / "demo_twoface.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert not [i for i in check(Design.model_validate(data), netlist=False).issues if i.rule == "crossing"]
    flat = copy.deepcopy(data)  # same layout with every waypoint on the bottom face: the four crossings are real
    for route in flat["routes"].values():
        for node in route.get("nodes") or []:
            if isinstance(node, dict):
                (node.get("params") or {}).pop("face_id", None)
    crossings = [i for i in check(Design.model_validate(flat), netlist=False).issues if i.rule == "crossing"]
    assert len(crossings) == 4


def test_built_route_overlap_is_an_error():
    """Two routes whose built conductors overlap: ``route_overlap`` (built geometry) as well as ``crossing``."""
    from quantcore_circuits.designer import Designer

    d = Designer("overlap", box=(0, 0, 7500, 7500), verbose=False)
    a1, a2 = d.add("A1", "BondPad", at=(1125, 3750), rot=270), d.add("A2", "BondPad", at=(6375, 3750), rot=90)
    b1, b2 = d.add("B1", "BondPad", at=(3750, 1125), rot=0), d.add("B2", "BondPad", at=(3750, 6375), rot=180)
    d.route("RA", a1.a, a2.a)
    d.route("RB", b1.a, b2.a)
    rules = {i.rule for i in d.drc().errors} if d.show() else set()
    assert {"route_overlap", "crossing"} <= rules


@pytest.mark.parametrize(("spacing", "short"), [(40.0, True), (120.0, False)])
def test_airbridge_pads_on_a_neighbouring_line(spacing, short):
    """KQC auto airbridges on RA reach a parallel line RB 40 µm away (pads short it to ground), not at 120 µm."""
    from quantcore_circuits.designer import Designer

    d = Designer("abshort", box=(0, 0, 7500, 7500), verbose=False)
    a1, a2 = d.add("A1", "BondPad", at=(1125, 3750), rot=270), d.add("A2", "BondPad", at=(6375, 3750), rot=90)
    b1, b2 = d.add("B1", "BondPad", at=(1125, 2500), rot=270), d.add("B2", "BondPad", at=(6375, 2500), rot=90)
    d.route("RA", a1.a, a2.a, airbridges="auto", nodes=[(2000, 3750), (5500, 3750)])
    y = 3750 - spacing
    d.route("RB", b1.a, b2.a, nodes=[(1500, 2500), (1500, y), (6000, y), (6000, 2500)])
    d.show()
    assert ("airbridge_short" in {i.rule for i in d.drc().errors}) == short


def test_route_running_over_itself_is_an_error(example_path):
    """``route_self_overlap`` (2026-11-17): nodes that loop back across the route's own first straight. The
    pieces of a clean route (straights, arcs, meander turns, a taper and its straight: the example's R1 and FLUX)
    only meet edge to edge."""
    from quantcore_circuits.assembly.drc import check
    from quantcore_circuits.designer import Designer

    d = Designer("selfloop", box=(0, 0, 7500, 7500), verbose=False)
    a1, a2 = d.add("A1", "BondPad", at=(1125, 3750), rot=270), d.add("A2", "BondPad", at=(6375, 3750), rot=90)
    d.route("RA", a1.a, a2.a, nodes=[(3000, 3750), (3000, 4500), (2500, 4500), (2500, 3000), (5000, 3000),
                                      (5000, 3750)])
    d.show()
    hits = [i for i in d.drc().errors if i.rule == "route_self_overlap"]
    assert [i.objects for i in hits] == [["RA"]] and abs(hits[0].where[0][0] - 2500) < 20  # at the crossing
    assert not [i for i in check(example_path, netlist=False).issues if i.rule == "route_self_overlap"]


def test_route_over_a_component_is_an_error():
    """``route_over_component`` (2026-11-17): a feedline drawn straight through a qubit that is not one of its
    ends; the qubit's own readout route ending on it is fine."""
    from quantcore_circuits.designer import Designer

    d = Designer("overcomp", box=(0, 0, 7500, 7500), verbose=False)
    a1, a2 = d.add("A1", "BondPad", at=(1125, 3750), rot=270), d.add("A2", "BondPad", at=(6375, 3750), rot=90)
    d.add("Q1", "Xmon", at=(4500, 3750))
    d.route("FL", a1.a, a2.a)
    d.show()
    hits = [i for i in d.drc().errors if i.rule == "route_over_component"]
    assert [i.objects for i in hits] == [["FL", "Q1"]]

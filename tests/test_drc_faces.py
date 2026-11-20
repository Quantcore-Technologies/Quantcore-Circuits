"""DRC on multi-face designs: per-face ``overlap`` and ``open_conductor``, and the route face in the crossing rule.

A tiny TSV transition built in memory: a front pad (``1t1``) and a back pad (``1b1``) stacked at the same place, two
signal vias (``TsvEllipse`` on both faces) under them, a feed line on ``1t1`` and an underpass on ``1b1``.
"""

from __future__ import annotations

import copy

import pytest

PAD = {"path": [[-15.0, 0], [15.0, 0]], "a": 40.0, "b": 24.0}
VIA = {"face_ids": ["1t1", "1b1"], "tsv_diameter": 10.0, "tsv_elliptical_width": 20.0, "tsv_margin": 2.0}


def _inst(cell: str, at, rot: float = 0.0, **params) -> dict:
    return {"cell": cell, "params": params, "place": {"at": list(at), "rot": rot}}


def _transition(instances: dict, name: str, x: float, rot: float) -> None:
    """Front pad ``<name>_F`` (closed on its far end), back pad ``<name>_B`` (closed on its near end), two vias."""
    instances[f"{name}_F"] = _inst("WaveguideCoplanar", (x, 1500), rot, term2=24.0, face_ids=["1t1", "1b1"], **PAD)
    instances[f"{name}_B"] = _inst("WaveguideCoplanar", (x, 1500), rot, term1=24.0, face_ids=["1b1", "1t1"], **PAD)
    for k, dy in enumerate((-10.0, 10.0)):
        instances[f"{name}_SV{k}"] = _inst("TsvEllipse", (x, 1500 + dy), **VIA)


def _design_data() -> dict:
    instances = {"L": _inst("WaveguideCoplanar", (500, 1500), term1=24.0, **PAD)}  # a front-face start pad
    _transition(instances, "T1", 1000.0, 0.0)
    _transition(instances, "T2", 2000.0, 180.0)
    return {
        "schema": "qcc/0.1",
        "name": "drc_faces",
        "chip": {"box": [0, 0, 3000, 3000], "params": {"with_grid": False, "cheese": "original"}},
        "instances": instances,
        "routes": {
            "FEED": {"from": "L.b", "to": "T1_F.a", "a": 40.0, "b": 24.0, "airbridges": "none"},
            "UNDER": {"from": "T1_B.b", "to": "T2_B.b", "a": 40.0, "b": 24.0, "airbridges": "none",
                      "params": {"face_ids": ["1b1"]}},
        },
    }


def _build(data: dict):
    from quantcore_circuits.assembly import build
    from quantcore_circuits.design import Design

    return build(Design.model_validate(data))


@pytest.fixture(scope="module")
def stacked():
    return _build(_design_data())


def _rules(report, rule: str) -> list:
    return [i for i in report.issues if i.rule == rule]


def test_route_face_reads_face_ids_and_waypoints():
    """``face_ids[0]`` is the face a route is drawn on (a list, as KQC has it); a ``face_id`` waypoint switches it."""
    from quantcore_circuits.assembly.drc import _route_end_face, _route_face, _segment_faces
    from quantcore_circuits.design import Design

    data = _design_data()
    data["routes"]["UP"] = {"from": "L.b", "to": "T2_F.a", "params": {"face_ids": ["2b1", "1t1"]},
                            "nodes": [[800, 1500], {"at": [1200, 1500], "params": {"face_id": "1t1"}}]}
    data["routes"]["OLD"] = {"from": "L.b", "to": "T2_F.a", "params": {"face_id": "2b1"}}
    design = Design.model_validate(data)
    assert _route_face(design, "FEED") == "1t1"  # nothing of its own and no plan: the default face
    assert _route_face(design, "UNDER") == _route_end_face(design, "UNDER") == "1b1"
    assert (_route_face(design, "UP"), _route_end_face(design, "UP")) == ("2b1", "1t1")
    assert _route_face(design, "OLD") == "2b1"  # a route-level face_id still counts when there is no face_ids
    built = {"polyline": [(500, 1500), (800, 1500), (1200, 1500), (2000, 1500)], "waypoint_index": [1, 2]}
    assert _segment_faces(design, "UP", built) == ["2b1", "2b1", "1t1"]
    assert _segment_faces(design, "UNDER", {"polyline": [(0, 0), (1, 0), (2, 0)]}) == ["1b1", "1b1"]


def test_stacked_tsv_pads_are_clean(stacked):
    """Front and back pad stacked as QPDK draws them: no open at the back pad, no overlap of pads and vias."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.drc import _conductor_opens, check

    port = stacked.plan.port("T1_B.b")  # the front pad's closing gap (1t1) lies under the back pad's port
    front_gap = pya.Region(stacked.cell.begin_shapes_rec(stacked.layout.layer(pya.LayerInfo(130, 1))))
    assert front_gap.interacting(pya.Region(pya.DBox(port.pos + port.dir * 0.5, port.pos + port.dir * 1.5)
                                            .enlarged(0.2, 0.2).to_itype(stacked.layout.dbu)))
    assert _conductor_opens(stacked) == []
    report = check(stacked, netlist=False)
    assert not _rules(report, "overlap")
    assert not _rules(report, "open_conductor")


def test_open_on_the_back_face_is_found():
    """Etch across the back pad's port on 1b1 (layer 2/1): the underpass is open there."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.drc import _conductor_opens

    result = _build(_design_data())  # its own build: the cut changes the layout
    p = result.plan.port("T1_B.b")
    across = pya.DVector(-p.dir.y, p.dir.x) * 30
    cut = pya.DPath([p.pos - across, p.pos + across], 1.0).polygon()
    result.cell.shapes(result.layout.layer(pya.LayerInfo(2, 1))).insert(cut)
    issues = _conductor_opens(result)
    assert [(i.rule, i.objects) for i in issues] == [("open_conductor", ["T1_B.b", "UNDER"])]


def test_route_end_on_a_face_the_component_lacks_is_open():
    """A route on 1b1 that ends on front-only pads: both ends are open (there is no metal of the pad on 1b1)."""
    from quantcore_circuits.assembly.drc import _conductor_opens

    data = _design_data()
    data["routes"]["FEED"]["params"] = {"face_ids": ["1b1"]}
    issues = _conductor_opens(_build(data))
    assert sorted(i.objects[0] for i in issues) == ["L.b", "T1_F.a"]
    assert all(i.rule == "open_conductor" and "draws only on 1t1" in i.message for i in issues)


def test_overlap_still_found_on_one_face():
    """Two components on the same face, two vias on top of each other, and a via on a pad's gap still overlap."""
    from quantcore_circuits.assembly.drc import check

    data = _design_data()
    extra = copy.deepcopy(data["instances"]["T1_F"])
    data["instances"]["X"] = extra  # a second front pad on the first
    data["instances"]["V2"] = _inst("TsvEllipse", (2000, 1490), **VIA)  # on T2_SV0
    data["instances"]["V3"] = _inst("TsvEllipse", (1000, 1532), **VIA)  # in the pads' 24 µm gap (y 1520–1544)
    pairs = {tuple(i.objects): i.message for i in _rules(check(_build(data), netlist=False), "overlap")}
    # not (T1_B, X): the back pad is on another face; not the vias under the pads' metal
    assert set(pairs) == {("T1_F", "X"), ("T2_SV0", "V2"), ("T1_F", "V3"), ("T1_B", "V3"), ("V3", "X")}
    assert pairs[("T1_F", "X")] == "T1_F and X overlap"
    assert pairs[("T1_F", "V3")].endswith("lands on the etch (1t1)")
    assert pairs[("T1_B", "V3")].endswith("lands on the etch (1b1)")


def test_crossing_on_another_face_is_not_a_crossing():
    """A 1b1 route (``face_ids``) crossing a 1t1 route is not a crossing; the same route on 1t1 is."""
    from quantcore_circuits.assembly.drc import check

    data = _design_data()
    data["instances"]["S"] = _inst("WaveguideCoplanar", (1500, 1100), 90.0, term1=24.0, face_ids=["1b1"], **PAD)
    data["instances"]["N"] = _inst("WaveguideCoplanar", (1500, 1900), 90.0, term2=24.0, face_ids=["1b1"], **PAD)
    data["routes"]["V"] = {"from": "S.b", "to": "N.a", "a": 40.0, "b": 24.0, "airbridges": "none",
                           "params": {"face_ids": ["1b1"]}}
    data["routes"]["UNDER"]["params"] = {}  # the underpass on 1t1 now, crossing nothing else on 1t1
    data["routes"]["UNDER"]["from"], data["routes"]["UNDER"]["to"] = "T1_F.b", "T2_F.b"
    assert not _rules(check(_build(data), netlist=False), "crossing")
    for name in ("S", "N"):
        data["instances"][name]["params"]["face_ids"] = ["1t1"]
    data["routes"]["V"]["params"] = {}
    assert [i.objects for i in _rules(check(_build(data), netlist=False), "crossing")] == [["UNDER", "V"]]

"""DRC between two routes that end on one component at different ports (a bus and a readout on one qubit, two
resonators on one coupler): their built geometry is compared, meanders included, except around that component."""

from __future__ import annotations

PAD = {"path": [[-15.0, 0], [15.0, 0]]}


def _inst(at, rot: float = 0.0, **params) -> dict:
    return {"cell": "WaveguideCoplanar", "params": {**PAD, **params}, "place": {"at": list(at), "rot": rot}}


def _build(routes: dict, **instances):
    from quantcore_circuits.assembly import build
    from quantcore_circuits.design import Design

    return build(Design.model_validate({
        "schema": "qcc/0.1",
        "name": "drc_route_pairs",
        "chip": {"box": [0, 0, 4000, 4000], "params": {"with_grid": False, "cheese": "original"}},
        "instances": {"HUB": _inst((2000, 2000)), **instances},  # ports a (west) and b (east), 30 µm apart
        "routes": routes,
    }))


def _issues(result, *rules) -> list:
    from quantcore_circuits.assembly.drc import check

    return [(i.rule, i.objects) for i in check(result, netlist=False).issues if i.rule in rules]


def test_meander_across_a_route_on_the_same_component_is_an_overlap():
    """R1's meander (its node polyline runs straight along y = 2000) swings across R2, and both end on HUB."""
    result = _build(
        {
            "R1": {"from": "HUB.a", "to": "E1.b", "type": "meander", "length": 3000, "airbridges": "none"},
            "R2": {"from": "HUB.b", "to": "E2.a", "airbridges": "none",
                   "nodes": [[2300, 2000], [2300, 2250], [1400, 2250]]},
        },
        E1=_inst((1000, 2000), term1=6.0),
        E2=_inst((1400, 2600), 90.0, term2=6.0),
    )
    assert _issues(result, "crossing", "route_overlap") == [("route_overlap", ["R1", "R2"])]


def test_spacing_of_two_routes_on_one_component_is_checked():
    """R1 and R2 leave HUB on opposite sides and come back side by side 18 µm apart (gaps 6 µm, half width 11 µm):
    no ground between them (``route_clearance``), found away from HUB."""
    routes = {
        "R1": {"from": "HUB.a", "to": "E1.a", "airbridges": "none", "nodes": [[1700, 2000]]},
        "R2": {"from": "HUB.b", "to": "E2.a", "airbridges": "none",
               "nodes": [[2300, 2000], [2300, 2500], [1718, 2500]]},
    }
    near = _build(routes, E1=_inst((1700, 3200), 90.0, term2=6.0), E2=_inst((1718, 3200), 90.0, term2=6.0))
    assert _issues(near, "route_overlap", "route_clearance") == [("route_clearance", ["R1", "R2"])]
    routes["R2"]["nodes"][-1] = [1800, 2500]  # 100 µm apart: clean
    apart = _build(routes, E1=_inst((1700, 3200), 90.0, term2=6.0), E2=_inst((1800, 3200), 90.0, term2=6.0))
    assert _issues(apart, "route_overlap", "route_clearance") == []


def test_shared_keepout_is_the_component_box_grown_by_the_half_width():
    from quantcore_circuits.assembly.drc import _shared_keepout

    result = _build(
        {
            "R1": {"from": "HUB.a", "to": "E1.b", "airbridges": "none"},
            "R2": {"from": "HUB.b", "to": "E2.a", "airbridges": "none", "a": 20, "b": 10},
        },
        E1=_inst((1000, 2000), term1=6.0),
        E2=_inst((3000, 2000), term2=6.0),
    )
    keepout = _shared_keepout(result, {"R1": {"HUB", "E1"}, "R2": {"HUB", "E2"}, "R3": {"E3", "E2"}})
    assert keepout("R1", "R3") is None
    hub = next(i for i in result.cell.each_inst() if i.property("id") == "HUB").dbbox()
    box = keepout("R1", "R2").bbox().to_dtype(result.layout.dbu)
    assert abs(box.left - (hub.left - 20)) < 1e-6 and abs(box.top - (hub.top + 20)) < 1e-6  # R2: 20/2 + 10

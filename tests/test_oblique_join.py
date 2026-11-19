"""Route joins at angled ports: the route's gap strips merge with the cell's etch, so the fab corner rounding leaves
no metal sliver there (route.waveguide.joined_nodes). Axis-aligned joins are drawn exactly as before."""

import importlib.util
import math
import warnings

import pytest
from kqcircuits.defaults import default_faces
from kqcircuits.pya_resolver import pya

from quantcore_circuits.assembly import build
from quantcore_circuits.assembly.netlist import check_netlist
from quantcore_circuits.layouts.wafers.fab_export import etch_region, round_corners
from quantcore_circuits.pdk import get_pdk
from quantcore_circuits.route import waveguide

CHIP = 7500.0
AT = (2400.0, 1589.0)  # CT1 of a reported build/test.json: its coupler_2 join missed the cell's etch by < 1 nm


def _design(cell: str, pin: str, port_at, port_dir, ab=None, name: str = "OJ") -> dict:
    """``cell`` at :data:`AT`, ``pin`` routed to a bond pad 1500 µm out along the nearest axis (and 400 µm aside, so
    an angled pin gets one oblique straight). Whether a join misses depends on the grid snapping at that place."""
    t = pya.DCplxTrans(1, 0, False, *AT)
    pos, d = t * pya.DPoint(*port_at), t * pya.DVector(*port_dir)
    axes = [pya.DVector(1, 0), pya.DVector(0, 1), pya.DVector(-1, 0), pya.DVector(0, -1)]
    ax = max(axes, key=lambda v: v.sprod(d))
    side = pya.DVector(-ax.y, ax.x)
    lat = math.copysign(400.0, d.sprod(side)) if abs(d.sprod(side)) > 0.2 else 0.0
    pad = pos + ax * 1500.0 + side * lat
    route = {"from": f"Q.{pin}", "to": "PAD.a", "type": "cpw"}
    if ab:
        route["a"], route["b"] = ab
    return {
        "schema": "qcc/0.1", "name": "oblique_join", "pdk": "quantcore_nb_sapphire_v1",
        "chip": {"box": [0.0, 0.0, CHIP, CHIP], "params": {"name_chip": name}},
        "instances": {
            "Q": {"cell": cell, "place": {"at": list(AT), "rot": 0.0}},
            "PAD": {"cell": "BondPad", "place": {"at": [pad.x, pad.y],
                                                 "rot": (math.degrees(math.atan2(-ax.y, -ax.x)) - 90.0) % 360}},
        },
        "routes": {"R": route},
    }


def _strips(pos, d, a, b, s0, s1, dbu) -> pya.Region:
    n = pya.DVector(-d.y, d.x)
    reg = pya.Region()
    for w0, w1 in ((a / 2, a / 2 + b), (-a / 2 - b, -a / 2)):
        corners = [pos + d * s + n * w for s, w in ((s0, w0), (s1, w0), (s1, w1), (s0, w1))]
        reg.insert(pya.DPolygon(corners).to_itype(dbu))
    return reg


def _join(design: dict):
    """(build, port, route a, route b, raw 1/0, fab-rounded 1/0) of a design's route R at Q."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = build(design)
    pdk = get_pdk(res.design.pdk)
    port = res.plan.port(design["routes"]["R"]["from"])
    params = res.plan.routes["R"].params
    raw = etch_region(res.cell, pdk.face, grid=False).merged()
    win = pya.Region(pya.DBox(port.pos.x - 80, port.pos.y - 80, port.pos.x + 80, port.pos.y + 80).to_itype(
        res.layout.dbu))
    fab = round_corners(raw & win, pdk.rounding, res.layout.dbu)  # the fab export's M1 rounding
    return res, port, float(params["a"]), float(params["b"]), raw, fab


def _slivers(etch: pya.Region, port, a: float, b: float, dbu: float) -> float:
    """µm² of metal narrower than 2.5 µm (and wider than 10 nm grid noise) in the route's gap strips ±2 µm about
    the port."""
    big = pya.Region(pya.DBox(port.pos.x - 60, port.pos.y - 60, port.pos.x + 60, port.pos.y + 60).to_itype(dbu))
    metal = (big - etch).merged()
    h = round(1.25 / dbu)
    thin = ((metal - metal.sized(-h).sized(h)) & _strips(port.pos, port.dir, a, b, -2, 2, dbu)).merged()
    return sum(p.area() for p in thin.each() if not pya.Region(p).sized(-5).is_empty()) * dbu * dbu


def _route_merges(res, port) -> bool:
    """The route's etch at the port overlaps or touches the cell's (no strip left apart by a hairline)."""
    dbu = res.layout.dbu
    li = res.layout.layer(default_faces["1t1"]["base_metal_gap_wo_grid"])
    insts = {i.property("id"): i for i in res.cell.each_inst()}
    box = pya.DBox(port.pos.x - 15, port.pos.y - 15, port.pos.x + 15, port.pos.y + 15).to_itype(dbu)
    cell = waveguide.etch_near(insts["Q"].cell, insts["Q"].cplx_trans, li, box)
    route = waveguide.etch_near(insts["R"].cell, insts["R"].cplx_trans, li, box)
    return not waveguide.misses_etch(cell, route, port.dir, dbu)


@pytest.mark.parametrize(
    "pin, at, direction, ab",
    [
        ("coupler_1", (310.099, -112.867), (math.cos(math.radians(340)), math.sin(math.radians(340))), None),
        ("coupler_2", (165.0, 285.788), (0.5, math.sqrt(3) / 2), (10, 6)),  # the reported test.json join
    ],
)
def test_concentric_transmon_oblique_join_has_no_sliver(pin, at, direction, ab):
    res, port, a, b, _, fab = _join(_design("ConcentricTransmon", pin, at, direction, ab=ab))
    assert abs(port.dir.x) > 0.1 and abs(port.dir.y) > 0.1  # an angled port
    assert _route_merges(res, port)
    assert _slivers(fab, port, a, b, res.layout.dbu) == 0.0
    assert res.refpoints["R_port_a"].distance(port.pos) < 1e-3  # the route's port stays on the cell's
    assert check_netlist(res).ok, check_netlist(res).issues  # the moved end's port text is bridged: no false open


@pytest.mark.skipif(importlib.util.find_spec("qiskit_metal") is None, reason="qiskit_metal not installed")
def test_star_qubit_oblique_join_has_no_sliver():
    res, port, a, b, _, fab = _join(_design("metal:StarQubit", "pin_rdout", (220.419, 303.381),
                                            (math.cos(math.radians(54)), math.sin(math.radians(54)))))
    assert abs(port.dir.x) > 0.1 and abs(port.dir.y) > 0.1
    assert _route_merges(res, port)
    assert _slivers(fab, port, a, b, res.layout.dbu) == 0.0


def test_join_fix_leaves_axis_joins_alone_and_closes_oblique_ones(monkeypatch):
    designs = {
        "axis": ("DoublePads", "cplr", (0.0, 350.0), (0, 1), None),
        "oblique": ("ConcentricTransmon", "coupler_2", (165.0, 285.788), (0.5, math.sqrt(3) / 2), (10, 6)),
    }
    fixed = {k: _join(_design(*d)) for k, d in designs.items()}
    monkeypatch.setattr(waveguide, "joined_nodes", lambda *args, **kwargs: None)
    # another chip name: KLayout would hand back the cached chip variant built with the fix
    plain = {k: _join(_design(*d, name="OJ0")) for k, d in designs.items()}
    res, port = fixed["axis"][0], fixed["axis"][1]
    assert port.dir.x == 0  # faces +y
    near = pya.Region(pya.DBox(port.pos.x - 100, port.pos.y - 100, port.pos.x + 100, port.pos.y + 100).to_itype(
        res.layout.dbu))
    assert ((fixed["axis"][4] ^ plain["axis"][4]) & near).is_empty()  # axis-aligned join: the same geometry
    assert not _route_merges(plain["oblique"][0], plain["oblique"][1])  # without the fix: a hairline ...
    res, port, a, b, _, fab = plain["oblique"]
    assert _slivers(fab, port, a, b, res.layout.dbu) > 0.1  # ... that the rounding opens into slivers

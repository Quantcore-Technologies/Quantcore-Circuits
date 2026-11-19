"""Catalog decisions of 2026-11-15 (docs/components/DUPLICATES.md): metal:MyQComponent is not offered, legacy cells
are marked but stay listed and placeable, alias groups share an equivalent circuit (same LOM for the same
dimensions), and CapacitiveXCoupler / WaveguideCoplanarCurved have ports (registry.KQC_EXTRA_PORTS) and a model."""

from __future__ import annotations

import importlib.util
import json
import math
from collections import defaultdict
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from quantcore_circuits.cli import app
from quantcore_circuits.layouts.catalog import ALIASES, EXCLUDED, LEGACY, alias_group, catalog, find, listing
from quantcore_circuits.layouts.registry import list_components, resolve_cell

HAS_METAL = importlib.util.find_spec("qiskit_metal") is not None


def _metal(ref: str) -> None:
    if ref.startswith("metal:") and not HAS_METAL:
        pytest.skip("qiskit_metal not installed")


# ---- removed --------------------------------------------------------------------------------------------------------
def test_myqcomponent_is_not_offered():
    """Design decision: metal:MyQComponent (= metal:Rectangle, Metal's user template) is not listed anywhere."""
    assert "metal:MyQComponent" in EXCLUDED
    refs = {c.ref for c in catalog(routes=True)}
    assert "metal:MyQComponent" not in refs and "metal:Rectangle" in refs
    assert find("metal:MyQComponent") is None and find("MyQComponent") is None
    assert "metal:MyQComponent" not in list_components()
    runner = CliRunner()
    for args in (["components", "--json"], ["components", "--json", "--all", "--source", "metal"]):
        res = runner.invoke(app, args)
        assert res.exit_code == 0, res.output
        assert "metal:MyQComponent" not in json.loads(res.output)
    res = runner.invoke(app, ["components", "--source", "metal"])
    assert res.exit_code == 0 and "MyQComponent" not in res.output


def test_myqcomponent_still_resolves_by_ref():
    _metal("metal:")
    assert resolve_cell("metal:MyQComponent").__name__  # Metal provides it; only the catalog does not offer it


# ---- legacy ---------------------------------------------------------------------------------------------------------
USER_LEGACY = {
    "SpiralPath", "SquidV0", "StripesTest", "ManhattanSingleJunction", "metal:SQUID_LOOP", "metal:BridgeFreeJunction",
    "DoublePadsSplines", "metal:NSquareSpiral", "metal:Airbridge", "CapacitiveXCoupler", "WaveguideCoplanarCurved",
}  # fmt: skip


def test_legacy_markers():
    assert set(LEGACY) == USER_LEGACY
    entries = {c.ref: c for c in catalog()}
    for ref in USER_LEGACY:
        assert ref in entries, f"legacy {ref} must stay in the catalog"
        assert entries[ref].legacy == LEGACY[ref] and entries[ref].tag().startswith("(legacy")
    assert not [c.ref for c in entries.values() if c.legacy and c.ref not in LEGACY]
    assert entries["Xmon"].legacy == "" and entries["Xmon"].tag() == ""
    lines = listing(list(entries.values()))
    assert any(ln.lstrip().startswith("SquidV0 ") and "(legacy)" in ln for ln in lines)
    assert not any(ln.lstrip().startswith("Xmon ") and "(legacy" in ln for ln in lines)
    records = json.loads(CliRunner().invoke(app, ["components", "--json", "--details"]).output)
    by_ref = {r["ref"]: r for r in records}
    assert by_ref["SquidV0"]["legacy"] == LEGACY["SquidV0"] and by_ref["Xmon"]["legacy"] == ""
    assert {"legacy", "alias_of", "aliases"} <= set(by_ref["Xmon"])


def _plan(ref: str):
    from quantcore_circuits.assembly import plan_design
    from quantcore_circuits.design import load_design

    probe = {"schema": "qcc/0.1", "name": "legacy_probe", "instances": {"X": {"cell": ref, "place": {"at": [0, 0]}}}}
    return plan_design(load_design(probe)).instances["X"]


@pytest.mark.parametrize("ref", sorted(USER_LEGACY))
def test_legacy_cells_resolve_and_place(ref):
    """Legacy cells stay usable: they resolve by name and plan like any design instance."""
    _metal(ref)
    assert resolve_cell(ref) is not None and find(ref).ref == ref
    placed = _plan(ref)
    assert placed is not None


# ---- aliases --------------------------------------------------------------------------------------------------------
USER_PAIRS = [
    ("CpweOpenEnd", "metal:OpenToGround"),
    ("metal:LineTee", "WaveguideCoplanarSplitter"),
    ("metal:LaunchpadWirebondDriven", "metal:LaunchpadWirebond"),
    ("CpweTaper", "WaveguideCoplanarTaper"),
]


def test_alias_table_is_consistent():
    members = [m for ms in ALIASES.values() for m in ms]
    assert len(members) == len(set(members)) and not set(members) & set(ALIASES)  # disjoint groups
    entries = {c.ref: c for c in catalog()}
    for canonical, ms in ALIASES.items():
        assert canonical in entries and entries[canonical].alias_of == ""
        assert set(entries[canonical].aliases) == set(ms)
        for m in ms:
            assert m in entries and entries[m].alias_of == canonical, m
            assert set(entries[m].aliases) == {canonical, *ms} - {m}
            assert f"alias of {canonical}" in entries[m].tag()
    for x, y in USER_PAIRS:
        assert y in alias_group(x) and x in alias_group(y), (x, y)
    assert entries["Xmon"].alias_of == "" and entries["Xmon"].aliases == []


def _fragment(ref: str, params: dict):
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    fn = lom_model(ref)
    return None if fn is None else fn("X", SimpleNamespace(cell=ref, params=params, junction=None), get_pdk())


def _num(v) -> float:
    return float(f"{float(v):.6g}")


def _circuit(frag, port_map: dict[str, str]):
    """A fragment as a circuit in the canonical's port names: port → node class, elements, lines (names and knobs,
    which carry each cell's own parameter names, are left out)."""
    if frag is None:
        return None
    on: dict[str, set] = defaultdict(set)
    for port, node in frag.port_nodes.items():
        on[node].add(port_map.get(port, port))

    def cls(node):
        if node == "gnd" or str(node).startswith("control:"):
            return node
        return "+".join(sorted(on[node])) if on.get(node) else "internal"

    def values(e):
        nums = {k: v for k, v in e.value.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        return tuple(sorted((k, _num(v)) for k, v in nums.items()))

    ports = {port_map.get(p, p): cls(n) for p, n in frag.port_nodes.items()}
    elements = sorted((e.type, tuple(sorted(cls(n) for n in e.nodes)), values(e)) for e in frag.elements)
    lines = sorted(
        (cls(ln.node), tuple(sorted((port_map.get(p, p) if p else "", t) for p, t in zip(ln.ports, ln.term))),
         _num(ln.length_um), _num(ln.a_um), _num(ln.b_um), ln.resonator, ln.through)
        for ln in frag.lines
    )  # fmt: skip
    return ports, elements, lines, len(frag.hangers), sorted(cls(n) for n in frag.straps)


# alias member → (its params, the canonical's params for the same dimensions, member port → canonical port)
ALIAS_CASES = {
    "metal:OpenToGround": (
        {"width": "12um", "gap": "7um", "termination_gap": "6um"}, {"a": 12, "b": 7, "length": 6}, {"open": "a"}
    ),
    "metal:LineTee": (
        {}, {"lengths": [50, 50, 50], "angles": [0, 180, 270]},
        {"prime_end": "a", "prime_start": "b", "second_end": "c"},
    ),
    "CpweTaper": (
        {"a": 10, "b": 6, "a_end": 20, "b_end": 12, "length": 31.416, "taper_type": 0},
        {"a": 10, "b": 6, "a2": 20, "b2": 12, "taper_length": 31.416}, {},
    ),
    "metal:LaunchpadWirebond": ({}, {}, {"tie": "a"}),
    "metal:LaunchpadWirebondDriven": ({}, {}, {"tie": "a", "in": "a"}),
    "Launcher": ({}, {}, {"port": "a"}),
    "ConnectorPad": ({}, {}, {}),
    "CpweBondPad": ({}, {}, {}),
    "CpwSegment": ({"length": 300, "a": 10, "b": 6}, {"path": [[-150, 0], [150, 0]], "a": 10, "b": 6}, {}),
    "TrilayerJunction": ({"finger_width": 0.5, "second_finger_width": 0.6, "clearer": True}, {}, {}),
    "TrilayerSquid": ({"finger_width": 0.25, "second_finger_width": 0.6, "clearer": True}, {}, {}),
    "metal:TransmonPocket6": (
        {"connection_pads": {"a": {"loc_W": 1, "loc_H": 1, "pad_cpw_shift": "5um", "pocket_rise": "65um"}}},
        {"connection_pads": {"a": {"loc_W": 1, "loc_H": 1}}}, {},
    ),
    "metal:TransmonStar": (
        {"num_points": 4, "arm_length": "200um", "junction_arm_index": 3, "connection_pads": {"a": {"arm_index": 1}}},
        {"connection_pads": {"a": {"connector_location": "90"}}}, {},
    ),
    "FluxHoleArray": ({}, {}, {}),
    "StripesTest": ({}, {"stripe_step": 0}, {}),
}


def test_every_alias_has_an_equivalence_case():
    assert set(ALIAS_CASES) == {m for ms in ALIASES.values() for m in ms}


@pytest.mark.parametrize("member", sorted(ALIAS_CASES))
def test_alias_shares_an_equivalent_circuit(member):
    """Alias = same kind, same circuit for the same dimensions: the member's LOM fragment, in the canonical's port
    names, equals the canonical's (nodes, element types and values, lines)."""
    canonical = alias_group(member)[0]
    _metal(member)
    _metal(canonical)
    own, theirs, port_map = ALIAS_CASES[member]
    got, want = _circuit(_fragment(member, own), port_map), _circuit(_fragment(canonical, theirs), {})
    assert got == want, f"{member} vs {canonical}:\n  {got}\n  {want}"
    if member not in ("FluxHoleArray", "StripesTest"):
        assert want is not None and (want[1] or want[2] or want[0]), "an electrical alias pair needs a model"


def test_user_launchpad_pair_directly():
    """metal:LaunchpadWirebondDriven ↔ metal:LaunchpadWirebond: one 50 Ω port; 'in' is the same pad conductor."""
    _metal("metal:")
    got = _circuit(_fragment("metal:LaunchpadWirebondDriven", {}), {"in": "tie"})
    assert got == _circuit(_fragment("metal:LaunchpadWirebond", {}), {})


# ---- new ports: CapacitiveXCoupler, WaveguideCoplanarCurved ---------------------------------------------------------
def _ports(ref: str, params: dict):
    from kqcircuits.defaults import default_layers
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.plan import pcell_params
    from quantcore_circuits.layouts.registry import create_cell, element_cell_ports

    cls = resolve_cell(ref)
    p = pcell_params(cls, params)
    layout = pya.Layout()
    cell = create_cell(layout, cls, **p)
    gap = pya.Region(cell.begin_shapes_rec(layout.layer(default_layers["1t1_base_metal_gap_wo_grid"]))).merged()
    return element_cell_ports(cls, cell, p), gap, layout.dbu


def _drawn(gap, port, dbu, depth=0.5, span=80.0, step=0.05):
    """(centre width, (gap, gap)) across the CPW ``depth`` µm inside a port."""
    from kqcircuits.pya_resolver import pya

    d = port.dir
    t, base = pya.DVector(-d.y, d.x), port.pos - d * depth

    def etched(s):
        q = (base + t * s).to_itype(dbu)
        return not gap.interacting(pya.Region(pya.Box(q.x - 1, q.y - 1, q.x + 1, q.y + 1))).is_empty()

    assert not etched(0), f"{port.name}: centre conductor etched"
    half, gaps = [], []
    for sign in (1, -1):
        s = 0.0
        while not etched(sign * s) and s < span:
            s += step
        h = s
        while etched(sign * s) and s < span:
            s += step
        half.append(h)
        gaps.append(s - h)
    return sum(half), gaps


def _beyond_is_open(gap, port, dbu) -> bool:
    """Nothing etched just outside the port across the centre width (a flush CPW end: a route continues there)."""
    from kqcircuits.pya_resolver import pya

    q = (port.pos + port.dir * 1.0).to_itype(dbu)
    return gap.interacting(pya.Region(pya.Box(q.x - 1, q.y - 1, q.x + 1, q.y + 1))).is_empty()


X_CASES = {
    "+": ({}, {"p11": (0, -250, -90), "p21": (250, 0, 0), "p31": (0, 250, 90), "p41": (-250, 0, 180)}),
    "x": ({"x_coupler_variant": "x"},
          {"p11": (-250, -250, -135), "p21": (250, -250, -45), "p31": (250, 250, 45), "p41": (-250, 250, 135)}),
    "x tall": ({"x_coupler_variant": "x", "x_coupler_height": 700},
               {"p11": (-250, -350, -90), "p21": (250, -350, -90), "p31": (250, 350, 90), "p41": (-250, 350, 90)}),
    "x wide": ({"x_coupler_variant": "x", "x_coupler_length": 600, "remove_capacitors": True},
               {"p11": (-300, -250, 180), "p21": (300, -250, 0), "p31": (300, 250, 0), "p41": (-300, 250, 180)}),
    "+ narrow": ({"a": 6, "b": 4, "x_coupler_height": 400},
                 {"p11": (0, -200, -90), "p21": (250, 0, 0), "p31": (0, 200, 90), "p41": (-250, 0, 180)}),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(X_CASES))
def test_x_coupler_ports_are_its_arm_ends(case):
    params, expect = X_CASES[case]
    ports, gap, dbu = _ports("CapacitiveXCoupler", params)
    assert set(ports) == set(expect)
    a, b = params.get("a", 10), params.get("b", 6)
    for name, (x, y, angle) in expect.items():
        port = ports[name]
        assert (port.pos.x, port.pos.y) == pytest.approx((x, y), abs=1e-6) and port.angle == pytest.approx(angle)
        width, gaps = _drawn(gap, port, dbu)
        assert width == pytest.approx(a, abs=0.3) and min(gaps) == pytest.approx(b, abs=0.3), (name, width, gaps)
        assert _beyond_is_open(gap, port, dbu), name


@pytest.mark.parametrize("params", [{}, {"alpha": -1.0, "r": 60}, {"alpha": math.pi / 2, "a": 20, "b": 12}])
def test_curved_segment_ports_are_its_ends(params):
    ports, gap, dbu = _ports("WaveguideCoplanarCurved", params)
    r, alpha = params.get("r", 100), params.get("alpha", math.pi)
    assert set(ports) == {"a", "b"}
    assert (ports["a"].pos.x, ports["a"].pos.y) == pytest.approx((r, 0))
    assert (ports["b"].pos.x, ports["b"].pos.y) == pytest.approx((r * math.cos(alpha), r * math.sin(alpha)))
    s = 1 if alpha >= 0 else -1
    da, db = ports["a"].dir, ports["b"].dir
    assert (da.x, da.y) == pytest.approx((0, -s)) and (db.x, db.y) == pytest.approx((-s * math.sin(alpha),
                                                                                   s * math.cos(alpha)))
    for port in ports.values():
        width, gaps = _drawn(gap, port, dbu)
        assert width == pytest.approx(params.get("a", 10), abs=0.3)
        assert min(gaps) == pytest.approx(params.get("b", 6), abs=0.3)
        assert _beyond_is_open(gap, port, dbu)


def test_new_ports_are_listed_by_the_cli():
    runner = CliRunner()
    res = runner.invoke(app, ["components", "CapacitiveXCoupler", "--json"])
    assert res.exit_code == 0 and {p["name"] for p in json.loads(res.output)} == {"p11", "p21", "p31", "p41"}
    res = runner.invoke(app, ["components", "WaveguideCoplanarCurved", "--json"])
    assert res.exit_code == 0 and {p["name"] for p in json.loads(res.output)} == {"a", "b"}
    assert find("CapacitiveXCoupler").port_names() == ["p11", "p21", "p31", "p41"]


def test_new_lom_models():
    x = _fragment("CapacitiveXCoupler", {})
    assert x.port_nodes == {k: k for k in ("p11", "p21", "p31", "p41")}
    star = [e for e in x.elements if "c" in e.nodes and "gnd" not in e.nodes]
    assert sorted(tuple(sorted(e.nodes)) for e in star) == [("c", k) for k in ("p11", "p21", "p31", "p41")]
    assert all(1 < e.value["estimate"] < 10 for e in star)  # a 2-finger coupler: a few fF
    assert all(5 < e.value["estimate"] < 200 for e in x.elements if "gnd" in e.nodes)
    one = _fragment("CapacitiveXCoupler", {"remove_capacitors": True})
    assert set(one.port_nodes.values()) == {"c"} and len(one.elements) == 1
    curved = _fragment("WaveguideCoplanarCurved", {"alpha": -1.0, "r": 60})
    (line,) = curved.lines
    assert curved.port_nodes == {"a": "line", "b": "line"} and line.ports == ("a", "b")
    assert line.length_um == pytest.approx(60.0) and line.term == ("short", "short")


def test_routes_connect_to_the_new_ports():
    """A route can end on an X-coupler arm and on a curved segment end; the LOM joins them to the pads."""
    from quantcore_circuits.designer import Designer

    d = Designer("new_ports", box=(0, 0, 6000, 4000), live=False, verbose=False)
    x = d.add("X", "CapacitiveXCoupler", at=(2000, 2000))
    p1 = d.add("P1", "BondPad", at=(500, 2000), rot=270)
    cv = d.add("CV", "WaveguideCoplanarCurved", at=(4000, 2500))
    p2 = d.add("P2", "BondPad", at=(5500, 2000), rot=90)
    d.route("R1", x.p41, p1.a)
    d.route("R2", cv.a, p2.a)
    d.route("R3", x.p21, cv.b)
    result = d.show()
    assert result.route_lengths()["R1"] > 0
    lb = d.lom()
    assert lb.port_map["X.p41"] == lb.port_map["P1.a"]
    assert lb.port_map["X.p21"] == lb.port_map["CV.a"] == lb.port_map["CV.b"] == lb.port_map["P2.a"]
    couplers = [b for b in lb.model.branches.values() if b.type == "C" and lb.port_map["X.p41"] in b.nodes]
    assert couplers, "the arm couples to the centre through its finger capacitor"

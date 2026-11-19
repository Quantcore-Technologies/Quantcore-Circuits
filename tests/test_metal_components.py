"""Quantum Metal components as cells (``metal:<Class>``): option handling, geometry, ports, build through the
Designer and the plan (skips without qiskit_metal; the first Metal import takes a few seconds)."""

from __future__ import annotations

import importlib.util
import json

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("qiskit_metal") is None, reason="qiskit_metal not installed")

from kqcircuits.pya_resolver import pya  # noqa: E402

from quantcore_circuits.assembly.plan import pcell_params  # noqa: E402
from quantcore_circuits.layouts.registry import cell_ref, create_cell, element_cell_ports, resolve_cell  # noqa: E402

POCKET = {"connection_pads": {"a": {"loc_W": 1, "loc_H": 1}, "b": {"loc_W": -1, "loc_H": -1}}}

# component → (options, expected ports besides squid_a/squid_b)
CASES = {
    "TransmonPocket": (POCKET, {"a", "b"}),
    "TransmonCross": ({"connection_pads": {"readout": {"connector_location": "90"}}}, {"readout"}),
    "TransmonPocketCL": ({"connection_pads": {"a": {"loc_W": 1, "loc_H": 1}}}, {"a", "Charge_Line"}),
    "TransmonConcentric": ({}, {"pin1", "pin2", "pin3"}),
    "StarQubit": ({}, {"pin_cpl1", "pin_cpl2", "pin_cpl3", "pin_cpl4", "pin_rdout"}),
    "TunableCoupler01": ({}, {"Control", "Flux"}),
    "LaunchpadWirebond": ({}, {"tie"}),
    "OpenToGround": ({}, {"open"}),
    "ShortToGround": ({}, {"short"}),
    "CapNInterdigital": ({}, {"north_end", "south_end"}),
    "Cap3Interdigital": ({}, {"a", "b"}),
    "LineTee": ({}, {"prime_start", "prime_end", "second_end"}),
    "JJ_Manhattan": ({}, set()),
    "ResonatorCoilRect": ({}, {"spiralPin"}),
}
HAS_JUNCTION = {"TransmonPocket", "TransmonCross", "TransmonPocketCL", "TransmonConcentric", "StarQubit"}


def _build(name: str, options: dict):
    cls = resolve_cell(f"metal:{name}")
    params = pcell_params(cls, options)
    layout = pya.Layout()
    cell = create_cell(layout, cls, what=name, **params)
    return cls, params, layout, cell


def _area(layout, cell, layer_name: str) -> float:
    from kqcircuits.defaults import default_layers

    region = pya.Region(cell.begin_shapes_rec(layout.layer(default_layers[f"1t1_{layer_name}"])))
    return region.merged().area() * layout.dbu**2


def test_options_are_normalised_and_validated():
    cls = resolve_cell("metal:TransmonPocket")
    params = cls.qcc_params({"pad_width": 455, "pad_gap": "0.03mm", "margin": 8, **POCKET})
    assert params["metal_class"] == "TransmonPocket" and params["margin"] == 8
    options = json.loads(params["options"])
    assert options["pad_width"] == "455um" and options["pad_gap"] == "0.03mm"
    assert options["connection_pads"]["a"] == {"loc_W": 1, "loc_H": 1}  # unitless pad options stay numbers
    assert cls.qcc_params(params) == params  # idempotent on PCell parameters
    with pytest.raises(ValueError, match="unknown option"):
        cls.qcc_params({"pad_widht": 455})
    with pytest.raises(ValueError, match="placement"):
        cls.qcc_params({"orientation": 90})


def test_inherited_element_params_do_not_override_metal_options():
    """A plan merges the chip's inherited KQC element params (``n`` = 64 circle points, ``r``, ``a``, ``b``, ...)
    into the PCell params; the Metal option of the same name (ResonatorCoilRect ``n`` = turns) must survive, so the
    coil keeps its ``spiralPin`` (tests.md regression, metal:ResonatorCoilRect lines contract)."""
    from quantcore_circuits.assembly.plan import element_params

    cls = resolve_cell("metal:ResonatorCoilRect")
    own = cls.qcc_params({"n": 3, "length": 2000})
    assert json.loads(own["options"])["n"] == 3  # design.json form: the Metal option wins
    params = element_params(cls, {"n": 64, "r": 100, "a": 10, "b": 6, "margin": 5}, {"n": 3, "length": 2000})
    assert params["n"] == 64 and json.loads(params["options"])["n"] == 3
    again = cls.qcc_params(params)  # what DesignChip.build → cls.create does with the plan params
    assert again["n"] == 64 and json.loads(again["options"])["n"] == 3
    layout = pya.Layout()
    cell = cls.create(layout, **params)
    assert "spiralPin" in element_cell_ports(cls, cell, params)


def test_resonator_coil_rect_ports_in_a_design():
    from quantcore_circuits.designer import Designer

    d = Designer("coil_chip", box=(0, 0, 3000, 3000), live=False, verbose=False)
    d.add("R1", "metal:ResonatorCoilRect", at=(1500, 1500), n=3, length=2000)
    result = d.show()
    assert "R1_port_spiralPin" in result.refpoints


def test_bare_numbers_on_variable_lengths_are_um():
    """Options whose Metal default is a design variable (``trace_width="cpw_width"``) are lengths: a bare number is
    µm, not Metal's mm (legacy-b: ``trace_width=20`` drew a 44 mm lead)."""
    cls = resolve_cell("metal:LaunchpadWirebondDriven")
    options = json.loads(cls.qcc_params({"trace_width": 20, "trace_gap": 12})["options"])
    assert options["trace_width"] == "20um" and options["trace_gap"] == "12um"
    _, params, layout, cell = _build("LaunchpadWirebondDriven", {"trace_width": 20, "trace_gap": 12})
    bbox = cell.dbbox()
    assert bbox.width() < 1000 and bbox.height() < 1000, bbox
    assert cls.qcc_port_widths(params)["tie"] == pytest.approx((20.0, 12.0))


def test_names_routes_and_module_attributes():
    from quantcore_circuits.layouts import metal

    cls = resolve_cell("metal:JJ_Manhattan")  # module-name / case-insensitive spelling
    assert cls is resolve_cell("metal:jj_manhattan") and cls.qcc_category == "junction"
    assert resolve_cell(cell_ref(resolve_cell("metal:LineTee"))) is resolve_cell("metal:LineTee")
    assert metal.MetalTransmonPocket is resolve_cell("metal:TransmonPocket")
    with pytest.raises(ValueError, match="meander"):
        resolve_cell("metal:RouteMeander")
    with pytest.raises(ValueError, match="unknown Quantum Metal component"):
        resolve_cell("metal:NoSuchQubit")


@pytest.mark.parametrize("name", sorted(CASES))
def test_component_builds_with_expected_ports(name):
    options, expected = CASES[name]
    cls, params, layout, cell = _build(name, options)
    ports = element_cell_ports(cls, cell, params)
    routing = {n for n in ports if not n.startswith("squid")}
    assert routing == expected
    for n in routing:
        assert ports[n].dir is not None and abs(ports[n].dir.length() - 1) < 1e-9
        assert ports[n].a > 0 and ports[n].b > 0
    assert {"squid_a", "squid_b"} <= set(ports) if name in HAS_JUNCTION else True
    if name == "JJ_Manhattan":
        assert _area(layout, cell, "SIS_junction") > 0
    elif name != "ShortToGround":
        assert _area(layout, cell, "base_metal_gap_wo_grid") > 0


def test_transmon_pocket_geometry_and_ports():
    cls, params, layout, cell = _build("TransmonPocket", POCKET)
    ports = element_cell_ports(cls, cell, params)
    a, b = ports["a"], ports["b"]
    assert (a.pos.x, a.pos.y, a.angle, a.a, a.b) == (425.0, 195.0, 0.0, 10.0, 6.0)
    assert (b.pos.x, b.pos.y, b.angle) == (-425.0, -195.0, 180.0)
    # junction line across the 30 µm pad gap: a = start (bottom pad), b = end (top pad)
    assert (ports["squid_a"].pos.y, ports["squid_b"].pos.y) == (-15.0, 15.0)
    assert _area(layout, cell, "SIS_junction") == pytest.approx(30 * 20)
    gap = _area(layout, cell, "base_metal_gap_wo_grid")
    # pocket − two 455×90 pads − two connector pads (125×30) and their leads, plus the CPW gaps of the leads
    assert 650 * 650 - 2 * 455 * 90 - 2 * 125 * 30 - 2 * 150 * 10 < gap < 650 * 650 - 2 * 455 * 90 + 2 * 2 * 150 * 6
    assert _area(layout, cell, "ground_grid_avoidance") > gap


def test_shapes_subtract_and_metal_layers():
    _, _, layout, cell = _build("Rectangle", {"width": 200, "height": 100, "subtract": "True"})
    assert _area(layout, cell, "base_metal_gap_wo_grid") == pytest.approx(200 * 100)
    _, _, layout, cell = _build("Rectangle", {"width": 200, "height": 100})
    assert _area(layout, cell, "base_metal_gap_wo_grid") == 0
    assert _area(layout, cell, "base_metal_addition") == pytest.approx(200 * 100)  # metal wins over other gaps


def test_paths_are_buffered_with_flat_ends():
    _, _, layout, cell = _build("LineTee", {})
    # prime CPW 100 µm long, second CPW 50 µm down to the prime centre line; gaps 6 µm on both sides
    gap = _area(layout, cell, "base_metal_gap_wo_grid")
    prime = 100 * 22 - 100 * 10
    second = 50 * 22 - 50 * 10
    assert gap == pytest.approx(prime + second - 2 * (11 * 6), rel=0.05)


def test_chip_cpw_width_drives_metal_variables():
    """Element ``a``/``b`` (inherited from the chip) set Metal's ``cpw_width``/``cpw_gap`` design variables, which
    the TransmonPocket connection pads use by default."""
    cls = resolve_cell("metal:TransmonPocket")
    widths = cls.qcc_port_widths({**pcell_params(cls, POCKET), "a": 15.0, "b": 8.0})
    assert widths["a"] == (15.0, 9.0)  # TransmonPocket's pins carry no gap: Metal's default 0.6 × width
    assert cls.qcc_port_widths(pcell_params(cls, POCKET))["a"] == (10.0, 6.0)


def test_designer_build_with_routes_and_plan_roundtrip(tmp_path):
    from quantcore_circuits.assembly import write_layout
    from quantcore_circuits.design import load_design
    from quantcore_circuits.designer import Designer

    d = Designer("metal_chip", box=(0, 0, 4000, 4000), live=False, verbose=False)
    q = d.add("Q1", "metal:TransmonPocket", at=(2000, 2000), pad_width=455, **POCKET)
    lp = d.add("L1", "metal:LaunchpadWirebond", at=(600, 2195))
    end = d.add("T1", "metal:OpenToGround", at=(3400, 2195))
    d.route("R1", lp.tie, q.b)
    d.route("R2", q.a, end.open)
    result = d.show()
    assert {"Q1_port_squid_a", "Q1_port_a", "L1_port_tie"} <= set(result.refpoints)
    plan = json.loads(result.plan.to_json())
    assert plan["instances"]["Q1"]["cell"] == "quantcore_circuits.layouts.metal.MetalTransmonPocket"
    assert json.loads(plan["instances"]["Q1"]["params"]["options"])["pad_width"] == "455um"
    path = d.save(tmp_path / "metal_chip.json")
    design = load_design(path)
    assert design.instances["Q1"].cell == "metal:TransmonPocket"
    assert design.instances["Q1"].params["connection_pads"]["a"]["loc_W"] == 1
    write_layout(result, tmp_path / "metal_chip.oas")
    assert (tmp_path / "metal_chip.oas").stat().st_size > 0


# ---- pin ends (audit issue 1: a pin whose own etch runs past the pin cut every route off it) ---------------------
CLAW = {"claw_length": 150, "claw_width": 35, "ground_spacing": 2, "claw_gap": 6, "claw_cpw_width": 10}
PIN_SETS = {
    "TransmonCross": {"connection_pads": {"a": {"connector_location": "90", **CLAW}, "b": {"connector_location": "0"}}},
    "TransmonCrossFL": {"connection_pads": {"a": {"connector_location": "90"}}},
    "TransmonPocketCL": {"connection_pads": {"a": {"loc_W": 1, "loc_H": 1}}},
    "TransmonPocket": POCKET,
}
# pins whose Metal etch continues past the pin at these options (build/audit/build_ports.json): all must be trimmed
ETCHED_PAST_PIN = {
    "TransmonCross": {"a", "b"},
    "TransmonCrossFL": {"a"},
    "TransmonInterdigitated": {"readout", "bus1", "bus2"},
    "TransmonPocketCL": {"Charge_Line"},
    "TunableCoupler01": {"Control"},
    "CapFingerInFrame": {"frame", "finger"},
    "ResonatorCoilRect": {"spiralPin"},
}


def _gap_region(layout, cell):
    from kqcircuits.defaults import default_layers

    return pya.Region(cell.begin_shapes_rec(layout.layer(default_layers["1t1_base_metal_gap_wo_grid"]))).merged()


def _etched_beyond(gap, layout, pin) -> int:
    """Probes on the gap layer just beyond the pin, across the pin width (0 = metal all over)."""
    (mx, my), (nx, ny) = pin.middle, pin.normal
    hits = 0
    for d in (0.05, 0.5, 2.0):
        for s in (-0.45, 0.0, 0.45):
            p = pya.DPoint(mx + nx * d - ny * s * pin.width, my + ny * d + nx * s * pin.width).to_itype(layout.dbu)
            hits += not gap.interacting(pya.Region(pya.Box(p.x - 1, p.y - 1, p.x + 1, p.y + 1))).is_empty()
    return hits


def _ends_conductor(geom, pin, dbu=0.001) -> bool:
    from quantcore_circuits.layouts.metal.component import _region, pin_end_strip

    (nx, ny) = pin.normal
    behind = pya.Region(pin_end_strip(pin, 0.5).moved(-0.5 * nx, -0.5 * ny).to_itype(dbu))
    return not (_region(geom.metal, dbu) & behind).is_empty()


def _metal_cells():
    from quantcore_circuits.layouts.metal.geometry import qlibrary_index

    return sorted(n for n, i in qlibrary_index().items() if not i.is_route)


@pytest.mark.parametrize("name", _metal_cells())
def test_pins_are_not_etched_beyond_the_pin(name):
    """At every pin that ends one of the component's conductors there is no etch within the pin width beyond the pin
    (Metal's renderer draws the route's trace over it); ``open_pins`` keeps Metal's etch there."""
    cls, params, layout, cell = _build(name, PIN_SETS.get(name, {}))
    geom = cls.qcc_geometry(params)
    gap = _gap_region(layout, cell)
    ends = {pn for pn, pin in geom.pins.items() if _ends_conductor(geom, pin)}
    assert ETCHED_PAST_PIN.get(name, set()) <= ends
    for pn in ends:
        assert _etched_beyond(gap, layout, geom.pins[pn]) == 0, f"{name}.{pn} is etched beyond the pin"
    if name in ETCHED_PAST_PIN:
        kept = pya.Layout()
        opened = create_cell(kept, cls, what=name, **{**params, "open_pins": ",".join(ETCHED_PAST_PIN[name])})
        kept_gap = _gap_region(kept, opened)
        for pn in ETCHED_PAST_PIN[name]:
            assert _etched_beyond(kept_gap, kept, geom.pins[pn]) == 9, f"open_pins did not keep {name}.{pn}"
        assert kept_gap.area() > gap.area()


def test_launchpad_driven_in_pin_keeps_its_pad_gap():
    """LaunchpadWirebondDriven ``in`` faces into the pad (a lumped-port terminal across the pad gap): not trimmed."""
    cls, params, layout, cell = _build("LaunchpadWirebondDriven", {})
    pin = cls.qcc_geometry(params).pins["in"]
    assert _etched_beyond(_gap_region(layout, cell), layout, pin) == 9


def test_metal_claw_and_route_are_one_conductor():
    """Design level (d12/d14 cut): a TransmonCross claw with a CPW route on it — the claw metal 1 µm inside the pin and
    the route's centre conductor 1 µm outside are one polygon of metal (gap layer complement), and the lead's
    ``open_conductor`` DRC finds nothing."""
    from quantcore_circuits.assembly.drc import _conductor_opens
    from quantcore_circuits.designer import Designer

    d = Designer("metal_claw", box=(0, 0, 3000, 3000), live=False, verbose=False)
    q = d.add(
        "Q",
        "metal:TransmonCross",
        at=(1500, 1000),
        cross_width=50,
        cross_length=220,
        cross_gap=20,
        connection_pads={"a": {"connector_type": "0", "connector_location": "90", "claw_cpw_length": 100, **CLAW}},
    )
    lp = d.add("L", "metal:LaunchpadWirebond", at=(600, 2400))
    d.route("R", q.a, lp.tie)
    result = d.show()
    assert _conductor_opens(result) == []
    port = result.plan.all_ports()["Q.a"]
    layout, dbu = result.layout, result.layout.dbu
    gap = pya.Region(result.cell.begin_shapes_rec(layout.layer(pya.LayerInfo(130, 1)))).merged()
    window = pya.DBox(port.pos.x - 30, port.pos.y - 30, port.pos.x + 30, port.pos.y + 30)
    metal = (pya.Region(window.to_itype(dbu)) - gap).merged()
    inside, outside = (port.pos - port.dir * 1.0).to_itype(dbu), (port.pos + port.dir * 1.0).to_itype(dbu)
    corner = pya.DPoint(window.left + 0.5, window.bottom + 0.5).to_itype(dbu)  # ground plane
    owners = [[k for k, poly in enumerate(metal.each()) if poly.inside(pt)] for pt in (inside, outside, corner)]
    assert owners[0] and owners[0] == owners[1] and owners[0] != owners[2]


METAL_ONLY = ("TransmonConcentricType2", "TunableCoupler02", "ResonatorLumped", "NSquareSpiral")


@pytest.mark.parametrize("name", METAL_ONLY)
def test_metal_only_cells_are_documented_and_draw_metal_only(name):
    """Audit issue 5: these Metal classes add no subtract geometry (no pocket): no etch, metal on
    base_metal_addition, and the catalog says so."""
    from quantcore_circuits.layouts.catalog import find

    _, _, layout, cell = _build(name, {})
    assert _area(layout, cell, "base_metal_gap_wo_grid") == 0
    assert _area(layout, cell, "base_metal_addition") > 0
    assert "no pocket" in find(f"metal:{name}").note


def test_metal_only_cell_on_a_rectangle_pocket():
    """The documented recipe: a metal:Rectangle pocket (subtract) under a metal-only cell → its metal is cut out of
    the M1 etch (holes in the pocket)."""
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    d = Designer("pocket_recipe", box=(0, 0, 6000, 6000), live=False, verbose=False)
    d.add("P", "metal:Rectangle", at=(3000, 3000), width=4200, height=1800, subtract=True)
    d.add("C", "metal:TunableCoupler02", at=(3000, 2625))
    result = d.show()
    m1 = fab_regions(result.cell, result.design.pdk, None, pya.DBox(0, 0, 6000, 6000))["M1"]
    pocket = 4200 * 1800
    assert sum(p.holes() for p in m1.each()) >= 5
    assert m1.area() * result.layout.dbu**2 < pocket - 1e5

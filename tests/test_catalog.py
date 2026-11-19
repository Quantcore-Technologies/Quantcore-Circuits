"""Component catalog (``layouts.catalog``), ``list_components`` and ``qcc components``."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantcore_circuits.cli import app
from quantcore_circuits.layouts.catalog import CATEGORIES, SOURCES, catalog, categories, find
from quantcore_circuits.layouts.registry import list_components, resolve_cell


def test_catalog_counts_and_fields():
    entries = catalog(routes=True)
    by_source = Counter(c.source for c in entries)
    # 41 Metal components + 6 routes: qlibrary minus metal:MyQComponent (catalog.EXCLUDED, 2026-11-15)
    assert by_source["quantcore"] >= 5 and by_source["kqc"] >= 65 and by_source["metal"] == 47
    refs = [c.ref for c in entries]
    assert len(refs) == len(set(refs))
    for c in entries:
        assert c.category in CATEGORIES and c.source in SOURCES and c.name and c.module
    routes = [c for c in entries if not c.cell]
    assert {c.name for c in routes} == {
        "RouteAnchors",
        "RouteFramed",
        "RouteMeander",
        "RouteMixed",
        "RoutePathfinder",
        "RouteStraight",
    }
    assert all("qcc route" in c.note for c in routes)
    assert not [c for c in catalog() if not c.cell]  # routes only on request


def test_categories_of_known_components():
    expect = {
        "Xmon": "qubit",
        "BondPad": "launcher",
        "TrilayerSquid": "junction",
        "Swissmon": "qubit",
        "Manhattan": "junction",
        "FingerCapacitorSquare": "capacitor",
        "CapacitiveXCoupler": "coupler",
        "Launcher": "launcher",
        "Meander": "waveguide",
        "AirbridgeConnection": "airbridge",
        "MarkerStandard": "marker",
        "FlipChipConnectorRf": "flip_chip",
        "JunctionTestPadsSimple": "test_structure",
        "Demo": "chip",
        "metal:TransmonPocket": "qubit",
        "metal:jj_manhattan": "junction",
        "metal:LineTee": "coupler",
        "metal:CapNInterdigital": "capacitor",
        "metal:LaunchpadWirebond": "launcher",
        "metal:OpenToGround": "termination",
        "metal:ResonatorCoilRect": "resonator",
        "metal:Rectangle": "shape",
        "TrilayerJunctionCompact": "junction",
        "JJFingerStraight": "shape",
        "JJFingerBent": "shape",
        "FluxHoles": "other",
        "CpweQuarterWaveResonator": "resonator",
        "NeckTermination": "termination",
        "Flipmon": "qubit",
        "Gatemon": "qubit",
        "GatemonCoupler": "coupler",
        "HyperbolicVertexCoupler": "coupler",
        "TransmonTaperedInsets": "qubit",
        "SmoothCapacitorSemicircle": "capacitor",
    }
    got = {c.ref: c.category for c in catalog()}
    assert {r: got.get(r) for r in expect} == expect
    assert "Xmon" in categories()["qubit"]


def test_find_and_filters():
    assert find("TransmonPocket").ref == "metal:TransmonPocket"
    assert find("metal:JJ_Manhattan").ref == "metal:jj_manhattan"
    assert find("xmon").ref == "Xmon"
    assert find("NoSuchThing") is None
    assert {c.source for c in catalog(source="metal")} == {"metal"}
    assert all(c.category == "qubit" for c in catalog(category="qubit"))
    assert not [c for c in catalog(chips=False) if c.category == "chip"]
    with pytest.raises(ValueError, match="unknown category"):
        catalog(category="bogus")


def test_kqc_and_quantcore_entries_resolve_to_their_class():
    for c in catalog(chips=True):
        if c.source == "metal":
            continue
        cls = resolve_cell(c.ref)
        assert cls.__name__ == c.name and cls.__module__ == c.module


def test_ports_of_default_instance():
    assert find("BondPad").port_names() == ["a"]
    assert {"claw_n"} <= set(find("Xmon").port_names())
    assert set(find("Launcher").ports_of()) == {"port"}


def test_list_components_uses_the_catalog():
    comps = list_components()
    assert "Xmon" in comps and "Swissmon" in comps and "metal:TransmonPocket" in comps
    assert "Demo" not in comps and "Demo" in list_components(chips=True)
    assert comps["Xmon"].__name__ == "Xmon"
    assert set(list_components(source="quantcore")) >= {"Xmon", "BondPad", "TrilayerJunction", "TrilayerSquid"}


def test_cli_components():
    runner = CliRunner()
    res = runner.invoke(app, ["components", "--json"])
    assert res.exit_code == 0, res.output
    refs = json.loads(res.output)
    assert "Xmon" in refs and "metal:TransmonPocket" in refs and all(isinstance(r, str) for r in refs)
    res = runner.invoke(app, ["components", "--json", "--details", "--source", "quantcore"])
    records = json.loads(res.output)
    assert {r["source"] for r in records} == {"quantcore"} and {"name", "ref", "category"} <= set(records[0])
    res = runner.invoke(app, ["components", "--category", "launcher"])
    assert res.exit_code == 0 and "BondPad" in res.output and "launcher:" in res.output
    res = runner.invoke(app, ["components", "BondPad", "--json"])
    assert json.loads(res.output)[0]["name"] == "a"
    assert runner.invoke(app, ["components", "--category", "bogus"]).exit_code != 0


def test_documented_port_exceptions_are_notes():
    """LauncherDC keeps KQC's undirected centre port (symmetric DC pad): the catalog says so, and the CLI shows it."""
    from quantcore_circuits.layouts.catalog import NOTES

    dc = find("LauncherDC")
    assert dc.note == NOTES["LauncherDC"] and "no direction" in dc.note
    ports = dc.ports_of()
    assert set(ports) == {"port"} and ports["port"].dir is None
    res = CliRunner().invoke(app, ["components", "--category", "launcher"])
    assert res.exit_code == 0 and "DC pad" in res.output


def test_make_catalog_script_writes_the_catalog():
    """``scripts/make_catalog.py`` (CATALOG.md generator): every legacy-map ref is a catalog cell, every inventory
    legacy file is mapped, and the Markdown is produced from per-ref checks."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("make_catalog", root / "scripts" / "make_catalog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    refs = {c.ref for c in catalog()}
    for path, entry in mod.LEGACY.items():
        assert entry["status"] in ("ported", "design", "not migrated"), path
        if entry["status"] == "not migrated":
            assert entry["reason"] in mod.REASONS, path
        for ref in entry.get("cells", []):
            assert ref.startswith("fn:") or ref in refs, f"{path}: {ref} is not a catalog cell"
    inventory = json.loads((root / "docs" / "components" / "inventory.json").read_text(encoding="utf-8"))
    files = {e["file"].replace("\\", "/").removeprefix("components/") for e in inventory["legacy"]}
    assert files == set(mod.LEGACY)
    checks = {ref: mod.check(ref, cat, {}) for ref, cat in (("BondPad", "launcher"), ("LauncherDC", "launcher"))}
    assert checks["BondPad"]["builds"] and checks["BondPad"]["ports"] == ["a"] and checks["BondPad"]["lom"]
    assert checks["LauncherDC"]["undirected"] == ["port"] and mod.ports_ok(checks["LauncherDC"]).startswith("no")
    text = mod.make_catalog(checks)
    assert text.startswith("# Component catalog") and "| BondPad | `BondPad` | quantcore | a | yes |" in text


# pad cells with a well-defined signal/ground gap → (params) built for the lumped-port check
LUMPED_PADS = {
    "BondPad": {},
    "ConnectorPad": {},
    "ConnectorPad rounded": {"rounded": True, "pad_width": 200, "pad_height": 200},
    "ConnectorPad chip_03": {"pad_width": 250, "pad_height": 250, "taper_length": 250, "a": 20, "b": 12},
    "CpweBondPad": {},
    "CpweBondPad mirror": {"mirror": True},
    "metal:LaunchpadWirebond": {},
    "metal:LaunchpadWirebondDriven": {"pad_width": 400, "pad_height": 300, "pad_gap": 195, "trace_width": 10},
    "metal:LaunchpadWirebondCoupled": {},
}


@pytest.mark.parametrize("case", sorted(LUMPED_PADS))
def test_pads_have_lumped_port_terminals(case):
    """Every launch/bond pad cell exposes ``lumped_signal`` (pad edge) / ``lumped_ground`` (ground edge) across its
    side gap: metal just behind each point, etch all the way between them, and the pad side is the conductor of
    port ``a``/``tie`` (sim_tools gives such a pad its 50 Ω lumped port)."""
    import importlib.util

    from kqcircuits.defaults import default_layers
    from kqcircuits.elements.element import get_refpoints
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.plan import pcell_params
    from quantcore_circuits.layouts.registry import create_cell, element_cell_ports

    ref = case.split()[0]
    if ref.startswith("metal:") and importlib.util.find_spec("qiskit_metal") is None:
        pytest.skip("qiskit_metal not installed")
    cls = resolve_cell(ref)
    params = pcell_params(cls, LUMPED_PADS[case])
    layout = pya.Layout()
    cell = create_cell(layout, cls, what=case, **params)
    rp = get_refpoints(layout.layer(default_layers["refpoints"]), cell, rec_levels=0)
    sig, gnd = rp["lumped_signal"], rp["lumped_ground"]
    gap = pya.Region(cell.begin_shapes_rec(layout.layer(default_layers["1t1_base_metal_gap_wo_grid"]))).merged()
    metal = (pya.Region(gap.bbox().enlarged(10 / layout.dbu)) - gap).merged()

    def etched(p):
        ip = p.to_itype(layout.dbu)
        return not gap.interacting(pya.Region(pya.Box(ip.x - 1, ip.y - 1, ip.x + 1, ip.y + 1))).is_empty()

    u = (gnd - sig) / (gnd - sig).length()
    assert (gnd - sig).length() > 1
    assert not etched(sig - u * 0.5) and not etched(gnd + u * 0.5)
    steps = 50
    assert all(etched(sig + (gnd - sig) * ((k + 0.5) / steps)) for k in range(steps))
    # the pad side is the signal conductor: it is the metal polygon at the port, not the ground plane
    ports = element_cell_ports(cls, cell, params)
    port = ports.get("a") or ports.get("tie")
    if ref == "metal:LaunchpadWirebondCoupled":
        return  # the pad couples to the tie lead through a finger capacitor (no galvanic path)
    # the cell's CPW ends at the port on ground (KQC convention): cut it there, as a route's gaps would
    t, half = pya.DVector(-port.dir.y, port.dir.x), port.a / 2 + port.b + 1
    cut = pya.DPolygon(
        [
            port.pos - t * half,
            port.pos + t * half,
            port.pos + t * half + port.dir * 0.2,
            port.pos - t * half + port.dir * 0.2,
        ]
    )
    metal = (metal - pya.Region(cut.to_itype(layout.dbu))).merged()
    inside = (port.pos - port.dir * 0.5).to_itype(layout.dbu)
    pad = [k for k, poly in enumerate(metal.each()) if poly.inside((sig - u * 0.5).to_itype(layout.dbu))]
    lead = [k for k, poly in enumerate(metal.each()) if poly.inside(inside)]
    ground = [k for k, poly in enumerate(metal.each()) if poly.inside((gnd + u * 0.5).to_itype(layout.dbu))]
    assert pad and pad == lead and pad != ground


# (ref, params) whose port widths come from KQC_PORT_WIDTHS / qcc_port_widths: drawn centre width == declared a,
# drawn gap >= declared b (a wider gap is the element's own clearance), probed 0.5 µm inside each directed port
PORT_WIDTH_CASES = {
    "WaveguideCoplanarTaper": {},
    "WaveguideCoplanarTaper xmonsdirectcoupling": {"a": 5, "b": 20, "a2": 10, "b2": 6},
    "AirbridgeConnection": {},
    "FluxlineStraight": {},
    "QuarterWaveCpwResonator": {},
    "QuarterWaveCpwResonator qualityfactor": {"res_a": 5, "res_b": 3},
    "Swissmon demo": {"port_width": [4, 10, 4]},
    "CircularTransmonSingleIsland": {},
    "ConcentricTransmon": {},
    "CpwResonator": {},
    "CpwResonator tail": {"tail": True},
    "Gatemon": {},
    "TransmonTaperedInsets floating_transmon": {
        "connection_pads": {"readout": {"pad_gap": 100}},
        "taper_height": 0,
        "junction_type": "No Squid",
    },
    "SmoothCapacitorSemicircle lead": {"lead_length": 40},
}


def _drawn_widths(gap, pos, d, dbu, depth=0.5, span=80.0, step=0.05):
    """(centre width, gap on each side) across the line 0.5 µm inside a port; None if the centre is etched."""
    from kqcircuits.pya_resolver import pya

    t = pya.DVector(-d.y, d.x)
    base = pos - d * depth

    def etched(s):
        q = (base + t * s).to_itype(dbu)
        return not gap.interacting(pya.Region(pya.Box(q.x - 1, q.y - 1, q.x + 1, q.y + 1))).is_empty()

    if etched(0):
        return None
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


@pytest.mark.parametrize("case", sorted(PORT_WIDTH_CASES))
def test_declared_port_widths_match_the_drawing(case):
    """Audit issues 3/4: a route takes a port's a/b, so they must be what is drawn there."""
    from kqcircuits.defaults import default_layers
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.plan import pcell_params
    from quantcore_circuits.layouts.registry import create_cell, element_cell_ports

    ref = case.split()[0]
    cls = resolve_cell(ref)
    params = pcell_params(cls, PORT_WIDTH_CASES[case])
    layout = pya.Layout()
    cell = create_cell(layout, cls, what=case, **params)
    gap = pya.Region(cell.begin_shapes_rec(layout.layer(default_layers["1t1_base_metal_gap_wo_grid"]))).merged()
    checked = 0
    for name, port in element_cell_ports(cls, cell, params).items():
        if port.dir is None:
            continue
        drawn = _drawn_widths(gap, port.pos, port.dir, layout.dbu)
        if drawn is None or drawn[0] >= 80:  # no CPW drawn at this port (e.g. a drive point in the ground plane)
            continue
        a, (g1, g2) = drawn
        assert abs(a - port.a) <= max(0.3, 0.02 * port.a), f"{case}.{name}: drawn a {a:.2f}, declared {port.a}"
        assert min(g1, g2) >= port.b - 0.3, f"{case}.{name}: drawn gaps {g1:.2f}/{g2:.2f}, declared b {port.b}"
        checked += 1
    assert checked


def test_export_fab_warns_about_dropped_layers(tmp_path):
    """Audit issue 6/7: device layers with no PDK fab layer are reported, not dropped silently. Airbridges have fab
    layers since PDK v3 (2026-11-03: 300/0 pads, 301/0 bridge); a KQC junction shadow (no fab layer) warns."""
    import warnings

    from kqcircuits.defaults import default_layers
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.designer import Designer
    from quantcore_circuits.layouts.wafers.fab_export import FabLayersDropped, dropped_layers, export_fab

    d = Designer("ab_chip", box=(0, 0, 2000, 2000), live=False, verbose=False)
    d.add("AB", "AirbridgeConnection", at=(1000, 1000))
    result = d.show()
    report = {}
    with warnings.catch_warnings():
        warnings.simplefilter("error", FabLayersDropped)  # airbridges are mapped: nothing dropped
        path = export_fab(result, tmp_path / "ab.oas", report=report)
    assert report["dropped"] == {}
    layout = pya.Layout()
    layout.read(str(path))
    written = {(info.layer, info.datatype) for info in layout.layer_infos()}
    assert {(300, 0), (301, 0), (1, 0)} <= written and (146, 1) not in written

    shadow = result.layout.layer(default_layers["1t1_SIS_shadow"])
    result.cell.shapes(shadow).insert(pya.DBox(990, 990, 1010, 1010))
    with pytest.warns(FabLayersDropped, match="SIS_shadow"):
        export_fab(result, tmp_path / "shadow.oas", report=report)
    assert report["dropped"] == dropped_layers(result.cell, result.design.pdk)
    assert any("SIS_shadow" in k for k in report["dropped"])

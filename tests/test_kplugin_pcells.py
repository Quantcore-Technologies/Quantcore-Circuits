"""G7 live PCells (kplugin/python/qcc_kplugin/pcells.py): the GUI-free parts with the standalone ``klayout`` module,
and the two ``qcc components`` options they use (``--schemas``, ``--oas``)."""

import json
import sys
from pathlib import Path

import klayout.db as kdb
import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kplugin" / "python"))

from qcc_kplugin import pcells  # noqa: E402

SCHEMA = [
    {"name": "w", "default": 10, "type": "int", "kqc_type": "double", "description": "width", "unit": "µm",
     "choices": []},
    {"name": "n", "default": 2, "type": "int", "kqc_type": "int", "description": "count", "unit": "", "choices": []},
    {"name": "kind", "default": "a", "type": "str", "kqc_type": "string", "description": "kind", "unit": "",
     "choices": ["a", "b"]},
    {"name": "on", "default": False, "type": "bool", "kqc_type": "boolean", "description": "on", "unit": "",
     "choices": []},
    {"name": "arms", "default": [100, 100], "type": "list", "kqc_type": "list", "description": "arms", "unit": "",
     "choices": []},
    {"name": "claws", "default": ["n"], "type": "list", "kqc_type": "list", "description": "claws", "unit": "",
     "choices": []},
]
SCHEMAS = {"Boxy": {"category": "other", "description": "test cell", "schema": SCHEMA}}


def test_values_are_coerced_and_only_changes_are_kept():
    assert pcells.norm(10.0) == 10 and pcells.norm((1.0, 2.5)) == [1, 2.5] and pcells.norm(True) is True
    # KLayout's dialog hands list items back as strings
    own = pcells.own_params(SCHEMA, {"w": 10.0, "n": 3, "kind": "a", "on": False, "arms": ["150", "100"],
                                     "claws": ["n", "e"]})
    assert own == {"n": 3, "arms": [150, 100], "claws": ["n", "e"]}
    assert pcells.full_params(SCHEMA, own)["w"] == 10 and pcells.full_params(SCHEMA, own)["arms"] == [150, 100]
    assert pcells.params_key("Boxy", {"n": 3.0}) == pcells.params_key("Boxy", {"n": 3})
    assert pcells.base_cell("quantcore_circuits.layouts.qubits.xmon.Xmon") == "Xmon"
    assert pcells.base_cell("kqcircuits.qubits.swissmon.Swissmon") == "kqcircuits.qubits.swissmon.Swissmon"
    assert pcells.liveable({"cell": "Boxy", "params": {"w": 12}}, SCHEMAS) == "Boxy"
    assert pcells.liveable({"cell": "Boxy", "params": {"shape": [[0, 0]]}}, SCHEMAS) is None  # not in the schema
    assert pcells.liveable({"cell": "Swissmon"}, SCHEMAS) is None


def _built_cell(layout, w=10.0):
    """A stand-in for a built component cell: a box on the etch layer and a sub-cell (like a junction)."""
    cell = layout.create_cell(f"Boxy_{w}")
    cell.shapes(layout.layer(kdb.LayerInfo(130, 1, "1t1_base_metal_gap_wo_grid"))).insert(kdb.DBox(0, 0, w, 5))
    sub = layout.create_cell(f"jj_{w}")
    sub.shapes(layout.layer(kdb.LayerInfo(136, 1, "1t1_SIS_junction"))).insert(kdb.DBox(0, 0, 1, 1))
    cell.insert(kdb.DCellInstArray(sub.cell_index(), kdb.DTrans(kdb.DVector(2, 2))))
    return cell


def _region(cell, info):
    li = cell.layout().find_layer(info)
    region = kdb.Region()
    if li is not None:
        region.insert(cell.begin_shapes_rec(li))  # a copy: Region(iterator) would keep reading the cell
    return region


@pytest.fixture
def library():
    provider = pcells.Provider("qcc-not-run")
    lib = pcells.make_library(SCHEMAS, provider)
    lib.register(pcells.LIB_NAME)
    yield lib, provider
    lib.delete()


def _design(**inst):
    return {"schema": "qcc/0.1", "name": "t", "chip": {"box": [0, 0, 5000, 5000]}, "instances": inst, "routes": {}}


def test_liven_swaps_static_cells_for_library_pcells_with_the_built_geometry(library):
    lib, provider = library
    layout = kdb.Layout()
    chip = layout.create_cell("DesignChip")
    built = _built_cell(layout, 10.0)
    built2 = _built_cell(layout, 25.0)
    i1 = chip.insert(kdb.DCellInstArray(built.cell_index(), kdb.DCplxTrans(1, 90, False, 100, 200)))
    i1.set_property("id", "B1")
    i2 = chip.insert(kdb.DCellInstArray(built2.cell_index(), kdb.DCplxTrans(1, 0, True, 900, 0)))
    i2.set_property("id", "B2")
    route = chip.insert(kdb.DCellInstArray(layout.create_cell("route").cell_index(), kdb.DTrans()))
    route.set_property("id", "R1")
    design = _design(B1={"cell": "Boxy", "place": {"at": [100, 200], "rot": 90}},
                     B2={"cell": "Boxy", "params": {"w": 25, "kind": "a"}, "place": {"at": [900, 0], "mirror": True}})
    etch = kdb.LayerInfo(130, 1, "1t1_base_metal_gap_wo_grid")
    ref = {n: _region(c, etch) for n, c in (("B1", built), ("B2", built2))}
    done = pcells.liven(chip, design, lib, provider)
    assert sorted(done) == ["B1", "B2"]
    by_id = {inst.property("id"): inst for inst in chip.each_inst()}
    assert set(by_id) == {"B1", "B2", "R1"} and not by_id["R1"].is_pcell()
    for name in ("B1", "B2"):
        inst = by_id[name]
        assert inst.is_pcell() and pcells.library_cell_name(inst, layout) == "Boxy"
        cell = layout.cell(inst.cell_index)
        got = _region(cell, kdb.LayerInfo(130, 1, "1t1_base_metal_gap_wo_grid"))
        assert (got ^ ref[name]).is_empty()  # the build's geometry, not a re-made one
        assert not _region(cell, kdb.LayerInfo(136, 1, "1t1_SIS_junction")).is_empty()  # sub-cells flattened in
    assert by_id["B1"].dcplx_trans == kdb.DCplxTrans(1, 90, False, 100, 200)
    assert by_id["B2"].pcell_parameters_by_name()["w"] == 25
    assert built._destroyed()  # the replaced static cell is pruned
    assert provider.fallback == set() and not provider.queue  # everything came from the build


def test_sync_turns_instance_tool_placements_and_dialog_edits_into_design_json(library):
    lib, provider = library
    layout = kdb.Layout()
    chip = layout.create_cell("DesignChip")
    pid = lib.layout().pcell_id("Boxy")
    variant = layout.add_pcell_variant(lib, pid, pcells.full_params(SCHEMA, {"n": 4}))
    chip.insert(kdb.DCellInstArray(variant, kdb.DCplxTrans(1, 270, False, 50, 60)))
    design = _design(B1={"cell": "Boxy", "params": {"w": 10, "note_kept": 1}, "place": {"at": [0, 0], "rot": 0}})
    edited = chip.insert(kdb.DCellInstArray(
        layout.add_pcell_variant(lib, pid, pcells.full_params(SCHEMA, {})), kdb.DTrans()))
    edited.set_property("id", "B1")
    del edited  # stale once another instance of the cell changes
    design, report = pcells.sync(design, chip, SCHEMAS)
    assert report == ["placed B2 (Boxy) at (50, 60) rot 270"]  # B1: the explicit default w = 10 is no change
    assert design["instances"]["B2"] == {"cell": "Boxy", "place": {"at": [50.0, 60.0], "rot": 270.0},
                                         "params": {"n": 4}}
    by_id = {inst.property("id"): inst for inst in chip.each_inst()}
    assert set(by_id) == {"B1", "B2"}
    by_id["B1"].change_pcell_parameters({**pcells.full_params(SCHEMA, {}), "w": 33.0, "arms": ["120", "100"]})
    design, report = pcells.sync(design, chip, SCHEMAS)
    assert report == ["B1: arms, w set in KLayout's PCell dialog"]
    assert design["instances"]["B1"]["params"] == {"w": 33, "note_kept": 1, "arms": [120, 100]}
    design, report = pcells.sync(design, chip, SCHEMAS)
    assert report == []


def test_an_unbuilt_parameter_set_is_previewed_and_fetched(library):
    lib, provider = library
    layout = kdb.Layout()
    top = layout.create_cell("TOP")
    pid = lib.layout().pcell_id("Boxy")
    first = layout.add_pcell_variant(lib, pid, pcells.full_params(SCHEMA, {"w": 99}))
    assert not layout.cell(first).bbox().empty()  # nothing cached: a marker square
    scratch = kdb.Layout()
    provider.cache.put(pcells.params_key("Boxy", {}), _built_cell(scratch, 10.0))
    v = layout.add_pcell_variant(lib, pid, pcells.full_params(SCHEMA, {"w": 44}))
    top.insert(kdb.DCellInstArray(v, kdb.DTrans()))
    assert layout.cell(v).dbbox().width() == pytest.approx(10)  # the nearest cached geometry until the real one lands
    key = pcells.params_key("Boxy", {"w": 44})
    assert key in provider.fallback and key in provider.queue  # fetched in the background (`qcc ... --oas`)


def test_cli_schemas_and_component_oas_match_the_build(tmp_path, example_path):
    from quantcore_circuits import build, write_layout
    from quantcore_circuits.cli import app

    res = CliRunner().invoke(app, ["components", "--source", "quantcore", "--schemas"])
    assert res.exit_code == 0, res.output
    schemas = json.loads(res.output)
    assert {"Xmon", "BondPad", "QubitResonator"} <= set(schemas)
    rows = {r["name"]: r for r in schemas["Xmon"]["schema"]}
    assert rows["a"]["kqc_type"] == "double" and rows["claws"]["kqc_type"] == "list"

    design = json.loads(example_path.read_text(encoding="utf-8"))
    q1 = design["instances"]["Q1"]
    out = tmp_path / "q1.oas"
    res = CliRunner().invoke(app, ["components", "Xmon", "--params", json.dumps(q1.get("params", {})), "--oas",
                                   str(out), "--design", str(example_path)])
    assert res.exit_code == 0, res.output
    built = tmp_path / "b.oas"
    write_layout(build(example_path), built, sidecar=False)
    a, b = kdb.Layout(), kdb.Layout()
    a.read(str(out))
    b.read(str(built))
    comp = next(c for c in a.top_cells() if c.name == "qcc_component")
    chip = next(c for c in b.each_cell() if c.name.startswith("Design"))
    inst = next(i for i in chip.each_inst() if i.property("id") == "Q1")
    q1_cell = b.cell(inst.cell_index)
    for li in b.layer_indexes():
        info = b.get_info(li)
        la = a.find_layer(info)
        ra, rb = kdb.Region(), kdb.Region()
        if la is not None:
            ra.insert(comp.begin_shapes_rec(la))
        rb.insert(q1_cell.begin_shapes_rec(li))
        assert (ra ^ rb).is_empty(), f"layer {info}"

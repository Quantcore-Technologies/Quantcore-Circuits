"""Flip-chip and multi-face fixes: the PDK cheese stays clear of TSVs, indium bumps, UBM and airbridges; a KQC chip
placed as one cell gets keep-outs from its own etch, not its bounding box; a taper that does not fit after its node
ends at the node (no overshoot, length counted once); snapshots hide every face's centre lines."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from kqcircuits.defaults import default_faces, default_layers
from kqcircuits.pya_resolver import pya

PLACE = {"rot": 0.0, "mirror": False, "snap": None, "to": None, "gap": 0.0}


def _design(name: str, instances: dict, routes: dict | None = None, box=4000.0, **chip) -> dict:
    return {
        "schema": "qcc/0.1",
        "name": name,
        "pdk": "quantcore_nb_sapphire_v1",
        "chip": {
            "cell": "quantcore_circuits.assembly.DesignChip",
            "box": [0.0, 0.0, box, box],
            "launchers": None,
            "params": {"with_grid": False, **chip},
        },
        "instances": {
            k: {"cell": cell, "params": params, "place": {"at": list(at), **PLACE}}
            for k, (cell, params, at) in instances.items()
        },
        "routes": routes or {},
    }


def _layer(result, face: str, name: str) -> pya.Region:
    return pya.Region(result.cell.begin_shapes_rec(result.layout.layer(default_faces[face][name])))


def _holes(result) -> pya.Region:
    return pya.Region(result.cell.begin_shapes_rec(result.layout.layer(default_layers["1t1_ground_grid"])))


def _stub(a: float, b: float) -> dict:
    """A 30 µm CPW stub (open far end) whose port ``a`` faces −x: a port for a route to end on."""
    return {"path": [[0.0, 0.0], [30.0, 0.0]], "a": a, "b": b, "term2": b}


VIAS_BUMPS_BRIDGES = {
    "V1": ("TsvEllipse", {"face_ids": ["1t1", "1b1"]}, (1600, 2000)),
    "V2": ("TsvStandard", {"face_ids": ["1t1", "1b1"]}, (1700, 2300)),
    "B1": ("FlipChipConnectorDc", {}, (2400, 2000)),
    "AB": ("AirbridgeRectangular", {}, (2000, 1600)),
}


@pytest.mark.parametrize("cheese", ["chip", "pdk"])
def test_cheese_keeps_clear_of_vias_bumps_ubm_and_airbridges(cheese):
    """No hole on or next to a TSV, an indium bump, UBM or an airbridge (pads and flyover): each is kept
    ``other_margin`` + ``clearance`` (9 + 4 µm) clear, and none of them is on the 3/0 mask layer."""
    import quantcore_circuits as qcc
    from quantcore_circuits.layouts.wafers.fab_export import CHEESE_CLEAR_LAYERS, fab_regions
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk()
    # a feedline, so the "pdk" band has a 3/0 to grow around
    instances = {**VIAS_BUMPS_BRIDGES, "S": ("WaveguideCoplanar", _stub(10.0, 6.0), (3000, 2150))}
    routes = {"FL": {"from": {"at": [1000, 2150], "dir": 0, "term": 0}, "to": "S.a"}}
    built = qcc.build(_design("vias_bumps", instances, routes, cheese=cheese))
    dbu = built.layout.dbu
    holes = _holes(built)
    assert holes.count() > 100
    reach = round((pdk.keepout.other_margin + pdk.cheese.clearance) / dbu) - 2
    m3 = fab_regions(built.cell, box=pya.DBox(*built.design.chip.box), grid=False)["M3"]
    for name in CHEESE_CLEAR_LAYERS:
        shapes = _layer(built, "1t1", name)
        assert not shapes.is_empty(), name
        assert holes.interacting(shapes.sized(reach)).is_empty(), f"a cheese hole within 13 µm of {name}"
        assert (shapes & m3).is_empty(), f"{name} is not a 1/0 feature: 3/0 is unchanged"
    if cheese == "chip":  # the whole-die cheese is still there right beside them
        bump = _layer(built, "1t1", "indium_bump")
        assert not holes.interacting(bump.sized(round(60 / dbu))).is_empty()


def test_cheese_band_is_not_grown_around_vias():
    """``cheese_holes(..., avoid=...)``: the avoid region only removes holes; the band still follows 3/0 alone."""
    from quantcore_circuits.layouts.wafers.fab_export import cheese_holes
    from quantcore_circuits.pdk import get_pdk

    rule, dbu = get_pdk().cheese, 0.001
    keepout = pya.Region(pya.DBox(0, 0, 200, 200).to_itype(dbu))
    far = pya.Region(pya.DBox(1000, 1000, 1020, 1020).to_itype(dbu))  # a via far from any component
    near = pya.Region(pya.DBox(230, 50, 250, 70).to_itype(dbu))  # a via inside the band
    plain = cheese_holes(keepout, rule, dbu)
    with_avoid = cheese_holes(keepout, rule, dbu, avoid=far + near)
    assert 0 < with_avoid.count() < plain.count()
    assert (with_avoid - plain).is_empty()  # only removed, never added
    gap = round(rule.clearance / dbu)
    assert with_avoid.interacting((far + near).sized(gap - 1)).is_empty()


def test_kqc_ground_bumps_after_the_build_are_kept_clear():
    """KQC places its automatic ground bumps (``with_gnd_bumps``) after the build: the PDK holes on or next to them
    are removed then."""
    import quantcore_circuits as qcc
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk()
    # KQC puts the bump grid inside its top-chip box (face 2b1: 1.5 mm in from the default 10 mm die)
    built = qcc.build(_design("gnd_bumps", {}, box=10000.0, cheese="chip", with_gnd_bumps=True))
    dbu = built.layout.dbu
    bumps, holes = _layer(built, "1t1", "indium_bump"), _holes(built)
    assert bumps.count() > 10 and holes.count() > 100
    reach = round((pdk.keepout.other_margin + pdk.cheese.clearance) / dbu) - 2
    assert holes.interacting(bumps.sized(reach)).is_empty()


def test_whole_kqc_chip_cell_keeps_out_its_etch_not_its_bounding_box():
    """A KQC chip PCell placed as one instance (KQC's Stripes test chip): 3/0 is its etch grown by
    ``other_margin``, not its bounding box + ``component_margin`` (nearly the whole die), so the cheese reaches the
    ground between the stripes."""
    import quantcore_circuits as qcc
    from kqcircuits.chips.stripes import Stripes
    from kqcircuits.elements.finger_capacitor_square import FingerCapacitorSquare

    from quantcore_circuits.layouts.wafers.fab_export import _is_chip, etch_region, keepout_region
    from quantcore_circuits.pdk import get_pdk

    assert _is_chip(Stripes) and not _is_chip(FingerCapacitorSquare) and not _is_chip(None)
    pdk = get_pdk()
    built = qcc.build(
        _design("stripes_cell", {"CHIP": ("Stripes", {"frames_enabled": []}, (0, 0))}, box=10000.0, cheese="chip")
    )
    dbu = built.layout.dbu
    etch = etch_region(built.cell, pdk.face, grid=False)
    keep = keepout_region(built.cell, pdk, etch)
    margin = round(pdk.keepout.other_margin / dbu)
    assert (etch.sized(margin - 1) - keep).is_empty()  # every etched shape is covered, with its margin
    assert keep.area() < 0.7 * etch.bbox().area()  # not the chip's bounding box
    holes = _holes(built)
    inside = pya.Region(etch.bbox().enlarged(-round(500 / dbu)))
    assert (holes & inside).count() > 10000  # the ground between the stripes is cheesed
    assert holes.interacting(keep).is_empty()


def _straight(y: float, waypoint: dict, **route) -> dict:
    """A 375 µm straight route from a free end at x = 1000 to the stub ``T<y>`` at x = 1375."""
    return {
        "from": {"at": [1000, y], "dir": 0, "term": 0},
        "to": f"T{y:.0f}.a",
        "nodes": [waypoint],
        "params": {"taper_length": 100.0},
        **route,
    }


def test_taper_too_long_for_its_straight_ends_at_its_node():
    """A widening taper 51 µm before the route's end ends at its waypoint (KQC would start it there and overshoot the
    end by 49 µm, the line running back over it): length 375 µm, like the mirrored route that tapers at its start; a
    taper that fits keeps its node."""
    import quantcore_circuits as qcc

    routes = {
        "END": _straight(2000, {"at": [1324, 2000], "a": 40.0, "b": 24.0}, a=10.0, b=6.0),  # widens 51 µm before the end
        "START": _straight(2500, {"at": [1051, 2500], "a": 10.0, "b": 6.0}, a=40.0, b=24.0),  # narrows 51 µm after it
        "FITS": _straight(3000, {"at": [1150, 3000], "a": 40.0, "b": 24.0}, a=10.0, b=6.0),
    }
    stubs = {f"T{y}": ("WaveguideCoplanar", _stub(*ab), (1375, y)) for y, ab in
             ((2000, (40.0, 24.0)), (2500, (10.0, 6.0)), (3000, (40.0, 24.0)))}
    built = qcc.build(_design("tapers", stubs, routes))
    lengths = built.route_lengths()
    assert lengths["END"] == pytest.approx(375.0, abs=1e-3)
    assert lengths["START"] == pytest.approx(375.0, abs=1e-3)
    assert lengths["FITS"] == pytest.approx(375.0, abs=1e-3)
    from kqcircuits.util.node import Node

    from quantcore_circuits.route.router import TAPER_END

    end, fits = built.plan.routes["END"], built.plan.routes["FITS"]
    # the plan keeps the waypoint where the design puts it (plugin handles, waypoint indices) ...
    assert [round(p.x, 6) for p in end.polyline()] == [1000.0, 1100.0, 1324.0, 1375.0]
    assert end.nodes[2].params[TAPER_END] == 100.0 and TAPER_END not in fits.nodes[2].params
    # ... and the cell is built with KQC's taper starting taper_length before it, so it ends at x = 1324
    kqc = Node.nodes_from_string(end.node_strings())
    assert round(kqc[2].position.x, 6) == 1224.0 and TAPER_END not in kqc[2].params
    assert [round(n.position.x, 6) for n in Node.nodes_from_string(fits.node_strings())][2] == 1150.0  # fits as is
    gap = built.layout.layer(default_layers["1t1_base_metal_gap_wo_grid"])
    for inst in built.cell.each_inst():
        if inst.property("id") == "END":
            etch = pya.Region(built.layout.cell(inst.cell_index).begin_shapes_rec(gap)).transformed(inst.cplx_trans)
            assert etch.bbox().right * built.layout.dbu == pytest.approx(1375.0, abs=1e-3)  # no overshoot


def test_snapshots_hide_every_faces_centre_lines():
    """The snapshot hides ``waveguide path`` on every face, and the Quantcore layer properties show each face like
    1t1 (KQC's own file shows ``2t1 waveguide path``); the cheese stays visible and real geometry is not hidden."""
    from quantcore_circuits.live.snapshot import HIDE, layer_props_path

    assert "waveguide path" in HIDE
    path = layer_props_path()
    if path is None:
        pytest.skip("KQC layer properties not found")
    visible = {}  # layer name ("2t1 waveguide path") → visible
    for elem in ET.parse(path).getroot().iter():
        source = elem.findtext("source") or ""
        if elem.tag in ("properties", "group-members") and "'" in source:
            visible[source.split("'")[1]] = elem.findtext("visible") == "true"
    for face in default_faces:
        assert not visible[f"{face} waveguide path"], face
        assert visible[f"{face} ground grid"], face
        for real in ("base metal gap wo grid", "base metal addition", "SIS junction", "airbridge pads",
                     "indium bump", "through silicon via"):
            assert visible[f"{face} {real}"], (face, real)
    hidden = [h.replace("_", " ").lower() for h in HIDE]
    for face in default_faces:
        for real in ("base metal gap wo grid", "indium bump", "underbump metallization", "through silicon via",
                     "airbridge flyover", "ground grid"):
            assert not any(h in f"{face} {real}".lower() for h in hidden), (face, real)


def test_cheese_goes_in_the_ground_plane_only():
    """``ground_region``: the die-edge ground and an enclosed ground of at least ``ground_island_mm2`` (1.5 mm²) get
    holes; an isolated pad (etched around, or drawn as ``base_metal_addition`` inside an etched area) gets none."""
    from quantcore_circuits.layouts.wafers.fab_export import cheese_holes, ground_region
    from quantcore_circuits.pdk import CheeseRule, get_pdk

    pdk, rule = get_pdk(), CheeseRule(fill="chip")
    assert rule.ground_island_mm2 == 1.5
    layout = pya.Layout()
    dbu = layout.dbu
    cell = layout.create_cell("TOP")
    face = default_faces[pdk.face]
    gap = cell.shapes(layout.layer(face["base_metal_gap_wo_grid"]))
    add = cell.shapes(layout.layer(face["base_metal_addition"]))

    def box(x0, y0, x1, y1):
        return pya.DBox(x0, y0, x1, y1).to_itype(dbu)

    ring = pya.Region(box(1000, 1000, 3000, 3000)) - pya.Region(box(1010, 1010, 2990, 2990))  # encloses 3.9 mm²
    gap.insert(ring)
    gap.insert(pya.Region(box(4000, 4000, 5000, 5000)) - pya.Region(box(4100, 4100, 4900, 4900)))  # 0.64 mm² pad
    gap.insert(box(4000, 1000, 5200, 2200))
    add.insert(box(4100, 1100, 5100, 2100))  # a 1.0 mm² pad drawn as metal on an etched area
    die = pya.DBox(0, 0, 6000, 6000)
    ground = ground_region(cell, pdk, die, rule)
    keepout = pya.Region(cell.begin_shapes_rec(layout.layer(face["base_metal_gap_wo_grid"]))).sized(round(9 / dbu))
    allowed = pya.Region(die.to_itype(dbu))
    holes = cheese_holes(keepout, rule, dbu, allowed, ground=ground)
    everywhere = cheese_holes(keepout, rule, dbu, allowed)
    pads = pya.Region(box(4100, 4100, 4900, 4900)) + pya.Region(box(4100, 1100, 5100, 2100))
    assert not (everywhere & pads).is_empty()  # without the ground plane the pads would be cheesed
    assert (holes & pads).is_empty()
    assert not (holes & pya.Region(box(1100, 1100, 2900, 2900))).is_empty()  # the enclosed ground keeps its cheese
    assert not (holes & pya.Region(box(100, 4000, 3000, 5900))).is_empty()  # and the die-edge ground


def test_test_chip_without_a_ground_plane_gets_no_cheese():
    """KQC's DaisyWoven test chip has no ground plane (its metal is probe pads and the chains between them): the
    whole-die cheese puts no hole in it."""
    import quantcore_circuits as qcc

    built = qcc.build(
        _design("daisy_cell", {"DC": ("DaisyWoven", {"frames_enabled": []}, (0, 0))}, box=10000.0, cheese="chip")
    )
    assert _holes(built).is_empty()

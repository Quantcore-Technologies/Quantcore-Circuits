"""Universal Quantcore (QCT) fab rules of the PDK (2026-11-03): cheese around the components (drawn in the build;
the original design's own cheese wins), corner rounding tied to the shortest dimension (fab export), the QCT brand,
the airbridge / TSV / flip-chip fab layers, the pad-edge rule (100 µm) and the PDK-margin design warnings."""

import pytest
from kqcircuits.pya_resolver import pya


@pytest.fixture
def built(example_path):
    import quantcore_circuits as qcc

    return qcc.build(example_path)


def test_cheese_is_a_band_around_the_components(built):
    from quantcore_circuits.layouts.wafers.fab_export import cheese_holes, fab_regions, frame_cheese_limits
    from quantcore_circuits.pdk import CheeseRule, get_pdk

    rule = get_pdk().cheese
    assert (rule.size, rule.gap, rule.rows, rule.pitch) == (5.0, 20.0, 3, 25.0)  # defaults
    dbu = built.layout.dbu
    raw = fab_regions(built.cell, box=pya.DBox(*built.design.chip.box), grid=False)
    allowed, exclude = frame_cheese_limits(built)
    holes = cheese_holes(raw["M3"], rule, dbu, allowed, exclude)
    assert holes.count() > 500
    assert holes.interacting(raw["M3"]).is_empty()  # no hole touches a structure's 3/0 keep-out
    d = round(rule.rows * rule.pitch / dbu)
    assert (holes - raw["M3"].minkowski_sum(pya.Box(-d, -d, d, d))).is_empty()  # only within 3 rows of it (x / y)
    assert (holes - allowed).is_empty() and (holes & exclude).is_empty()  # design area, clear of the frame
    sizes = {(round(p.bbox().width() * dbu, 6), round(p.bbox().height() * dbu, 6)) for p in holes.each()}
    assert sizes == {(5.0, 5.0)}
    xs = sorted({round(p.bbox().center().x * dbu, 6) for p in holes.each()})
    assert all(abs((b - a) % 25.0) < 1e-6 for a, b in zip(xs, xs[1:]))  # on the chip-aligned 25 µm grid
    corner = pya.Region(pya.DBox(4500, 100, 7400, 1000).to_itype(dbu))  # empty ground far from every structure
    assert (holes & corner).is_empty()  # not over the whole chip
    two_rows = cheese_holes(raw["M3"], CheeseRule(rows=2), dbu, allowed, exclude)
    assert 0 < two_rows.count() < holes.count()


def test_export_fab_applies_cheese_and_rounding_but_raw_regions_do_not(built, tmp_path):
    from quantcore_circuits.layouts.wafers.fab_export import export_fab, fab_regions

    box = pya.DBox(*built.design.chip.box)
    raw = fab_regions(built.cell, box=box, grid=False)["M1"]
    report = {}
    path = export_fab(built, tmp_path / "fab.oas", report=report)
    lay = pya.Layout()
    lay.read(str(path))
    m1 = pya.Region(lay.top_cell().begin_shapes_rec(lay.layer(1, 0)))
    assert report["cheese_holes"] > 500 and m1.count() > raw.count() + 500
    assert report["cheese_source"] == "build"  # the build drew the band; the export adds none
    plain = export_fab(built, tmp_path / "plain.oas", cheese=False, rounding=False)
    lay2 = pya.Layout()
    lay2.read(str(plain))
    m1_plain = pya.Region(lay2.top_cell().begin_shapes_rec(lay2.layer(1, 0)))
    assert (m1_plain ^ raw).area() * 1e-6 < 1.0  # both off: the raw etch (up to file round-off)


def test_rounding_radius_follows_the_shortest_dimension():
    from quantcore_circuits.layouts.wafers.fab_export import round_corners, shortest_dimension
    from quantcore_circuits.pdk import CornerRounding

    dbu = 0.001
    rule = CornerRounding()
    strip = pya.Polygon(pya.Box(0, 0, 6000, 400000))  # a 6 µm × 400 µm gap
    pad = pya.Polygon(pya.Box(0, 0, 300000, 300000))  # a 300 µm pad window
    assert shortest_dimension(strip, rule.min_edge / dbu) * dbu == pytest.approx(5.91, abs=0.1)  # ≈ its width
    rs, rp = round_corners(pya.Region(strip), rule, dbu), round_corners(pya.Region(pad), rule, dbu)
    assert rs.count() == 1 and next(rs.each()).num_points() > 4
    # area removed at 4 convex corners = (4 − π) r²: r ≈ 1.5 µm for the strip, the 10 µm cap for the pad
    lost_strip = (pya.Region(strip).area() - rs.area()) * dbu**2
    lost_pad = (pya.Region(pad).area() - rp.area()) * dbu**2
    assert lost_strip == pytest.approx((4 - 3.14159) * 1.48**2, rel=0.15)
    assert lost_pad == pytest.approx((4 - 3.14159) * 10.0**2, rel=0.05)
    middle = pya.Region(pya.Box(0, 5000, 6000, 395000))
    assert ((pya.Region(strip) - rs) & middle).is_empty()  # only the corners change, the strip keeps its width


def test_brand_is_qct_and_new_layers_map():
    from quantcore_circuits.assembly.plan import element_params
    from quantcore_circuits.layouts.chips.design_chip import DesignChip
    from quantcore_circuits.layouts.registry import resolve_cell
    from quantcore_circuits.pdk import get_pdk

    assert DesignChip.get_schema()["name_brand"].default == "QCT"
    assert element_params(resolve_cell("Demo"), {}, {})["name_brand"] == "QCT"  # whole KQC chips as cells
    assert element_params(resolve_cell("Demo"), {}, {"name_brand": "X"})["name_brand"] == "X"
    layers = {name: (fl.layer, fl.datatype) for name, fl in get_pdk().fab_layers.items()}
    assert layers["AIRBRIDGE_PADS"] == (300, 0) and layers["TSV"] == (700, 0) and layers["FC_M1"] == (800, 0)
    assert get_pdk().brand == "QCT"


def test_3_0_is_a_filled_keepout_per_route_and_component(built, monkeypatch):
    """Design rule: 3/0 = each 1/0 feature *and* what lies between its gaps (CPW centre conductor, qubit island) plus
    ground margin; routes follow the CPW, components get a rectangle (or their own ``qcc_keepout``)."""
    from quantcore_circuits.layouts import Xmon
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    dbu = built.layout.dbu
    raw = fab_regions(built.cell, box=pya.DBox(*built.design.chip.box))
    m1, m3 = raw["M1"], raw["M3"]
    plain = fab_regions(built.cell, box=pya.DBox(*built.design.chip.box), grid=False)
    cheese = m1 - plain["M1"]
    m3 = plain["M3"]  # the keep-outs; the cheese holes are on 3/0 as well (see test_cheese_is_on_3_0_too)
    assert cheese.count() > 500 and cheese.interacting(m3).is_empty()  # the build's cheese band stays out of the keep-outs
    assert (m1 - cheese - m3).is_empty() and all(p.holes() == 0 for p in m3.each())
    centre = pya.Region(pya.DBox(2000, 3746, 2200, 3754).to_itype(dbu))  # feedline centre conductor (metal)
    assert (centre - m3).is_empty()
    q1 = built.plan.instances["Q1"]  # the Xmon carries its legacy-PCell keep-out (qcc_keepout): all of it in 3/0
    own = pya.Region()
    for shape in Xmon.qcc_keepout(dict(q1.params)):
        own.insert((pya.DPolygon(shape) if isinstance(shape, pya.DBox) else shape).transformed(q1.trans).to_itype(dbu))
    assert ((own - m3).area() * dbu**2) < 1.0
    assert own.area() * dbu**2 > 100 * 100  # a big region engulfing ground around the cross, not the 1/0 outline

    calls = []

    def own_keepout(params):  # a cell's own legacy-style keep-out overrides the bbox rule
        calls.append(params)
        return [pya.DBox(-1000, -1000, 1000, 1000)]

    monkeypatch.setattr(Xmon, "qcc_keepout", staticmethod(own_keepout), raising=False)
    m3_own = fab_regions(built.cell, box=pya.DBox(*built.design.chip.box))["M3"]
    assert calls and m3_own.area() > m3.area()


def test_cheese_is_drawn_in_the_build_unless_the_original_has_its_own(example_path):
    """Decision, 2026-11-03: layouts show the PDK band; a design with its own cheese keeps it (the original wins); the
    simulation export never has any."""
    from kqcircuits.defaults import default_layers

    import quantcore_circuits as qcc
    from quantcore_circuits.assembly.plan import pdk_cheese
    from quantcore_circuits.design import load_design
    from quantcore_circuits.layouts.wafers.fab_export import cheese_holes, fab_regions, frame_cheese_limits
    from quantcore_circuits.pdk import get_pdk
    from quantcore_circuits.sim_tools.builder import simulation_design

    def grid(result):
        return pya.Region(result.cell.begin_shapes_rec(result.layout.layer(default_layers["1t1_ground_grid"])))

    design = load_design(example_path)
    built = qcc.build(design)
    drawn = grid(built)
    raw = fab_regions(built.cell, box=pya.DBox(*design.chip.box), grid=False)
    allowed, exclude = frame_cheese_limits(built)
    expected = cheese_holes(raw["M3"], get_pdk().cheese, built.layout.dbu, allowed, exclude)
    assert drawn.count() > 500 and (drawn ^ expected).is_empty()  # the band of the fab rule, in the layout
    assert drawn.interacting(raw["M3"]).is_empty()

    original = design.model_copy(deep=True)
    original.chip.params["cheese"] = "original"
    assert not pdk_cheese(original) and grid(qcc.build(original)).is_empty()
    own = design.model_copy(deep=True)
    own.chip.params["with_grid"] = True  # the original's whole-area grid
    assert not pdk_cheese(own)
    sim, _ = simulation_design(design, "Q1R1", "q3d_cmatrix")
    assert not pdk_cheese(sim) and grid(qcc.build(sim)).is_empty()


def test_pads_sit_the_pdk_pad_distance_from_the_die_edge(example_path):
    """PDK pad rule (2026-11-03; 100 µm since 2026-11-10): place.edge puts a pad's outer etch ``pad_edge`` from
    the die edge; the DRC flags pads elsewhere."""
    from quantcore_circuits.assembly import drc
    from quantcore_circuits.assembly.sidecar import sidecar_dict
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.pdk import get_pdk

    edge = get_pdk().frame.pad_edge
    assert edge == get_pdk().frame.margin == 100.0  # 2026-11-10 (was one dicing-marker width, 25 µm)
    d = Designer.load(example_path, verbose=False)
    to = dict(d.data["routes"]["R1"]["to"])
    to.pop("s")
    to["near"] = [3125.0, 3700.0]  # the coupler stays put when the feedline's start moves with PAD_W
    d["R1"].set(to=to)
    before = {i.objects[0] for i in drc.check(d.show(), netlist=False).issues if i.rule == "pad_edge"}
    assert {"PAD_W", "PAD_E", "PAD_F"} <= before
    d["PAD_W"].move(edge="w")
    d["PAD_E"].move(edge="auto")
    d["PAD_F"].move(edge="s")
    result = d.show()
    box = sidecar_dict(result, overlays=False)["instances"]
    x0, y0, x1, y1 = result.design.chip.box
    assert box["PAD_W"]["bbox"][0] - x0 == pytest.approx(edge)
    assert x1 - box["PAD_E"]["bbox"][2] == pytest.approx(edge)
    assert box["PAD_F"]["bbox"][1] - y0 == pytest.approx(edge)
    assert box["PAD_F"]["bbox"][0] == pytest.approx(2664.5)  # the position along the edge is kept
    assert not [i for i in drc.check(result, netlist=False).issues if i.rule == "pad_edge"]


def test_hanger_near_point_matches_arclength(example_path):
    """``near=(x, y)`` keeps a hanger where it is when the feedline's start moves (pads moved to the die edge)."""
    from quantcore_circuits.designer import Designer

    d = Designer.load(example_path, verbose=False)
    base = d.show().plan.routes["R1"]
    to = dict(d.data["routes"]["R1"]["to"])
    s = to.pop("s")
    mid = base.nodes[-1].position + (base.nodes[-2].position - base.nodes[-1].position) * 0.5  # coupler centre
    to["near"] = [mid.x, mid.y + 50.0]  # any point beside it
    d["R1"].set(to=to)
    moved = d.show().plan.routes["R1"]
    assert s is not None and moved.nodes[-1].position == base.nodes[-1].position  # same coupler
    d["PAD_W"].move(edge="w")
    assert d.show().plan.routes["R1"].nodes[-1].position == base.nodes[-1].position  # unaffected by the pad move


def test_tapered_pad_rings_are_bond_pads():
    """Decision, 2026-11-18: a ``TaperedPad`` (chip_06's wire-bond rings) counts as a bond pad, so the ``pad_edge`` DRC
    checks its etch window against the 100 µm rule: one at the rule passes, one flush with the die edge is flagged."""
    from quantcore_circuits.assembly import drc
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.pdk import get_pdk

    assert drc._bond_pad("TaperedPad")  # pylint: disable=protected-access
    edge = get_pdk().frame.pad_edge
    ring = {"pad_width": 800, "pad_height": 800, "conn_height": 0.001, "finger_width": 800, "window_width": 1000,
            "window_height": 1000, "x": 0, "y": 100}  # chip_06's ring: an 800 µm pad in a 1000 µm window
    d = Designer("t_rings", box=(0, 0, 6000, 6000), verbose=False)
    with d.batch():
        d.add("WB_ok", "TaperedPad", at=(3000, 6000 - edge - 1000), **ring)  # window from its origin up
        d.add("WB_flush", "TaperedPad", at=(1500, 6000 - 1000), **ring)
    flagged = {i.objects[0] for i in drc.check(d.show(), netlist=False).issues if i.rule == "pad_edge"}
    assert flagged == {"WB_flush"}


def test_kqc_launchers_follow_the_pad_edge_rule():
    from kqcircuits.defaults import default_layers

    from quantcore_circuits.designer import Designer
    from quantcore_circuits.pdk import get_pdk

    d = Designer("t_sma8", box=(0, 0, 10000, 10000), launchers="SMA8", verbose=False)
    result = d.show()
    layout = result.layout
    etch = layout.layer(default_layers["1t1_base_metal_gap_wo_grid"])
    launchers = [
        layout.cell(inst.cell_index).dbbox_per_layer(etch).transformed(inst.dcplx_trans)
        for inst in result.cell.each_inst()
        if layout.cell(inst.cell_index).name.startswith("Launcher")
    ]
    assert len(launchers) == 8
    dist = sorted(round(min(b.left, b.bottom, 10000 - b.right, 10000 - b.top), 3) for b in launchers)
    assert dist == [get_pdk().frame.pad_edge] * 8  # KQC's SMA8 preset leaves 20 µm


def test_pdk_margin_warnings():
    """Design warnings (2026-11-03): flagged, never enforced."""
    from quantcore_circuits.assembly.drc import pdk_margin_issues
    from quantcore_circuits.circuit.bridges import lj_from_rn
    from quantcore_circuits.design import Design

    lj_45k = lj_from_rn(45e3)  # a PDK-nominal single junction
    design = Design.model_validate(
        {
            "name": "t_margins",
            "instances": {
                "Q1": {
                    "cell": "Swissmon",
                    "place": {"at": [3000, 3000]},
                    "params": {"junction_type": "Quantcore Junction"},
                    "junction": {"Lj_nH": 3 * lj_45k},
                },
                "Q2": {
                    "cell": "Swissmon",
                    "place": {"at": [5000, 3000]},
                    "params": {"junction_type": "Quantcore Junction"},
                    "junction": {"Lj_nH": lj_45k},
                },
                "Q3": {"cell": "Swissmon", "place": {"at": [5000, 5000]}, "junction": {"Lj_nH": lj_45k}},
                "X": {
                    "cell": "metal:TransmonCross",
                    "place": {"at": [3000, 5000]},
                    "params": {
                        "cross_length": "200um",
                        "cross_width": "30um",
                        "connection_pads": {"a": {"claw_length": "220um", "ground_spacing": "5um"}},
                    },
                },
            },
            "targets": {"Q1": {"f_q_GHz": 3.2}, "Q2": {"f_q_GHz": 5.5}},
        }
    )
    issues = {(i.rule, i.objects[0]) for i in pdk_margin_issues(design, {})}
    assert ("pdk_rn", "Q1") in issues and ("pdk_rn", "Q2") not in issues
    assert ("pdk_rn", "Q3") not in issues  # a SQUID (unset → Quantcore Squid) is judged as a device: 45 kΩ
    assert ("pdk_fq", "Q1") in issues and ("pdk_fq", "Q2") not in issues
    assert ("pdk_claw", "X") in issues


def test_unset_junctions_default_to_the_quantcore_trilayer():
    """Decision #36: every junction of the Quantcore PDK is the trilayer Quantcore junction."""
    from quantcore_circuits.assembly.plan import element_params
    from quantcore_circuits.layouts.registry import resolve_cell

    swissmon = resolve_cell("Swissmon")
    assert element_params(swissmon, {}, {})["junction_type"] == "Quantcore Squid"
    assert element_params(swissmon, {}, {"junction_type": "Sim"})["junction_type"] == "Sim"  # explicit choices stay
    assert element_params(resolve_cell("metal:TransmonCross"), {}, {})["junction_type"] == "Quantcore Junction"


def test_export_honours_the_original_cheese(example_path, tmp_path):
    """A design marked cheese "original" (its own holes, e.g. legacy flux holes drawn on the etch) gets no PDK band
    at export either."""
    import quantcore_circuits as qcc
    from quantcore_circuits.design import load_design
    from quantcore_circuits.layouts.wafers.fab_export import export_fab

    design = load_design(example_path)
    design.chip.params["cheese"] = "original"
    report = {}
    export_fab(qcc.build(design), tmp_path / "orig.oas", report=report)
    assert report["cheese_holes"] == 0 and report["cheese_source"] == "original"


def test_a_design_can_draw_its_original_cheese_rule(example_path):
    """The original wins: chip cheese as a dict (e.g. Quantum Metal's GDS cheese: 25 µm squares on a 100 µm pitch,
    25 µm from all geometry, 200 µm from the edge) is drawn instead of the PDK band."""
    from kqcircuits.defaults import default_layers

    import quantcore_circuits as qcc
    from quantcore_circuits.assembly.plan import cheese_spec
    from quantcore_circuits.design import load_design
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    design = load_design(example_path)
    design.chip.params["cheese"] = {"size": 25, "gap": 75, "rows": 1000, "clearance": 25, "edge": 200}
    assert cheese_spec(design)["rule"]["size"] == 25 and cheese_spec(design)["edge"] == 200
    built = qcc.build(design)
    dbu = built.layout.dbu
    holes = pya.Region(built.cell.begin_shapes_rec(built.layout.layer(default_layers["1t1_ground_grid"])))
    sizes = {(round(p.bbox().width() * dbu, 6), round(p.bbox().height() * dbu, 6)) for p in holes.each()}
    assert holes.count() > 1000 and sizes == {(25.0, 25.0)}
    m3 = fab_regions(built.cell, box=pya.DBox(*design.chip.box), grid=False)["M3"]
    assert holes.interacting(m3.sized(round(24.9 / dbu))).is_empty()  # ≥ 25 µm from every keep-out
    inner = pya.Region(pya.DBox(*design.chip.box).enlarged(-200, -200).to_itype(dbu))
    assert (holes - inner).is_empty()  # 200 µm edge band
    corner = pya.Region(pya.DBox(4500, 100, 7400, 1000).to_itype(dbu))
    assert not (holes & corner).is_empty()  # whole-area cheese, not a band
    design.chip.params["cheese"] = {"pitch": 3}
    with pytest.raises(ValueError, match="unknown field"):
        cheese_spec(design)


def test_3_0_fills_features_but_not_enclosed_ground(built):
    """3/0 covers each feature filled (a bond pad's legacy ring hook covers its metal too), while a large ground
    area enclosed by several keep-outs (inside a closed bus ring) stays outside it, so the cheese reaches it
    (notebooks-metal, 2026-11-10)."""
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions, fill_small_holes

    m3 = fab_regions(built.cell, box=pya.DBox(*built.design.chip.box))["M3"]
    assert all(p.holes() == 0 for p in m3.each())  # q1_r1: no enclosed ground; the pads are filled
    ring = pya.Region(pya.Box(0, 0, 1000, 1000)) - pya.Region(pya.Box(100, 100, 900, 900))  # an 800 µm hole (dbu=1)
    ring += pya.Region(pya.Box(2000, 0, 2100, 100)) - pya.Region(pya.Box(2040, 40, 2060, 60))  # a 20 µm hole
    kept = fill_small_holes(ring.merged(), 200 * 200)
    holes = sorted(pya.Polygon(list(p.each_point_hole(0)), True).area() for p in kept.each() if p.holes())
    assert holes == [800 * 800]  # the large one stays, the small one is filled


def test_cheese_stays_4um_from_3_0_and_routes_reach_10um_past_their_gaps(built):
    """Fab change 2026-11-17: no cheese hole within 4 µm of 3/0, and a route's 3/0 is its CPW footprint + 10 µm."""
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk()
    assert (pdk.keepout.route_margin, pdk.keepout.component_margin, pdk.keepout.other_margin) == (10.0, 24.0, 9.0)
    assert pdk.keepout.own_grow == 4.0 and pdk.cheese.clearance == 4.0
    dbu = built.layout.dbu
    box = pya.DBox(*built.design.chip.box)
    m3 = fab_regions(built.cell, box=box, grid=False)["M3"]
    cheese = fab_regions(built.cell, box=box)["M1"] - fab_regions(built.cell, box=box, grid=False)["M1"]
    assert cheese.count() > 500
    d = round(4.0 / dbu) - 1  # the holes lie outside 3/0 grown by 4 µm (a square: stricter than Euclidean)
    assert cheese.interacting(m3.minkowski_sum(pya.Box(-d, -d, d, d))).is_empty()
    # feedline straight at y = 3750: centre 10 µm + gaps 2 x 6 µm = +-11 µm, 3/0 = +-21 µm
    x0, x1 = round(2000 / dbu), round(2200 / dbu)

    def strip(y0, y1):
        return pya.Region(pya.Box(x0, round(y0 / dbu), x1, round(y1 / dbu)))

    assert (strip(3750 - 20.9, 3750 + 20.9) - m3).is_empty()  # 10 µm past each gap edge
    assert (strip(3750 + 21.1, 3750 + 22.0) & m3).is_empty() and (strip(3750 - 22.0, 3750 - 21.1) & m3).is_empty()


def _read_fab(path):
    """{fab layer name: Region} of a written fab file."""
    from quantcore_circuits.pdk import get_pdk

    layout = pya.Layout()
    layout.read(str(path))
    top = layout.top_cell()
    by_number = {(i.layer, i.datatype): idx for idx, i in zip(layout.layer_indexes(), layout.layer_infos())}
    return {
        name: pya.Region(list(p.polygon for p in top.shapes(by_number[fl.layer, fl.datatype]).each()))
        for name, fl in get_pdk().fab_layers.items()
        if (fl.layer, fl.datatype) in by_number
    }


def test_cheese_is_on_3_0_too(example_path, tmp_path):
    """Fab change 2026-11-17: every cheese hole on 1/0 is also on 3/0 (the same squares, not grown): 3/0 = the
    keep-outs + the holes, for the PDK band, for the band the export adds, and for a design's own grid; ``cheese=False``
    puts holes on neither layer. Regions are compared in memory (an OASIS round trip moves a big polygon by 0.05 µm²)."""
    import quantcore_circuits as qcc
    from quantcore_circuits.design import load_design
    from quantcore_circuits.layouts.wafers.fab_export import export_fab, fab_regions, frame_cheese_limits
    from quantcore_circuits.pdk import get_pdk

    dbu = 0.001
    plain_design = load_design(example_path)
    box = pya.DBox(*plain_design.chip.box)

    def regions(result, rounding, **kw):
        return fab_regions(result.cell, box=box, rounding=rounding, **kw)

    # 1. the build's PDK band
    built = qcc.build(plain_design)
    old, new = regions(built, True, grid=False), regions(built, True)
    holes = new["M1"] - old["M1"]
    assert holes.count() > 500 and (old["M1"] - new["M1"]).is_empty()
    assert (new["M3"] ^ (old["M3"] + holes)).is_empty() and (new["M3"] - old["M3"]).area() > 0
    d = round(get_pdk().cheese.clearance / dbu) - 1  # the clearance is to the keep-outs, not to the holes themselves
    assert holes.interacting(old["M3"].minkowski_sum(pya.Box(-d, -d, d, d))).is_empty()
    for name in new:  # nothing else changes
        if name not in ("M1", "M3"):
            assert (new[name] ^ old[name]).is_empty(), name
    report = {}
    export_fab(built, tmp_path / "band.oas", report=report)
    assert report["cheese_source"] == "build" and report["cheese_holes"] == holes.count()

    # 2. the band the export adds (a design marked "original" without holes of its own; cheese=rule adds the band)
    exp = plain_design.model_copy(deep=True)
    exp.chip.params["cheese"] = "original"
    built_exp = qcc.build(exp)
    allowed, exclude = frame_cheese_limits(built_exp)
    old = regions(built_exp, True, grid=False)
    new = regions(built_exp, True, cheese=get_pdk().cheese, cheese_allowed=allowed, cheese_exclude=exclude)
    holes = new["M1"] - old["M1"]
    assert holes.count() > 500 and (new["M3"] ^ (old["M3"] + holes)).is_empty()
    report = {}
    export_fab(built_exp, tmp_path / "export.oas", report=report, cheese=get_pdk().cheese)
    assert report["cheese_source"] == "export" and report["cheese_holes"] == holes.count()

    # 3. a design's own cheese (KQC's whole-area grid): kept, and on 3/0 as well
    own = plain_design.model_copy(deep=True)
    own.chip.params["with_grid"] = True
    built_own = qcc.build(own)
    old, new = regions(built_own, None, grid=False), regions(built_own, None)
    holes = new["M1"] - old["M1"]
    assert holes.count() > 500 and (new["M3"] ^ (old["M3"] + holes)).is_empty()
    assert (new["M3"] - old["M3"]).area() > 0

    # 4. --no-cheese: holes on neither layer, 3/0 = the keep-outs
    for result, rounding in ((built, True), (built_own, False)):
        report = {}
        path = export_fab(result, tmp_path / "none.oas", cheese=False, rounding=rounding, report=report)
        got = _read_fab(path)
        ref = regions(result, True if rounding else None, grid=False)
        assert report["cheese_holes"] == 0
        assert (got["M1"] ^ ref["M1"]).area() * dbu**2 < 0.5 and (got["M3"] ^ ref["M3"]).area() * dbu**2 < 0.5

"""Designer features beyond the single-qubit example: chip launchers, arrays, wrapper-cell parameter hooks."""

import pytest

from quantcore_circuits.designer import Designer


def test_chip_launchers_are_routable_ports():
    d = Designer("t_launchers", box=(0, 0, 10000, 10000), launchers="SMA8", verbose=False)
    assert {"WN", "EN", "SW"} <= set(d.chip_ports)
    q = d.add("q1", "Xmon", at=(5000, 4600))
    fl = d.route("fl", "chip.WN", "chip.EN")
    d.route("r1", q.claw_n, fl.hanger(s=4000, length=300, side="right"), meander=4000)
    result = d.show()
    assert set(result.plan.routes) == {"fl", "r1"}
    with pytest.raises(ValueError, match="chip launchers"):
        d.route("bad", "chip.XX", "q1.claw_n")


def test_array_places_a_grid_with_a_parameter_sweep():
    d = Designer("t_array", box=(0, 0, 10000, 10000), verbose=False)
    pads = d.array(
        "p",
        "BondPad",
        origin=(1000, 1000),
        pitch=(1500, 1200),
        shape=(3, 2),
        vary={"pad_width": [200, 210, 220, 230, 240, 250]},
    )
    assert [h.name for h in pads] == ["p_0_0", "p_0_1", "p_1_0", "p_1_1", "p_2_0", "p_2_1"]
    assert d.data["instances"]["p_2_1"]["place"]["at"] == [4000.0, 2200.0]
    assert d.data["instances"]["p_1_1"]["params"]["pad_width"] == 230
    d.show()


def test_wrapper_cells_convert_their_own_parameters(monkeypatch):
    from quantcore_circuits.assembly.plan import element_params, pcell_params
    from quantcore_circuits.layouts import BondPad

    calls = []

    def qcc_params(params):
        calls.append(params)
        return {"pad_width": params.pop("width")}

    monkeypatch.setattr(BondPad, "qcc_params", staticmethod(qcc_params), raising=False)
    assert pcell_params(BondPad, {"width": 210}) == {"pad_width": 210}
    assert element_params(BondPad, {}, {"width": 220})["pad_width"] == 220
    d = Designer("t_hook", verbose=False)
    d.add("p", "BondPad", at=(5000, 5000), width=230)  # not a PCell parameter: the hook validates it
    assert calls


def test_netlist_matches_unnamed_kqc_ports():
    """KQC Launcher's port is unnamed (refpoint ``port``); KLayout's netlist calls the pin ``$0``."""
    from quantcore_circuits.assembly.netlist import check_netlist

    d = Designer("t_launcher_pins", box=(0, 0, 4000, 2000), verbose=False)
    a = d.add("A", "Launcher", at=(800, 1000), rot=180)
    b = d.add("B", "Launcher", at=(3200, 1000), rot=0)
    d.route("FL", a.port, b.port)
    assert check_netlist(d.show()).ok


def test_named_launcher_subset():
    d = Designer(
        "t_ard",
        box=(0, 0, 10000, 10000),
        launchers={"type": "ARD24", "assign": {2: "FL_IN", 3: "FL_OUT"}},
        verbose=False,
    )
    assert set(d.chip_ports) == {"FL_IN", "FL_OUT"}
    d.route("FL", "chip.FL_IN", "chip.FL_OUT")
    d.show()
    assert "couplings" not in d.design.to_json_dict()  # optional section stays out of existing designs


def test_declared_coupling_is_validated_and_saved(tmp_path):
    from quantcore_circuits.design import load_design

    d = Designer("t_couple", verbose=False)
    d.add("QB1", "Swissmon", at=(3000, 5000))
    d.add("QB2", "Swissmon", at=(3400, 5000))
    d.couple("C12", "QB1", "QB2", C_fF=0.4, note="arm tips 10 µm apart")
    with pytest.raises(ValueError, match="no instance"):
        d.couple("bad", "QB1", "QB9")
    path = d.save(tmp_path / "c.json")
    c = load_design(path).couplings["C12"]
    assert (c.between, c.type, c.value) == (("QB1", "QB2"), "C", 0.4)


def test_pdk_die_frame_and_layer_map(tmp_path):
    """components/pdk_geometry_summary.md: dicing Ls, 3×3 alignment grids, device ID; v2 fab layer numbers."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.drc import check
    from quantcore_circuits.layouts.chips.frame import frame_shapes, keepouts
    from quantcore_circuits.layouts.wafers.fab_export import export_fab
    from quantcore_circuits.pdk import get_pdk

    frame = get_pdk().frame
    box = pya.DBox(0, 0, 7500, 7500)
    shapes = frame_shapes(box, frame)
    assert len(shapes["marker_0"]) == 8 and len(shapes["marker_1"]) == 36
    sw = sorted(
        (b.center().x, b.center().y, b.width())
        for b in shapes["marker_1"]
        if b.center().x < 1000 and b.center().y < 1000
    )
    assert sw[0] == (302.5, 305.0, 5.0) and (452.5, 305.0, 10.0) in sw and (452.5, 452.5, 5.0) in sw
    assert keepouts(box, frame)["device_id"] == pya.DBox(3400, 100, 4100, 400)

    chip = {"name_chip": "QC01", "device_id_side": "bottom"}  # fixed side: the pad below really overlaps the ID
    d = Designer("t_frame", box=(0, 0, 7500, 7500), chip=chip, verbose=False)
    d.add("P1", "BondPad", at=(3750, 250), rot=0)  # a pad may reach the edge, but not the device ID
    d.add("Q1", "Xmon", at=(7450, 3750))  # in the margin
    report = check(d.show(), netlist=False)
    kinds = {i.rule for i in report.issues}
    assert {"frame_keepout", "frame_margin"} <= kinds
    path = export_fab(d.result, tmp_path / "fab.oas")
    lay = pya.Layout()
    lay.read(str(path))
    nums = {(li.layer, li.datatype) for li in lay.layer_infos()}
    assert {(1, 0), (2, 0), (3, 0), (4, 0), (50, 0), (100, 0), (1000, 0), (1001, 0)} <= nums
    assert (150, 0) not in nums


def test_device_id_moves_to_the_first_empty_side():
    """Design rule (2026-11-03): the device ID sits at the bottom unless the design occupies that spot; then it goes to
    the first empty side (top, left, right). The DRC keep-out and the ground grid follow it."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly.drc import check, device_id_block
    from quantcore_circuits.layouts.chips.frame import device_id_box
    from quantcore_circuits.pdk import get_pdk

    frame, box = get_pdk().frame, pya.DBox(0, 0, 7500, 7500)
    pads = {
        "bottom": ((3750, 250), 0),
        "top": ((3750, 7250), 180),
        "left": ((250, 3750), 270),
        "right": ((7250, 3750), 90),
    }

    def chip_with(sides, **chip):
        d = Designer("t_devid", box=(0, 0, 7500, 7500), chip={"name_chip": "QC01", **chip}, verbose=False)
        for side in sides:
            at, rot = pads[side]
            d.add(f"P_{side}", "BondPad", at=at, rot=rot)
        return d, d.show()

    for occupied, expected in (
        ([], "bottom"),
        (["bottom"], "top"),
        (["bottom", "top"], "left"),
        (["bottom", "top", "left"], "right"),
    ):
        d, result = chip_with(occupied)
        block = device_id_block(result)
        assert block == device_id_box(box, frame, expected), (occupied, block)
        assert not [i for i in check(result, netlist=False).issues if i.rule == "frame_keepout"], occupied
        text = pya.Region(result.cell.begin_shapes_rec(result.layout.layer(pya.LayerInfo(130, 1))))
        text &= pya.Region(block.to_itype(result.layout.dbu))
        assert not text.is_empty()  # the chip name is etched inside the chosen block
        if expected in ("left", "right"):
            assert block.height() > block.width()  # turned 90° on the sides

    d, result = chip_with(list(pads))  # every edge centre taken: slides along the bottom to the nearest free spot
    block = device_id_block(result)
    assert block.bottom == device_id_box(box, frame, "bottom").bottom and block.center().x != 3750
    assert not [i for i in check(result, netlist=False).issues if i.rule == "frame_keepout"]
    etched = pya.Region(result.cell.begin_shapes_rec(result.layout.layer(pya.LayerInfo(130, 1))))
    pad = etched & pya.Region(pya.DBox(3000, 0, 4500, 1000).to_itype(result.layout.dbu))  # the bottom pad only
    gap = min(
        abs(block.left - pad.bbox().to_dtype(result.layout.dbu).right),
        abs(pad.bbox().to_dtype(result.layout.dbu).left - block.right),
    )
    assert gap >= 25.0 - 1e-6  # clearance to the pad

    from quantcore_circuits.layouts.chips.frame import choose_device_id

    full = pya.Region(box.to_itype(0.001))  # nothing free anywhere: the ID is optional (design rule) → none
    assert choose_device_id(box, frame, full, 0.001) == (None, None)

    # beside a feedline pad, 50 µm away, when every edge centre is taken (design rule)
    pad = pya.DBox(3450, 100, 4050, 700)
    busy = pya.Region()
    for s in ("top", "left", "right"):  # the bottom centre is taken by the pad itself
        busy.insert(device_id_box(box, frame, s).to_itype(0.001))
    side, block = choose_device_id(box, frame, busy + pya.Region(pad.to_itype(0.001)), 0.001, anchors=[pad])
    assert side == "bottom" and (abs(block.right - (pad.left - 50)) < 1e-6 or abs(block.left - (pad.right + 50)) < 1e-6)

    # a chip without an ID (no name, or no room) keeps no device-ID keep-out, and the DRC does not warn about it
    d = Designer("t_noid", box=(0, 0, 7500, 7500), chip={"name_chip": ""}, verbose=False)
    d.add("P", "BondPad", at=(3750, 250), rot=0)  # sits where the bottom ID would be
    result = d.show()
    assert device_id_block(result) is False
    assert not [i for i in check(result, netlist=False).issues if "device" in i.message]

    d, result = chip_with([], device_id_side="right")  # a fixed side is honoured
    assert device_id_block(result) == device_id_box(box, frame, "right")


def test_load_does_not_rewrite_its_source_unless_live_or_asked(example_path, tmp_path):
    """``Designer.load`` + ``show()`` used to save back to the source even headless (it overwrote shared examples)."""
    import shutil

    src = shutil.copy(example_path, tmp_path / "d.json")
    before = src.read_text(encoding="utf-8")
    d = Designer.load(src, out=tmp_path / "d.oas", verbose=False)  # live=False → no autosave
    d["Q1"].set(cross_length=333)
    d.show()
    assert src.read_text(encoding="utf-8") == before
    d = Designer.load(src, out=tmp_path / "d.oas", verbose=False, autosave=True)
    d["Q1"].set(cross_length=333)
    d.show()
    assert '"cross_length": 333' in src.read_text(encoding="utf-8")


def test_snap_placement_keeps_mirror():
    """``Designer.add(..., snap=, to=, mirror=True)`` used to drop ``mirror``; the snapped port still coincides."""
    from quantcore_circuits.assembly import plan_design

    d = Designer("snapmirror", box=(0, 0, 7500, 7500), verbose=False)
    pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270)
    d.add("PAD_X", "BondPad", snap="a", to=pw.a, mirror=True)
    assert d.data["instances"]["PAD_X"]["place"]["mirror"] is True
    plan = plan_design(d.design)
    assert plan.instances["PAD_X"].trans.is_mirror()
    a, b = plan.port("PAD_X.a").pos, plan.port("PAD_W.a").pos
    assert (a - b).length() < 1e-6


def test_shape_parameters_from_json():
    """KQC TypeShape parameters (paths) are written as point lists in design.json and become pya.DPath at build."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.registry import resolve_cell, shape_params

    spiral = resolve_cell("SpiralResonatorPolygon")
    p = shape_params(
        spiral,
        {"input_path": [[-200, 0], [0, 0]], "poly_path": {"points": [[0, 600], [800, 0]], "width": 10}, "length": 3000},
    )
    assert isinstance(p["input_path"], pya.DPath) and p["poly_path"].width == 10 and p["length"] == 3000
    assert shape_params(spiral, {"input_path": "(0,0;100,0) w=0 bx=0 ex=0 r=false"})["input_path"].num_points() == 2
    d = Designer("t_shapes", verbose=False)
    w = d.add("W", "WaveguideCoplanar", at=(1000, 5000), path=[[0, 0], [300, 0], [300, 300]])
    assert w.ports["b"].pos.x == pytest.approx(300) and w.ports["b"].pos.y == pytest.approx(300)
    d.show()


def test_custom_and_overridden_launchers():
    """KQC produce_n_launchers through design.json: a custom set (SampleHolderTest-style 40 pads) or a preset with
    overrides; a custom set without n is rejected."""
    d = Designer(
        "t_l40",
        box=(0, 0, 10000, 10000),
        launchers={"n": 40, "width": 200, "gap": 120, "indent": 500, "pitch": 900},
        verbose=False,
    )
    assert len(d.chip_ports) == 40
    d.route("L", "chip.1", "chip.2")
    d.show()
    d = Designer(
        "t_ard",
        box=(0, 0, 10000, 10000),
        launchers={"type": "ARD24", "pitch": 1000, "assign": {2: "IN", 3: "OUT"}},
        verbose=False,
    )
    p = d.chip_ports
    assert set(p) == {"IN", "OUT"} and p["OUT"].pos.x - p["IN"].pos.x == pytest.approx(1000)
    with pytest.raises(ValueError, match="custom launchers need"):
        Designer("t_bad", launchers={"width": 3}, verbose=False).design  # noqa: B018


def test_hanger_bend_and_meander_direction_options(example_path, tmp_path):
    """Design question (2026-11-03): the coupler's 90° bend and the meander's first-turn side are options, not rules."""
    from quantcore_circuits.design import load_design

    d = Designer.load(example_path, verbose=False)
    base = d.show().plan.routes["R1"]
    d["R1"].set(meander_direction=-1)
    flipped = d.show().plan.routes["R1"]
    seg = [i for i, n in enumerate(flipped.nodes) if n.length_increment][0]
    assert flipped.nodes[seg].meander_direction == -1 and base.nodes[seg].meander_direction == 1
    assert flipped.length == pytest.approx(base.length, abs=0.05)  # same fixed length, mirrored meander
    path = d.save(tmp_path / "flip.json")
    assert load_design(path).routes["R1"].meander_direction == -1
    assert "meander_direction" not in load_design(example_path).to_json_dict()["routes"]["R1"]  # default stays out

    from quantcore_circuits.design.schema import HangerEnd

    h = HangerEnd(hanger="FL", s=2000, length=300, bend=False)
    assert h.bend is False and HangerEnd(hanger="FL", s=2000, length=300).bend is True

    # bend=False: the route runs into the coupler along the feedline axis (no 90° bend at the coupler start); the
    # coupler is shifted so the route can arrive from the side
    d2 = Designer.load(example_path, verbose=False)
    to = dict(d2.data["routes"]["R1"]["to"], bend=False, s=2400)
    d2["R1"].set(to=to)
    straight = d2.show().plan.routes["R1"]
    *_, p_in, p_c0, p_c1 = [n.position for n in straight.nodes]
    assert p_in.y == pytest.approx(p_c0.y) == pytest.approx(p_c1.y)  # lead-in collinear with the coupler
    assert straight.length == pytest.approx(4200, abs=0.05)
    assert load_design(d2.save(tmp_path / "straight.json")).routes["R1"].to.bend is False


def test_per_corner_radius_builds(tmp_path):
    """``Waypoint.r`` bends that corner only: the built length drops by (2 − π/2)·Δr for a 90° corner; a meander on the
    straight between two corners of different radii still reaches its length; unset radii stay out of the JSON."""
    import copy
    import math
    from pathlib import Path

    from quantcore_circuits.assembly import build
    from quantcore_circuits.design import design_hash, load_design

    base = {
        "schema": "qcc/0.1", "name": "corner", "chip": {"box": [0, 0, 7500, 7500]},
        "instances": {"P1": {"cell": "BondPad", "place": {"at": [1125, 3750], "rot": 270}},
                      "P2": {"cell": "BondPad", "place": {"at": [3750, 1125], "rot": 0}}},
        "routes": {"R": {"from": "P1.a", "to": "P2.a", "nodes": [[2000, 3750], [3750, 3750]]}},
    }
    one = copy.deepcopy(base)
    one["routes"]["R"]["nodes"][1] = {"at": [3750, 3750], "r": 250}
    l0 = build(load_design(base)).plan.routes["R"].length
    l1 = build(load_design(one)).plan.routes["R"].length
    assert l0 - l1 == pytest.approx((2 - math.pi / 2) * 150, abs=0.01)
    assert load_design(one).to_json_dict()["routes"]["R"]["nodes"][1]["r"] == 250
    as_dict = copy.deepcopy(base)
    as_dict["routes"]["R"]["nodes"][1] = {"at": [3750, 3750]}  # a waypoint dict without r: same hash as before
    assert "r" not in load_design(as_dict).to_json_dict()["routes"]["R"]["nodes"][1]
    flux = load_design(Path(__file__).parents[1] / "examples" / "q1_r1_feedline.json").to_json_dict()["routes"]["FLUX"]
    assert "r" not in flux["nodes"][0]  # existing designs keep their canonical JSON, so their hashes
    assert design_hash(load_design(one)) != design_hash(load_design(base))

    mixed = copy.deepcopy(base)
    mixed["routes"]["R"].update(type="meander", length=5800, meander_segment=4)
    mixed["routes"]["R"]["nodes"] = [[2000, 3750], {"at": [3000, 3750], "r": 200}, [3000, 2500], [3750, 2500]]
    plan = build(load_design(mixed)).plan.routes["R"]
    assert plan.length == pytest.approx(5800, abs=0.05)
    assert plan.nodes[4].length_increment  # the meander sits on the split straight

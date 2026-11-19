"""Wafer assembly (``layouts/wafers/wafer.py``): counts, names, layers 500/0 + 501/0, notch, centred packing."""

import math

import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits.layouts.wafers.wafer import Wafer, row_letters
from quantcore_circuits.pdk import QCC_LAYERS


def test_layer_numbers():
    assert (QCC_LAYERS["wafer_boundary"].layer, QCC_LAYERS["wafer_boundary"].datatype) == (500, 0)
    assert (QCC_LAYERS["wafer_markers"].layer, QCC_LAYERS["wafer_markers"].datatype) == (501, 0)
    from quantcore_circuits.pdk import QUANTCORE_NB_SAPPHIRE_V1 as pdk

    assert pdk.fab_layers["WAFER_BOUNDARY"].layer == 500 and pdk.fab_layers["WAFER_MARKERS"].layer == 501


@pytest.mark.parametrize(
    "diameter, die, count",
    [(100, 7.5, 100), (100, 5, 238), (100, 10, 52), (150, 10, 137)],
)
def test_dense_counts(diameter, die, count):
    w = Wafer(diameter_mm=diameter, die_mm=die)
    assert w.die_count == count
    # a dense wafer cannot hold more than the usable area allows
    usable = math.pi * (diameter / 2 - w.edge_mm) ** 2
    assert w.die_count * die * die < usable


def test_every_die_inside_usable_area_and_clear_of_each_other():
    w = Wafer(diameter_mm=100, die_mm=7.5)
    usable = w._usable
    boxes = []
    for d in w.dies:
        box = pya.Box(*(int(round(v / 0.001)) for v in d.box_um))
        assert (pya.Region(box) - usable).is_empty(), d.name
        boxes.append(box)
    merged = pya.Region(boxes)
    assert merged.merged().area() == merged.area()  # no overlaps
    r_far = max(math.hypot(abs(d.x_mm) + 3.75, abs(d.y_mm) + 3.75) for d in w.dies)
    assert r_far <= 50 - w.edge_mm + 1e-9


def test_names_rows_letters_columns_numbers():
    w = Wafer(diameter_mm=100, die_mm=7.5)
    assert w.dies[0].row == "A" and [d.col for d in w.dies if d.row == "A"] == sorted(
        d.col for d in w.dies if d.row == "A"
    )
    assert len({d.name for d in w.dies}) == w.die_count
    rows = sorted({d.row for d in w.dies})
    assert rows[0] == "A" and rows[-1] == row_letters(len(rows) - 1)
    # rows go top to bottom, columns left to right
    k = w.dies[-1]
    assert w.dies[0].y_mm > k.y_mm
    last = [d for d in w.dies if d.row == k.row]
    assert min(last, key=lambda d: d.x_mm).col == min(d.col for d in last)
    assert last[0].x_mm < last[-1].x_mm
    assert min(d.col for d in w.dies) == 1
    assert row_letters(0) == "A" and row_letters(25) == "Z" and row_letters(26) == "AA"


def test_layers_500_and_501_written(tmp_path):
    w = Wafer(diameter_mm=100, die_mm=7.5)
    out = w.write(tmp_path / "w.oas")
    ly = pya.Layout()
    ly.read(str(out))
    top = ly.top_cells()[0]
    l500, l501 = ly.find_layer(500, 0), ly.find_layer(501, 0)
    assert l500 is not None and l501 is not None
    assert not top.dbbox_per_layer(l500).empty() and not top.dbbox_per_layer(l501).empty()
    assert abs(top.dbbox_per_layer(l500).width() - 100000) < 5  # the wafer outline is 100 mm wide
    assert out.with_suffix(".csv").exists()
    # the labels are drawn: more 501/0 polygons than dies
    assert pya.Region(top.begin_shapes_rec(l501)).count() > w.die_count


def test_notch_on_the_bottom_edge():
    w = Wafer(diameter_mm=100, die_mm=7.5)
    poly = pya.Region(w.outline_polygon_um().to_itype(0.001))
    # notch: the lowest point of the outline is no longer on the circle, the width at the notch row is cut
    circle = Wafer(diameter_mm=100, die_mm=7.5, orientation="none")
    assert poly.area() < pya.Region(circle.outline_polygon_um().to_itype(0.001)).area()
    # a point just above the apex is outside the wafer, a point beside the notch is inside
    inside_at_notch = pya.Region(pya.Box(-100, -49500_000, 100, -49400_000)) & poly
    assert inside_at_notch.is_empty()  # in the notch (the apex is 1 mm above the rim)
    beside = pya.Region(pya.Box(3_000_000, -49000_000, 3_100_000, -48900_000)) & poly
    assert not beside.is_empty()
    # notch on the right edge turns the notch
    r = Wafer(diameter_mm=100, die_mm=7.5, orientation_side="right")
    assert (
        pya.Region(pya.Box(49500_000, -100, 49600_000, 100)) & pya.Region(r.outline_polygon_um().to_itype(0.001))
    ).is_empty()


def test_notch_keeps_dies_off_the_notch():
    with_notch = Wafer(diameter_mm=100, die_mm=7.5, edge_mm=0.5)
    plain = Wafer(diameter_mm=100, die_mm=7.5, edge_mm=0.5, orientation="none")
    assert with_notch.die_count <= plain.die_count
    notch_zone = pya.DBox(-1500, -50000, 1500, -48000)  # around the notch (apex at -49000)
    for d in with_notch.dies:
        assert not pya.DBox(*d.box_um).overlaps(notch_zone), d.name


def test_flat_orientation():
    f = Wafer(diameter_mm=100, die_mm=7.5, orientation="flat")
    bb = pya.Region(f.outline_polygon_um().to_itype(0.001)).bbox()
    assert bb.bottom * 0.001 == pytest.approx(-math.sqrt(50000**2 - 16250**2), abs=1)


def test_centred_packing_respects_radius_and_offset():
    w = Wafer(diameter_mm=100, die_mm=7.5, packing="centred", radius_mm=30, offset_mm=(5.0, -4.0))
    assert 0 < w.die_count < Wafer(diameter_mm=100, die_mm=7.5).die_count
    for d in w.dies:
        x0, y0, x1, y1 = (v / 1000 for v in d.box_um)
        reach = max(math.hypot(x - 5.0, y + 4.0) for x in (x0, x1) for y in (y0, y1))
        assert reach <= 30 + 1e-9, d.name
    # the pattern is centred on the offset, not on the wafer centre
    xs = [d.x_mm for d in w.dies]
    assert abs((min(xs) + max(xs)) / 2 - 5.0) < 7.6
    assert w.die_count > Wafer(diameter_mm=100, die_mm=7.5, packing="centred", radius_mm=20).die_count


def test_centred_needs_a_radius():
    with pytest.raises(ValueError):
        Wafer(packing="centred")


def test_mixed_sizes_bands():
    w = Wafer(diameter_mm=100, bands=[(5, 2), (7.5, 2), (10, 3)])
    assert set(w.counts_by_size()) == {5, 7.5, 10}
    assert [d.row for d in w.dies][0] == "A"
    usable = w._usable
    for d in w.dies:
        assert (pya.Region(pya.Box(*(int(round(v / 0.001)) for v in d.box_um))) - usable).is_empty()


def test_chip_placed_and_table(tmp_path):
    chip = pya.Layout()
    chip.dbu = 0.001
    c = chip.create_cell("tiny")
    c.shapes(chip.layer(100, 0)).insert(pya.DBox(0, 0, 7000, 7000))
    c.shapes(chip.layer(1, 0)).insert(pya.DBox(1000, 1000, 2000, 2000))
    src = tmp_path / "tiny.oas"
    chip.write(str(src))
    w = Wafer(diameter_mm=100, die_mm=7.5, packing="centred", radius_mm=12)
    out = w.write(tmp_path / "w.oas", chips={"*": src})
    assert all(d.chip == "tiny" for d in w.dies)
    ly = pya.Layout()
    ly.read(str(out))
    top = ly.top_cells()[0]
    l1 = ly.find_layer(1, 0)
    assert pya.Region(top.begin_shapes_rec(l1)).count() == w.die_count
    d = w.dies[0]
    probe = pya.DBox(d.x_mm * 1000 - 2500, d.y_mm * 1000 - 2500, d.x_mm * 1000 - 1500, d.y_mm * 1000 - 1500)
    assert not (
        pya.Region(top.begin_shapes_rec(l1)) & pya.Region(probe.to_itype(0.001))
    ).is_empty()  # centred on the die
    with pytest.raises(ValueError):  # a chip bigger than the die is refused
        Wafer(diameter_mm=100, die_mm=5, packing="centred", radius_mm=8).build(chips={"*": src})
    assert w.table()[0]["chip"] == "tiny" and "| die |" in w.table_markdown()


def test_mixed_names_are_unique_and_count_from_the_left():
    w = Wafer(diameter_mm=100, bands=[(5, 2), (7.5, 2), (10, 3)])
    assert len({d.name for d in w.dies}) == w.die_count
    for row in {d.row for d in w.dies}:
        dies = [d for d in w.dies if d.row == row]
        assert [d.col for d in dies] == list(range(1, len(dies) + 1))

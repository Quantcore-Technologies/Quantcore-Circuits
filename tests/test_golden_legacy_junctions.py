"""Golden XOR tests: legacy junction generations and junction test pads vs the legacy QWri scripts (fab mode,
tolerance 1 dbu), on the parameters the legacy chips use."""

import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits.layouts.junctions.jj_fingers import JJFingerBent, JJFingerStraight
from quantcore_circuits.layouts.junctions.legacy_junctions import (
    SquidV0,
    TrilayerJunctionCompact,
    TrilayerJunctionHSQ,
    TrilayerSquidHSQ,
)
from quantcore_circuits.layouts.junctions.trilayer import TrilayerJunction, TrilayerSquid
from quantcore_circuits.layouts.others.test_pads import (
    JunctionGroundPad,
    JunctionTestPads,
    junction_ground_pad_regions,
    junction_test_pad_regions,
    legacy_test_pad_params,
)
from quantcore_circuits.pdk import QCC_LAYERS
from tests.legacy_ref import legacy, scripts

pytestmark = pytest.mark.skipif(not legacy.available(), reason="legacy components/ folder not present")

GAP = pya.LayerInfo(130, 1)  # 1t1_base_metal_gap_wo_grid
SIS1, SIS2 = pya.LayerInfo(136, 1), pya.LayerInfo(139, 1)
HSQ = QCC_LAYERS["hsq"]  # legacy drew HSQ on 500/0; the PDK v2 spacer layer is 50/0
LAYERS = (
    ((1, 0), GAP, "M1 gaps"),
    ((2, 0), SIS1, "straight finger"),
    ((4, 0), SIS2, "bent finger"),
    ((500, 0), HSQ, "HSQ"),
)


def region(cell, info):
    return pya.Region(cell.begin_shapes_rec(cell.layout().layer(info))).merged()


def assert_xor_empty(a: pya.Region, b: pya.Region, what: str, allow_empty: bool = False):
    diff = (a.merged() ^ b.merged()).sized(-1)  # ignore slivers up to 2 dbu
    assert diff.is_empty(), f"{what}: XOR not empty, area {diff.area()} dbu², bbox {diff.bbox()}"
    assert allow_empty or a.area() > 0, f"{what}: empty"


def compare(cell, ref, ref_cell, layers, what, shift=None):
    for legacy_layer, ours, name in layers:
        ref_region = scripts.top_region(ref, ref_cell, legacy_layer).transformed(shift or pya.Trans())
        assert_xor_empty(region(cell, ours), ref_region, f"{what} {name}", allow_empty=ref_region.is_empty())


# chip_05/06/08 call create_junction(bot, top) with bot = 5 or 8 (×0.1 µm) and top = 0.6 µm; js=1 is the default
@pytest.mark.parametrize("js, second", [(1.0, 0), (5, 0.6), (8, 0.6)])
def test_trilayer_junction_hsq(tmp_path, js, second):
    ref = scripts.creator_layout("junction_creator_HSQ.py", "create_junction", tmp_path, js, second)
    layout = pya.Layout()
    cell = TrilayerJunctionHSQ.create(layout, finger_width=0.1 * js, second_finger_width=second)
    compare(cell, ref, f"JUNC_{int(js)}", LAYERS[1:], f"TrilayerJunctionHSQ js={js}", pya.Trans(0, False, 0, 10000))


@pytest.mark.parametrize("js, second", [(2, 0), (5, 0.6)])
def test_trilayer_squid_hsq(tmp_path, js, second):
    ref = scripts.creator_layout("squid_creator_HSQ.py", "create_squid", tmp_path, js, second)
    layout = pya.Layout()
    cell = TrilayerSquidHSQ.create(layout, finger_width=0.1 * js, second_finger_width=second)
    compare(cell, ref, f"JUNC_{int(js)}", LAYERS[1:], f"TrilayerSquidHSQ js={js}", pya.Trans(0, False, 0, 10000))


@pytest.mark.parametrize(
    "script, func, cls",
    [
        ("xjc_junction_TL_mod_v0.1.py", "create_junction", TrilayerJunctionHSQ),
        ("xjc_squid_TL_mod_v0.1.py", "create_squid", TrilayerSquidHSQ),
    ],
)
@pytest.mark.parametrize("js, second", [(1.0, 0), (5, 0.6)])
def test_xjc_v01_is_the_hsq_generation(tmp_path, script, func, cls, js, second):
    """The ``xjc_*_TL_mod_v0.1`` scripts = the first HSQ generation with 0.2 µm HSQ tails (``hsq_extra=0.2``)."""
    ref = scripts.creator_layout(script, func, tmp_path, js, second)
    layout = pya.Layout()
    cell = cls.create(layout, finger_width=0.1 * js, second_finger_width=second, hsq_extra=0.2)
    compare(
        cell, ref, f"JUNC_{int(js)}", LAYERS[1:], f"{cls.__name__} ({script}) js={js}", pya.Trans(0, False, 0, 10000)
    )


@pytest.mark.parametrize("js", [1.0, 2.0])
def test_squid_v0_junction_creator_sq(tmp_path, js):
    ref = scripts.module_path_layout("junction_creator_sq.py", "create_junction_squid", tmp_path, js)
    layout = pya.Layout()
    cell = SquidV0.create(layout, second_finger_width=0.2 * js + 0.06)
    compare(cell, ref, "JUNC_", LAYERS[1:3], f"SquidV0 js={js}", pya.Trans(0, False, 0, 9000))


def test_squid_v0_junction_pad(tmp_path):
    ref = scripts.junction_pad_layout(tmp_path)
    layout = pya.Layout()
    cell = SquidV0.create(layout, second_finger_width=0.26, bent_window_height=16)
    compare(cell, ref, "SQUID", LAYERS[1:3], "SquidV0 (junction_pad.py)", pya.Trans(0, False, 0, 9000))


# (script, cell, sizes): chip_01/02 AVAQUS size 1 (and the commented 1.75); chip_04 Nb_TL; chip_05/06/08 HSQ with
# bottom fingers 0.5/0.8 µm (size 2.5/4) and a 0.6 µm top finger; chip_10a the small xtp pads
TEST_PADS = [
    ("testPad_AVAQUS.py", "TESTAVA", 1.0, None),
    ("testPad_AVAQUS.py", "TESTAVA", 1.75, None),
    ("testPad_Nb_TL.py", "TEST_TL", 2.5, 0.6),
    ("testPad_Nb_TL.py", "TEST_TL", 4.0, 0.5),
    ("testPad_Nb_TL_HSQ.py", "TEST_TL", 2.5, 0.6),
    ("testPad_Nb_TL_HSQ.py", "TEST_TL", 4.0, 0.6),
    ("xtp_testpads_TL_small.py", "TEST_TL", 2.5, 0.6),
    ("xtp_testpads_TL_small.py", "TEST_TL", 5.0, 0.6),
]


@pytest.mark.parametrize("script, ref_cell, size, second", TEST_PADS)
def test_junction_test_pads(tmp_path, script, ref_cell, size, second):
    args = (size,) if second is None else (size, second)
    ref = scripts.module_path_layout(script, "create_testPad", tmp_path, *args)
    params = legacy_test_pad_params(script[:-3], size, second or 0)
    layout = pya.Layout()
    cell = JunctionTestPads.create(layout, **params)
    compare(cell, ref, ref_cell, LAYERS, f"JunctionTestPads {script} size={size}")
    # the legacy second-metal pattern (3/0) is not drawn, but the geometry function reproduces it
    m3 = junction_test_pad_regions(0.001, **params)["m3"]
    assert_xor_empty(m3, scripts.top_region(ref, ref_cell, (3, 0)), f"{script} 3/0")


@pytest.mark.parametrize("size", [1.0, 1.75])
def test_junction_ground_pad(tmp_path, size):
    ref = scripts.module_path_layout("testPad.py", "create_testPad", tmp_path, size)
    layout = pya.Layout()
    cell = JunctionGroundPad.create(layout, finger_width=0.2 * size + 0.06)
    compare(cell, ref, "TEST", LAYERS[:3], f"JunctionGroundPad size={size}")
    m3 = junction_ground_pad_regions(0.001, finger_width=0.2 * size + 0.06)["m3"]
    assert_xor_empty(m3, scripts.top_region(ref, "TEST", (3, 0)), "testPad 3/0")


# chip_11f places chip_11m's JX_500 built with create_testPad(1.0, 0.6); 2.5 is chip_11m's own __main__ call
@pytest.mark.parametrize("size, second", [(1.0, 0.6), (2.5, 0.6)])
def test_trilayer_junction_compact(tmp_path, size, second):
    ref = scripts.module_path_layout("chip_11m_TestJJ16x_pads.py", "create_testPad", tmp_path, size, second)
    layout = pya.Layout()
    cell = TrilayerJunctionCompact.create(layout, finger_width=0.2 * size, second_finger_width=second)
    compare(cell, ref, "JX_500", LAYERS[1:], f"TrilayerJunctionCompact size={size}", pya.Trans(0, False, 0, 6000))


# legacy "JJ_finger Top" / "JJ_finger Bottom" parameter sets: defaults, chip_11m (JX_500), the squid scripts
# (x = ±8, invert), chip_10a_3X_SQUID's positive straight fingers
FINGER_TOP = [
    {},
    {"width": 12, "height": 12, "finger_length": 3, "x": 0, "y": -2.4, "pad_width": 1.2, "finger_width": 0.2},
    {"width": 32, "height": 20, "finger_length": 3.2, "x": 8, "y": -3.6, "finger_width": 0.5, "pad_width": 1.1},
    {"negative": False, "width": 0.5, "height": 0.5, "finger_length": 0.8, "x": 8, "finger_width": 0.4},
    {"invert": True, "x": -8, "y": -3.6},
]
FINGER_BOTTOM = [
    {},
    {"width": 12, "height": 12, "finger_length": 3, "x": 0.2, "y": -3.4, "pad_width": 1.6, "finger_width": 0.6},
    {"width": 32, "height": 19, "finger_length": 3, "conn_height": 1, "x": 8, "y": -2, "finger_width": 0.5},
    {"width": 32, "height": 19, "finger_length": 3, "conn_height": 1, "x": -8, "y": -2, "invert": True},
    {"negative": False, "finger_length": 3, "conn_height": 1},
]
_OURS = {"width": "window_width", "height": "window_height"}
_LAYOUTS = []  # keep the layouts of built cells alive


def build(cls, **params):
    layout = pya.Layout()
    _LAYOUTS.append(layout)
    return cls.create(layout, **params)


@pytest.mark.parametrize("params", FINGER_TOP, ids=[f"top{i}" for i in range(len(FINGER_TOP))])
def test_jj_finger_straight(params):
    ref = legacy.legacy_region("JJ_finger Top", layer=(2, 0), **params)
    cell = build(JJFingerStraight, **{_OURS.get(k, k): v for k, v in params.items()})
    assert_xor_empty(region(cell, SIS1), ref, f"JJFingerStraight {params}")


@pytest.mark.parametrize("params", FINGER_BOTTOM, ids=[f"bottom{i}" for i in range(len(FINGER_BOTTOM))])
def test_jj_finger_bent(params):
    ref = legacy.legacy_region("JJ_finger Bottom", layer=(4, 0), **params)
    cell = build(JJFingerBent, **{_OURS.get(k, k): v for k, v in params.items()})
    assert_xor_empty(region(cell, SIS2), ref, f"JJFingerBent {params}")


@pytest.mark.parametrize(
    "cls",
    [TrilayerJunction, TrilayerSquid, TrilayerJunctionHSQ, TrilayerSquidHSQ, TrilayerJunctionCompact, JunctionTestPads],
)
def test_spacer_gradient_levels(cls):
    """Decision #4: the 51–53/0 shades are three dose levels *inside* each rectangular 50/0 spacer, nested strips of
    width / 3 across the box (spacer_1 next to the junction finger, spacer_3 outermost); on by default (PDK switch
    ``JunctionProcess.spacer_gradient``), off with ``spacer_gradient=False``; the 50/0 spacer itself is unchanged."""
    cell = build(cls)
    hsq = region(cell, HSQ)
    levels = [region(cell, QCC_LAYERS[f"spacer_{k}"]) for k in (1, 2, 3)]
    assert not hsq.is_empty() and all(not lev.is_empty() for lev in levels)
    union = levels[0] + levels[1] + levels[2]
    assert (union ^ hsq).is_empty(), "levels must tile the spacer"
    assert all((levels[i] & levels[j]).is_empty() for i, j in ((0, 1), (0, 2), (1, 2)))
    for box in hsq.each():  # every HSQ box: three strips of width/3, inner (nearest the finger axis) = spacer_1
        bb = box.bbox()
        parts = [(lev & pya.Region(bb)).bbox() for lev in levels]
        assert all(abs(p.width() - bb.width() / 3) <= 1 for p in parts), (bb, parts)
        assert all(p.height() == bb.height() for p in parts)
    off = build(cls, spacer_gradient=False)
    assert all(region(off, QCC_LAYERS[f"spacer_{k}"]).is_empty() for k in (1, 2, 3))
    assert (region(off, HSQ) ^ hsq).is_empty()


def test_spacer_gradient_inner_strip_faces_the_junction():
    """TrilayerJunction: the HSQ boxes flank the straight finger (x = 0); spacer_1 is the strip next to it."""
    cell = build(TrilayerJunction, finger_width=0.5, second_finger_width=0.6)
    s1, s3 = (region(cell, QCC_LAYERS[f"spacer_{k}"]) for k in (1, 3))
    for poly in s1.each():
        x1 = abs(poly.bbox().center().x)
        assert all(abs(q.bbox().center().x) > x1 for q in s3.each() if q.bbox().center().x * poly.bbox().center().x > 0)


def test_spacer_gradient_windows_and_concentric_rings():
    """Decision #4: windows (a spacer with a hole) and concentric (round) spacers split into three rings of equal width,
    level 1 at the hole / the core."""
    from quantcore_circuits.layouts.junctions.trilayer import spacer_gradient_levels

    frame = pya.Region(pya.Box(-3000, -3000, 3000, 3000)) - pya.Region(pya.Box(-1500, -1500, 1500, 1500))
    levels = spacer_gradient_levels(frame, 0.001)
    assert [lev.bbox() for lev in levels] == [
        pya.Box(-2000, -2000, 2000, 2000),
        pya.Box(-2500, -2500, 2500, 2500),
        pya.Box(-3000, -3000, 3000, 3000),
    ]
    assert ((levels[0] + levels[1] + levels[2]) ^ frame).is_empty()
    disc = pya.Region(pya.Polygon.ellipse(pya.Box(-3000, -3000, 3000, 3000), 128))
    levels = spacer_gradient_levels(disc, 0.001)
    assert ((levels[0] + levels[1] + levels[2]) ^ disc).is_empty()
    widths = [lev.bbox().width() for lev in levels]
    assert widths[0] < widths[1] < widths[2] == 6000 and abs(widths[0] - 2000) < 20 and abs(widths[1] - 4000) < 20


@pytest.mark.parametrize(
    "cls",
    [TrilayerJunctionHSQ, TrilayerSquidHSQ, SquidV0, TrilayerJunctionCompact, JunctionTestPads, JunctionGroundPad],
)
def test_cells_plan_with_defaults(cls):
    from quantcore_circuits.assembly import plan_design
    from quantcore_circuits.design import load_design

    probe = {"schema": "qcc/0.1", "name": "probe", "instances": {"X": {"cell": cls.__name__, "place": {"at": [0, 0]}}}}
    placed = plan_design(load_design(probe)).instances["X"]
    assert placed.cell.endswith(cls.__name__)
    assert cls.qcc_category in ("junction", "test_structure")


# chip_05_flux_TLQubits: Xmon Cross width 400 / spacing 20, junction_creator_HSQ / squid_creator_HSQ called with
# (bot[i-1], top[i-1]): bot = [5, 5, 5, 5, 5, 8] (× 0.1 µm), top = 0.6 µm, SQUIDs at i = 3, 4; chip_10a the same sweep
# with the xjc_*_TL_mod generation (Trilayer Junction / Trilayer Squid)
CHIP_SWEEP = [
    ("junction_creator_HSQ.py", "create_junction", "Trilayer Junction HSQ", 8, 0.6),  # chip_05 Q1 (bot[-1])
    ("junction_creator_HSQ.py", "create_junction", "Trilayer Junction HSQ", 5, 0.6),
    ("squid_creator_HSQ.py", "create_squid", "Trilayer Squid HSQ", 5, 0.6),
    ("xjc_junction_TL_mod.py", "create_junction", "Trilayer Junction", 8, 0.6),  # chip_10a
    ("xjc_junction_TL_mod.py", "create_junction", "Trilayer Junction", 5, 0.6),
    ("xjc_squid_TL_mod.py", "create_squid", "Trilayer Squid", 5, 0.6),
]


@pytest.mark.parametrize("script, func, junction_type, js, second", CHIP_SWEEP)
def test_xmon_junction_size_sweep(tmp_path, script, func, junction_type, js, second):
    """Xmon ``junction_params`` carry the chips' junction-size sweep to the junction cell: the Xmon's fingers and HSQ
    XOR clean against the legacy script's junction placed in the 20 µm gap below the 400 µm cross."""
    from quantcore_circuits.layouts.qubits.xmon import Xmon

    ref = scripts.creator_layout(script, func, tmp_path, js, second)
    layout = pya.Layout()
    params = {
        "cross_length": 400,
        "gap": 20,
        "junction_type": junction_type,
        "junction_params": {"finger_width": 0.1 * js, "second_finger_width": second},
    }
    cell = Xmon.create(layout, **Xmon.qcc_params(params))
    # legacy junction cell centred on its 20 µm window = the gap centre, 210 µm below the cross centre
    shift = pya.Trans(0, False, 0, int(round(-(400 / 2 + 20 / 2) / 0.001)))
    compare(cell, ref, f"JUNC_{int(js)}", LAYERS[1:], f"Xmon {junction_type} js={js} second={second}", shift)

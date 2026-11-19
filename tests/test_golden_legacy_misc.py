"""Golden XOR tests: ported QWri markers, pads, CPW segment, flux holes, shapes and the ``cpwe`` cells vs. the legacy
code (``components/``, executed read-only), 1-dbu tolerance. Parameter sets are the legacy chips'/macros' own."""

from __future__ import annotations

import sys

import pytest
from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya

from quantcore_circuits.layouts.others import connector_pads, cpw_segment, cpwe, markers, shapes
from quantcore_circuits.pdk import QCC_LAYERS
from tests.legacy_ref import legacy

pytestmark = pytest.mark.skipif(not legacy.available(), reason="legacy components/ folder not present")

GAP = default_layers["1t1_base_metal_gap_wo_grid"]
ADD = default_layers["1t1_base_metal_addition"]
ALIGN, DICING, BOUNDARY = QCC_LAYERS["marker_1"], QCC_LAYERS["marker_0"], QCC_LAYERS["chip_boundary"]
QC = "pymacros/QuantumPcells"


def region(cell, info):
    return pya.Region(cell.begin_shapes_rec(cell.layout().layer(info))).merged()


def assert_xor_empty(a: pya.Region, b: pya.Region, what: str):
    diff = (a.merged() ^ b.merged()).sized(-1)  # ignore slivers up to 2 dbu
    assert diff.is_empty(), f"{what}: XOR not empty, area {diff.area()} dbu², bbox {diff.bbox()}"
    assert a.area() > 0, f"{what}: empty"


_LAYOUTS = []  # keep the layouts of built cells alive


def build(cls, **params):
    layout = pya.Layout()
    _LAYOUTS.append(layout)
    return cls.create(layout, **params)


# ---- PCells ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("thickness, width", [(50, 500), (20, 150)])
def test_corner_marker(thickness, width):
    ref = legacy.legacy_pcell_regions(f"{QC}/Marker.lym", "Marker", "Marker", thickness=thickness, width=width)
    cell = build(markers.CornerMarker, thickness=thickness, width=width)
    assert_xor_empty(region(cell, ALIGN), ref[(1, 0)], "CornerMarker")
    cell = build(markers.CornerMarker, thickness=thickness, width=width, marker_layer="base_metal_gap_wo_grid")
    assert_xor_empty(region(cell, GAP), ref[(1, 0)], "CornerMarker (legacy etch)")


def test_corner_marker_hsq():
    """chip_05: the HSQ marker (l = 500/0, fab_l = 150/0)."""
    ref = legacy.legacy_pcell_regions(
        f"{QC}/Marker.lym",
        "Marker",
        "Marker",
        layers=((500, 0), (150, 0)),
        l=pya.LayerInfo(500, 0),
        fab_l=pya.LayerInfo(150, 0),
        thickness=50,
        width=150,
    )
    cell = build(markers.CornerMarker, thickness=50, width=150, hsq=True)
    assert_xor_empty(region(cell, QCC_LAYERS["hsq"]), ref[(500, 0)], "CornerMarker hsq")
    assert_xor_empty(region(cell, QCC_LAYERS["hsq_boundary"]), ref[(150, 0)], "CornerMarker hsq_boundary")
    assert region(cell, GAP).is_empty()


@pytest.mark.parametrize("size", [5000, 7500])
def test_boundary_box(size):
    ref = legacy.legacy_pcell_regions(f"{QC}/boundaryBox.lym", "BoundBox", "Bound Box", layers=((9, 0),), size=size)
    assert_xor_empty(region(build(markers.BoundaryBox, size=size), BOUNDARY), ref[(9, 0)], "BoundaryBox")


@pytest.mark.parametrize(
    "params",
    [
        {"trace_width": 10, "pad_height": 300, "pad_width": 275, "conn_height": 300, "round": False},  # chip_01/02
        {"trace_width": 10, "pad_height": 200, "pad_width": 600, "conn_height": 500, "round": True},  # chip_03
        {"trace_width": 10, "pad_height": 300, "pad_width": 275, "conn_height": 300, "round": True},
    ],
)
def test_connector_pad_v1(params):
    ref = legacy.legacy_pcell_regions(
        f"{QC}/connector_pad.lym", "ConnectorPad", "Connector Pad", fab=True, sim=False, trace_gap=6, **params
    )
    cell = build(
        connector_pads.ConnectorPad,
        pad_width=params["pad_width"],
        pad_height=params["pad_height"],
        taper_length=params["conn_height"],
        a=params["trace_width"],
        b=6,
        rounded=params["round"],
    )
    assert_xor_empty(region(cell, GAP), ref[(1, 0)], f"ConnectorPad {params}")


@pytest.mark.parametrize("ground", [True, False])
def test_tapered_pad(ground):
    legacy_params = {"pad_width": 100, "pad_height": 150, "conn_height": 120, "finger_width": 3, "width": 300}
    legacy_params |= {"height": 400, "x": 5, "y": -10, "ground": ground}
    ref = legacy.legacy_pcell_regions(f"{QC}/pad.lym", "Pad", "Pad", **legacy_params)
    cell = build(
        connector_pads.TaperedPad,
        pad_width=100,
        pad_height=150,
        conn_height=120,
        finger_width=3,
        window_width=300,
        window_height=400,
        x=5,
        y=-10,
        negative=ground,
    )
    assert_xor_empty(region(cell, GAP if ground else ADD), ref[(1, 0)], f"TaperedPad ground={ground}")


@pytest.mark.parametrize("length", [5950, 7500 - 2000 - 40, 7500 - 2000 - 40 - 210])  # chips 01/02, 03, 07
def test_cpw_segment(length):
    ref = legacy.legacy_pcell_regions(
        f"{QC}/CPW.lym", "CPW", "Coplanar Waveguide", length=length, lc_thickness=2, rc_thickness=2, fab=True, c_gap=0
    )
    cell = build(cpw_segment.CpwSegment, length=length, lc_thickness=2, rc_thickness=2)
    assert_xor_empty(region(cell, GAP), ref[(1, 0)], f"CpwSegment {length}")


@pytest.mark.parametrize("params", [{}, {"length": 300, "arc_length": 100}, {"length": 60, "flag": True, "width": 3}])
def test_arc(params):
    ref = legacy.legacy_pcell_regions(f"{QC}/Arc.lym", "Arc", "Arc", **params)
    ours = {"length": params.get("length", 100), "width": params.get("width", 5)}
    ours |= {"arc_length": params.get("arc_length", 100), "clockwise": params.get("flag", False)}
    assert_xor_empty(region(build(shapes.ArcPath, **ours), GAP), ref[(1, 0)], f"ArcPath {params}")


@pytest.mark.parametrize("params", [{}, {"inner_r": 5, "outer_r": 60, "width": 2, "spacing": 3, "n": 128}])
def test_spiral(params):
    ref = legacy.legacy_pcell_regions("pymacros/spiral.lym", "Spiral", "Spiral", **params)
    ours = {k: v for k, v in params.items() if k != "n"} | ({"turn_points": params["n"]} if "n" in params else {})
    assert_xor_empty(region(build(shapes.SpiralPath, **ours), GAP), ref[(1, 0)], f"SpiralPath {params}")


# ---- draw.py / die_creator / chips ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def draw_ns():
    folder = str(legacy.LEGACY / "python")
    sys.path.insert(0, folder)
    try:
        cpwe_ns = legacy.macro_namespace(legacy.LEGACY / "python" / "cpwe.py")
    finally:
        sys.path.remove(folder)
    return cpwe_ns


def draw_layout(draw_ns):
    layout = pya.Layout()
    draw_ns["draw"].make_cell("TOP", 0.001, layout)
    cell, _ = draw_ns["draw"].get_current_cell()
    return layout, cell


def legacy_drawn(layout, cell, layer=1):
    return pya.Region(cell.begin_shapes_rec(layout.layer(layer, 0))).merged()


@pytest.mark.parametrize(
    "func, args, cls, params",
    [
        ("marker", (0, 0, 1), markers.CrossMarker, {}),
        ("global_marker", (0, 0, 1), markers.GlobalMarker, {}),
        ("marker_dicing", (0, 0, 1), markers.DicingMarker, {}),
        ("marker_align", (0, 0, 7500e3, 7500e3, 1), markers.AlignmentMarkers, {}),
        (
            "marker_align",
            (0, 0, 5000e3, 10000e3, 1),
            markers.AlignmentMarkers,
            {"chip_width": 5000, "chip_height": 1e4},
        ),
    ],
)
def test_draw_markers(draw_ns, func, args, cls, params):
    layout, cell = draw_layout(draw_ns)
    draw_ns["draw"].__dict__[func](*args)
    layer = DICING if cls is markers.DicingMarker else ALIGN
    assert_xor_empty(region(build(cls, **params), layer), legacy_drawn(layout, cell), f"{cls.__name__}")


def test_ebeam_marker():
    """The (inline) e-beam marker of die_creator.create_die, executed from its source lines."""
    text = (legacy.LEGACY / "python" / "die_creator.py").read_text(encoding="utf-8")
    lines = [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith(("markerContainer", "marker ", "markerLayout"))
    ]
    layout = pya.Layout()
    layout.dbu = 0.001
    namespace = {"pya": pya, "layout": layout}
    exec("\n".join(lines), namespace)  # noqa: S102
    assert_xor_empty(region(build(markers.EbeamMarker), ALIGN), namespace["markerLayout"], "EbeamMarker")


def test_flux_holes_like_chip_07():
    """chip_07: ``CellInstArray(hole, Trans(x, y), Vector(0, dy), Vector(dx, 0), int(ly / dy), int(lx / dx))``."""
    layout = pya.Layout()
    layout.dbu = 0.001
    top, hole = layout.create_cell("TOP"), layout.create_cell("hole")
    s, dx, dy, lx, ly = 5, 20, 15, 890, 30
    hole.shapes(layout.layer(1, 0)).insert(
        pya.Box(-s / 2 / layout.dbu, -s / 2 / layout.dbu, s / 2 / layout.dbu, s / 2 / layout.dbu)
    )
    trans = pya.Trans(pya.Point(0, 0))
    top.insert(
        pya.CellInstArray(
            hole.cell_index(),
            trans,
            pya.Vector(0, dy / layout.dbu),
            pya.Vector(dx / layout.dbu, 0),
            int(ly / dy),
            int(lx / dx),
        )
    )
    ref = legacy_drawn(layout, top)
    cell = build(cpw_segment.FluxHoleArray, hole_size=s, pitch_x=dx, pitch_y=dy, nx=int(lx / dx), ny=int(ly / dy))
    assert_xor_empty(region(cell, GAP), ref, "FluxHoleArray")


def test_flux_holes_script(tmp_path):
    """``flux_holes.py`` ``flux_holes()`` (50 µm holes, 200 µm pitch, 20 × 20), run with its output redirected."""
    src = legacy.LEGACY / "python" / "flux_holes.py"
    text = src.read_text(encoding="utf-8")
    old = r'layout.write(r"D:\Designs\ScriptedDesigns\junctions\fluxHoles.gds")'
    assert old in text
    gds = tmp_path / "fluxHoles.gds"
    text = text.replace(old, f"layout.write({str(gds)!r})")
    namespace = {"pya": pya, "__name__": "legacy_flux_holes"}
    exec(compile(text, str(src), "exec"), namespace)  # noqa: S102
    namespace["flux_holes"]()
    ref = pya.Layout()
    ref.read(str(gds))
    cell = build(cpw_segment.FluxHoleArray, hole_size=50, pitch_x=200, pitch_y=200, nx=20, ny=20)
    assert_xor_empty(region(cell, GAP), legacy_drawn(ref, ref.cell("flux_holes")), "FluxHoleArray (flux_holes.py)")


# ---- cpwe.py -------------------------------------------------------------------------------------------------
# Cong macros: w, s = 10000, 5373; bond pad 0.5e6, 0.3e6, tl 10e3, bl 50e3, btl 0.5e6, t_type 3, weight 25
W, S = 10000, 5373


@pytest.mark.parametrize("mirror, markers_on", [(False, False), (True, True), (False, True)])
def test_cpwe_bond_pad(draw_ns, mirror, markers_on):
    layout, cell = draw_layout(draw_ns)
    draw_ns["b_pad"](0, 0, "h", 0.5e6, 0.3e6, W, S, 10000, 50000, 0.5e6, 3, 25, False, mirror, markers_on, 1)
    ours = build(cpwe.CpweBondPad, a=W / 1000, b=S / 1000, mirror=mirror, markers=markers_on)
    assert_xor_empty(region(ours, GAP), legacy_drawn(layout, cell), f"CpweBondPad mirror={mirror}")


@pytest.mark.parametrize("flip, ex2", [(True, (0.0053 - 0.00522973445725) * 1e9), (False, 520000.0)])
def test_cpwe_quarter_wave(draw_ns, flip, ex2):
    """``coupled quarter waves cpwe v1.lym`` / ``Template_1.lym`` resonators."""
    layout, cell = draw_layout(draw_ns)
    args = (0, 0, "h", W, S, 3000, 1600, 200000, 20000, 20000, 50000, 1000000, 2, 300000, ex2, flip, 1)
    _, _, length = draw_ns["quarter_cap_coupled"](*args)
    params = {"a": W / 1000, "b": S / 1000, "excess_2": ex2 / 1000, "flip": flip}
    ours = build(cpwe.CpweQuarterWaveResonator, **params)
    assert_xor_empty(region(ours, GAP), legacy_drawn(layout, cell), f"CpweQuarterWaveResonator flip={flip}")
    assert cpwe.CpweQuarterWaveResonator.qcc_resonator_length(params) == pytest.approx(length / 1000)


@pytest.mark.parametrize(
    "func, args, cls, params",
    [
        ("finger_cap", (0, 0, "h", W, S, 2000, 50000, 4, False, 1), cpwe.CpweFingerCapacitor, {}),
        ("gap_cap", (0, 0, "h", W, S, 5000, False, 1), cpwe.CpweGapCapacitor, {}),
        ("finger_line", (0, 0, "h", W, S, 2000, 4000, 2000, 10, False, 1), cpwe.CpweFingerLine, {}),
        ("tapper", (0, 0, "h", W, S, 20000, 12000, 100000, 0, 25, 1000, False, 1), cpwe.CpweTaper, {}),
        (
            "tapper",
            (0, 0, "h", W, S, 20000, 12000, 100000, 2, 5, 1000, False, 1),
            cpwe.CpweTaper,
            {"taper_type": 2, "weight": 5},
        ),
        ("term_open", (0, 0, "h", W, S, 10000, False, 1), cpwe.CpweOpenEnd, {}),
        ("meander_line", (0, 0, "h", W, S, 50000, 500000, 0.5, 2, False, False, 1), cpwe.CpweMeanderLine, {}),
        (
            "meander_line",
            (0, 0, "h", W, S, 50000, 500000, 0.3, 3, True, False, 1),
            cpwe.CpweMeanderLine,
            {"bias": 0.3, "meanders": 3, "flip": True},
        ),
    ],
)
def test_cpwe_cells(draw_ns, func, args, cls, params):
    layout, cell = draw_layout(draw_ns)
    draw_ns[func](*args)
    ours = build(cls, a=W / 1000, b=S / 1000, **params)
    assert_xor_empty(region(ours, GAP), legacy_drawn(layout, cell), f"{cls.__name__} {params}")


def test_cpwe_quarter_wave_lead(draw_ns):
    """legacy ``cpwe.quarter_wave`` = CpweMeanderLine with ``lead``."""
    layout, cell = draw_layout(draw_ns)
    draw_ns["quarter_wave"](0, 0, "h", W, S, 100000, 50000, 500000, 0.5, 2, False, 1)
    ours = build(cpwe.CpweMeanderLine, a=W / 1000, b=S / 1000, lead=100)
    assert_xor_empty(region(ours, GAP), legacy_drawn(layout, cell), "CpweMeanderLine lead")


# ---- wafer level ------------------------------------------------------------------------------------------------
def test_wafer_map_75(tmp_path):
    """Cong ``75x75_diewafer.lym`` (run with its output path redirected into tmp_path)."""
    from quantcore_circuits.layouts.wafers.legacy_wafer import WaferMap75

    src = legacy.LEGACY / "pymacros" / "Cong" / "75x75_diewafer.lym"
    text = legacy.macro_text(src)
    line = next(ln for ln in text.splitlines() if ln.startswith("path="))
    text = text.replace(line, f"path={str(tmp_path) + '/'!r}")
    folder = str(legacy.LEGACY / "python")
    sys.path.insert(0, folder)
    try:
        exec(compile(text, str(src), "exec"), {"pya": pya, "__name__": "legacy_wafer75"})  # noqa: S102
    finally:
        sys.path.remove(folder)
    ref = pya.Layout()
    ref.read(str(tmp_path / "75x75wafer.gds"))
    top = ref.top_cells()[0]
    cell = build(WaferMap75)
    ours_1 = region(cell, QCC_LAYERS["chip_boundary"]) + region(cell, QCC_LAYERS["wafer_markers"])
    assert_xor_empty(ours_1, legacy_drawn(ref, top, 1), "WaferMap75 borders + labels")
    assert_xor_empty(region(cell, QCC_LAYERS["wafer_boundary"]), legacy_drawn(ref, top, 2), "WaferMap75 circle")


def test_die_and_wafer_positions():
    from quantcore_circuits.layouts.wafers.legacy_wafer import die_chip_offsets, wafer_01_die_positions

    assert die_chip_offsets() == [(3750, 3750), (-3750, 3750), (-3750, -3750), (3750, -3750)]
    dies, res = wafer_01_die_positions()
    assert len(dies) == 16 and dies[0] == (-22500.0, 22500.0) and dies[-1] == (22500.0, -22500.0)
    assert len(res) == 9 + 9 + 5 + 5 + 5 + 5


def test_flux_holes_at_centres():
    """Notebook 14 ``FluxHoles``: ``draw.rectangle(size, size, cx, cy)`` per centre; pairs or a flat list."""
    centers = [[100, 0], [110, 0], [-35.5, 12.25]]
    cell = build(cpw_segment.FluxHoles, **cpw_segment.FluxHoles.qcc_params({"centers": centers, "hole_size": 5}))
    ref = pya.Region()
    for x, y in centers:
        ref.insert(pya.DBox(x - 2.5, y - 2.5, x + 2.5, y + 2.5).to_itype(0.001))
    assert_xor_empty(region(cell, GAP), ref, "FluxHoles")
    flat = build(cpw_segment.FluxHoles, centers=[v for c in centers for v in c], hole_size=5)
    assert_xor_empty(region(flat, GAP), ref, "FluxHoles (flat)")
    with pytest.raises(ValueError, match="unknown"):
        cpw_segment.FluxHoles.qcc_params({"centres": centers})


def test_flux_holes_plan_from_design():
    from quantcore_circuits.assembly import plan_design
    from quantcore_circuits.design import load_design

    probe = {
        "schema": "qcc/0.1",
        "name": "probe",
        "instances": {"H": {"cell": "FluxHoles", "params": {"centers": [[0, 0], [20, 0]]}, "place": {"at": [0, 0]}}},
    }
    placed = plan_design(load_design(probe)).instances["H"]
    assert placed.cell.endswith("FluxHoles") and not placed.local_ports


# chips 01–06: textGen.text('JS=1.0', dbu, 200, False), the qubit numbers ('1', 300, True), chip_03 'TOP=500nm' and
# the chip signature 'QCG_Nb03_W'
@pytest.mark.parametrize(
    "text, mag, inv", [("JS=1.0", 200, False), ("1", 300, True), ("TOP=500nm", 200, False), ("QCG_Nb03_W", 200, False)]
)
def test_text_label(text, mag, inv):
    ref = pya.TextGenerator.default_generator().text(text, 0.001, mag, inv)
    cell = build(shapes.TextLabel, text=text, mag=mag, inverted=inv)
    assert_xor_empty(region(cell, GAP), ref, f"TextLabel {text!r}")
    metal = build(shapes.TextLabel, text=text, mag=mag, inverted=inv, metal=True)
    assert region(metal, GAP).is_empty() and not region(metal, ADD).is_empty()

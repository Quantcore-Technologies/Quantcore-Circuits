"""``SpiralLine`` (legacy ``components/python/draw.py::spiral``, request #7: kinetic-inductance / TWPA spirals):
golden XOR against the legacy function, ports and the LOM line."""

from __future__ import annotations

import math

import pytest
from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya

from quantcore_circuits.layouts.others.spirals import SpiralLine
from tests.legacy_ref import legacy

ADD, GAP = default_layers["1t1_base_metal_addition"], default_layers["1t1_base_metal_gap_wo_grid"]
_KEEP = []


def region(cell, info) -> pya.Region:
    return pya.Region(cell.begin_shapes_rec(cell.layout().layer(info))).merged()


def build(**params):
    layout = pya.Layout()
    _KEEP.append(layout)
    return SpiralLine.create(layout, **params)


@pytest.fixture(scope="module")
def draw_module():
    """The legacy ``draw`` module, executed read-only; its double-Fermat branch computes ``y_bls`` and then uses an
    undefined ``y1s`` (NameError), so that one name is fixed in the executed copy."""
    if not legacy.available():
        pytest.skip("legacy components/ folder not present")
    path = legacy.LEGACY / "python" / "draw.py"
    text = path.read_text(encoding="utf-8", errors="replace")
    assert text.count("y_bls=r*np.sin(phi)") == 1
    namespace: dict = {"__name__": "qwri_legacy_draw"}
    exec(compile(text.replace("y_bls=r*np.sin(phi)", "y1s=r*np.sin(phi)"), str(path), "exec"), namespace)  # noqa: S102
    return namespace


# (spiral_type, start, end, spiral_r µm, width µm, points)
CASES = [
    ("archimedean", 0.0, 10 * math.pi, 2.0, 1.0, 600),
    ("fermat", 0.0, 12 * math.pi, 10.0, 2.0, 1000),
    ("fermat", 0.5, 8 * math.pi, 15.0, 3.0, 400),
    ("double_fermat", 0.0, 12 * math.pi, 10.0, 2.0, 1000),
    ("double_fermat", 0.2, 6 * math.pi, 20.0, 1.5, 500),
]


@pytest.mark.parametrize("kind, start, end, r, w, n", CASES)
def test_spiral_line_matches_legacy_draw(draw_module, kind, start, end, r, w, n):
    """Legacy call: ``spiral(x, y, w, start_ang, end_ang, spiral_r, spiral_type, npoints, layer)`` in dbu (1 nm);
    ours: µm. The etched variant (``metal=False``) is the legacy drawing on 1/0."""
    import klayout.db as kdb

    layout = kdb.Layout()
    _KEEP.append(layout)
    draw_module["make_cell"]("TOP", 0.001, layout)
    cell, _ = draw_module["get_current_cell"]()
    draw_module["spiral"](0, 0, w * 1000, start, end, r * 1000, {"archimedean": 0, "fermat": 1}.get(kind, 2), n, 1)
    ref = pya.Region(cell.begin_shapes_rec(layout.layer(1, 0))).merged()
    ours = region(
        build(spiral_type=kind, start_angle=start, end_angle=end, spiral_r=r, width=w, points=n, metal=False), GAP
    )
    diff = (ours ^ ref).sized(-1)
    assert diff.is_empty(), f"{kind}: XOR area {diff.area()} dbu²"
    assert ours.area() > 0
    metal = build(spiral_type=kind, start_angle=start, end_angle=end, spiral_r=r, width=w, points=n)
    assert (region(metal, ADD) ^ ours).is_empty() and region(metal, GAP).is_empty()


def test_spiral_line_ports_and_pocket():
    """Double Fermat: both ends outside, on opposite sides (point reflection), facing outward along the tangent;
    the pocket is the bbox grown by ``pocket_margin`` minus the line."""
    from quantcore_circuits.layouts.registry import element_cell_ports

    cell = build(pocket_margin=20)
    ports = element_cell_ports(SpiralLine, cell, {"pocket_margin": 20})
    a, b = ports["a"], ports["b"]
    r_end = 10 * math.sqrt(12 * math.pi)
    assert a.pos.distance(pya.DPoint(0, 0)) == pytest.approx(r_end, abs=0.01)
    assert b.pos.distance(pya.DPoint(0, 0)) == pytest.approx(r_end, abs=0.01)
    assert a.pos.x == pytest.approx(-b.pos.x, abs=0.002) and a.pos.y == pytest.approx(-b.pos.y, abs=0.002)
    assert (a.a, a.b) == (2.0, 6.0) and a.dir is not None and b.dir is not None
    line, pocket = region(cell, ADD), region(cell, GAP)
    assert (line & pocket).is_empty() and pocket.bbox() == line.bbox().enlarged(20000, 20000)
    fermat = element_cell_ports(SpiralLine, build(spiral_type="fermat"), {"spiral_type": "fermat"})
    assert fermat["a"].pos.distance(pya.DPoint(0, 0)) < 0.01  # single Fermat starts at the centre


def test_spiral_line_length_and_lom():
    """LOM: one conductor a → b, a resonator line of the drawn length (open ends), gap = mean turn spacing."""
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    params = {"spiral_type": "double_fermat", "spiral_r": 10, "end_angle": 12 * math.pi, "width": 2}
    pts = SpiralLine.qcc_points(params)
    length = sum(pts[i].distance(pts[i + 1]) for i in range(len(pts) - 1)) / 1000
    assert SpiralLine.qcc_length(params) == pytest.approx(length)
    # a Fermat arm r = s√φ from 0 to Φ has length ≈ s ∫ √(φ + 1/(4φ)) dφ ≈ (2/3) s Φ^1.5 for large Φ (two arms here)
    assert length == pytest.approx(2 * (2 / 3) * 10 * (12 * math.pi) ** 1.5, rel=0.02)
    turns = 6
    assert SpiralLine.qcc_turn_gap(params) == pytest.approx((10 * math.sqrt(12 * math.pi)) / turns / 2 - 2, rel=0.01)
    inst = Instance.model_validate({"cell": "SpiralLine", "params": params, "place": {"at": [0, 0]}})
    frag = lom_model("SpiralLine")("S", inst, get_pdk())
    (line,) = frag.lines
    assert line.ports == ("a", "b") and line.term == ("open", "open") and line.resonator
    assert line.length_um == pytest.approx(length) and line.a_um == 2
    assert frag.port_nodes == {"a": "line", "b": "line"}
    etched = Instance.model_validate({"cell": "SpiralLine", "params": {"metal": False}, "place": {"at": [0, 0]}})
    assert not lom_model("SpiralLine")("S", etched, get_pdk()).lines

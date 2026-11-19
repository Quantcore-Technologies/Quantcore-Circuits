"""Cells re-implemented from gdsfactory/quantum-rf-pdk (QPDK, MIT) and sqdlab/SQDMetal (Apache-2.0) for the
builder's QPDK / SQDMetal replicas: NeckTermination, Flipmon, Gatemon + GatemonCoupler, TransmonTaperedInsets,
SmoothCapacitorSemicircle, HyperbolicVertexCoupler. The sources are never imported or run; the expected numbers
below are worked out by hand from their code (cited per test)."""

from __future__ import annotations

import math

import pytest
from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya

from quantcore_circuits.assembly.plan import pcell_params
from quantcore_circuits.layouts.ports import CellBuildError
from quantcore_circuits.layouts.registry import create_cell, element_cell_ports, resolve_cell
from tests.test_catalog import _drawn_widths

GAP, ADD = "1t1_base_metal_gap_wo_grid", "1t1_base_metal_addition"


def _build(ref: str, **params):
    cls = resolve_cell(ref)
    pp = pcell_params(cls, params)
    layout = pya.Layout()
    cell = create_cell(layout, cls, what=ref, **pp)
    return layout, cell, element_cell_ports(cls, cell, pp)


def _region(layout, cell, layer: str) -> pya.Region:
    return pya.Region(cell.begin_shapes_rec(layout.layer(default_layers[layer]))).merged()


def _refpoints(layout, cell) -> dict:
    from kqcircuits.elements.element import get_refpoints

    return get_refpoints(layout.layer(default_layers["refpoints"]), cell, rec_levels=0)


def _etched(region: pya.Region, p: pya.DPoint, dbu: float) -> bool:
    q = p.to_itype(dbu)
    return not region.interacting(pya.Region(pya.Box(q.x - 1, q.y - 1, q.x + 1, q.y + 1))).is_empty()


def _close(p: pya.DPoint, x: float, y: float, tol: float = 1e-3) -> bool:
    return abs(p.x - x) <= tol and abs(p.y - y) <= tol


def _dir(port) -> tuple[float, float]:
    return round(port.dir.x, 6), round(port.dir.y, 6)


def _check_cpw_ports(layout, cell, ports, names):
    """Drawn centre width == declared a and drawn gaps >= declared b just inside each named port."""
    gap = _region(layout, cell, GAP)
    for name in names:
        port = ports[name]
        drawn = _drawn_widths(gap, port.pos, port.dir, layout.dbu)
        assert drawn is not None, f"{name}: centre conductor etched at the port"
        a, (g1, g2) = drawn
        assert abs(a - port.a) <= 0.3, f"{name}: drawn a {a:.2f}, declared {port.a}"
        assert min(g1, g2) >= port.b - 0.3, f"{name}: drawn gaps {g1:.2f}/{g2:.2f}, declared b {port.b}"


# ---- NeckTermination (qpdk/cells/vortex.py::neck_termination) -------------------------------------------------
def test_neck_termination_geometry_and_port():
    layout, cell, ports = _build("NeckTermination")
    dbu = layout.dbu
    assert set(ports) == {"o1"}
    o1 = ports["o1"]
    assert _close(o1.pos, 0, 0) and _dir(o1) == (-1, 0) and (o1.a, o1.b) == (10, 6)
    gap = _region(layout, cell, GAP)
    # window 425 × 380 µm; outermost hole row: 425 + 6 + 3 × 5.5 + 4 = 451.5 µm, 190 + 6 + 3 × 5.5 + 4 = 216.5 µm
    assert gap.bbox().to_dtype(dbu) == pya.DBox(0, -216.5, 451.5, 216.5)
    # the conductor runs from the port to the far window edge: unetched on the axis, etched beside it
    for x in (0.5, 50, 99.5, 200, 424.5):
        assert not _etched(gap, pya.DPoint(x, 0), dbu), x
    assert _etched(gap, pya.DPoint(300, 1.2), dbu) and not _etched(gap, pya.DPoint(300, 0.9), dbu)  # 2 µm neck
    assert _etched(gap, pya.DPoint(50, 3.2), dbu) and not _etched(gap, pya.DPoint(50, 2.8), dbu)  # taper: 6 µm at x 50
    assert not _etched(gap, pya.DPoint(425.5, 0), dbu)  # the neck joins the ground
    # hole-free column on the neck axis beyond the window: (24 + 4) / 2 = 14 µm half-width
    holes_beyond = (gap & pya.Region(pya.DBox(426, -220, 460, 220).to_itype(dbu))).merged()
    assert all(abs(p.bbox().center().y * dbu) > 14 for p in holes_beyond.each())
    assert holes_beyond.count() > 0
    rp = _refpoints(layout, cell)
    assert _close(rp["neck_start"], 100, 0) and _close(rp["neck_end"], 425, 0)
    _check_cpw_ports(layout, cell, ports, ["o1"])


def test_neck_termination_options_and_checks():
    layout, cell, _ = _build("NeckTermination", taper_shape="smooth", trap_hole_rows=0, neck_width=1)
    gap = _region(layout, cell, GAP)
    assert gap.count() == 2 and gap.bbox().to_dtype(layout.dbu) == pya.DBox(0, -190, 425, 190)  # two halves
    # raised cosine: half width at mid-taper (1 + (10 - 1) / 2) / 2 = 2.75 µm
    assert _etched(gap, pya.DPoint(50, 2.9), layout.dbu) and not _etched(gap, pya.DPoint(50, 2.6), layout.dbu)
    for bad in ({"neck_width": 10}, {"window_width": 20}, {"trap_hole_size": 6}):
        with pytest.raises(CellBuildError):
            _build("NeckTermination", **bad)


# ---- GatemonCoupler + Gatemon (qpdk/cells/gatemon.py) ---------------------------------------------------------
def test_gatemon_coupler_ports():
    layout, cell, ports = _build("GatemonCoupler")
    assert set(ports) == {"o1", "o2", "qubit"}
    assert _close(ports["o1"].pos, 0, 0) and _dir(ports["o1"]) == (-1, 0)
    assert _close(ports["o2"].pos, 600, 0) and _dir(ports["o2"]) == (1, 0)
    q = ports["qubit"]
    assert _close(q.pos, 200, -45) and _dir(q) == (0, -1) and (q.a, q.b) == (150, 40)  # 10/2 + 40 below the line
    _check_cpw_ports(layout, cell, ports, ["o1", "o2"])
    _, _, top = _build("GatemonCoupler", qubit_side="top", coupling_position=150)
    assert _close(top["qubit"].pos, 150, 45) and _dir(top["qubit"]) == (0, 1)


def test_gatemon_geometry_and_ports():
    layout, cell, ports = _build("Gatemon")
    dbu = layout.dbu
    assert set(ports) == {"readout", "gate", "squid_a", "squid_b"}
    r, g = ports["readout"], ports["gate"]
    assert _close(r.pos, 0, 75) and _dir(r) == (0, 1) and (r.a, r.b) == (150, 40)
    # QPDK: pocket bottom = -75 - 0.15·60 - 100 - 0.2·60 = -196; gate CPW 50 µm below it at x = -40 + 100
    assert _close(g.pos, 60, -246) and _dir(g) == (0, -1) and (g.a, g.b) == (10, 6)
    gap = _region(layout, cell, GAP)
    assert gap.bbox().to_dtype(dbu) == pya.DBox(-135, -246, 135, 115)  # pocket ± (75 + 60), top 75 + 40
    assert not _etched(gap, pya.DPoint(0, 0), dbu) and _etched(gap, pya.DPoint(0, 100), dbu)
    assert not _etched(gap, pya.DPoint(60, -130), dbu) and not _etched(gap, pya.DPoint(53, -134), dbu)  # feed, landing
    rp = _refpoints(layout, cell)
    assert _close(rp["junction"], -20, -134) and _close(rp["port_squid_a"], -40, -75)
    assert _close(rp["port_squid_b"], -40, -196)
    _check_cpw_ports(layout, cell, ports, ["gate"])
    # the island is its own conductor (the weak link is not drawn): metal in the pocket = island + gate feed
    metal = (pya.Region(gap.bbox()) - gap).merged() & pya.Region(pya.DBox(-135, -196, 135, 115).to_itype(dbu))
    assert metal.count() == 2
    with pytest.raises(CellBuildError):
        _build("Gatemon", electrode_offset=-60)  # electrodes outside the island (QPDK check)


def test_gatemon_snaps_to_its_coupler():
    """The gatemon's pocket opens exactly onto the coupler's conductor edge (QPDK gatemon_test_chip placement)."""
    from quantcore_circuits.assembly import build
    from quantcore_circuits.design import load_design

    design = {
        "schema": "qcc/0.1",
        "name": "gatemon_probe",
        "chip": {"box": [0, 0, 2000, 2000], "params": {"die_frame": False}},
        "instances": {
            "K": {"cell": "GatemonCoupler", "place": {"at": [700, 1200]}},
            "G": {"cell": "Gatemon", "place": {"snap": "G.readout", "to": "K.qubit"}},
        },
    }
    result = build(load_design(design))
    g = result.plan.instances["G"]
    readout = g.ports["readout"]
    assert _close(readout.pos, 900, 1155) and _dir(readout) == (0, 1)
    assert g.trans.angle % 360 == pytest.approx(0)
    gap = pya.Region(result.top.begin_shapes_rec(result.layout.layer(default_layers[GAP]))).merged()
    dbu = result.layout.dbu
    assert not _etched(gap, pya.DPoint(900, 1200), dbu)  # line conductor intact over the island
    assert _etched(gap, pya.DPoint(900, 1194.8), dbu) and _etched(gap, pya.DPoint(900, 1157), dbu)  # pocket to line
    assert not _etched(gap, pya.DPoint(900, 1150), dbu)  # island


# ---- Flipmon (qpdk/cells/transmon.py::flipmon_with_bbox) ------------------------------------------------------
def test_flipmon_faces_and_coupler():
    layout, cell, ports = _build("Flipmon", junction_type="No Squid")
    dbu = layout.dbu
    assert set(ports) == {"coupler", "squid_a", "squid_b"}
    c = ports["coupler"]
    assert _close(c.pos, 170, 0) and _dir(c) == (1, 0) and (c.a, c.b) == (10, 6)  # 110 + 30 + 30
    m1 = _region(layout, cell, GAP)
    m2 = _region(layout, cell, "2b1_base_metal_gap_wo_grid")
    assert m1.bbox().to_dtype(dbu) == pya.DBox(-170, -170, 170, 170)
    assert m2.bbox().to_dtype(dbu) == pya.DBox(-150, -150, 150, 150)  # 110 + 40
    # M1: disc r 60, gap 60-80, ring 80-140 (QPDK ring = centre radius ± width / 2), gap 140-170
    for r, etched in ((59, False), (70, True), (81, False), (139, False), (141, True), (169, True)):
        assert _etched(m1, pya.DPoint(0, r), dbu) is etched, r
    assert not _etched(m2, pya.DPoint(0, 109), dbu) and _etched(m2, pya.DPoint(0, 111), dbu)
    for face in ("1t1", "2b1"):
        bump = _region(layout, cell, f"{face}_indium_bump")
        assert bump.bbox().to_dtype(dbu).width() == pytest.approx(15, abs=0.01)
    # coupler plate 145-155 µm (QPDK: 10 µm beyond outer_ring_outside, rotated R180) with its etch box ± 2 µm
    assert not _etched(m1, pya.DPoint(150, 28), dbu) and _etched(m1, pya.DPoint(150, 30.5), dbu)
    assert _etched(m1, pya.DPoint(143.5, 0), dbu) and not _etched(m1, pya.DPoint(145.5, 0), dbu)
    # M1 conductors: disc, ring, plate + lead (no junction drawn)
    metal = (pya.Region(m1.bbox()) - m1).merged() & pya.Region(
        pya.DPolygon.ellipse(pya.DBox(-169, -169, 169, 169), 256).to_itype(dbu)
    )
    assert metal.count() == 3
    rp = _refpoints(layout, cell)
    assert _close(rp["junction"], 70, 0) and _close(rp["port_squid_a"], 60, 0) and _close(rp["port_squid_b"], 80, 0)
    assert _close(rp["outer_ring_outside"], 140, 0)
    _check_cpw_ports(layout, cell, ports, ["coupler"])


@pytest.mark.parametrize("junction_type", ["Manhattan", "Trilayer Junction", "No Squid"])
def test_flipmon_junction_types_and_rotation(junction_type):
    layout, cell, ports = _build("Flipmon", junction_type=junction_type, junction_position_rotation=180)
    rp = _refpoints(layout, cell)
    assert _close(rp["junction"], -70, 0)
    if junction_type != "No Squid":
        fingers = _region(layout, cell, "1t1_SIS_junction")
        assert not fingers.is_empty()
        box = fingers.bbox().to_dtype(layout.dbu)
        assert -82 < box.left and box.right < -58  # across the disc-ring gap on the -x side
    _, _, bare = _build("Flipmon", with_coupler=False, junction_type="No Squid")
    assert "coupler" not in bare


# ---- HyperbolicVertexCoupler (qpdk/cells/hyperbolic.py::hyperbolic_vertex_coupler) -----------------------------
def test_hyperbolic_vertex_coupler_pins():
    layout, cell, ports = _build("HyperbolicVertexCoupler")
    dbu = layout.dbu
    assert set(ports) == {"o1", "o2", "o3"}
    for k in range(3):
        p = ports[f"o{k + 1}"]
        a = math.radians(120 * k)
        assert _close(p.pos, round(60 * math.cos(a), 3), round(60 * math.sin(a), 3))  # 40 + 20, 1 nm grid
        assert p.dir.x == pytest.approx(math.cos(a), abs=1e-4) and p.dir.y == pytest.approx(math.sin(a), abs=1e-4)
    gap = _region(layout, cell, GAP)
    # three pie-slice pins: the metal inside r = 43 (rim 40 + half the 6 µm ground gap) is three islands
    metal = (pya.Region(gap.bbox()) - gap).merged() & pya.Region(
        pya.DPolygon.ellipse(pya.DBox(-43, -43, 43, 43), 256).to_itype(dbu)
    )
    assert metal.count() == 3
    assert _etched(gap, pya.DPoint(20 * math.cos(math.radians(60)), 20 * math.sin(math.radians(60))), dbu)
    _check_cpw_ports(layout, cell, ports, ["o1"])
    _, _, seven = _build("HyperbolicVertexCoupler", q=7, rotation=10, pin_radius=60)
    assert len(seven) == 7
    assert math.degrees(math.atan2(seven["o1"].dir.y, seven["o1"].dir.x)) == pytest.approx(10, abs=1e-3)
    for bad in ({"q": 1}, {"q": 16}):  # q = 16 at r 40: inner chord 2·30·sin(π/16) − 4 = 7.7 µm < 10 µm lead
        with pytest.raises(CellBuildError):
            _build("HyperbolicVertexCoupler", **bad)


# ---- TransmonTaperedInsets (SQDMetal Comps/Qubits.py) ----------------------------------------------------------
TWO_TRANSMONS = {"pocket_lower_tighten": 0, "pocket_height": 420, "chrgln_pin_x_offset": 0, "chrgln_pin_y_offset": -10}


def test_transmon_tapered_insets_pins_and_pads():
    layout, cell, ports = _build("TransmonTaperedInsets", junction_type="No Squid", **TWO_TRANSMONS)
    dbu = layout.dbu
    expected = {  # SQDMetal pin middles / normals (2_transmons_wRes_comp options)
        "top_right_pin": ((490, 105), (1, 0)),
        "top_left_pin": ((-490, 105), (1, 0)),
        "bottom_right_pin": ((490, -105), (0, 1)),
        "bottom_left_pin": ((-490, -105), (0, 1)),
        "top_pocket_pin": ((0, 210), (1, 0)),
        "bottom_pocket_pin": ((0, -210), (-1, 0)),
    }
    assert set(ports) == set(expected) | {"squid_a", "squid_b"}
    for name, ((x, y), d) in expected.items():
        assert _close(ports[name].pos, x, y) and _dir(ports[name]) == d, name
    gap = _region(layout, cell, GAP)
    assert gap.bbox().to_dtype(dbu) == pya.DBox(-500, -210, 500, 210)
    # pads: 800 µm + round ends of 55 µm radius → ±455 µm; 110 µm high from y = 50
    for p, etched in (((454, 105), False), ((456, 105), True), ((0, 51), False), ((300, 49), True), ((0, 0), True)):
        assert _etched(gap, pya.DPoint(*p), dbu) is etched, p
    # taper tips 20 µm apart at x = 0 (pad_gap 100 - 2 × 40), flat tip kept by the 50 µm opening (≈ 16 µm wide)
    assert not _etched(gap, pya.DPoint(0, 10.5), dbu) and _etched(gap, pya.DPoint(0, 9.5), dbu)
    assert not _etched(gap, pya.DPoint(7, 10.5), dbu) and _etched(gap, pya.DPoint(19, 10.5), dbu)
    pads = _region(layout, cell, ADD)
    assert pads.count() == 2  # two floating pads, also positive metal
    rp = _refpoints(layout, cell)
    assert _close(rp["port_squid_a"], 0, 18) and _close(rp["port_squid_b"], 0, -18)
    assert _close(rp["pin_island"], 0, 30) and _close(rp["pin_reservoir"], 0, -30)


def test_transmon_tapered_insets_connection_pad():
    """floating_transmon: readout pad 100 µm above the top pad, wire to pocket_width / 2 + cpw_extend = 700 µm."""
    params = {"connection_pads": {"readout": {"pad_gap": 100}}, "inductor_height": 100, "taper_height": 0}
    layout, cell, ports = _build("TransmonTaperedInsets", **params)
    dbu = layout.dbu
    ro = ports["readout"]
    assert _close(ro.pos, 0, 700) and _dir(ro) == (0, 1) and (ro.a, ro.b) == (10, 6)
    _check_cpw_ports(layout, cell, ports, ["readout"])
    gap = _region(layout, cell, GAP)
    assert not _etched(gap, pya.DPoint(95, 275), dbu) and _etched(gap, pya.DPoint(105, 275), dbu)  # 200 × 30 pad
    assert not _etched(gap, pya.DPoint(0, 500), dbu) and _etched(gap, pya.DPoint(7, 500), dbu)  # wire in the ground
    assert not _etched(gap, pya.DPoint(-20, 295), dbu)  # 75 µm outer fillet between pad and wire
    rp = _refpoints(layout, cell)
    assert _close(rp["port_squid_a"], 0, 50) and _close(rp["port_squid_b"], 0, -50)
    fingers = _region(layout, cell, "1t1_SIS_junction")
    assert not fingers.is_empty()  # Manhattan across the 100 µm pad gap
    side = {"connection_pads": {"r": {"loc_W": 1, "loc_H": -1}}, "inset_width": 60, "junction_position": "right"}
    _, _, sp = _build("TransmonTaperedInsets", **side)
    assert _close(sp["r"].pos, 700, -265) and _dir(sp["r"]) == (1, 0)
    with pytest.raises(ValueError, match="unknown option"):
        pcell_params(resolve_cell("TransmonTaperedInsets"), {"connection_pads": {"r": {"pad_wdth": 3}}})


# ---- SmoothCapacitorSemicircle (SQDMetal Comps/Capacitors.py) --------------------------------------------------
CAP = {"rect_width": 160, "rect_length": 80, "semi_radius": 60, "fillet_radius": 5, "fillet_resolution": 20}


def test_semicircle_capacitor_frame_and_ports():
    layout, cell, ports = _build("SmoothCapacitorSemicircle", **CAP)
    dbu = layout.dbu
    assert set(ports) == {"a", "target"}
    assert _close(ports["target"].pos, 0, 0) and _dir(ports["target"]) == (-1, 0)
    assert _close(ports["a"].pos, 30, 0) and _dir(ports["a"]) == (-1, 0)  # pad back edge: 100 - 80 + 10
    pad = _region(layout, cell, ADD)
    assert pad.bbox().to_dtype(dbu) == pya.DBox(30, -80, 110, 80)
    gap = _region(layout, cell, GAP)
    assert gap.bbox().to_dtype(dbu) == pya.DBox(5, -105, 135, 105)  # 25 µm clearances
    assert not _etched(gap, pya.DPoint(35, 0), dbu) and _etched(gap, pya.DPoint(45, 0), dbu)  # bite centre x 100, r 60
    rp = _refpoints(layout, cell)
    assert _close(rp["semicircle_center"], 100, 0)
    layout, cell, ports = _build("SmoothCapacitorSemicircle", orientation=180, lead_length=40, **CAP)
    assert _close(ports["a"].pos, 10, 0) and _dir(ports["a"]) == (1, 0)
    assert _region(layout, cell, ADD).bbox().to_dtype(layout.dbu) == pya.DBox(-110, -80, 10, 80)
    _check_cpw_ports(layout, cell, ports, ["a"])


@pytest.mark.parametrize("pin_offset, overlaps", [(-10, True), (0, False), (10, False)])
def test_semicircle_capacitor_on_the_qubit_pin(pin_offset, overlaps):
    """2_transmons_wRes_comp: Capacitor1 on Qubit1.top_right_pin, orientation 180. With the notebook's
    chrgln_pin_y_offset = -10 the source formulas put the bite centre 10 µm inside the pad end's centre, so the pad
    end (r 55) pokes 5 µm through the bite (r 60) into the capacitor; at 0 the two arcs are concentric (5 µm gap)."""
    params = {**TWO_TRANSMONS, "chrgln_pin_y_offset": pin_offset, "junction_type": "No Squid"}
    qlayout, qcell, qports = _build("TransmonTaperedInsets", **params)
    pin = qports["top_right_pin"]
    clayout, ccell, _ = _build("SmoothCapacitorSemicircle", orientation=180, **CAP)
    angle = math.degrees(math.atan2(pin.dir.y, pin.dir.x))
    cap = _region(clayout, ccell, ADD).transformed(
        pya.DCplxTrans(1, angle, False, pin.pos.x, pin.pos.y).to_itrans(clayout.dbu)
    )
    pads = _region(qlayout, qcell, ADD)
    assert (not (pads & cap).is_empty()) is overlaps
    if not overlaps:
        assert (pads & cap.sized(int(4 / qlayout.dbu))).is_empty()  # at least 4 µm clearance


def test_gatemon_process_layers():
    """Decision #29: the gatemon's contacts, nanotube, hBN, Al patches and top gate are drawn on the proposed 600–604/0
    layers (no fab numbers yet): contacts reach island and ground, the tube bridges the tip gap, the hBN lies
    in the pocket between island and ground and under the top gate, which lands on the M1 gate feed."""
    from quantcore_circuits.layouts.qubits.qpdk_cells import GATEMON_LAYERS, Gatemon

    layout = pya.Layout()
    cell = Gatemon.create(layout)
    reg = {k: pya.Region(cell.begin_shapes_rec(layout.layer(v))).merged() for k, v in GATEMON_LAYERS.items()}
    assert all(not r.is_empty() for r in reg.values())
    assert [(v.layer, v.datatype) for v in GATEMON_LAYERS.values()] == [(600 + i, 0) for i in range(5)]
    gap = pya.Region(cell.begin_shapes_rec(layout.layer(pya.LayerInfo(130, 1)))).merged()
    island = pya.Region(pya.DBox(-75, -75, 75, 75).to_itype(layout.dbu))
    contacts = list(reg["cnt_contact"].each())
    assert len(contacts) == 2  # island-side and ground-side contact, separated at the weak link
    assert sum(1 for c in contacts if not (pya.Region(c) & island).is_empty()) == 1
    assert all(not (pya.Region(c) - gap).is_empty() for c in contacts)  # each lands on M1 metal (island / ground)
    tube = reg["cnt"]
    assert all(not (tube & pya.Region(c)).is_empty() for c in contacts)  # the nanotube bridges both tips
    assert (reg["hbn"] - gap).is_empty() and (reg["top_gate"] & reg["hbn"]).area() > 0
    assert not (reg["top_gate"] - gap).is_empty()  # overlaps the M1 gate landing
    assert (reg["jj_patch"] - reg["cnt_contact"]).is_empty()
    off_layout = pya.Layout()
    off = Gatemon.create(off_layout, draw_process_layers=False)
    assert all(pya.Region(off.begin_shapes_rec(off_layout.layer(v))).is_empty() for v in GATEMON_LAYERS.values())

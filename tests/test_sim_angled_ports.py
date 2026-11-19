"""50 Ω termination of a line the eigenmode / driven box edge crosses at an angle (C6b, 2026-11-18).

KQC's at-edge port (signal 1 µm inside the box edge, ground ``a`` further in along the box normal) needs a square
crossing: on a diagonal line KQC finds no metal edge at its points, the port has no polygon and AEDT skips it, leaving
the line open (m53's ``D5_readout``, demoqpu17, tutorial 03: the 45° surface-17 lattice). A straight line crossing at
an angle now gets its port on its own axis just inside the box, the cut square to the line; square crossings keep
the at-edge port. Export only, no AEDT, nothing solved; ``sim_tools.geometry_check`` judges each job.
"""

from __future__ import annotations

import math

import pytest
from kqcircuits.pya_resolver import pya

from .test_sim_export_causes import PADS, _cell_design, _cell_export
from .test_sim_export_geometry import LJ

DBU = 0.001
# the box of group "cell" below: the Xmon at (5000, 5000) (its 130/1 bbox) + margin_um 200
BOX = (4625.0, 4625.0, 5375.0, 5454.0)


def _unit(deg: float) -> tuple[float, float]:
    return math.cos(math.radians(deg)), math.sin(math.radians(deg))


def _angled_design(angle: float) -> dict:
    """An Xmon and two straight lines at ``angle`` (deg from the x axis) through two corners of the box, open ends
    outside it: L_W (from the west pad) crosses the left edge ``angle`` from its normal and the top edge
    ``90° - angle`` from it; L_E (from the east pad) the right and the bottom edges likewise."""
    ux, uy = _unit(angle)
    q_w = (BOX[0], BOX[3] - 80.0)  # on the left edge, 80 µm below the top-left corner
    q_e = (BOX[2], BOX[1] + 80.0)  # on the right edge, 80 µm above the bottom-right corner
    routes = {
        "L_W": {"from": "BP_W.a", "type": "cpw", "nodes": [[q_w[0] - 450 * ux, q_w[1] - 450 * uy]],
                "to": {"at": [q_w[0] + 450 * ux, q_w[1] + 450 * uy], "dir": angle + 180.0, "term": 6.0}},
        "L_E": {"from": "BP_E.a", "type": "cpw", "nodes": [[q_e[0] + 450 * ux, q_e[1] + 450 * uy]],
                "to": {"at": [q_e[0] - 450 * ux, q_e[1] - 450 * uy], "dir": angle, "term": 6.0}},
    }
    data = _cell_design(f"geo_angled_{int(angle)}", {**PADS, "X": {"cell": "Xmon", "junction": LJ,
                                                                 "place": {"at": [5000.0, 5000.0], "rot": 0.0}}},
                        routes)
    data["sim_groups"]["cell"]["margin_um"] = 200.0
    return data


def _crossing_angle(box: pya.DBox, sig, gnd) -> float:
    """Angle (deg) between the port axis (signal → ground) and the normal of the box edge the port is next to."""
    from quantcore_circuits.sim_tools.builder import _outward

    s, g = pya.DPoint(*sig[:2]), pya.DPoint(*gnd[:2])
    v = g - s
    out = _outward(box, s)
    return math.degrees(math.acos(min(1.0, abs(v.sprod(out)) / v.length())))


@pytest.mark.parametrize("angle", [45.0, 30.0])
def test_angled_crossings_get_a_port_on_the_line_axis(angle, tmp_path, caplog):
    """Every line end leaving the eigenmode box has a 50 Ω port with a polygon, cut square to the line (the port axis
    is the line's own direction, not the box normal) and the job passes the geometry check."""
    import json

    setup, job, check, logged = _cell_export(tmp_path, _angled_design(angle), "hfss_eigenmode", caplog)
    assert (setup.box.left, setup.box.bottom, setup.box.right, setup.box.top) == BOX  # no edge moved
    edge = [p for p in setup.ports if p.kind == "edge_lumped"]
    assert sorted(p.name for p in edge) == ["L_E", "L_E", "L_W", "L_W"]
    data = {d["number"]: d for d in setup.simulation.get_port_data()}
    angles = sorted(_crossing_angle(setup.box, data[p.number]["signal_location"], data[p.number]["ground_location"])
                    for p in edge)
    assert angles == pytest.approx(sorted([angle, angle, 90.0 - angle, 90.0 - angle]), abs=0.02)
    for p in edge:
        d = data[p.number]
        assert "polygon" in d, (p.name, d)
        assert d["resistance"] == 50.0 and d["etch_width"] == 16.0
        poly = pya.DPolygon([pya.DPoint(x, y) for x, y, _ in d["polygon"]])
        assert abs(poly.area() - 10.0 * 10.0) < 0.05  # a × a: the cut across the 10 µm centre conductor, square
        assert all(setup.box.contains(pt) for pt in poly.each_point_hull())
        for loc in ("signal_location", "ground_location"):  # AEDT: the current line's ends lie on the sheet
            pt = pya.DPoint(*d[loc][:2])
            assert poly.inside(pt) or min(e.distance_abs(pt) for e in poly.each_edge()) < 1e-9, (p.name, loc)
    assert not logged, logged
    assert not check["errors"], check["errors"]
    assert not [n for n in setup.notes if "no port polygon" in n], setup.notes
    assert any("on the line's own axis" in n for n in setup.notes), setup.notes
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    assert [p["kind"] for p in meta["ports"]].count("edge_lumped") == 4


def test_angled_crossing_driven_uses_the_lumped_port(tmp_path, caplog):
    """Driven: a wave port needs the line normal to the box face, so an angled crossing gets the same lumped 50 Ω
    port (signal on the line, the stub to the box wall the reference)."""
    setup, _, check, logged = _cell_export(tmp_path, _angled_design(45.0), "hfss_driven", caplog)
    data = {d["number"]: d for d in setup.simulation.get_port_data()}
    lumped = [p for p in setup.ports if p.kind == "edge_lumped"]
    assert len(lumped) == 4 and not [p for p in setup.ports if p.kind == "edge"]
    for p in lumped:
        d = data[p.number]
        assert d["type"] == "InternalPort" and "polygon" in d
        s, g = pya.DPoint(*d["signal_location"][:2]), pya.DPoint(*d["ground_location"][:2])
        from quantcore_circuits.sim_tools.builder import _outward

        assert (s - g).sprod(_outward(setup.box, g)) < 0  # the signal point is the inner one (on the line)
    assert not logged and not check["errors"], check["errors"]
    assert any("lumped 50 Ω port instead of a wave port" in n for n in setup.notes), setup.notes


def test_line_port_geometry():
    """line_port on synthetic centre lines: on the axis, the cut's corner nearest the edge 1 µm inside it; at 90° it
    is KQC's at-edge port; a bend, a short straight or a line almost along the edge gets none."""
    from quantcore_circuits.sim_tools.builder import line_port

    box = pya.DBox(0, 0, 1000, 1000)
    a, b = 10.0, 6.0
    # 90°: the at-edge geometry (signal 1 µm inside the bottom edge, along the normal)
    lp = line_port([[pya.DPoint(500, -100), pya.DPoint(500, 300)]], box, pya.DPoint(500, 0), a, b)
    assert lp.signal.distance(pya.DPoint(500, 1)) < 1e-9 and lp.direction.sprod(pya.DVector(0, 1)) > 1 - 1e-12
    assert abs(lp.angle) < 1e-9
    # 45° and 30° from the normal, crossing the bottom edge at (500, 0)
    for deg in (45.0, 30.0):
        u = pya.DVector(math.sin(math.radians(deg)), math.cos(math.radians(deg)))
        spine = [[pya.DPoint(500, 0) - u * 100, pya.DPoint(500, 0) + u * 300]]
        lp = line_port(spine, box, pya.DPoint(500, 0), a, b)
        assert abs(lp.angle - deg) < 1e-6
        assert abs((lp.signal - pya.DPoint(500, 0)).vprod(u)) < 1e-9  # on the axis
        t = pya.DVector(-u.y, u.x) * ((a + b) / 2)
        assert abs(min((lp.signal + t).y, (lp.signal - t).y) - 1.0) < 1e-9  # nearest corner of the cut: 1 µm in
    # a bend at the crossing (an arc of 4° segments), a straight too short for the cut, a line 85° off the normal
    arc = [[pya.DPoint(500 + 100 * math.cos(math.radians(t)) - 100, -20 + 100 * math.sin(math.radians(t)))
            for t in range(0, 92, 4)]]
    assert line_port(arc, box, pya.DPoint(round(arc[0][0].x, 3), 0), a, b) is None
    short = [[pya.DPoint(500, -100), pya.DPoint(500, 5)], [pya.DPoint(500, 5), pya.DPoint(520, 25)]]
    assert line_port(short, box, pya.DPoint(500, 0), a, b) is None
    u = pya.DVector(math.sin(math.radians(85)), math.cos(math.radians(85)))
    assert line_port([[pya.DPoint(500, 0) - u * 100, pya.DPoint(500, 0) + u * 300]], box, pya.DPoint(500, 0), a,
                     b) is None


def test_line_port_ok_on_a_45_degree_cpw():
    """line_port_ok: KQC finds both edges after the cut and the cut parts the stub (to the box edge) from the line;
    the at-edge port of the same diagonal line fails edge_port_ok (the old C6 failure)."""
    from quantcore_circuits.sim_tools.builder import edge_port_ok, line_port, line_port_ok

    box = pya.DBox(0, 0, 1000, 1000)
    a, b = 10.0, 6.0
    u = pya.DVector(1, 1) * (1 / math.sqrt(2))
    n = pya.DVector(-u.y, u.x)
    p0, p1 = pya.DPoint(500, 0) - u * 200, pya.DPoint(500, 0) + u * 400

    def strip(off0, off1):
        return pya.DPolygon([p0 + n * off0, p1 + n * off0, p1 + n * off1, p0 + n * off1]).to_itype(DBU)

    gaps = pya.Region([strip(a / 2, a / 2 + b), strip(-a / 2 - b, -a / 2)])
    assert not edge_port_ok(gaps, box, pya.DPoint(500, 0), a, b, DBU)
    lp = line_port([[p0, p1]], box, pya.DPoint(500, 0), a, b)
    ground = lp.signal + lp.direction * a
    assert line_port_ok(gaps, box, lp.edge, lp.signal, ground, a + b, DBU)
    # a cut too narrow for the conductor leaves the stub joined to the line
    assert not line_port_ok(gaps, box, lp.edge, lp.signal, ground, a - 2.0, DBU)


def test_port_points_on_a_slanted_polygon():
    """AEDT refused a Lumped RLC whose current line ended 1e-5 µm outside its slanted port sheet (m53 FLNE_3, render
    2026-11-18): the exported points move onto the midpoints of KQC's signal / ground edges, and the geometry check
    flags a point off the polygon."""
    from quantcore_circuits.sim_tools.builder import edge_midpoint_locations
    from quantcore_circuits.sim_tools.geometry_check import check_port_lines

    s1, s2, g1, g2 = (8640.001, 9560.0), (8647.072, 9567.071), (8632.93, 9567.071), (8640.001, 9574.142)
    port = {"number": 6, "type": "InternalPort", "junction": False,
            "polygon": [[*s1, 0.0], [*s2, 0.0], [*g2, 0.0], [*g1, 0.0]],
            "signal_edge": ((*s1, 0.0), (*s2, 0.0)), "ground_edge": ((*g1, 0.0), (*g2, 0.0)),
            "signal_location": [8643.53651, 9563.53549, 0.0], "ground_location": [8636.46549, 9570.60651, 0.0]}
    meta = {"ports": [{"number": 6, "name": "FLNE_3", "kind": "edge_lumped"}]}
    bad = check_port_lines(meta, {"ports": [port]})
    assert len(bad) == 2 and "outside the port polygon" in bad[0]
    fixed = edge_midpoint_locations(port)
    assert not check_port_lines(meta, {"ports": [fixed]})
    assert fixed["signal_location"] == [(s1[0] + s2[0]) / 2, (s1[1] + s2[1]) / 2, 0.0]

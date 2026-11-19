import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits.design.schema import Route
from quantcore_circuits.route.router import RouteEnd, RoutingError, corner_violations, merge_collinear, plan_route

DEFAULTS = {"a": 10, "b": 6, "r": 100}


def end(x, y, dx, dy):
    return RouteEnd(pya.DPoint(x, y), pya.DVector(dx, dy), 10, 6)


def pts(plan):
    return [(round(p.x, 6), round(p.y, 6)) for p in plan.polyline()]


def test_straight_route_keeps_stubs():
    plan = plan_route("S", Route(**{"from": "A.a", "to": "B.a"}), end(0, 0, 1, 0), end(1000, 0, -1, 0), DEFAULTS)
    assert pts(plan) == [(0, 0), (100, 0), (900, 0), (1000, 0)]


def test_elbow_route_is_manhattan_and_fits():
    plan = plan_route("L", Route(**{"from": "A.a", "to": "B.a"}), end(0, 0, 1, 0), end(1000, 800, 0, -1), DEFAULTS)
    p = plan.polyline()
    assert all(abs(q.x - r.x) < 1e-9 or abs(q.y - r.y) < 1e-9 for q, r in zip(p, p[1:]))
    assert not corner_violations(p, 100)


def manhattan_and_fits(plan, r=100):
    p = merge_collinear(plan.polyline())
    return all(abs(q.x - s.x) < 1e-9 or abs(q.y - s.y) < 1e-9 for q, s in zip(p, p[1:])) and not corner_violations(
        p, r) and not corner_violations(plan.polyline(), r)


def test_jog_too_short_for_its_bends_detours_around():
    # facing ports 50 µm apart sideways: an S-jog needs 2r; the router goes around with three more corners
    plan = plan_route("J", Route(**{"from": "A.a", "to": "B.a"}), end(0, 0, 0, 1), end(50, 1000, 0, -1), DEFAULTS)
    assert manhattan_and_fits(plan)


def test_sideways_port_under_a_hanger_coupler_detours():
    # a port facing east whose hanger coupler starts 100 µm above-left of its stub end (TwoPadTransmon at rot 0)
    hanger = RouteEnd(pya.DPoint(3275, 3722), None, 10, 6, term=0.0,
                      approach=[pya.DPoint(2975, 3622), pya.DPoint(2975, 3722)])
    plan = plan_route("R", Route(**{"from": "Q.right", "to": "FL.x"}), end(3010, 2200, 1, 0), hanger, DEFAULTS)
    assert manhattan_and_fits(plan)
    assert pts(plan)[-2:] == [(2975, 3722), (3275, 3722)]


def test_port_at_an_angle_leaves_along_its_stub_then_goes_manhattan_or_oblique():
    # ConcentricTransmon coupler_2 faces 60°: the stub runs along the port, then the router draws one oblique bend where
    # the port's axis meets the other end's axis (an axis port 2900 µm east: it does here), else Manhattan corners
    # (was "could not auto-route Manhattan path", which also blocked every later edit of the user's design from showing)
    c, s = 0.5, 0.8660254037844386
    for far in (end(2900, 3500, 0, -1), end(1500, 3000, c, -s)):  # an axis port, and a second port at an angle
        plan = plan_route("A", Route(**{"from": "Q.c", "to": "B.a"}), end(2565, 1875, c, s), far, DEFAULTS)
        p = plan.polyline()
        assert (round(p[1].x - p[0].x, 6), round(p[1].y - p[0].y, 6)) == (round(100 * c, 6), round(100 * s, 6))
        assert not corner_violations(merge_collinear(p), 100)
    # the axis port: the oblique leg continues the stub's direction up to the bend above the end's axis
    plan = plan_route("A", Route(**{"from": "Q.c", "to": "B.a"}), end(2565, 1875, c, s), end(2900, 3500, 0, -1), DEFAULTS)
    p = plan.polyline()
    assert (round(p[2].x, 1), round(p[2].y, 1)) == (2900.0, 2455.2) and all(
        abs(q.x - r.x) < 1e-9 for q, r in zip(p[2:], p[3:]))
    # the other end's axis behind its stub: Manhattan after the stub, as before
    plan = plan_route("A", Route(**{"from": "Q.c", "to": "B.a"}), end(2565, 1875, c, s), end(2900, 1500, 0, 1), DEFAULTS)
    p = plan.polyline()
    assert all(abs(q.x - r.x) < 1e-9 or abs(q.y - r.y) < 1e-9 for q, r in zip(p[1:-1], p[2:-1]))


def test_user_nodes_too_close_for_their_bends_are_a_clear_error():
    # the router never moves the user's nodes: a 50 µm jog between two of them stays an error naming the segment
    route = Route(**{"from": "A.a", "to": "B.a", "nodes": [[0, 500], [50, 500]]})
    with pytest.raises(RoutingError, match="bends need"):
        plan_route("J", route, end(0, 0, 0, 1), end(50, 1000, 0, -1), DEFAULTS)


def test_waypoint_on_port_axis_replaces_stub():
    route = Route(**{"from": "A.a", "to": "B.a", "nodes": [{"at": [0, 950], "a": 1, "b": 7.5}]})
    plan = plan_route("F", route, end(0, 0, 0, 1), end(0, 1000, 0, -1), DEFAULTS)
    # the waypoint lies on both port axes: closer than r to B it replaces B's stub; A's stub stays a segment
    assert pts(plan) == [(0, 0), (0, 100), (0, 950), (0, 1000)]
    assert plan.nodes[2].params == {"a": 1, "b": 7.5}


def test_meander_can_use_a_straight_that_ends_at_a_waypoint_on_the_port_axis():
    from quantcore_circuits.route.router import meander_segment_index

    route = Route(**{"from": "A.a", "to": "B.a", "type": "meander", "length": 6000, "nodes": [[0, 2000], [500, 2000]]})
    plan = plan_route("M", route, end(0, 0, 0, 1), end(500, 2300, 0, -1), DEFAULTS)
    assert pts(plan)[:3] == [(0, 0), (0, 100), (0, 2000)]
    assert meander_segment_index(plan.nodes, None, plan.fixed_segments) == 2  # the 1900 µm straight, not the stub


def test_airbridges_auto_sets_n_bridges():
    route = Route(**{"from": "A.a", "to": "B.a", "airbridges": "auto"})
    plan = plan_route("AB", route, end(0, 0, 1, 0), end(3000, 0, -1, 0), DEFAULTS)
    assert all(n.params.get("n_bridges") == -1 for n in plan.nodes[1:])


def test_corner_violation_model():
    square = [pya.DPoint(0, 0), pya.DPoint(0, 300), pya.DPoint(150, 300), pya.DPoint(150, 600)]
    [(seg, length, need)] = corner_violations(square, 100)
    assert (seg, length, need) == (2, 150.0, pytest.approx(200.0))
    assert not corner_violations(square, 75)


def test_collinear_points_do_not_split_a_leg():
    """A straight leg given as several collinear points is one leg for the bend check (builder-c, KQC paths)."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.route.router import corner_violations, merge_collinear

    pts = [pya.DPoint(0, 0), pya.DPoint(30, 0), pya.DPoint(60, 1e-9), pya.DPoint(200, 0), pya.DPoint(200, 200)]
    assert len(merge_collinear(pts)) == 3
    assert corner_violations(merge_collinear(pts), r=50) == []
    assert corner_violations([pya.DPoint(0, 0), pya.DPoint(30, 0), pya.DPoint(30, 200)], r=50)  # a real violation


def test_waypoint_radius_applies_to_its_corner_only():
    """``Waypoint.r``: that corner's own bend radius (node param ``corner_r``); the bend-fit check uses it."""
    from quantcore_circuits.route.waveguide import WaveguideCompositeCorners, waveguide_class

    nodes = [{"at": [500, 0], "r": 250}, [500, 800]]
    plan = plan_route("C", Route(**{"from": "A.a", "to": "B.a", "nodes": nodes}), end(0, 0, 1, 0),
                      end(1200, 800, -1, 0), DEFAULTS)
    by_pos = {(round(n.position.x), round(n.position.y)): n.params for n in plan.nodes}
    assert by_pos[(500, 0)] == {"corner_r": 250.0} and by_pos[(500, 800)] == {}
    assert waveguide_class(plan.nodes) is WaveguideCompositeCorners
    plain = plan_route("P", Route(**{"from": "A.a", "to": "B.a", "nodes": [[500, 0], [500, 800]]}), end(0, 0, 1, 0),
                       end(1200, 800, -1, 0), DEFAULTS)
    assert waveguide_class(plain.nodes).__name__ == "WaveguideComposite"  # no per-corner radius: stock KQC
    # 300 µm leg: fits two r=100 bends (200 µm) but not r=250 + r=100 (350 µm)
    tight = [{"at": [500, 0], "r": 250}, [500, 300]]
    with pytest.raises(RoutingError, match="corner r 250"):
        plan_route("T", Route(**{"from": "A.a", "to": "B.a", "nodes": tight}), end(0, 0, 1, 0),
                   end(1200, 300, -1, 0), DEFAULTS)
    square = [pya.DPoint(0, 0), pya.DPoint(0, 300), pya.DPoint(150, 300), pya.DPoint(150, 600)]
    assert not corner_violations(square, 100, radii={(0.0, 300.0): 50.0, (150.0, 300.0): 50.0})


def test_last_node_off_a_hanger_approach_gets_the_corners_into_it():
    # a node moved in Route handles off the coupler's approach axis: the approach straight (r long) has room for the
    # bend into the coupler only, so the router adds the corner that enters it straight
    hanger = RouteEnd(pya.DPoint(3275, 3722), None, 10, 6, term=0.0,
                      approach=[pya.DPoint(2975, 3622), pya.DPoint(2975, 3722)])
    route = Route(**{"from": "Q.n", "to": "FL.x", "nodes": [[2700, 3000]]})
    plan = plan_route("R", route, end(2700, 2454, 0, 1), hanger, DEFAULTS)
    assert manhattan_and_fits(plan)
    assert (2700, 3000) in pts(plan) and pts(plan)[-2:] == [(2975, 3722), (3275, 3722)]


def test_meander_moves_to_another_straight_when_the_longest_cannot_take_it():
    from quantcore_circuits.route.router import fix_length

    plan = plan_route("M", Route(**{"from": "A.a", "to": "B.a", "type": "meander", "length": 3000}),
                      end(0, 0, 1, 0), end(1500, 800, -1, 0), DEFAULTS)
    longest = max((i for i in range(1, len(plan.nodes)) if i not in plan.fixed_segments),
                  key=lambda i: (plan.nodes[i].position - plan.nodes[i - 1].position).length())

    def measure(p):  # the meander "does not fit" on the longest straight (as KQC's "too close" error)
        inc = {i: n.length_increment for i, n in enumerate(p.nodes) if n.length_increment}
        if longest in inc:
            raise ValueError("Cannot create a Meander because start and end points are too close")
        base = sum((q.position - n.position).length() for n, q in zip(p.nodes, p.nodes[1:]))
        return base + sum(inc.values())

    got = fix_length(plan, measure)
    assert abs(got.length - 3000) < 0.01
    assert [i for i, n in enumerate(got.nodes) if n.length_increment] != [longest]
    with pytest.raises(RoutingError, match="does not fit on segment"):
        fix_length(plan, measure, segment=longest)


# ---- oblique straights (ports that face an angle) --------------------------------------------------------------------
def _dir(deg):
    import math

    return pya.DVector(math.cos(math.radians(deg)), math.sin(math.radians(deg)))


def at_angle(x, y, deg):
    return RouteEnd(pya.DPoint(x, y), _dir(deg), 10, 6)


def test_ports_facing_each_other_along_an_oblique_line_get_one_straight():
    import math

    a = math.radians(-18)  # StarQubit pin_cpl2 at 72° steps
    for off in (0.0, 0.5, 20.0):  # exactly on the line, a snapped position off it, a few µm off
        far = at_angle(1500 * math.cos(a) - off * math.sin(a), 1500 * math.sin(a) + off * math.cos(a), 162)
        plan = plan_route("S", Route(**{"from": "A.a", "to": "B.a"}), at_angle(0, 0, -18), far, DEFAULTS)
        p = plan.polyline()
        assert len(p) == 4 and plan.fixed_segments == {1, 3}  # stub, the straight, stub: the straight can hold a meander
        assert not corner_violations(merge_collinear(p), 100) and not corner_violations(p, 100)
        # the middle segment runs between the stub ends and is not axis aligned
        assert abs(p[2].x - p[1].x) > 1 and abs(p[2].y - p[1].y) > 1


def test_angled_port_whose_ray_meets_the_other_ends_axis_gets_one_oblique_bend():
    plan = plan_route("V", Route(**{"from": "A.a", "to": "B.a"}), at_angle(0, 0, -18), end(1500, -1500, 0, 1), DEFAULTS)
    p = plan.polyline()
    assert [(round(q.x, 1), round(q.y, 1)) for q in p[2:]] == [(1500.0, -487.4), (1500.0, -1400.0), (1500.0, -1500.0)]
    assert not corner_violations(merge_collinear(p), 100)
    # the ray passes behind the other end's stub: no oblique V, the Manhattan stair as before
    plan = plan_route("V", Route(**{"from": "A.a", "to": "B.a"}), at_angle(0, 0, 60), end(1500, 2500, 0, -1), DEFAULTS)
    assert all(abs(q.x - r.x) < 1e-9 or abs(q.y - r.y) < 1e-9 for q, r in zip(plan.polyline()[2:], plan.polyline()[3:]))


def test_axis_ports_keep_their_manhattan_routes():
    plan = plan_route("L", Route(**{"from": "A.a", "to": "B.a"}), end(0, 0, 1, 0), end(1000, 800, 0, -1), DEFAULTS)
    assert pts(plan) == [(0, 0), (100, 0), (1000, 0), (1000, 700), (1000, 800)] or manhattan_and_fits(plan)
    assert all(abs(q.x - r.x) < 1e-9 or abs(q.y - r.y) < 1e-9 for q, r in zip(plan.polyline(), plan.polyline()[1:]))


def test_oblique_route_with_a_meander_reaches_its_length(tmp_path):
    from quantcore_circuits.assembly import build

    d = {"schema": "qcc/0.1", "name": "obl", "pdk": "quantcore_nb_sapphire_v1",
         "chip": {"box": [0, 0, 7500, 7500], "params": {"name_chip": "OBL"}},
         "instances": {"SQ1": {"cell": "metal:StarQubit", "place": {"at": [5440, 1176], "rot": 0}},
                       "SQ2": {"cell": "metal:StarQubit", "place": {"at": [7104.4, 635.2], "rot": 180}}},
         "routes": {"R1": {"from": "SQ1.pin_cpl2", "to": "SQ2.pin_cpl2", "type": "meander", "length": 1500.0}}}
    r = build(d)
    p = r.plan.routes["R1"].polyline()
    assert len(p) == 4 and abs(p[2].y - p[1].y) > 1 and abs(p[2].x - p[1].x) > 1  # one oblique straight between stubs
    assert r.route_lengths()["R1"] == pytest.approx(1500.0, abs=0.05)


def test_meander_stays_on_its_straight_when_too_many_turns_are_asked(tmp_path):
    """A meander with more turns than the straight can hold (each turn takes 2r along it) used to run its first and
    last bends past the straight's end nodes (qpdk_cpw_jpa: over the SQUID termination). The turn count is now cut
    to what fits, and the meander's etched geometry stays inside the route's envelope (nodes ± a/2 + b along the
    straight, the meander's own width across it)."""
    from quantcore_circuits.assembly import build

    d = {"schema": "qcc/0.1", "name": "mnd", "pdk": "quantcore_nb_sapphire_v1",
         "chip": {"box": [0, 0, 7500, 7500], "params": {"name_chip": "MND"}},
         "instances": {"A": {"cell": "metal:LaunchpadWirebondDriven", "place": {"at": [1000, 3000], "rot": 0}},
                       "B": {"cell": "metal:LaunchpadWirebondDriven", "place": {"at": [1700, 3000], "rot": 180}}},
         "routes": {"R": {"from": "A.tie", "to": "B.tie", "type": "meander", "length": 3000.0, "meanders": 6,
                          "r": 60.0}}}
    r = build(d)
    plan = r.plan.routes["R"]
    assert r.route_lengths()["R"] == pytest.approx(3000.0, abs=0.05)
    seg = next(i for i, n in enumerate(plan.nodes) if n.length_increment is not None)
    assert plan.nodes[seg].params["meanders"] <= 3  # a 0.53 mm straight holds int(530 / 120 - 1) turns, not 6
    pts = [n.position for n in plan.nodes]
    x0, x1 = sorted((pts[seg - 1].x, pts[seg].x))
    a, b = plan.params["a"], plan.params["b"]
    found = 0
    it = r.cell.begin_instances_rec()
    while not it.at_end():
        if it.inst_cell().basic_name() == "Meander":
            gaps = pya.Region(it.inst_cell().begin_shapes_rec(r.layout.layer(pya.LayerInfo(130, 1))))
            box = it.dtrans() * gaps.bbox().to_dtype(r.layout.dbu)  # the Meander's own etch (CPW gaps)
            assert box.left >= x0 - a / 2 - b - 1e-3 and box.right <= x1 + a / 2 + b + 1e-3, box
            found += 1
        it.next()
    assert found == 1


# ---- length fixing without zigzags (2026-11-18) --------------------------------------------------------------
def _pads_design(route: dict) -> dict:
    return {"schema": "qcc/0.1", "name": "lfx", "pdk": "quantcore_nb_sapphire_v1",
            "chip": {"box": [0, 0, 7500, 7500], "params": {"name_chip": "LFX"}},
            "instances": {"A": {"cell": "metal:LaunchpadWirebondDriven", "place": {"at": [1000, 3000], "rot": 0}},
                          "B": {"cell": "metal:LaunchpadWirebondDriven", "place": {"at": [3000, 4000], "rot": 180}}},
            "routes": {"R": route}}


def _meanders(result) -> int:
    n, it = 0, result.cell.begin_instances_rec()
    while not it.at_end():
        n += it.inst_cell().basic_name() == "Meander"
        it.next()
    return n


ZIG = {"from": "A.tie", "to": "B.tie", "nodes": [[1600, 3000], [1600, 3600], [2200, 3600], [2200, 4000]], "r": 80.0}


@pytest.mark.parametrize("extra", [0.004, 0.6])
def test_a_path_about_its_length_gets_no_zigzag(extra):
    """A meander route whose waypoint path is already (about) its length: within 0.01 µm no meander at all; a small
    leftover goes into the free corners' radius (a few nm to µm less), never into KQC's flattened-bend zigzag along
    the straight (m51 / a7 / tut222 serpentines). The port stubs keep the route radius; the length is met."""
    from quantcore_circuits.assembly import build

    base = build(_pads_design(dict(ZIG))).route_lengths()["R"]
    r = build(_pads_design({**ZIG, "type": "meander", "length": base + extra}))
    plan = r.plan.routes["R"]
    assert _meanders(r) == 0 and not [n for n in plan.nodes if n.length_increment is not None]
    assert r.route_lengths()["R"] == pytest.approx(base + extra, abs=0.01)
    trimmed = [n.params["corner_r"] for n in plan.nodes if "corner_r" in n.params]
    if extra < 0.01:
        assert not trimmed
    else:
        assert trimmed and all(80 * 0.95 <= t < 80 for t in trimmed)
        stubs = [plan.nodes[i] for i in (1, len(plan.nodes) - 2)]  # corners next to the port stubs
        assert all("corner_r" not in n.params for n in stubs)


def test_meander_turns_never_flatten_into_a_zigzag():
    """KQC lays as many turns as fit; with a small leftover their bends flatten (width < r: slanted near-straight
    segments over the whole straight). Then fewer turns keep the meander at least r wide; a real meander (KQC's wavy
    or 90° turns, e.g. ibm_falcon's readouts at +700 µm on 3 mm) keeps KQC's own choice."""
    from quantcore_circuits.route.router import max_meanders, meander_turns, meander_width

    r, span = 50.0, 3000.0
    assert meander_turns(700.0, span, r) == -1 and meander_width(700.0, r, max_meanders(span, r)) >= r
    assert meander_width(1e4, r, 5) > 4 * r  # all bends 90°: KQC's closed form
    for extra in (2.0, 20.0, 75.0):
        k = meander_turns(extra, span, r)
        assert 1 <= k < max_meanders(span, r)
        assert meander_width(extra, r, k) >= r or k == 1
        assert k == 1 or meander_width(extra, r, k + 1) < r  # the most turns that keep it r wide
    assert meander_turns(20.0, span, r, meanders=4) <= 4
